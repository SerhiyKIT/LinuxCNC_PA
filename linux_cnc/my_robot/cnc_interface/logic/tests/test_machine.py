import pytest
from unittest.mock import patch, MagicMock
import linuxcnc
import os
import sys

# Add project root to sys.path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from logic.core.machine import MachineController

@pytest.fixture
def controller_setup():
    """Fixture to create controller with all necessary mocks"""
    with patch('linuxcnc.stat', return_value=MagicMock()), \
         patch('linuxcnc.command', return_value=MagicMock()), \
         patch('linuxcnc.error_channel', return_value=MagicMock()), \
         patch('logic.core.machine.config') as mock_config:
        
        mock_config.MACHINE_PARAMS = {"LINEAR_VEL": 1.0, "JOG_CMD_FLAG": 1}
        mock_config.JOINT_LIMITS = {}
        mock_config.DEFAULT_MANUAL_MODE = 'axis'
        
        controller = MachineController()
        yield controller

# --- TESTS POLLING / STATUS ---

def test_poll_calls_linuxcnc(controller_setup):
    # poll() should call status.poll()
    c = controller_setup
    c.poll()
    c.status.poll.assert_called_once()

def test_poll_updates_data(controller_setup):
    # poll() should update status data
    c = controller_setup

    def mock_poll_effect():
        c.status.task_state = linuxcnc.STATE_ON

    c.status.poll.side_effect = mock_poll_effect()
    c.poll()

    assert c.status.task_state == linuxcnc.STATE_ON

def test_poll_errors_critical(controller_setup):
    # poll_errors() should return error for NML_ERROR
    c = controller_setup
    c.error_channel.poll.return_value = (linuxcnc.NML_ERROR, "Joint 0 following error")

    text, level = c.poll_errors()

    assert text == "Joint 0 following error"
    assert level == "error"

def test_poll_errors_warning(controller_setup):
    # poll_errors() should return warning for NML_TEXT
    c = controller_setup
    c.error_channel.poll.return_value = (linuxcnc.NML_TEXT, "Cycle started")

    text, level = c.poll_errors()

    assert text == "Cycle started"
    assert level == "warning"

def test_poll_errors_none(controller_setup):
    # poll_errors() should return None if no error
    c = controller_setup
    c.error_channel.poll.return_value = None

    result = c.poll_errors()

    assert result is None

# --- TESTS STATE CONTROL ---

def test_toggle_estop_from_error_to_reset(controller_setup):
    # toggle_estop() should reset from ESTOP
    c = controller_setup

    c.status.estop = linuxcnc.STATE_ESTOP
    c.toggle_estop()
    
    c.status.poll.assert_called()
    c.command.state.assert_called_with(linuxcnc.STATE_ESTOP_RESET)

def test_toggle_estop_from_reset_to_error(controller_setup):
    # toggle_estop() should activate ESTOP from reset
    c = controller_setup

    c.status.estop = linuxcnc.STATE_ESTOP_RESET
    c.toggle_estop()

    c.command.state.assert_called_with(linuxcnc.STATE_ESTOP)

def test_set_power_on(controller_setup):
    # set_power(True) should turn power ON
    c = controller_setup

    c.set_power(True)

    c.command.state.assert_called_with(linuxcnc.STATE_ON)

def test_set_power_off(controller_setup):
    # set_power(False) should turn power OFF
    c = controller_setup

    c.set_power(False)

    c.command.state.assert_called_with(linuxcnc.STATE_OFF)
    
def test_set_mode_changes_when_different(controller_setup):
    # set_mode() should change mode if different
    c = controller_setup
    
    c.status.task_mode = linuxcnc.MODE_MANUAL
    target_mode = linuxcnc.MODE_MDI
    
    c.set_mode(target_mode)
    
    c.status.poll.assert_called()
    c.command.mode.assert_called_with(target_mode)
    c.command.wait_complete.assert_called_once()

