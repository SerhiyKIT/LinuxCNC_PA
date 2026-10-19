# system/bt-cnc-bridge/protocol.py
"""
Протокол v1: розбір команд, форматування відповідей, кадрування рядків.

Чистий модуль — без linuxcnc і D-Bus, щоб його можна було тестувати
і перенести в клієнти (Windows/Android).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from bridge_constants import (
    AXES, E_ARGS, E_OVERFLOW, E_PATH, E_UNKNOWN, FO_RANGE, MAX_JOINTS,
    PROGRAM_EXTS, RO_RANGE, RX_BUFFER_MAX,
)


class ProtocolError(Exception):
    """Помилка, яку треба віддати клієнту як `ERR <code> <text>`."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple = ()


# ---------------------------------------------------------------------------
# Розбір аргументів
# ---------------------------------------------------------------------------

def parse_joint(token: str) -> int:
    """`J0`, `j0` або `0` -> 0."""
    raw = token[1:] if token[:1] in ("J", "j") else token
    if not raw.isdigit() or not 0 <= int(raw) < MAX_JOINTS:
        raise ProtocolError(E_ARGS, f"joint має бути J0..J{MAX_JOINTS - 1}")
    return int(raw)


def parse_axis(token: str) -> str:
    """`x` / `X` -> `X` (світова вісь)."""
    axis = token.upper()
    if len(axis) != 1 or axis not in AXES:
        raise ProtocolError(E_ARGS, "вісь має бути одна з " + " ".join(AXES))
    return axis


def parse_jog_target(token: str) -> int | str:
    """Ціль jogstop: joint (`J0`/`0`) або світова вісь (`X`..`C`)."""
    if token.upper() in AXES:
        return token.upper()
    return parse_joint(token)


def parse_float(token: str, what: str) -> float:
    try:
        value = float(token)
    except ValueError:
        raise ProtocolError(E_ARGS, f"{what}: очікується число") from None
    if not math.isfinite(value):
        raise ProtocolError(E_ARGS, f"{what}: очікується скінченне число")
    return value


def parse_on_off(token: str, cmd: str) -> bool:
    if token == "on":
        return True
    if token == "off":
        return False
    raise ProtocolError(E_ARGS, f"{cmd} on|off")


def validate_program_name(name: str) -> str:
    """Лише ім'я файлу в PROJECTS_DIR: без шляхів, `..` і прихованих файлів."""
    if (not name or "/" in name or "\\" in name or "\0" in name
            or name.startswith(".") or ".." in name):
        raise ProtocolError(E_PATH, "лише ім'я файлу без шляху")
    if not name.lower().endswith(PROGRAM_EXTS):
        raise ProtocolError(E_PATH, "дозволені " + ", ".join(PROGRAM_EXTS))
    return name


def _no_args(name: str, rest: list[str]) -> Command:
    if rest:
        raise ProtocolError(E_ARGS, f"{name} без аргументів")
    return Command(name)


def _pct(name: str, rest: list[str], lo_hi: tuple[int, int]) -> Command:
    if len(rest) != 1:
        raise ProtocolError(E_ARGS, f"{name} <{lo_hi[0]}-{lo_hi[1]}>")
    value = parse_float(rest[0], name)
    if not lo_hi[0] <= value <= lo_hi[1]:
        raise ProtocolError(E_ARGS, f"{name} <{lo_hi[0]}-{lo_hi[1]}>")
    return Command(name, (value,))


def _home(name: str, rest: list[str]) -> Command:
    if len(rest) != 1:
        raise ProtocolError(E_ARGS, f"{name} all|<J>")
    return Command(name, (-1 if rest[0] == "all" else parse_joint(rest[0]),))


# ---------------------------------------------------------------------------
# Розбір рядка
# ---------------------------------------------------------------------------

NO_ARG_CMDS = frozenset({
    "ver", "help", "take", "release", "status", "ping", "ls",
    "pause", "resume", "stop", "step",
})


