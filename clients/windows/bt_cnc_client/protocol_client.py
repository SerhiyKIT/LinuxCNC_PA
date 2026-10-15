# clients/windows/bt_cnc_client/protocol_client.py
"""
Клієнтська частина протоколу v1 bt-cnc-bridge (див.
system/bt-cnc-bridge/README.md).

Без Qt і без bleak: транспорт передається як async-функція запису байтів,
вхідні байти подаються через CncClient.feed(). Цей модуль — основа для
перенесення в Android-клієнт.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Копія з system/bt-cnc-bridge/bridge_constants.py (клієнт ставиться окремо)
PROTOCOL_VERSION = 1
SERVICE_UUID = "a002da01-7653-4ff1-a840-6568658847c6"
RX_UUID      = "a002da02-7653-4ff1-a840-6568658847c6"   # клієнт -> Pi (write)
TX_UUID      = "a002da03-7653-4ff1-a840-6568658847c6"   # Pi -> клієнт (notify)
DEVICE_NAME  = "CNC-Robot"
JOINTS       = 6

PING_INTERVAL   = 0.2    # с, heartbeat під час jogc (watchdog мосту — 500 мс)
COMMAND_TIMEOUT = 5.0    # с, очікування OK/ERR
RX_LINE_MAX     = 4096   # захист від сміття без '\n'

E_TIMEOUT = "timeout"
E_LINK    = "link"


class CommandError(Exception):
    """`ERR <code> <text>` від мосту або помилка зв'язку."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text


# ---------------------------------------------------------------------------
# Розбір вхідних рядків
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reply:
    ok: bool
    cmd: str = ""        # для OK — ім'я команди
    data: str = ""       # для OK — дані, для ERR — текст
    code: str = ""       # для ERR — код


@dataclass
class Status:
    st: str = "nocnc"
    mode: str = ""
    homed: list[int] = field(default_factory=list)
    j: list[float] = field(default_factory=list)
    prog: str = ""
    line: int = 0
    run: str = "idle"
    fo: int = 100
    ro: int = 100
    ctl: int = 0

    @classmethod
    def from_json(cls, text: str) -> "Status":
        raw = json.loads(text)
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        return cls(**known)

    @property
    def is_on(self) -> bool:
        return self.st == "on"

    @property
    def all_homed(self) -> bool:
        return bool(self.homed) and all(self.homed)


@dataclass(frozen=True)
class Incoming:
    kind: str                     # "reply" | "status" | "error" | "unknown"
    reply: Reply | None = None
    status: Status | None = None
    text: str = ""


def parse_line(line: str) -> Incoming:
    head, _, rest = line.partition(" ")
    if head == "OK":
        cmd, _, data = rest.partition(" ")
        return Incoming("reply", reply=Reply(True, cmd, data))
    if head == "ERR":
        code, _, text = rest.partition(" ")
        return Incoming("reply", reply=Reply(False, data=text, code=code))
    if head == "EVT":
        kind, _, payload = rest.partition(" ")
        if kind == "S":
            try:
                return Incoming("status", status=Status.from_json(payload))
            except (ValueError, TypeError):
                return Incoming("unknown", text=line)
        if kind == "E":
            return Incoming("error", text=payload)
    return Incoming("unknown", text=line)


class LineAssembler:
    """Збирає notify-пакети в рядки до '\\n'."""

    def __init__(self, limit: int = RX_LINE_MAX) -> None:
        self.buf = b""
        self.limit = limit

    def feed(self, data: bytes) -> list[str]:
        self.buf += data
        lines = []
        while b"\n" in self.buf:
            raw, self.buf = self.buf.split(b"\n", 1)
            raw = raw.rstrip(b"\r")
            if raw:
                lines.append(raw.decode("utf-8", errors="replace"))
        if len(self.buf) > self.limit:
            logger.warning("відкинуто %d байт без кінця рядка", len(self.buf))
            self.buf = b""
        return lines


# ---------------------------------------------------------------------------
# Клієнт
# ---------------------------------------------------------------------------

