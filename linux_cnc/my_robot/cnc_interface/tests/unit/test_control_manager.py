import pytest
import unittest
from unittest.mock import MagicMock
from logic.managers.control_manager import ControlManager

# Fixtures to mock dependencies
@pytest.fixture
def mock_cnc():
    cnc = MagicMock()
    cnc.speed = 100
    return cnc

@pytest.fixture
def mock_widgets():
    return MagicMock()

@pytest.fixture
def manager(mock_cnc, mock_widgets):
    return ControlManager(mock_cnc, mock_widgets)

# --- TESTS FOR toggle_power ---

def test_toggle_power_turns_on(manager, mock_cnc):
    """Check that power turns on"""
    manager.toggle_power(current_power_state=False)
    mock_cnc.poll.assert_called_once()
    mock_cnc.set_power.assert_called_with(True)

def test_toggle_power_turns_off_and_resets_homing_flag(manager, mock_cnc):
    """Check that turning off resets homing_complete_shown flag"""
    manager.homing_complete_shown = True
    manager.toggle_power(current_power_state=True)
    
    mock_cnc.set_power.assert_called_with(False)
    assert manager.homing_complete_shown is False

def test_toggle_power_handles_exception(manager, mock_cnc):
    """Check robustness against errors (e.g. lost connection)"""
    mock_cnc.poll.side_effect = Exception("CNC Connection Lost")
    # The test should not fail with an exception
    manager.toggle_power(False) 
    print("Exception handled correctly")

# --- TESTS FOR execute_homing ---

def test_execute_homing_aborts_if_not_ready(manager, mock_cnc):
    """Homing does not start if the machine is not ready (e.g. E-Stop pressed)"""
    mock_cnc.can_home.return_value = False
    manager.execute_homing()
    mock_cnc.home_all_sequence.assert_not_called()

def test_execute_homing_starts_immediately_if_not_homed(manager, mock_cnc):
    """Homing starts immediately if the machine is not homed yet"""
    mock_cnc.can_home.return_value = True
    mock_cnc.is_all_homed.return_value = False
    
    manager.execute_homing()
    mock_cnc.home_all_sequence.assert_called_once()

def test_execute_homing_with_confirmation_ok(manager, mock_cnc, mocker):
    """If already homed, homing starts only after confirmation (OK)"""
    mock_cnc.can_home.return_value = True
    mock_cnc.is_all_homed.return_value = True
    # Simulate user choosing "OK"
    mocker.patch('logic.managers.control_manager.MachineDialogs.confirm_rehome', return_value=True)
    
    manager.execute_homing()
    mock_cnc.home_all_sequence.assert_called_once()

def test_execute_homing_with_confirmation_cancel(manager, mock_cnc, mocker):
    """If already homed and user presses Cancel — nothing happens"""
    mock_cnc.can_home.return_value = True
    mock_cnc.is_all_homed.return_value = True
    # Simulate user choosing "Cancel"
    mocker.patch('logic.managers.control_manager.MachineDialogs.confirm_rehome', return_value=False)
    
    manager.execute_homing()
    mock_cnc.home_all_sequence.assert_not_called()

# --- TESTS FOR switch_control_mode ---

@pytest.mark.parametrize("panel_type, expected_teleop", [
    ("axis", True),
    ("joint", False)
])
def test_switch_control_mode_logic(manager, mock_cnc, panel_type, expected_teleop):
    """Check mode switching when conditions are met (ready + homed)"""
    manager.switch_control_mode(panel_type, is_ready=True, all_homed=True)
    
    assert mock_cnc.manual_mode == panel_type
    mock_cnc.set_teleop.assert_called_with(expected_teleop)

def test_switch_control_mode_ignores_if_not_homed(manager, mock_cnc):
    """Mode should not change if machine is not ready or not homed"""
    manager.switch_control_mode("axis", is_ready=True, all_homed=False)
    
    assert mock_cnc.set_teleop.call_count == 0
    # Check that manual_mode attribute did not change (remains default)
    assert not hasattr(mock_cnc, 'manual_mode') or mock_cnc.manual_mode != "axis"
    
def test_power_off_with_empty_states(manager, mock_cnc):
    # Check: ensure no KeyError occurs if the dictionary is empty
    manager.on_btn_power_off_clicked({}) 
    mock_cnc.set_power.assert_called_with(True) # because not False = True
    
def test_power_toggle_order(manager, mock_cnc):
    manager.toggle_power(False)
    # Verify that poll() was called BEFORE set_power()
    expected_calls = [unittest.mock.call.poll(), unittest.mock.call.set_power(True)]
    assert mock_cnc.mock_calls == expected_calls