def parse(line: str) -> Command:
    """Розбирає один рядок команди. Кидає ProtocolError."""
    line = line.strip()
    if not line:
        raise ProtocolError(E_ARGS, "порожній рядок")
    head, _, tail = line.partition(" ")
    name = head.lower()
    rest = tail.split()

    if name in NO_ARG_CMDS:
        return _no_args(name, rest)

    if name == "pin":
        if len(rest) != 1:
            raise ProtocolError(E_ARGS, "pin <PIN>")
        return Command(name, (rest[0],))

    if name in ("estop", "power"):
        if len(rest) != 1:
            raise ProtocolError(E_ARGS, f"{name} on|off")
        return Command(name, (parse_on_off(rest[0].lower(), name),))

    if name in ("home", "unhome"):
        return _home(name, [t.lower() if t.lower() == "all" else t for t in rest])

    if name == "jog":
        if len(rest) != 2:
            raise ProtocolError(E_ARGS, "jog <J> <+-крок>")
        step = parse_float(rest[1], "крок")
        if step == 0:
            raise ProtocolError(E_ARGS, "крок не може бути 0")
        return Command(name, (parse_joint(rest[0]), step))

    if name == "jogc":
        if len(rest) != 3 or rest[1] not in ("+", "-"):
            raise ProtocolError(E_ARGS, "jogc <J> <+|-> <швидкість>")
        vel = parse_float(rest[2], "швидкість")
        if vel <= 0:
            raise ProtocolError(E_ARGS, "швидкість має бути > 0")
        return Command(name, (parse_joint(rest[0]), 1 if rest[1] == "+" else -1, vel))

    if name == "jogw":
        if len(rest) != 2:
            raise ProtocolError(E_ARGS, "jogw <X..C> <+-крок>")
        step = parse_float(rest[1], "крок")
        if step == 0:
            raise ProtocolError(E_ARGS, "крок не може бути 0")
        return Command(name, (parse_axis(rest[0]), step))

    if name == "jogwc":
        if len(rest) != 3 or rest[1] not in ("+", "-"):
            raise ProtocolError(E_ARGS, "jogwc <X..C> <+|-> <швидкість>")
        vel = parse_float(rest[2], "швидкість")
        if vel <= 0:
            raise ProtocolError(E_ARGS, "швидкість має бути > 0")
        return Command(name, (parse_axis(rest[0]), 1 if rest[1] == "+" else -1, vel))

    if name == "jogstop":
        if len(rest) > 1:
            raise ProtocolError(E_ARGS, "jogstop [J|вісь]")
        return Command(name, (parse_jog_target(rest[0]) if rest else None,))

    if name == "file":
        sub, _, raw = tail.strip().partition(" ")
        if sub == "begin":
            return Command(name, ("begin", validate_program_name(raw.strip())))
        if sub == "data":
            # Рядок програми як є (порожній теж дозволений)
            return Command(name, ("data", line.split(" ", 2)[2] if raw else ""))
        if sub in ("end", "abort") and not raw:
            return Command(name, (sub,))
        raise ProtocolError(E_ARGS, "file begin <файл> | data <рядок> | end | abort")

    if name == "rm":
        return Command(name, (validate_program_name(tail.strip()),))

    if name == "mdi":
        code = tail.strip()
        if not code:
            raise ProtocolError(E_ARGS, "mdi <G-код>")
        return Command(name, (code,))

    if name == "open":
        # Ім'я може містити пробіли — беремо весь хвіст
        return Command(name, (validate_program_name(tail.strip()),))

    if name == "run":
        if len(rest) > 1 or (rest and not rest[0].isdigit()):
            raise ProtocolError(E_ARGS, "run [номер рядка]")
        return Command(name, (int(rest[0]) if rest else 0,))

    if name == "fo":
        return _pct(name, rest, FO_RANGE)
    if name == "ro":
        return _pct(name, rest, RO_RANGE)

    raise ProtocolError(E_UNKNOWN, f"невідома команда '{name}', див. help")


# ---------------------------------------------------------------------------
# Відповіді
# ---------------------------------------------------------------------------

def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def format_ok(cmd: str, data: str | None = None) -> str:
    return f"OK {cmd} {data}" if data else f"OK {cmd}"


def format_err(code: str, text: str) -> str:
    return f"ERR {code} {_one_line(text)}"


def format_status(status: dict) -> str:
    return "EVT S " + json.dumps(status, ensure_ascii=False, separators=(",", ":"))


def format_event_error(text: str) -> str:
    return f"EVT E {_one_line(text)}"


# ---------------------------------------------------------------------------
# Кадрування
# ---------------------------------------------------------------------------

class LineAssembler:
    """Збирає байти з RX у рядки до '\\n' ('\\r' ігнорується як кінець рядка)."""

    def __init__(self, limit: int = RX_BUFFER_MAX) -> None:
        self.limit = limit
        self.buf = b""
        self.discarding = False   # пропускаємо залишок занадто довгого рядка

    def feed(self, data: bytes) -> list[str | ProtocolError]:
        """Повертає зібрані рядки; на місці переповнення — ProtocolError."""
        out: list[str | ProtocolError] = []
        for byte in data:
            if byte in (0x0A, 0x0D):
                if self.discarding:
                    self.discarding = False
                elif self.buf:
                    out.append(self.buf.decode("utf-8", errors="replace"))
                self.buf = b""
                continue
            if self.discarding:
                continue
            if len(self.buf) >= self.limit:
                self.buf = b""
                self.discarding = True
                out.append(ProtocolError(E_OVERFLOW, f"рядок довший за {self.limit} байт"))
                continue
            self.buf += bytes((byte,))
        return out

    def reset(self) -> None:
        self.buf = b""
        self.discarding = False


def split_payload(text: str, size: int) -> list[bytes]:
    """Ріже рядок (з '\\n' в кінці) на пакети <= size байт, не розриваючи UTF-8."""
    data = (text.rstrip("\n") + "\n").encode("utf-8")
    size = max(4, size)
    chunks = []
    while data:
        cut = min(size, len(data))
        while cut < len(data) and (data[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(data[:cut])
        data = data[cut:]
    return chunks
