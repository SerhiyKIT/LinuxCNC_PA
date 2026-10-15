# system/bt-cnc-bridge/safety.py
"""
Безпека мосту: PIN, власник керування, watchdog безперервного jog,
політика при обриві з'єднання.

Чистий модуль: час береться з переданої функції `clock` (для тестів).
Клієнт ідентифікується довільним рядком — у мосту це шлях D-Bus пристрою.
"""
from __future__ import annotations

import hmac
import time
from dataclasses import dataclass, field
from typing import Callable

from bridge_constants import (
    ANYONE_CMDS, E_AUTH, E_BUSY, E_LOCKED, E_OWNER, LOCKOUT_SEC,
    MAX_PIN_FAILS, PUBLIC_CMDS, READ_CMDS,
)
from protocol import ProtocolError


@dataclass
class DisconnectActions:
    """Що зробити з верстатом після обриву з'єднання клієнта."""
    stop_jogs: list[int] = field(default_factory=list)
    released: bool = False
    program: str | None = None      # "pause" | "abort" | None


class Safety:
    def __init__(self, pin: str, watchdog_ms: int, max_jog_vel: float,
                 on_disconnect: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.pin = pin
        self.watchdog_sec = watchdog_ms / 1000.0
        self.max_jog_vel = max_jog_vel
        self.on_disconnect = on_disconnect
        self.clock = clock

        self.authed: set[str] = set()
        self.owner: str | None = None
        # Лічильник спроб глобальний: перепідключення не скидає блокування
        self.pin_fails = 0
        self.locked_until = 0.0
        # joint -> час останнього ping під час jogc
        self.jogging: dict[int, float] = {}

    # --- PIN -------------------------------------------------------------

    def login(self, client: str, pin: str) -> None:
        now = self.clock()
        if not self.pin:
            self.authed.add(client)
            return
        if now < self.locked_until:
            raise ProtocolError(E_LOCKED, f"зачекайте {int(self.locked_until - now) + 1} с")
        if hmac.compare_digest(pin.encode(), self.pin.encode()):
            self.pin_fails = 0
            self.authed.add(client)
            return
        self.pin_fails += 1
        if self.pin_fails >= MAX_PIN_FAILS:
            self.pin_fails = 0
            self.locked_until = now + LOCKOUT_SEC
            raise ProtocolError(E_LOCKED, f"забагато спроб, блокування {LOCKOUT_SEC} с")
        raise ProtocolError(E_AUTH, "невірний PIN")

    def is_authed(self, client: str) -> bool:
        return not self.pin or client in self.authed

    # --- Власник ---------------------------------------------------------

    def take(self, client: str) -> None:
        if self.owner not in (None, client):
            raise ProtocolError(E_BUSY, "керування зайняте іншим клієнтом")
        self.owner = client

    def release(self, client: str) -> list[int]:
        """Звільняє керування; повертає joints, які треба зупинити."""
        if self.owner != client:
            raise ProtocolError(E_OWNER, "ви не керуєте")
        self.owner = None
        return self.stop_all_jogs()

    def check_access(self, client: str, cmd: str) -> None:
        """Чи можна клієнту виконати команду. Кидає ProtocolError."""
        if cmd in PUBLIC_CMDS:
            return
        if not self.is_authed(client):
            raise ProtocolError(E_AUTH, "спершу pin <PIN>")
        if cmd in READ_CMDS or cmd in ANYONE_CMDS:
            return
        if self.owner != client:
            raise ProtocolError(E_OWNER, "спершу take")

    # --- Jog / watchdog ----------------------------------------------------

    def clamp_velocity(self, vel: float, joint_max: float | None) -> float:
        limit = self.max_jog_vel if joint_max is None else min(self.max_jog_vel, joint_max)
        return min(abs(vel), limit)

    def start_jogc(self, joint: int) -> None:
        self.jogging[joint] = self.clock()

    def ping(self) -> None:
        now = self.clock()
        for joint in self.jogging:
            self.jogging[joint] = now

    def stop_jog(self, joint: int | None) -> list[int]:
        if joint is None:
            return self.stop_all_jogs()
        self.jogging.pop(joint, None)
        return [joint]

    def stop_all_jogs(self) -> list[int]:
        joints = sorted(self.jogging)
        self.jogging.clear()
        return joints

    def expired(self) -> list[int]:
        """Joints, для яких ping не приходив довше за WATCHDOG_MS."""
        now = self.clock()
        late = sorted(j for j, t in self.jogging.items() if now - t > self.watchdog_sec)
        for joint in late:
            del self.jogging[joint]
        return late

    # --- Обрив з'єднання ------------------------------------------------

    def disconnect(self, client: str, program_running: bool) -> DisconnectActions:
        self.authed.discard(client)
        if self.owner != client:
            return DisconnectActions()
        self.owner = None
        return DisconnectActions(
            stop_jogs=self.stop_all_jogs(),
            released=True,
            program=self.on_disconnect if program_running else None,
        )
