# logic/core/machine.py
from __future__ import annotations

import os
import logging
from typing import Any

import linuxcnc
import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_JOG_CONTINUOUS = linuxcnc.JOG_CONTINUOUS
_JOG_INCREMENT  = linuxcnc.JOG_INCREMENT
_JOG_STOP       = linuxcnc.JOG_STOP

_MODE_MANUAL = linuxcnc.MODE_MANUAL
_MODE_MDI    = linuxcnc.MODE_MDI
_MODE_AUTO   = linuxcnc.MODE_AUTO

_STATE_ON           = linuxcnc.STATE_ON
_STATE_OFF          = linuxcnc.STATE_OFF
_STATE_ESTOP        = linuxcnc.STATE_ESTOP
_STATE_ESTOP_RESET  = linuxcnc.STATE_ESTOP_RESET

_INTERP_IDLE    = linuxcnc.INTERP_IDLE
_INTERP_PAUSED  = linuxcnc.INTERP_PAUSED
_INTERP_READING = linuxcnc.INTERP_READING
_INTERP_WAITING = linuxcnc.INTERP_WAITING

_ERROR_KINDS = (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _severity(kind: int) -> str:
    """Map a LinuxCNC error kind to a human-readable severity string."""
    if kind in _ERROR_KINDS:
        return "error"
    if kind == linuxcnc.NML_TEXT:
        return "warning"
    return "info"


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class MachineController:
    """
    Low-level controller for the LinuxCNC API.
    Uses *logic/config.py* for machine parameters and joint limits.

    Public method names are intentionally preserved for API compatibility.
    """

    def __init__(self) -> None:
        # LinuxCNC communication handles
        self.status        = linuxcnc.stat()
        self.command       = linuxcnc.command()
        self.error_channel = linuxcnc.error_channel()

        # Config snapshots
        self.params = config.MACHINE_PARAMS
        self.limits = config.JOINT_LIMITS

        # Derived settings
        self.speed             = self.params.get("LINEAR_VEL", 1.0) * 60
        self.linear_jog_speed  = 300.0
        self.angular_jog_speed = 30.0
        self.manual_mode       = config.DEFAULT_MANUAL_MODE

        # File tracking
        self.last_loaded_file: str | None = None
        self.reload_needed                = False

        # Jog / teleop flags from config
        self.JOG_CMD_FLAG       = self.params.get("JOG_CMD_FLAG", 1)
        self.TELEOP_ENABLE_VAL  = self.params.get("TELEOP_ENABLE_VAL", 0)

    # -----------------------------------------------------------------------
    # Polling / Status
    # -----------------------------------------------------------------------

    def poll(self) -> None:
        """Refresh machine status from LinuxCNC."""
        self.status.poll()

    def poll_errors(self) -> tuple[str, str] | None:
        """
        Check for new messages from LinuxCNC.

        Returns:
            ``(message_text, severity)`` where severity is one of
            ``"info"``, ``"warning"``, or ``"error"``; or ``None`` when there
            is no pending message.
        """
        error = self.error_channel.poll()
        if not error:
            return None

        kind, text = error
        return text, _severity(kind)

    # -----------------------------------------------------------------------
    # State Control
    # -----------------------------------------------------------------------

    def toggle_estop(self) -> None:
        """Toggle the Emergency Stop state."""
        self.poll()
        if self.status.estop == _STATE_ESTOP:
            self.command.state(_STATE_ESTOP_RESET)
        else:
            self.command.state(_STATE_ESTOP)

    def set_power(self, state: bool) -> None:
        """Switch machine power ON (``True``) or OFF (``False``)."""
        self.command.state(_STATE_ON if state else _STATE_OFF)

    def set_mode(self, mode: int) -> None:
        """
        Switch task mode (MANUAL / MDI / AUTO).

        The command is skipped when the machine is already in the requested
        mode so that unnecessary ``wait_complete`` round-trips are avoided.
        """
        self.poll()
        if self.status.task_mode != mode:
            self.command.mode(mode)
            self.command.wait_complete()

    # -----------------------------------------------------------------------
    # Motion Control
    # -----------------------------------------------------------------------

    def home_axis(self, axis_num: int) -> None:
        """
        Home a specific axis or all axes (pass ``-1`` for all).
        Switches to MANUAL mode and disables teleop beforehand.
        """
        self.set_mode(_MODE_MANUAL)
        self.command.teleop_enable(0)
        self.command.home(int(axis_num))

    def set_teleop(self, enable: bool) -> None:
        """Enable or disable teleoperation (World-mode jogging)."""
        self.poll()
        value = 1 if enable else 0
        if self.status.kinematics_type != value:
            self.command.teleop_enable(value)
            self.command.wait_complete()

    def is_ready(self) -> bool:
        """Return ``True`` when the machine is powered on and not in E-Stop."""
        try:
            self.status.poll()
            return (
                not self.status.estop
                and self.status.task_state == _STATE_ON
            )
        except Exception:
            return False

    def sync_mode(self, want_teleop: bool) -> bool:
        """
        Synchronise kinematics mode.

        Args:
            want_teleop: ``True`` for World mode (Axes), ``False`` for Joint mode.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        try:
            self.status.poll()
            self.set_mode(_MODE_MANUAL)
            self.command.teleop_enable(1 if want_teleop else 0)
            self.command.wait_complete()
            return True
        except Exception as exc:
            logger.error("sync_mode failed: %s", exc)
            return False

    def jog(
        self,
        index: int,
        direction: float,
        speed: float,
        increment: float,
        is_joint: bool,
    ) -> None:
        """
        Jog a joint or axis.

        Continuous jogging is used when *increment* is ``0``; otherwise an
        incremental jog is issued.
        """
        index     = int(index)
        direction = float(direction)
        speed     = float(speed)
        increment = float(increment)

        flag = self.JOG_CMD_FLAG if is_joint else 0
        vel  = speed / 60.0

        if increment == 0:
            self.command.jog(_JOG_CONTINUOUS, flag, index, direction * vel)
        else:
            self.command.jog(_JOG_INCREMENT, flag, index, direction * vel, increment)

    def stop_jog(self, index: int, is_joint: bool) -> None:
        """Stop an active jog on *index*."""
        flag = self.JOG_CMD_FLAG if is_joint else 0
        self.command.jog(_JOG_STOP, flag, int(index))

    # -----------------------------------------------------------------------
    # Overrides
    # -----------------------------------------------------------------------

    def set_feed_override(self, rate: float) -> None:
        """Set feed-rate override (``1.0`` == 100 %)."""
        self.command.feedrate(rate)

    def set_rapid_override(self, rate: float) -> None:
        """Set rapid-rate override (``1.0`` == 100 %)."""
        self.command.rapidrate(rate)

    def set_spindle_override(self, rate: float) -> None:
        """Set spindle-speed override (``1.0`` == 100 %)."""
        self.command.spindleoverride(rate)

    def set_max_velocity(self, velocity: float) -> None:
        """Set the maximum axis velocity (units per minute)."""
        self.command.maxvel(velocity / 60.0)

    # -----------------------------------------------------------------------
    # File Management
    # -----------------------------------------------------------------------

    def is_interpreter_idle(self) -> bool:
        """
        Return ``True`` when the G-code interpreter is idle.

        Used to guard against loading a new programme while one is running or
        paused.
        """
        self.status.poll()
        return self.status.interp_state == _INTERP_IDLE

    def open_program(self, filepath: str) -> bool:
        """
        Load a G-code file into LinuxCNC.

        Raises:
            FileNotFoundError: When *filepath* does not exist on disk.
            RuntimeError: When the interpreter is busy (RUNNING / PAUSED).
            Exception: On any LinuxCNC ``program_open`` error.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл не знайдено: {filepath}")

        if not self.is_interpreter_idle():
            raise RuntimeError(
                "Неможливо відкрити файл: інтерпретатор зайнятий (RUNNING/PAUSED)"
            )

        try:
            self.command.program_open(filepath)
            self.last_loaded_file = filepath
            return True
        except Exception as exc:
            raise Exception(f"LinuxCNC program_open error: {exc}") from exc

    def get_last_file(self) -> str | None:
        """Return the path of the last successfully loaded file, or ``None``."""
        return self.last_loaded_file

    # -----------------------------------------------------------------------
    # Program Execution
    # -----------------------------------------------------------------------

    def cycle_start(self, line_number: int = 0) -> None:
        """
        Start execution of the loaded G-code programme from *line_number*.

        Raises:
            Exception: When no file is loaded or not all joints are homed.
        """
        self.status.poll()

        if not self.status.file:
            raise Exception("Файл не завантажено")
        if not all(self.status.homed[:3]):
            raise Exception("Виконайте Home All перед запуском")

        self.command.mode(_MODE_AUTO)
        self.command.wait_complete()
        self.command.auto(linuxcnc.AUTO_RUN, line_number)

    def cycle_resume(self) -> None:
        """Resume a paused programme, switching to AUTO mode if necessary."""
        self.status.poll()
        if self.status.interp_state != _INTERP_PAUSED:
            return
        if self.status.task_mode != _MODE_AUTO:
            self.command.mode(_MODE_AUTO)
            self.command.wait_complete()
        self.command.auto(linuxcnc.AUTO_RESUME)

    def cycle_pause(self) -> None:
        """Pause the currently running programme."""
        self.command.auto(linuxcnc.AUTO_PAUSE)

    def cycle_stop(self) -> None:
        """Abort execution and return the machine to MANUAL mode."""
        self.command.abort()
        self.command.wait_complete()
        self.command.mode(_MODE_MANUAL)

    def cycle_step(self) -> None:
        """Execute a single G-code line in AUTO mode (step-by-step debugging)."""
        self.status.poll()

        if not self.status.file or not all(self.status.homed[:3]):
            return

        if self.status.task_mode != _MODE_AUTO:
            self.command.mode(_MODE_AUTO)
            self.command.wait_complete()

        self.command.auto(linuxcnc.AUTO_STEP)

    # -----------------------------------------------------------------------
    # MDI and Custom Commands
    # -----------------------------------------------------------------------

    def send_mdi(self, code: str) -> bool:
        """
        Send an MDI command string to LinuxCNC.

        The command is rejected (returns ``False``) when the interpreter is
        busy so that conflicts with running programmes are avoided.  The
        previous task mode is restored after execution.
        """
        self.status.poll()

        if self.status.interp_state != _INTERP_IDLE:
            logger.warning("MDI '%s' rejected: machine is busy", code)
            return False

        prev_mode = self.status.task_mode
        try:
            if prev_mode != _MODE_MDI:
                self.command.mode(_MODE_MDI)
                self.command.wait_complete()

            self.command.mdi(code)
            self.command.wait_complete()

            if prev_mode != _MODE_MDI:
                self.command.mode(prev_mode)
                self.command.wait_complete()

            return True
        except Exception as exc:
            logger.error("MDI execution failed: %s", exc)
            return False

    def set_gripper_force(self, value_0_to_1: float) -> None:
        """
        Set gripper force via a HAL analogue output pin.

        Args:
            value_0_to_1: Normalised force in the range ``[0.0, 1.0]``
                where ``1.0`` is maximum force.
        """
        self.command.set_analog_output(1, float(value_0_to_1))

    # -----------------------------------------------------------------------
    # Helpers / Getters
    # -----------------------------------------------------------------------

    def is_idle(self) -> bool:
        """Return ``True`` when the interpreter is doing nothing."""
        self.poll()
        return self.status.interp_state == _INTERP_IDLE

    def get_position(self) -> tuple:
        """Return the current Cartesian position ``(X, Y, Z, A, B, C)``."""
        self.poll()
        return self.status.position

    def get_states(self) -> dict[str, Any]:
        """
        Return a snapshot of key machine states for UI logic and control decisions.

        Includes power/E-Stop state, interpreter state, homing status,
        current positions, loaded file information, and active G/M-codes.
        """
        self.poll()

        task_state  = self.status.task_state
        estop_state = self.status.estop

        power_on  = task_state == _STATE_ON
        estop_off = estop_state != _STATE_ESTOP

        interp     = self.status.interp_state
        is_idle    = interp == _INTERP_IDLE
        is_paused  = interp == _INTERP_PAUSED
        is_running = interp in (_INTERP_READING, _INTERP_WAITING)

        joints_count = self.params.get("JOINTS_COUNT", 6)
        homed_status = self.status.homed
        all_homed    = all(
            homed_status[i]
            for i in range(min(joints_count, len(homed_status)))
        )

        return {
            # Power / safety
            "power_on":  power_on,
            "estop_off": estop_off,
            "is_ready":  power_on and estop_off,
            "all_homed": all_homed,

            # Interpreter state
            "is_idle":    is_idle,
            "is_paused":  is_paused,
            "is_running": is_running,

            # Positions
            "actual_position": self.status.actual_position,
            "joint_position":  self.status.joint_actual_position,

            # File / mode
            "has_file":    bool(self.status.file),
            "manual_mode": getattr(self, "manual_mode", "axis"),
            "teleop":      self.status.kinematics_type == 1,

            # G-code context
            "gcodes":   self.status.gcodes,
            "mcodes":   self.status.mcodes,
            "settings": self.status.settings,

            # Execution tracking
            "current_file": self.status.file,
            "motion_line":  self.status.motion_line,
            
            "linear_jog_speed": self.linear_jog_speed,
        }

    def can_home(self) -> bool:
        """
        Return ``True`` when the machine state permits homing.

        All three conditions must hold: not in E-Stop, power on, interpreter idle.
        """
        self.poll()

        is_not_in_error = self.status.estop != _STATE_ESTOP
        is_power_on     = self.status.task_state == _STATE_ON
        is_idle         = self.status.interp_state == _INTERP_IDLE

        if not (is_not_in_error and is_power_on and is_idle):
            logger.debug(
                "Homing blocked — NotInError:%s, PowerOn:%s, Idle:%s",
                is_not_in_error, is_power_on, is_idle,
            )

        return is_not_in_error and is_power_on and is_idle

    def is_all_homed(self) -> bool:
        """Return ``True`` when every configured joint has been homed."""
        self.poll()
        count = self.params.get("JOINTS_COUNT", 6)
        return all(self.status.homed[i] for i in range(count))

    def home_all_sequence(self) -> None:
        """Switch to MANUAL mode, disable teleop, then home all joints."""
        self.set_mode(_MODE_MANUAL)
        self.set_teleop(False)
        self.command.home(-1)