def test_set_mode_skips_when_already_set(controller_setup):
    # set_mode() should do nothing if mode is already set
    c = controller_setup
    
    c.status.task_mode = linuxcnc.MODE_AUTO
    
    c.set_mode(linuxcnc.MODE_AUTO)
    
    c.command.mode.assert_not_called()
    c.command.wait_complete.assert_not_called()
    
# --- TESTS MOTION CONTROL ---

def test_home_specific_axis(controller_setup):
    # home_axis() should home specific axis
    c = controller_setup
    
    c.home_axis(0)
    
    c.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
    c.command.teleop_enable.assert_called_with(0)
    c.command.home.assert_called_with(0)

def test_home_all_axes(controller_setup):
    # home_axis(-1) should home all axes
    c = controller_setup
    
    c.home_axis(-1)
    
    c.command.home.assert_called_with(-1)

def test_home_axis_converts_string_to_int(controller_setup):
    # home_axis() should convert string to int
    c = controller_setup
    
    c.home_axis("2")
    
    c.command.home.assert_called_with(2)
    
def test_set_teleop_enable(controller_setup):
    # set_teleop(True) should enable teleop
    c = controller_setup
    c.status.kinematics_type = 0 
    
    c.set_teleop(True)
    
    c.command.teleop_enable.assert_called_with(1)
    c.command.wait_complete.assert_called_once()

def test_set_teleop_disable(controller_setup):
    # set_teleop(False) should disable teleop
    c = controller_setup
    c.status.kinematics_type = 1
    c.set_teleop(False)
    
    c.command.teleop_enable.assert_called_with(0)
    c.command.wait_complete.assert_called_once()

def test_set_teleop_no_change(controller_setup):
    # set_teleop() should do nothing if already set
    c = controller_setup
    c.status.kinematics_type = 1
    
    c.set_teleop(True) 
    
    c.command.teleop_enable.assert_not_called()
    c.command.wait_complete.assert_not_called()
    
def test_is_ready_success(controller_setup):
    # is_ready() should return True if ready
    c = controller_setup
    
    c.status.estop = 0 
    c.status.task_state = linuxcnc.STATE_ON
    
    assert c.is_ready() is True
    c.status.poll.assert_called()

def test_is_ready_fails_on_estop(controller_setup):
    # is_ready() should return False if ESTOP is pressed
    c = controller_setup
    
    c.status.estop = 1  
    c.status.task_state = linuxcnc.STATE_ON
    
    assert c.is_ready() is False

def test_is_ready_fails_on_power_off(controller_setup):
    # is_ready() should return False if power is OFF
    c = controller_setup
    
    c.status.estop = 0
    c.status.task_state = linuxcnc.STATE_OFF
    
    assert c.is_ready() is False

def test_is_ready_handles_exception(controller_setup):
    # is_ready() should handle exceptions in poll()
    c = controller_setup
    
    c.status.poll.side_effect = Exception("Connection lost")
    
    assert c.is_ready() is False
    
def test_sync_mode_full_setup(controller_setup):
    # sync_mode() should set MANUAL and enable teleop if needed
    c = controller_setup
    
    c.status.task_mode = linuxcnc.MODE_AUTO
    
    result = c.sync_mode(want_teleop=True)
    
    c.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
    c.command.teleop_enable.assert_called_with(1)
    assert c.command.wait_complete.call_count == 2
    assert result is True

def test_sync_mode_partial_setup(controller_setup):
    # sync_mode() should only enable/disable teleop if mode is correct
    c = controller_setup
    
    c.status.task_mode = linuxcnc.MODE_MANUAL
    
    result = c.sync_mode(want_teleop=False)
    
    c.command.mode.assert_not_called()
    c.command.teleop_enable.assert_called_with(0)
    assert c.command.wait_complete.call_count == 1
    assert result is True

def test_sync_mode_error_handling(controller_setup):
    # sync_mode() should return False on exception
    c = controller_setup
    
    c.command.teleop_enable.side_effect = Exception("Hardware timeout")
    
    result = c.sync_mode(want_teleop=True)
    
    assert result is False

# --- TESTS FOR JOG (MANUAL CONTROL) ---

