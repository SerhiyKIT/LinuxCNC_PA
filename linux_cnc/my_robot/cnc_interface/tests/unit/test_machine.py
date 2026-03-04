"""
Tests for logic/core/machine.py  –  MachineController
======================================================

Run with:
    pytest test_machine.py -v

All LinuxCNC symbols are mocked so the tests run without a real LinuxCNC
installation.  Every mock value is explicit so tests never rely on
MagicMock's auto-created truthy attributes.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# Mock the entire linuxcnc module before it is imported by machine.py
# ---------------------------------------------------------------------------
linuxcnc_mock = MagicMock()

# State constants
linuxcnc_mock.STATE_ESTOP       = 1
linuxcnc_mock.STATE_ESTOP_RESET = 2
linuxcnc_mock.STATE_OFF         = 3
linuxcnc_mock.STATE_ON          = 4

# Mode constants
linuxcnc_mock.MODE_MANUAL = 1
linuxcnc_mock.MODE_AUTO   = 2
linuxcnc_mock.MODE_MDI    = 3

# Interpreter states
linuxcnc_mock.INTERP_IDLE    = 1
linuxcnc_mock.INTERP_READING = 2
linuxcnc_mock.INTERP_PAUSED  = 3
linuxcnc_mock.INTERP_WAITING = 4

# Jog commands
linuxcnc_mock.JOG_CONTINUOUS = 0
linuxcnc_mock.JOG_INCREMENT  = 1
linuxcnc_mock.JOG_STOP       = 2

# Error kinds
linuxcnc_mock.NML_ERROR       = 11
linuxcnc_mock.NML_TEXT        = 12
linuxcnc_mock.OPERATOR_ERROR  = 13
linuxcnc_mock.OPERATOR_TEXT   = 14

# Auto commands
linuxcnc_mock.AUTO_RUN    = 0
linuxcnc_mock.AUTO_PAUSE  = 1
linuxcnc_mock.AUTO_RESUME = 2
linuxcnc_mock.AUTO_STEP   = 3

sys.modules["linuxcnc"] = linuxcnc_mock

# Make the module importable from any working directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import after mocking
import linuxcnc  # noqa: E402  (this is the mock)
from logic.core.machine import MachineController  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctrl():
    """
    Return a MachineController with all LinuxCNC handles mocked.

    Status attributes are pre-set to safe, explicit values so every test
    starts from a known baseline and is not surprised by MagicMock defaults.
    """
    mock_stat    = MagicMock()
    mock_command = MagicMock()
    mock_error   = MagicMock()

    # Baseline status – machine is on, out of e-stop, interpreter idle
    mock_stat.task_state    = linuxcnc.STATE_ON
    mock_stat.task_mode     = linuxcnc.MODE_MANUAL
    mock_stat.estop         = linuxcnc.STATE_ESTOP_RESET
    mock_stat.interp_state  = linuxcnc.INTERP_IDLE
    mock_stat.kinematics_type = 0
    mock_stat.homed         = [1, 1, 1, 0, 0, 0, 0, 0, 0]
    mock_stat.file          = "job.ngc"
    mock_stat.actual_position       = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mock_stat.joint_actual_position = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mock_stat.position      = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mock_stat.gcodes        = []
    mock_stat.mcodes        = []
    mock_stat.settings      = (0, 0, 0)
    mock_stat.motion_line   = 0

    # Raise by default so tests that forget to set interp_state don't silently pass
    mock_error.poll.return_value = None

    linuxcnc_mock.stat.return_value          = mock_stat
    linuxcnc_mock.command.return_value       = mock_command
    linuxcnc_mock.error_channel.return_value = mock_error

    with patch("logic.core.machine.config") as mock_config:
        mock_config.MACHINE_PARAMS    = {"LINEAR_VEL": 1.0, "JOG_CMD_FLAG": 1, "JOINTS_COUNT": 6}
        mock_config.JOINT_LIMITS      = {}
        mock_config.DEFAULT_MANUAL_MODE = "axis"

        c = MachineController()
        # Swap out the instances so tests can configure them directly
        c.status        = mock_stat
        c.command       = mock_command
        c.error_channel = mock_error
        yield c


# ===========================================================================
# Polling / Status
# ===========================================================================

class TestPoll:
    def test_poll_delegates_to_status(self, ctrl):
        """poll() must call status.poll() exactly once."""
        ctrl.poll()
        ctrl.status.poll.assert_called_once()

    def test_poll_side_effect_is_visible(self, ctrl):
        """Mutations made inside poll's side-effect are reflected on status."""
        def _side_effect():
            ctrl.status.task_state = linuxcnc.STATE_OFF

        ctrl.status.poll.side_effect = _side_effect
        ctrl.poll()
        assert ctrl.status.task_state == linuxcnc.STATE_OFF