class CncClient:
    """
    Відправка команд і зіставлення відповідей.

    Міст відповідає рівно одним OK/ERR на кожну команду в порядку надходження,
    тому відповіді зіставляються з чергою очікування (FIFO). Якщо до мосту
    підключено кілька клієнтів, їхні відповіді теж приходять сюди (BLE notify
    широкомовний) — тому використовуйте один клієнт одночасно.
    """

    def __init__(self, write: Callable[[bytes], Awaitable[None]],
                 on_status: Callable[[Status], None] = lambda s: None,
                 on_event_error: Callable[[str], None] = lambda t: None,
                 on_line: Callable[[str, str], None] = lambda d, t: None) -> None:
        self._write = write
        self.on_status = on_status
        self.on_event_error = on_event_error
        self.on_line = on_line              # ("<" | ">", рядок) — для журналу
        self.assembler = LineAssembler()
        self.pending: deque[tuple[str, asyncio.Future]] = deque()
        self.lock = asyncio.Lock()
        self.status = Status()

    # --- вхід ---------------------------------------------------------------

    def feed(self, data: bytes) -> None:
        for line in self.assembler.feed(data):
            self._handle(line)

    def _handle(self, line: str) -> None:
        msg = parse_line(line)
        if msg.kind == "status":
            self.status = msg.status
            self.on_status(msg.status)
            return
        if not (msg.kind == "reply" and msg.reply.cmd == "ping"):
            self.on_line("<", line)
        if msg.kind == "error":
            self.on_event_error(msg.text)
        elif msg.kind == "reply":
            if not self.pending:
                logger.debug("відповідь без запиту: %s", line)
                return
            _, fut = self.pending.popleft()
            if not fut.done():
                fut.set_result(msg.reply)

    def connection_lost(self) -> None:
        while self.pending:
            _, fut = self.pending.popleft()
            if not fut.done():
                fut.set_exception(CommandError(E_LINK, "з'єднання розірвано"))
        self.assembler = LineAssembler()

    # --- команди ------------------------------------------------------------

    async def command(self, line: str, timeout: float = COMMAND_TIMEOUT) -> str:
        """Надсилає команду, повертає дані з `OK` або кидає CommandError."""
        name = line.split(" ", 1)[0].lower()
        fut = asyncio.get_running_loop().create_future()
        async with self.lock:                  # рядки не перемішуються між пакетами
            self.pending.append((name, fut))
            if name != "ping":
                self.on_line(">", "pin ****" if name == "pin" else line)
            try:
                await self._write((line + "\n").encode("utf-8"))
            except Exception as exc:
                self._drop(fut)
                raise CommandError(E_LINK, str(exc)) from exc
        try:
            reply: Reply = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            # Відповідь могла загубитись — прибираємо, щоб не зсунути чергу
            self._drop(fut)
            raise CommandError(E_TIMEOUT, f"немає відповіді на '{name}'") from None
        if not reply.ok:
            raise CommandError(reply.code, reply.data)
        return reply.data

    def _drop(self, fut: asyncio.Future) -> None:
        self.pending = deque(p for p in self.pending if p[1] is not fut)

    # Тонкі обгортки — щоб UI не складав рядки протоколу сам
    async def version(self) -> int:
        return int(await self.command("ver"))

    async def login(self, pin: str) -> None:
        await self.command(f"pin {pin}")

    async def take(self) -> None:
        await self.command("take")

    async def release(self) -> None:
        await self.command("release")

    async def request_status(self) -> None:
        await self.command("status")

    async def estop(self, on: bool) -> None:
        await self.command("estop on" if on else "estop off")

    async def power(self, on: bool) -> None:
        await self.command("power on" if on else "power off")

    async def home_all(self) -> None:
        await self.command("home all")

    async def jog_step(self, joint: int, step: float) -> str:
        return await self.command(f"jog J{joint} {step:+g}")

    async def jog_continuous(self, joint: int, direction: int, vel: float) -> str:
        return await self.command(f"jogc J{joint} {'+' if direction > 0 else '-'} {vel:g}")

    async def jog_stop(self, joint: int | None = None) -> None:
        await self.command("jogstop" if joint is None else f"jogstop J{joint}")

    async def ping(self) -> None:
        await self.command("ping", timeout=1.0)

    async def mdi(self, code: str) -> None:
        await self.command(f"mdi {code}")

    async def list_programs(self) -> list[str]:
        return json.loads(await self.command("ls") or "[]")

    async def open_program(self, name: str) -> None:
        await self.command(f"open {name}")

    async def run(self, line: int = 0) -> None:
        await self.command(f"run {line}" if line else "run")

    async def pause(self) -> None:
        await self.command("pause")

    async def resume(self) -> None:
        await self.command("resume")

    async def stop(self) -> None:
        await self.command("stop")

    async def step(self) -> None:
        await self.command("step")

    async def feed_override(self, percent: int) -> None:
        await self.command(f"fo {int(percent)}")


class JogHold:
    """
    Безперервний jog, поки кнопку утримують: `jogc` + `ping` кожні 200 мс,
    відпускання — `jogstop`. Якщо ping не пройшов, jog зупиняється.
    """

    def __init__(self, client: CncClient, on_error: Callable[[str], None] = lambda t: None,
                 interval: float = PING_INTERVAL) -> None:
        self.client = client
        self.on_error = on_error
        self.interval = interval
        self.joint: int | None = None
        self.task: asyncio.Task | None = None
        # Збільшується при кожному stop: якщо кнопку відпустили, поки йшов
        # jogc, heartbeat запускати не можна
        self.generation = 0

    @property
    def active(self) -> bool:
        return self.joint is not None

    async def start(self, joint: int, direction: int, vel: float) -> None:
        await self.stop()
        generation = self.generation
        self.joint = joint
        try:
            await self.client.jog_continuous(joint, direction, vel)
        except CommandError:
            if self.generation == generation:
                self.joint = None
            raise
        if self.generation != generation:
            return          # stop() уже відправив jogstop після нашого jogc
        self.task = asyncio.ensure_future(self._heartbeat())

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.interval)
                await self.client.ping()
        except asyncio.CancelledError:
            raise
        except CommandError as exc:
            self.on_error(f"jog зупинено: {exc.text}")
            await self.stop()

    def reset(self) -> None:
        """Обрив зв'язку: забути jog без відправки команд (міст зупинить сам)."""
        self.generation += 1
        self.joint = None
        task, self.task = self.task, None
        if task:
            task.cancel()

    async def stop(self) -> None:
        self.generation += 1
        task, self.task = self.task, None
        if task and task is not asyncio.current_task():
            task.cancel()
        joint, self.joint = self.joint, None
        if joint is not None:
            try:
                await self.client.jog_stop(joint)
            except CommandError as exc:
                # Міст однаково зупинить jog через watchdog
                self.on_error(f"jogstop: {exc.text}")