def test_jog_continuous_positive(controller_setup):
    # Test continuous forward movement (X+)
    c = controller_setup
    
    c.jog(index=0, direction=1, speed=600.0, increment=0, is_joint=False)
    
    c.command.jog.assert_called_with(linuxcnc.JOG_CONTINUOUS, 0, 0, 10.0)

def test_jog_continuous_negative_joint(controller_setup):
    # Test continuous backward movement in Joint mode (Joint 1-)
    c = controller_setup
    
    c.jog(index=1, direction=-1, speed=300.0, increment=0, is_joint=True)
    
    c.command.jog.assert_called_with(linuxcnc.JOG_CONTINUOUS, 1, 1, -5.0)

def test_jog_incremental_logic(controller_setup):
    # Test incremental movement (Y+)
    c = controller_setup
    
    c.jog(index=1, direction=1, speed=120.0, increment=5.0, is_joint=False)
    
    c.command.jog.assert_called_with(linuxcnc.JOG_INCREMENT, 0, 1, 2.0, 5.0)

def test_jog_converts_types(controller_setup):
    # Check if the method correctly converts strings to numbers
    c = controller_setup
    
    c.jog(index="0", direction="1", speed="60.0", increment="0", is_joint=False)
    
    c.command.jog.assert_called_with(linuxcnc.JOG_CONTINUOUS, 0, 0, 1.0)
    
# --- TESTS OVERRIDES ---

def test_stop_jog(controller_setup):
    # Check stopping movement for a specific axis
    c = controller_setup
    
    c.stop_jog(index="0", is_joint=False)
    
    c.command.jog.assert_called_with(linuxcnc.JOG_STOP, 0, 0)

def test_set_feed_override(controller_setup):
    # Check feed override (1.2 = 120%)
    c = controller_setup
    
    c.set_feed_override("1.2")
    
    c.command.feedrate.assert_called()

def test_set_max_velocity_math(controller_setup):
    # Check conversion of max velocity (min -> sec)
    c = controller_setup
    
    c.set_max_velocity(1200.0)
    
    c.command.maxvel.assert_called_with(20.0)
    
# --- TESTS FILE MANAGEMENT ---

def test_is_interpreter_idle_true(controller_setup):
    # Check interpreter idle state
    c = controller_setup
    
    c.status.interp_state = linuxcnc.INTERP_IDLE
    
    assert c.is_interpreter_idle() is True
    c.status.poll.assert_called()

def test_open_program_success(controller_setup, tmp_path):
    # Test successful file loading
    c = controller_setup
    
    test_file = tmp_path / "test.ngc"
    test_file.write_text("G0 X10")
    
    c.status.interp_state = linuxcnc.INTERP_IDLE
    
    result = c.open_program(str(test_file))
    
    assert result is True
    assert c.last_loaded_file == str(test_file)
    c.command.program_open.assert_called_with(str(test_file))

def test_open_program_file_not_found(controller_setup):
    # Test error: file does not exist
    c = controller_setup
    
    with pytest.raises(FileNotFoundError):
        c.open_program("/non/existent/path.ngc")

def test_get_last_file(controller_setup):
    # Check saving the path of the last file
    c = controller_setup
    c.last_loaded_file = "last_run.ngc"
    
    assert c.get_last_file() == "last_run.ngc"
    
# --- TESTS PROGRAM EXECUTION ---

def test_cycle_start_fails_no_file(controller_setup):
    # Prevent starting if no file is loaded
    c = controller_setup
    c.status.file = ""
    
    with pytest.raises(Exception, match="Файл не завантажено"):
        c.cycle_start()

def test_cycle_start_fails_not_homed(controller_setup):
    # Prevent starting if not all axes are homed
    c = controller_setup
    c.status.file = "test.ngc"
    c.status.homed = [1, 1, 0, 0, 0, 0, 0, 0, 0]
    
    with pytest.raises(Exception, match="Виконайте Home All"):
        c.cycle_start()