class TestPollErrors:
    def test_nml_error_returns_error_level(self, ctrl):
        ctrl.error_channel.poll.return_value = (linuxcnc.NML_ERROR, "Joint 0 error")
        text, level = ctrl.poll_errors()
        assert text == "Joint 0 error"
        assert level == "error"

    def test_operator_error_returns_error_level(self, ctrl):
        ctrl.error_channel.poll.return_value = (linuxcnc.OPERATOR_ERROR, "Op error")
        text, level = ctrl.poll_errors()
        assert level == "error"

    def test_nml_text_returns_warning_level(self, ctrl):
        ctrl.error_channel.poll.return_value = (linuxcnc.NML_TEXT, "Cycle started")
        text, level = ctrl.poll_errors()
        assert text == "Cycle started"
        assert level == "warning"

    def test_operator_text_returns_info_level(self, ctrl):
        ctrl.error_channel.poll.return_value = (linuxcnc.OPERATOR_TEXT, "Info msg")
        _, level = ctrl.poll_errors()
        assert level == "info"

    def test_no_error_returns_none(self, ctrl):
        ctrl.error_channel.poll.return_value = None
        assert ctrl.poll_errors() is None


# ===========================================================================
# State Control
# ===========================================================================

class TestToggleEstop:
    def test_from_estop_sends_reset(self, ctrl):
        ctrl.status.estop = linuxcnc.STATE_ESTOP
        ctrl.toggle_estop()
        ctrl.command.state.assert_called_with(linuxcnc.STATE_ESTOP_RESET)

    def test_from_reset_sends_estop(self, ctrl):
        ctrl.status.estop = linuxcnc.STATE_ESTOP_RESET
        ctrl.toggle_estop()
        ctrl.command.state.assert_called_with(linuxcnc.STATE_ESTOP)

    def test_calls_poll_first(self, ctrl):
        """toggle_estop() must refresh status before reading estop."""
        ctrl.toggle_estop()
        ctrl.status.poll.assert_called()


class TestSetPower:
    def test_true_sends_state_on(self, ctrl):
        ctrl.set_power(True)
        ctrl.command.state.assert_called_with(linuxcnc.STATE_ON)

    def test_false_sends_state_off(self, ctrl):
        ctrl.set_power(False)
        ctrl.command.state.assert_called_with(linuxcnc.STATE_OFF)


class TestSetMode:
    def test_switches_when_mode_differs(self, ctrl):
        ctrl.status.task_mode = linuxcnc.MODE_MANUAL
        ctrl.set_mode(linuxcnc.MODE_MDI)
        ctrl.command.mode.assert_called_with(linuxcnc.MODE_MDI)
        ctrl.command.wait_complete.assert_called_once()

    def test_skips_command_when_mode_matches(self, ctrl):
        ctrl.status.task_mode = linuxcnc.MODE_AUTO
        ctrl.set_mode(linuxcnc.MODE_AUTO)
        ctrl.command.mode.assert_not_called()
        ctrl.command.wait_complete.assert_not_called()

    def test_polls_before_checking_mode(self, ctrl):
        ctrl.set_mode(linuxcnc.MODE_MANUAL)
        ctrl.status.poll.assert_called()


# ===========================================================================
# Motion Control
# ===========================================================================

class TestHomeAxis:
    def test_homes_specific_axis(self, ctrl):
        ctrl.home_axis(0)
        ctrl.command.home.assert_called_with(0)

    def test_homes_all_axes_with_minus_one(self, ctrl):
        ctrl.home_axis(-1)
        ctrl.command.home.assert_called_with(-1)

    def test_converts_string_argument_to_int(self, ctrl):
        ctrl.home_axis("2")
        ctrl.command.home.assert_called_with(2)

    def test_sets_manual_mode_first(self, ctrl):
        ctrl.status.task_mode = linuxcnc.MODE_AUTO
        ctrl.home_axis(0)
        ctrl.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)

    def test_disables_teleop_before_homing(self, ctrl):
        ctrl.home_axis(0)
        ctrl.command.teleop_enable.assert_called_with(0)


