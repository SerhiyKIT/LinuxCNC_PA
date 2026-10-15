# system/bt-cnc-bridge/cnc_backend.py
"""
Обгортка над linuxcnc.stat / command / error_channel для BLE-мосту.

Не залежить від cnc_interface/ і заліза — говорить з LinuxCNC лише через NML.
Кожна команда перевіряє передумови і кидає CncError із зрозумілим текстом
замість винятків linuxcnc. Якщо LinuxCNC не запущений — E_NOCNC, а
перепідключення пробується не частіше ніж раз на RECONNECT_SEC.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from bridge_constants import (
    E_CNC, E_NOCNC, E_NOFILE, E_PATH, E_STATE, E_TIMEOUT, MAX_JOINTS,
    POSITION_DIGITS, PROGRAM_EXTS, RECONNECT_SEC, WAIT_TIMEOUT,
)
from protocol import ProtocolError, validate_program_name

logger = logging.getLogger(__name__)


class CncError(ProtocolError):
    """Помилка виконання команди на верстаті."""


def _import_linuxcnc():
    try:
        import linuxcnc
        return linuxcnc
    except ImportError:
        return None


class CncBackend:
    def __init__(self, projects_dir: str, lc: Any = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.lc = lc if lc is not None else _import_linuxcnc()
        self.projects_dir = projects_dir
        self.clock = clock
        self.stat = None
        self.cmd = None
        self.errors = None
        self.joint_max_vel: dict[int, float] = {}
        self.last_attempt = -RECONNECT_SEC

    # -----------------------------------------------------------------------
    # З'єднання
    # -----------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.stat is not None

    def _connect(self) -> None:
        lc = self.lc
        stat = lc.stat()
        stat.poll()                       # кидає linuxcnc.error, якщо LinuxCNC не запущений
        self.cmd = lc.command()
        self.errors = lc.error_channel()
        self.stat = stat
        self.joint_max_vel = self._read_joint_limits(stat)
        logger.info("підключено до LinuxCNC (%s)", stat.ini_filename)

    def _read_joint_limits(self, stat) -> dict[int, float]:
        limits = {}
        try:
            ini = self.lc.ini(stat.ini_filename)
            for j in range(self.joint_count()):
                value = ini.find(f"JOINT_{j}", "MAX_VELOCITY")
                if value is not None:
                    limits[j] = float(value)
        except Exception as exc:          # без INI просто не обрізаємо по joint
            logger.warning("не вдалося прочитати ліміти з INI: %s", exc)
        return limits

    def disconnect(self) -> None:
        if self.connected:
            logger.info("з'єднання з LinuxCNC втрачено")
        self.stat = self.cmd = self.errors = None

    def ensure(self) -> None:
        """Гарантує з'єднання або кидає E_NOCNC."""
        if self.connected:
            return
        now = self.clock()
        if self.lc is not None and now - self.last_attempt >= RECONNECT_SEC:
            self.last_attempt = now
            try:
                self._connect()
                return
            except Exception as exc:
                logger.debug("LinuxCNC недоступний: %s", exc)
                self.disconnect()
        raise CncError(E_NOCNC, "LinuxCNC не запущений")

    def poll(self):
        self.ensure()
        try:
            self.stat.poll()
        except Exception:
            self.disconnect()
            raise CncError(E_NOCNC, "LinuxCNC не відповідає") from None
        return self.stat

    def joint_count(self) -> int:
        try:
            return min(int(self.stat.joints), MAX_JOINTS)
        except Exception:
            return MAX_JOINTS

    # -----------------------------------------------------------------------
    # Стан
    # -----------------------------------------------------------------------

    def _state_name(self, s) -> str:
        lc = self.lc
        if s.task_state == lc.STATE_ESTOP:
            return "estop"
        return "on" if s.task_state == lc.STATE_ON else "off"

    def _mode_name(self, s) -> str:
        lc = self.lc
        return {lc.MODE_MANUAL: "manual", lc.MODE_MDI: "mdi",
                lc.MODE_AUTO: "auto"}.get(s.task_mode, "?")

    def _run_name(self, s) -> str:
        lc = self.lc
        if s.interp_state == lc.INTERP_PAUSED or getattr(s, "paused", False):
            return "paused"
        if s.interp_state in (lc.INTERP_READING, lc.INTERP_WAITING):
            return "run"
        return "idle"

    def status(self) -> dict:
        s = self.poll()
        n = self.joint_count()
        return {
            "st":    self._state_name(s),
            "mode":  self._mode_name(s),
            "homed": [1 if s.homed[j] else 0 for j in range(n)],
            "j":     [round(s.joint_actual_position[j], POSITION_DIGITS) for j in range(n)],
            "prog":  os.path.basename(s.file or ""),
            "line":  int(s.motion_line),
            "run":   self._run_name(s),
            "fo":    round(s.feedrate * 100),
            "ro":    round(s.rapidrate * 100),
        }

    def is_running(self) -> bool:
        """Програма/MDI виконується або на паузі (не idle)."""
        try:
            s = self.poll()
        except CncError:
            return False
        return s.interp_state != self.lc.INTERP_IDLE

    def poll_errors(self) -> list[str]:
        if not self.connected:
            return []
        messages = []
        try:
            while True:
                item = self.errors.poll()
                if not item:
                    break
                kind, text = item
                if kind in (self.lc.NML_ERROR, self.lc.OPERATOR_ERROR):
                    messages.append(str(text))
        except Exception:
            self.disconnect()
        return messages

    # -----------------------------------------------------------------------
    # Передумови
    # -----------------------------------------------------------------------

    def _require_on(self, s) -> None:
        if s.task_state != self.lc.STATE_ON:
            raise CncError(E_STATE, "машина не увімкнена (estop off, power on)")

    def _require_idle(self, s) -> None:
        if s.interp_state != self.lc.INTERP_IDLE:
            raise CncError(E_STATE, "виконується програма/MDI")

    def _require_homed(self, s) -> None:
        if not all(s.homed[j] for j in range(self.joint_count())):
            raise CncError(E_STATE, "спершу home all")

    def _require_joint(self, joint: int) -> None:
        if not 0 <= joint < self.joint_count():
            raise CncError(E_STATE, f"joint {joint} відсутній у конфігурації")

    def _wait(self) -> None:
        rc = self.cmd.wait_complete(WAIT_TIMEOUT)
        if rc == -1:
            raise CncError(E_TIMEOUT, "LinuxCNC не відповів вчасно")
        if rc == self.lc.RCS_ERROR:
            raise CncError(E_CNC, "LinuxCNC відхилив команду")

    def _set_mode(self, mode: int) -> None:
        s = self.poll()
        if s.task_mode != mode:
            self.cmd.mode(mode)
            self._wait()

    def _joint_mode(self) -> None:
        """Ручний режим + вимкнений teleop (jog/home по joints)."""
        self._set_mode(self.lc.MODE_MANUAL)
        self.cmd.teleop_enable(0)
        self._wait()

    # -----------------------------------------------------------------------
    # Команди
    # -----------------------------------------------------------------------

    def estop(self, on: bool) -> None:
        self.ensure()
        self.cmd.state(self.lc.STATE_ESTOP if on else self.lc.STATE_ESTOP_RESET)
        self._wait()

    def power(self, on: bool) -> None:
        s = self.poll()
        if on and s.task_state == self.lc.STATE_ESTOP:
            raise CncError(E_STATE, "спершу estop off")
        if not on and s.task_state != self.lc.STATE_ON:
            return
        self.cmd.state(self.lc.STATE_ON if on else self.lc.STATE_OFF)
        self._wait()

    def home(self, joint: int) -> None:
        """joint = -1 — усі. Не чекаємо завершення: хоумінг довгий."""
        s = self.poll()
        self._require_on(s)
        self._require_idle(s)
        if joint >= 0:
            self._require_joint(joint)
        self._joint_mode()
        self.cmd.home(joint)

    def unhome(self, joint: int) -> None:
        s = self.poll()
        self._require_on(s)
        self._require_idle(s)
        if joint >= 0:
            self._require_joint(joint)
        self._joint_mode()
        self.cmd.unhome(joint)
        self._wait()

    def _prepare_jog(self, joint: int) -> None:
        s = self.poll()
        self._require_on(s)
        self._require_idle(s)
        self._require_joint(joint)
        self._joint_mode()

    def jog_increment(self, joint: int, step: float, vel: float) -> None:
        """Напрямок задає знак швидкості, крок — додатний (як у AXIS)."""
        self._prepare_jog(joint)
        speed = vel if step > 0 else -vel
        self.cmd.jog(self.lc.JOG_INCREMENT, True, joint, speed, abs(step))

    def jog_continuous(self, joint: int, direction: int, vel: float) -> None:
        self._prepare_jog(joint)
        self.cmd.jog(self.lc.JOG_CONTINUOUS, True, joint, direction * vel)

    def jog_stop(self, joints: list[int]) -> None:
        """Зупинка без передумов — має спрацювати завжди, коли є з'єднання."""
        if not self.connected:
            return
        for joint in joints:
            try:
                self.cmd.jog(self.lc.JOG_STOP, True, joint)
            except Exception as exc:
                logger.error("jog stop J%d: %s", joint, exc)

    def mdi(self, code: str) -> None:
        s = self.poll()
        self._require_on(s)
        self._require_homed(s)
        self._require_idle(s)
        self._set_mode(self.lc.MODE_MDI)
        # Не чекаємо завершення: рух може тривати довго
        self.cmd.mdi(code)

    def list_programs(self) -> list[str]:
        try:
            names = os.listdir(self.projects_dir)
        except OSError:
            raise CncError(E_NOFILE, f"немає каталогу {self.projects_dir}") from None
        return sorted(n for n in names
                      if n.lower().endswith(PROGRAM_EXTS) and not n.startswith(".")
                      and os.path.isfile(os.path.join(self.projects_dir, n)))

    def program_path(self, name: str) -> str:
        """Повний шлях до файлу лише всередині PROJECTS_DIR (з урахуванням symlink)."""
        try:
            validate_program_name(name)
        except ProtocolError as exc:
            raise CncError(exc.code, exc.text) from None
        base = os.path.realpath(self.projects_dir)
        path = os.path.realpath(os.path.join(base, name))
        if os.path.dirname(path) != base:
            raise CncError(E_PATH, "файл поза каталогом проєктів")
        if not os.path.isfile(path):
            raise CncError(E_NOFILE, f"файл '{name}' не знайдено")
        return path

    def open_program(self, name: str) -> None:
        path = self.program_path(name)
        s = self.poll()
        self._require_idle(s)
        self._set_mode(self.lc.MODE_AUTO)
        self.cmd.program_open(path)
        self._wait()

    def _prepare_auto(self):
        s = self.poll()
        self._require_on(s)
        self._require_homed(s)
        if not s.file:
            raise CncError(E_STATE, "файл не відкрито (open)")
        return s

    def run(self, line: int) -> None:
        s = self._prepare_auto()
        self._require_idle(s)
        self._set_mode(self.lc.MODE_AUTO)
        self.cmd.auto(self.lc.AUTO_RUN, line)

    def pause(self) -> None:
        s = self.poll()
        if s.interp_state not in (self.lc.INTERP_READING, self.lc.INTERP_WAITING):
            raise CncError(E_STATE, "програма не виконується")
        self.cmd.auto(self.lc.AUTO_PAUSE)

    def resume(self) -> None:
        s = self.poll()
        if s.interp_state != self.lc.INTERP_PAUSED:
            raise CncError(E_STATE, "програма не на паузі")
        self.cmd.auto(self.lc.AUTO_RESUME)

    def stop(self) -> None:
        self.ensure()
        self.cmd.abort()
        self._wait()

    def step(self) -> None:
        s = self._prepare_auto()
        if s.interp_state not in (self.lc.INTERP_IDLE, self.lc.INTERP_PAUSED):
            raise CncError(E_STATE, "спершу pause")
        if s.interp_state == self.lc.INTERP_IDLE:
            self._set_mode(self.lc.MODE_AUTO)
        self.cmd.auto(self.lc.AUTO_STEP)

    def feed_override(self, percent: float) -> None:
        self.ensure()
        self.cmd.feedrate(percent / 100.0)

    def rapid_override(self, percent: float) -> None:
        self.ensure()
        self.cmd.rapidrate(percent / 100.0)