def test_cycle_start_success(controller_setup):
    # Successful program start with switching to AUTO mode
    c = controller_setup
    c.status.file = "test.ngc"
    c.status.homed = [1, 1, 1, 0, 0, 0, 0, 0, 0] 
    
    c.cycle_start(line_number=10)
    
    c.command.mode.assert_called_with(linuxcnc.MODE_AUTO)
    c.command.wait_complete.assert_called()
    c.command.auto.assert_called_with(linuxcnc.AUTO_RUN, 10)

def test_cycle_resume_from_paused(controller_setup):
    # Resume execution after pause
    c = controller_setup
    c.status.interp_state = linuxcnc.INTERP_PAUSED
    c.status.task_mode = linuxcnc.MODE_MANUAL 
    
    c.cycle_resume()
    
    c.command.mode.assert_called_with(linuxcnc.MODE_AUTO)
    c.command.auto.assert_called_with(linuxcnc.AUTO_RESUME)

def test_cycle_stop(controller_setup):
    # Stop cycle (Abort) and switch to manual mode
    c = controller_setup
    
    c.cycle_stop()
    
    c.command.abort.assert_called_once()
    c.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
    
# --- TESTS MDI and Custom Commands ---
def test_send_mdi_success_with_mode_restore(controller_setup):
    # Test successful MDI command with restoring previous mode (Manual)
    c = controller_setup
    
    c.status.task_mode = linuxcnc.MODE_MANUAL
    c.status.interp_state = linuxcnc.INTERP_IDLE
    
    result = c.send_mdi("G0 X50")
    
    c.command.mode.assert_any_call(linuxcnc.MODE_MDI)
    c.command.mdi.assert_called_with("G0 X50")
    c.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
    
    assert result is True
    assert c.command.wait_complete.call_count >= 2

def test_send_mdi_rejected_when_busy(controller_setup):
    # MDI should be rejected if the machine is running a program
    c = controller_setup
    c.status.interp_state = linuxcnc.INTERP_READING 
    
    result = c.send_mdi("G0 Y20")
    
    c.command.mdi.assert_not_called()
    assert result is False

def test_set_gripper_force(controller_setup):
    # Check writing to HAL analog output (e.g., for gripper force)
    c = controller_setup
    
    c.set_gripper_force("0.75")
    
    c.command.set_analog_output.assert_called_with(1, 0.75)

# --- TESTS HELPERS / GETTERS ---

def test_get_states_comprehensive(controller_setup):
    # Test that get_states() returns a comprehensive and correct state dictionary
    c = controller_setup
    
    c.status.task_state = linuxcnc.STATE_ON
    c.status.estop = linuxcnc.STATE_ESTOP_RESET
    
    c.status.interp_state = linuxcnc.INTERP_IDLE
    c.status.file = "path/to/job.ngc"
    
    c.status.homed = [1, 1, 1, 0, 0, 0]
    c.params = {"JOINTS_COUNT": 3}
    
    c.status.actual_position = (10.0, 20.0, -5.0, 0, 0, 0)
    c.status.joint_actual_position = (10.0, 20.0, -5.0, 0, 0, 0)
    
    c.status.gcodes = [80]
    c.status.mcodes = [5]
    c.status.settings = (0, 0, 0)
    c.status.motion_line = 0
    c.status.kinematics_type = 1

    states = c.get_states()
    
    assert states['power_on'] is True
    assert states['is_ready'] is True
    assert states['all_homed'] is True 
    assert states['actual_position'][0] == 10.0
    assert states['current_file'] == "path/to/job.ngc"

def test_can_home_conditions(controller_setup):
    # Test that can_home() returns True when all conditions for homing are met
    c = controller_setup
    
    c.status.estop = linuxcnc.STATE_ESTOP_RESET 
    c.status.task_state = linuxcnc.STATE_ON
    c.status.interp_state = linuxcnc.INTERP_IDLE
    
    assert c.can_home() is True

def test_home_all_sequence_logic(controller_setup):
    # Test that home_all_sequence() performs the correct command sequence for homing all axes
    c = controller_setup
    
    c.home_all_sequence()
    
    c.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
    c.command.teleop_enable.assert_called_with(0)
    c.command.home.assert_called_with(-1)