class TestSetTeleop:
    def test_enable_when_not_enabled(self, ctrl):
        ctrl.status.kinematics_type = 0
        ctrl.set_teleop(True)
        ctrl.command.teleop_enable.assert_called_with(1)
        ctrl.command.wait_complete.assert_called_once()

    def test_disable_when_enabled(self, ctrl):
        ctrl.status.kinematics_type = 1
        ctrl.set_teleop(False)
        ctrl.command.teleop_enable.assert_called_with(0)
        ctrl.command.wait_complete.assert_called_once()

    def test_no_op_when_already_in_desired_state(self, ctrl):
        ctrl.status.kinematics_type = 1
        ctrl.set_teleop(True)   # already 1 → no change
        ctrl.command.teleop_enable.assert_not_called()
        ctrl.command.wait_complete.assert_not_called()


class TestIsReady:
    def test_returns_true_when_on_and_not_estopped(self, ctrl):
        ctrl.status.estop      = linuxcnc.STATE_ESTOP_RESET  # falsy (0) is fine too
        ctrl.status.task_state = linuxcnc.STATE_ON
        # STATE_ESTOP_RESET != STATE_ESTOP, so `not estop` depends on the mock value.
        # Use the numeric value from our mock (2 != 1) — is_ready checks `not estop`.
        # To be safe we set estop to the falsy sentinel 0.
        ctrl.status.estop = 0
        assert ctrl.is_ready() is True

    def test_returns_false_when_estopped(self, ctrl):
        ctrl.status.estop      = 1          # truthy → estop active
        ctrl.status.task_state = linuxcnc.STATE_ON
        assert ctrl.is_ready() is False

    def test_returns_false_when_power_off(self, ctrl):
        ctrl.status.estop      = 0
        ctrl.status.task_state = linuxcnc.STATE_OFF
        assert ctrl.is_ready() is False

    def test_returns_false_on_poll_exception(self, ctrl):
        ctrl.status.poll.side_effect = Exception("Connection lost")
        assert ctrl.is_ready() is False

    def test_calls_poll(self, ctrl):
        ctrl.status.estop      = 0
        ctrl.status.task_state = linuxcnc.STATE_ON
        ctrl.is_ready()
        ctrl.status.poll.assert_called()


class TestSyncMode:
    def test_switches_to_manual_then_enables_teleop(self, ctrl):
        ctrl.status.task_mode = linuxcnc.MODE_AUTO
        result = ctrl.sync_mode(want_teleop=True)
        ctrl.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
        ctrl.command.teleop_enable.assert_called_with(1)
        assert ctrl.command.wait_complete.call_count == 2
        assert result is True

    def test_only_sets_teleop_when_already_manual(self, ctrl):
        ctrl.status.task_mode = linuxcnc.MODE_MANUAL
        result = ctrl.sync_mode(want_teleop=False)
        ctrl.command.mode.assert_not_called()
        ctrl.command.teleop_enable.assert_called_with(0)
        assert ctrl.command.wait_complete.call_count == 1
        assert result is True

    def test_returns_false_on_exception(self, ctrl):
        ctrl.command.teleop_enable.side_effect = Exception("Hardware timeout")
        assert ctrl.sync_mode(want_teleop=True) is False


# ===========================================================================
# Jog
# ===========================================================================

