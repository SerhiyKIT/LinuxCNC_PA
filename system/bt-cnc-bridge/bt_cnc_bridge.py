#!/usr/bin/env python3
# system/bt-cnc-bridge/bt_cnc_bridge.py
"""
BLE-міст LinuxCNC: керування роботом з телефона/ноутбука по Bluetooth LE.

Протокол — текстові рядки (див. README.md). Клас Bridge не залежить від
D-Bus і тестується з моком linuxcnc; BlueZ підключається лише в main().
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Callable

from bridge_constants import (
    CONFIG_FILES, DEFAULT_CONFIG, E_CNC, HELP_TEXT, MAX_JOINTS,
    ON_DISCONNECT_MODES, PROTOCOL_VERSION, STATUS_HZ_RANGE,
)
from cnc_backend import CncBackend, CncError
from protocol import (
    Command, LineAssembler, ProtocolError, format_err, format_event_error,
    format_ok, format_status, parse,
)
from safety import Safety

logger = logging.getLogger("bt-cnc-bridge")


# ---------------------------------------------------------------------------
# Конфіг
# ---------------------------------------------------------------------------

def _strip_comment(value: str) -> str:
    """`pause      # pause | abort` -> `pause` (коментар лише після пробілу)."""
    for sep in (" #", "\t#"):
        if sep in value:
            value = value.split(sep, 1)[0]
    return value.strip().strip('"')


def load_config(paths: list[str] = CONFIG_FILES) -> dict:
    raw: dict[str, str] = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    raw[key.strip().upper()] = _strip_comment(value)
            logger.info("конфіг: %s", path)
            break
        except FileNotFoundError:
            continue

    cfg = dict(DEFAULT_CONFIG)
    for key, default in DEFAULT_CONFIG.items():
        if key not in raw:
            continue
        try:
            cfg[key] = type(default)(raw[key])
        except ValueError:
            logger.warning("%s=%r некоректне, беру %r", key, raw[key], default)

    if cfg["ON_DISCONNECT"] not in ON_DISCONNECT_MODES:
        logger.warning("ON_DISCONNECT=%r некоректне, беру pause", cfg["ON_DISCONNECT"])
        cfg["ON_DISCONNECT"] = "pause"
    lo, hi = STATUS_HZ_RANGE
    cfg["STATUS_HZ"] = min(max(cfg["STATUS_HZ"], lo), hi)
    for key in ("MAX_JOG_VEL", "JOG_VEL", "WATCHDOG_MS"):
        if cfg[key] <= 0:
            logger.warning("%s має бути > 0, беру %r", key, DEFAULT_CONFIG[key])
            cfg[key] = DEFAULT_CONFIG[key]
    return cfg


# ---------------------------------------------------------------------------
# Ядро мосту
# ---------------------------------------------------------------------------

class Bridge:
    def __init__(self, cfg: dict, backend: CncBackend, safety: Safety,
                 send: Callable[[str], None]) -> None:
        self.cfg = cfg
        self.backend = backend
        self.safety = safety
        self.send = send
        self.assemblers: dict[str, LineAssembler] = {}
        self.streaming = False      # після take/status шлемо EVT S при змінах
        self.last_status: dict | None = None

    # --- вхід -------------------------------------------------------------

    def handle_bytes(self, client: str, data: bytes) -> None:
        assembler = self.assemblers.setdefault(client, LineAssembler())
        for item in assembler.feed(data):
            if isinstance(item, ProtocolError):
                self.send(format_err(item.code, item.text))
            else:
                self.handle_line(client, item)

    def handle_line(self, client: str, line: str) -> None:
        try:
            cmd = parse(line)
            self.safety.check_access(client, cmd.name)
            if cmd.name not in ("ping", "pin"):
                logger.info("%s: %s", client.rsplit("/", 1)[-1], line.strip()[:80])
            data = getattr(self, "cmd_" + cmd.name)(client, cmd)
            self.send(format_ok(cmd.name, data))
            if cmd.name in ("take", "status"):
                self.streaming = True
                self.push_status(force=True)
        except ProtocolError as exc:
            self.send(format_err(exc.code, exc.text))
        except Exception as exc:          # міст не має падати через одну команду
            logger.exception("помилка команди")
            self.send(format_err(E_CNC, str(exc) or exc.__class__.__name__))

    # --- команди ---------------------------------------------------------
    # Кожна повертає дані для `OK <cmd> [дані]` або кидає ProtocolError.

    def cmd_ver(self, client, cmd: Command):
        return str(PROTOCOL_VERSION)

    def cmd_help(self, client, cmd: Command):
        return HELP_TEXT.replace("\n", " | ")

    def cmd_pin(self, client, cmd: Command):
        self.safety.login(client, cmd.args[0])

    def cmd_take(self, client, cmd: Command):
        self.safety.take(client)

    def cmd_release(self, client, cmd: Command):
        self._stop_jogs(self.safety.release(client))

    def cmd_status(self, client, cmd: Command):
        return None                       # сам статус іде окремим EVT S

    def cmd_ping(self, client, cmd: Command):
        # Watchdog продовжує лише власник керування
        if self.safety.owner == client:
            self.safety.ping()

    def cmd_ls(self, client, cmd: Command):
        return json.dumps(self.backend.list_programs(), ensure_ascii=False, separators=(",", ":"))

    def cmd_estop(self, client, cmd: Command):
        if cmd.args[0]:
            self.safety.stop_all_jogs()
        self.backend.estop(cmd.args[0])

    def cmd_power(self, client, cmd: Command):
        self.backend.power(cmd.args[0])

    def cmd_home(self, client, cmd: Command):
        self.backend.home(cmd.args[0])

    def cmd_unhome(self, client, cmd: Command):
        self.backend.unhome(cmd.args[0])

    def _jog_vel(self, joint: int, vel: float) -> float:
        return self.safety.clamp_velocity(vel, self.backend.joint_max_vel.get(joint))

    def cmd_jog(self, client, cmd: Command):
        joint, step = cmd.args
        vel = self._jog_vel(joint, self.cfg["JOG_VEL"])
        self.backend.jog_increment(joint, step, vel)
        return f"J{joint} {step:g} @{vel:g}"

    def cmd_jogc(self, client, cmd: Command):
        joint, direction, vel = cmd.args
        vel = self._jog_vel(joint, vel)
        self.backend.jog_continuous(joint, direction, vel)
        self.safety.start_jogc(joint)
        return f"J{joint} {'+' if direction > 0 else '-'}{vel:g}"

    def cmd_jogstop(self, client, cmd: Command):
        joint = cmd.args[0]
        self.safety.stop_jog(joint)
        self.backend.jog_stop(list(range(MAX_JOINTS)) if joint is None else [joint])

    def cmd_mdi(self, client, cmd: Command):
        self.backend.mdi(cmd.args[0])

    def cmd_open(self, client, cmd: Command):
        self.backend.open_program(cmd.args[0])
        return cmd.args[0]

    def cmd_run(self, client, cmd: Command):
        self.backend.run(cmd.args[0])

    def cmd_pause(self, client, cmd: Command):
        self.backend.pause()

    def cmd_resume(self, client, cmd: Command):
        self.backend.resume()

    def cmd_stop(self, client, cmd: Command):
        self.safety.stop_all_jogs()
        self.backend.stop()

    def cmd_step(self, client, cmd: Command):
        self.backend.step()

    def cmd_fo(self, client, cmd: Command):
        self.backend.feed_override(cmd.args[0])

    def cmd_ro(self, client, cmd: Command):
        self.backend.rapid_override(cmd.args[0])

    # --- періодичні задачі ---------------------------------------------

    def _stop_jogs(self, joints: list[int]) -> None:
        if joints:
            self.backend.jog_stop(joints)

    def watchdog_tick(self) -> None:
        late = self.safety.expired()
        if late:
            self.backend.jog_stop(late)
            logger.warning("watchdog: зупинено J%s", ",".join(map(str, late)))
            self.send(format_event_error("watchdog " + " ".join(f"J{j}" for j in late)))

    def status_tick(self) -> None:
        for text in self.backend.poll_errors():
            self.send(format_event_error(text))
        if self.streaming:
            self.push_status()

    def push_status(self, force: bool = False) -> None:
        try:
            status = self.backend.status()
        except CncError:
            status = {"st": "nocnc"}
        status["ctl"] = 1 if self.safety.owner else 0
        if force or status != self.last_status:
            self.last_status = status
            self.send(format_status(status))

    # --- з'єднання --------------------------------------------------------

    def client_disconnected(self, client: str) -> None:
        self.assemblers.pop(client, None)
        actions = self.safety.disconnect(client, self.backend.is_running())
        if not actions.released:
            return
        logger.warning("власник керування відключився")
        # Зупиняємо всі joints: дешевше, ніж пропустити якийсь jog
        self.backend.jog_stop(list(range(MAX_JOINTS)))
        if actions.program:
            try:
                if actions.program == "abort":
                    self.backend.stop()
                else:
                    self.backend.pause()
            except ProtocolError as exc:
                logger.error("обрив: %s не виконано: %s", actions.program, exc.text)
        self.send(format_event_error("власник відключився" +
                                     (f", програма: {actions.program}" if actions.program else "")))

    def subscribers_changed(self, active: bool) -> None:
        """Ніхто не підписаний на TX — вважаємо, що всі відключились."""
        if active:
            return
        self.streaming = False
        self.last_status = None
        clients = set(self.safety.authed)
        if self.safety.owner:
            clients.add(self.safety.owner)
        for client in clients:
            self.client_disconnected(client)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(levelname)s %(name)s: %(message)s")
    # D-Bus/GLib імпортуються лише тут, щоб Bridge тестувався без них
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib

    import ble_gatt
    from bridge_constants import DBUS_APP_PATH, WATCHDOG_TICK_MS

    cfg = load_config()
    if not cfg["PIN"]:
        logger.warning("PIN не задано — керувати може будь-хто поруч")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = ble_gatt.find_adapter(bus)
    if not adapter:
        logger.error("Bluetooth-адаптер не знайдено")
        sys.exit(1)

    backend = CncBackend(cfg["PROJECTS_DIR"])
    if backend.lc is None:
        logger.error("модуль linuxcnc не знайдено")
    safety = Safety(cfg["PIN"], cfg["WATCHDOG_MS"], cfg["MAX_JOG_VEL"], cfg["ON_DISCONNECT"])

    service: ble_gatt.SerialService | None = None
    bridge = Bridge(cfg, backend, safety, send=lambda text: service.send(text))
    app = ble_gatt.Application(bus)
    service = ble_gatt.SerialService(bus, DBUS_APP_PATH + "/service0",
                                     on_write=bridge.handle_bytes,
                                     on_subscribe=bridge.subscribers_changed)
    app.services.append(service)

    loop = GLib.MainLoop()

    def fatal(msg: str) -> None:
        logger.error(msg)
        loop.quit()
        sys.exit(1)

    def periodic(fn):
        def tick():
            try:
                fn()
            except Exception:
                logger.exception("помилка в %s", fn.__name__)
            return True
        return tick

    ble_gatt.register(bus, adapter, app, DBUS_APP_PATH + "/adv0", cfg["NAME"], fatal)
    ble_gatt.watch_disconnects(bus, bridge.client_disconnected)
    GLib.timeout_add(WATCHDOG_TICK_MS, periodic(bridge.watchdog_tick))
    GLib.timeout_add(int(1000 / cfg["STATUS_HZ"]), periodic(bridge.status_tick))
    loop.run()


if __name__ == "__main__":
    main()