class TestJog:
    def test_continuous_positive_axis(self, ctrl):
        """speed=600 unit/min → vel=10 unit/s, flag=0 (axis mode)."""
        ctrl.jog(index=0, direction=1, speed=600.0, increment=0, is_joint=False)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_CONTINUOUS, 0, 0, 10.0)

    def test_continuous_negative_joint(self, ctrl):
        """speed=300 → vel=5, flag=JOG_CMD_FLAG=1, direction negative."""
        ctrl.jog(index=1, direction=-1, speed=300.0, increment=0, is_joint=True)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_CONTINUOUS, 1, 1, -5.0)

    def test_incremental_axis(self, ctrl):
        """Non-zero increment → JOG_INCREMENT with increment argument."""
        ctrl.jog(index=1, direction=1, speed=120.0, increment=5.0, is_joint=False)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_INCREMENT, 0, 1, 2.0, 5.0)

    def test_incremental_joint(self, ctrl):
        ctrl.jog(index=2, direction=1, speed=60.0, increment=1.0, is_joint=True)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_INCREMENT, 1, 2, 1.0, 1.0)

    def test_converts_string_arguments(self, ctrl):
        ctrl.jog(index="0", direction="1", speed="60.0", increment="0", is_joint=False)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_CONTINUOUS, 0, 0, 1.0)

    def test_zero_increment_triggers_continuous(self, ctrl):
        ctrl.jog(index=0, direction=1, speed=60.0, increment=0, is_joint=False)
        args = ctrl.command.jog.call_args[0]
        assert args[0] == linuxcnc.JOG_CONTINUOUS

    def test_nonzero_increment_triggers_incremental(self, ctrl):
        ctrl.jog(index=0, direction=1, speed=60.0, increment=0.1, is_joint=False)
        args = ctrl.command.jog.call_args[0]
        assert args[0] == linuxcnc.JOG_INCREMENT


class TestStopJog:
    def test_stop_axis(self, ctrl):
        ctrl.stop_jog(index=0, is_joint=False)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_STOP, 0, 0)

    def test_stop_joint(self, ctrl):
        ctrl.stop_jog(index=2, is_joint=True)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_STOP, 1, 2)

    def test_converts_string_index(self, ctrl):
        ctrl.stop_jog(index="0", is_joint=False)
        ctrl.command.jog.assert_called_with(linuxcnc.JOG_STOP, 0, 0)


# ===========================================================================
# Overrides
# ===========================================================================

class TestOverrides:
    def test_set_feed_override(self, ctrl):
        ctrl.set_feed_override(1.5)
        ctrl.command.feedrate.assert_called_with(1.5)

    def test_set_rapid_override(self, ctrl):
        ctrl.set_rapid_override(0.5)
        ctrl.command.rapidrate.assert_called_with(0.5)

    def test_set_spindle_override(self, ctrl):
        ctrl.set_spindle_override(1.2)
        ctrl.command.spindleoverride.assert_called_with(1.2)

    def test_set_max_velocity_converts_units(self, ctrl):
        """1200 unit/min ÷ 60 = 20 unit/s."""
        ctrl.set_max_velocity(1200.0)
        ctrl.command.maxvel.assert_called_with(20.0)

    def test_set_max_velocity_zero(self, ctrl):
        ctrl.set_max_velocity(0.0)
        ctrl.command.maxvel.assert_called_with(0.0)


# ===========================================================================
# File Management
# ===========================================================================

class TestIsInterpreterIdle:
    def test_returns_true_when_idle(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        assert ctrl.is_interpreter_idle() is True

    def test_returns_false_when_running(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_READING
        assert ctrl.is_interpreter_idle() is False

    def test_returns_false_when_paused(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_PAUSED
        assert ctrl.is_interpreter_idle() is False

    def test_calls_poll(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        ctrl.is_interpreter_idle()
        ctrl.status.poll.assert_called()


class TestOpenProgram:
    def test_loads_existing_file(self, ctrl, tmp_path):
        f = tmp_path / "part.ngc"
        f.write_text("G0 X10")
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE

        result = ctrl.open_program(str(f))

        assert result is True
        assert ctrl.last_loaded_file == str(f)
        ctrl.command.program_open.assert_called_with(str(f))

    def test_raises_file_not_found(self, ctrl):
        with pytest.raises(FileNotFoundError, match="Файл не знайдено"):
            ctrl.open_program("/no/such/file.ngc")

    def test_raises_runtime_error_when_busy(self, ctrl, tmp_path):
        f = tmp_path / "part.ngc"
        f.write_text("G0 X0")
        ctrl.status.interp_state = linuxcnc.INTERP_READING

        with pytest.raises(RuntimeError, match="інтерпретатор зайнятий"):
            ctrl.open_program(str(f))

    def test_raises_on_linuxcnc_error(self, ctrl, tmp_path):
        f = tmp_path / "part.ngc"
        f.write_text("G0 X0")
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        ctrl.command.program_open.side_effect = Exception("NML error")

        with pytest.raises(Exception, match="LinuxCNC program_open error"):
            ctrl.open_program(str(f))

    def test_does_not_update_last_file_on_failure(self, ctrl, tmp_path):
        f = tmp_path / "part.ngc"
        f.write_text("G0 X0")
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        ctrl.command.program_open.side_effect = Exception("fail")
        ctrl.last_loaded_file = "previous.ngc"

        with pytest.raises(Exception):
            ctrl.open_program(str(f))

        assert ctrl.last_loaded_file == "previous.ngc"


class TestGetLastFile:
    def test_returns_none_initially(self, ctrl):
        ctrl.last_loaded_file = None
        assert ctrl.get_last_file() is None

    def test_returns_previously_loaded_path(self, ctrl):
        ctrl.last_loaded_file = "run.ngc"
        assert ctrl.get_last_file() == "run.ngc"


# ===========================================================================
# Program Execution
# ===========================================================================

class TestCycleStart:
    def test_raises_when_no_file(self, ctrl):
        ctrl.status.file = ""
        with pytest.raises(Exception, match="Файл не завантажено"):
            ctrl.cycle_start()

    def test_raises_when_not_all_homed(self, ctrl):
        ctrl.status.file  = "job.ngc"
        ctrl.status.homed = [1, 1, 0, 0, 0, 0, 0, 0, 0]
        with pytest.raises(Exception, match="Виконайте Home All"):
            ctrl.cycle_start()

    def test_success_switches_to_auto_and_runs(self, ctrl):
        ctrl.status.file  = "job.ngc"
        ctrl.status.homed = [1, 1, 1, 0, 0, 0, 0, 0, 0]

        ctrl.cycle_start(line_number=10)

        ctrl.command.mode.assert_called_with(linuxcnc.MODE_AUTO)
        ctrl.command.wait_complete.assert_called()
        ctrl.command.auto.assert_called_with(linuxcnc.AUTO_RUN, 10)

    def test_default_line_number_is_zero(self, ctrl):
        ctrl.status.file  = "job.ngc"
        ctrl.status.homed = [1, 1, 1, 0, 0, 0, 0, 0, 0]
        ctrl.cycle_start()
        ctrl.command.auto.assert_called_with(linuxcnc.AUTO_RUN, 0)


class TestCycleResume:
    def test_resumes_paused_program(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_PAUSED
        ctrl.status.task_mode    = linuxcnc.MODE_MANUAL

        ctrl.cycle_resume()

        ctrl.command.mode.assert_called_with(linuxcnc.MODE_AUTO)
        ctrl.command.auto.assert_called_with(linuxcnc.AUTO_RESUME)

    def test_no_op_when_not_paused(self, ctrl):
        """cycle_resume() must be silent when the interpreter is not paused."""
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        ctrl.cycle_resume()
        ctrl.command.auto.assert_not_called()

    def test_skips_mode_switch_when_already_auto(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_PAUSED
        ctrl.status.task_mode    = linuxcnc.MODE_AUTO
        ctrl.cycle_resume()
        ctrl.command.mode.assert_not_called()
        ctrl.command.auto.assert_called_with(linuxcnc.AUTO_RESUME)


class TestCyclePause:
    def test_sends_auto_pause(self, ctrl):
        ctrl.cycle_pause()
        ctrl.command.auto.assert_called_with(linuxcnc.AUTO_PAUSE)


class TestCycleStop:
    def test_aborts_and_switches_to_manual(self, ctrl):
        ctrl.cycle_stop()
        ctrl.command.abort.assert_called_once()
        ctrl.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)

    def test_wait_complete_called_after_abort(self, ctrl):
        ctrl.cycle_stop()
        # abort → wait_complete → mode
        assert ctrl.command.wait_complete.call_count >= 1


class TestCycleStep:
    def test_executes_one_step(self, ctrl):
        ctrl.status.file  = "job.ngc"
        ctrl.status.homed = [1, 1, 1, 0, 0, 0, 0, 0, 0]
        ctrl.status.task_mode = linuxcnc.MODE_AUTO

        ctrl.cycle_step()

        ctrl.command.auto.assert_called_with(linuxcnc.AUTO_STEP)

    def test_switches_to_auto_if_needed(self, ctrl):
        ctrl.status.file      = "job.ngc"
        ctrl.status.homed     = [1, 1, 1, 0, 0, 0, 0, 0, 0]
        ctrl.status.task_mode = linuxcnc.MODE_MANUAL

        ctrl.cycle_step()

        ctrl.command.mode.assert_called_with(linuxcnc.MODE_AUTO)

    def test_no_op_when_no_file(self, ctrl):
        ctrl.status.file  = ""
        ctrl.status.homed = [1, 1, 1, 0, 0, 0, 0, 0, 0]
        ctrl.cycle_step()
        ctrl.command.auto.assert_not_called()

    def test_no_op_when_not_homed(self, ctrl):
        ctrl.status.file  = "job.ngc"
        ctrl.status.homed = [1, 0, 1, 0, 0, 0, 0, 0, 0]
        ctrl.cycle_step()
        ctrl.command.auto.assert_not_called()


# ===========================================================================
# MDI and Custom Commands
# ===========================================================================

class TestSendMdi:
    def test_success_restores_previous_mode(self, ctrl):
        ctrl.status.task_mode   = linuxcnc.MODE_MANUAL
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE

        result = ctrl.send_mdi("G0 X50")

        ctrl.command.mode.assert_any_call(linuxcnc.MODE_MDI)
        ctrl.command.mdi.assert_called_with("G0 X50")
        ctrl.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
        assert result is True
        assert ctrl.command.wait_complete.call_count >= 2

    def test_rejected_when_interpreter_busy(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_READING
        result = ctrl.send_mdi("G0 Y20")
        ctrl.command.mdi.assert_not_called()
        assert result is False

    def test_returns_false_on_mdi_exception(self, ctrl):
        ctrl.status.task_mode    = linuxcnc.MODE_MANUAL
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        ctrl.command.mdi.side_effect = Exception("MDI failed")

        assert ctrl.send_mdi("G0 Z0") is False

    def test_no_mode_switch_when_already_mdi(self, ctrl):
        ctrl.status.task_mode    = linuxcnc.MODE_MDI
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE

        ctrl.send_mdi("G28")

        # mode() should NOT be called at all (already in MDI, nothing to restore)
        ctrl.command.mode.assert_not_called()


class TestSetGripperForce:
    def test_writes_to_analog_output(self, ctrl):
        ctrl.set_gripper_force(0.75)
        ctrl.command.set_analog_output.assert_called_with(1, 0.75)

    def test_converts_string_to_float(self, ctrl):
        ctrl.set_gripper_force("0.5")
        ctrl.command.set_analog_output.assert_called_with(1, 0.5)

    def test_full_force(self, ctrl):
        ctrl.set_gripper_force(1.0)
        ctrl.command.set_analog_output.assert_called_with(1, 1.0)

    def test_zero_force(self, ctrl):
        ctrl.set_gripper_force(0.0)
        ctrl.command.set_analog_output.assert_called_with(1, 0.0)


# ===========================================================================
# Helpers / Getters
# ===========================================================================

class TestIsIdle:
    def test_true_when_idle(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        assert ctrl.is_idle() is True

    def test_false_when_reading(self, ctrl):
        ctrl.status.interp_state = linuxcnc.INTERP_READING
        assert ctrl.is_idle() is False


class TestGetPosition:
    def test_returns_position_tuple(self, ctrl):
        ctrl.status.position = (1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
        pos = ctrl.get_position()
        assert pos == (1.0, 2.0, 3.0, 0.0, 0.0, 0.0)

    def test_calls_poll(self, ctrl):
        ctrl.get_position()
        ctrl.status.poll.assert_called()


class TestGetStates:
    def _configured_ctrl(self, ctrl):
        ctrl.status.task_state       = linuxcnc.STATE_ON
        ctrl.status.estop            = linuxcnc.STATE_ESTOP_RESET
        ctrl.status.interp_state     = linuxcnc.INTERP_IDLE
        ctrl.status.file             = "job.ngc"
        ctrl.status.homed            = [1, 1, 1, 0, 0, 0]
        ctrl.params                  = {"JOINTS_COUNT": 3}
        ctrl.status.actual_position  = (10.0, 20.0, -5.0, 0, 0, 0)
        ctrl.status.joint_actual_position = (10.0, 20.0, -5.0, 0, 0, 0)
        ctrl.status.gcodes           = [80]
        ctrl.status.mcodes           = [5]
        ctrl.status.settings         = (0, 0, 0)
        ctrl.status.motion_line      = 0
        ctrl.status.kinematics_type  = 1
        return ctrl

    def test_power_and_ready_flags(self, ctrl):
        c = self._configured_ctrl(ctrl)
        states = c.get_states()
        assert states["power_on"]  is True
        assert states["is_ready"]  is True

    def test_all_homed_true_when_all_homed(self, ctrl):
        c = self._configured_ctrl(ctrl)
        assert c.get_states()["all_homed"] is True

    def test_all_homed_false_when_partially_homed(self, ctrl):
        c = self._configured_ctrl(ctrl)
        c.status.homed = [1, 0, 1, 0, 0, 0]
        assert c.get_states()["all_homed"] is False

    def test_interpreter_state_flags(self, ctrl):
        c = self._configured_ctrl(ctrl)
        c.status.interp_state = linuxcnc.INTERP_PAUSED
        states = c.get_states()
        assert states["is_idle"]    is False
        assert states["is_paused"]  is True
        assert states["is_running"] is False

    def test_running_flag_for_reading(self, ctrl):
        c = self._configured_ctrl(ctrl)
        c.status.interp_state = linuxcnc.INTERP_READING
        assert c.get_states()["is_running"] is True

    def test_has_file_flag(self, ctrl):
        c = self._configured_ctrl(ctrl)
        c.status.file = "test.ngc"
        assert c.get_states()["has_file"] is True

    def test_no_file_flag(self, ctrl):
        c = self._configured_ctrl(ctrl)
        c.status.file = ""
        assert c.get_states()["has_file"] is False

    def test_position_returned(self, ctrl):
        c = self._configured_ctrl(ctrl)
        assert c.get_states()["actual_position"][0] == 10.0

    def test_teleop_flag(self, ctrl):
        c = self._configured_ctrl(ctrl)
        c.status.kinematics_type = 1
        assert c.get_states()["teleop"] is True

    def test_current_file_in_states(self, ctrl):
        c = self._configured_ctrl(ctrl)
        assert c.get_states()["current_file"] == "job.ngc"


class TestCanHome:
    def test_true_when_all_conditions_met(self, ctrl):
        ctrl.status.estop        = linuxcnc.STATE_ESTOP_RESET
        ctrl.status.task_state   = linuxcnc.STATE_ON
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        assert ctrl.can_home() is True

    def test_false_when_estopped(self, ctrl):
        ctrl.status.estop        = linuxcnc.STATE_ESTOP
        ctrl.status.task_state   = linuxcnc.STATE_ON
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        assert ctrl.can_home() is False

    def test_false_when_power_off(self, ctrl):
        ctrl.status.estop        = linuxcnc.STATE_ESTOP_RESET
        ctrl.status.task_state   = linuxcnc.STATE_OFF
        ctrl.status.interp_state = linuxcnc.INTERP_IDLE
        assert ctrl.can_home() is False

    def test_false_when_interpreter_busy(self, ctrl):
        ctrl.status.estop        = linuxcnc.STATE_ESTOP_RESET
        ctrl.status.task_state   = linuxcnc.STATE_ON
        ctrl.status.interp_state = linuxcnc.INTERP_READING
        assert ctrl.can_home() is False


class TestIsAllHomed:
    def test_true_when_all_joints_homed(self, ctrl):
        ctrl.status.homed = [1, 1, 1, 1, 1, 1]
        ctrl.params = {"JOINTS_COUNT": 6}
        assert ctrl.is_all_homed() is True

    def test_false_when_one_joint_not_homed(self, ctrl):
        ctrl.status.homed = [1, 1, 1, 1, 1, 0]
        ctrl.params = {"JOINTS_COUNT": 6}
        assert ctrl.is_all_homed() is False

    def test_uses_joints_count_from_params(self, ctrl):
        """With JOINTS_COUNT=3 only the first three indices matter."""
        ctrl.status.homed = [1, 1, 1, 0, 0, 0]
        ctrl.params = {"JOINTS_COUNT": 3}
        assert ctrl.is_all_homed() is True


class TestHomeAllSequence:
    def test_correct_command_order(self, ctrl):
        ctrl.status.task_mode = linuxcnc.MODE_AUTO   # needs switching
        ctrl.status.kinematics_type = 1               # needs teleop disable

        ctrl.home_all_sequence()

        ctrl.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
        ctrl.command.teleop_enable.assert_called_with(0)
        ctrl.command.home.assert_called_with(-1)