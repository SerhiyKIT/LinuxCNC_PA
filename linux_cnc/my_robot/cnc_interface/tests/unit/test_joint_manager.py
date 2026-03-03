import pytest
from unittest.mock import MagicMock
from logic.managers.joint_manager import JointManager

@pytest.fixture
def mock_cnc():
    """Create a mock CNC controller."""
    cnc = MagicMock()
    cnc.angular_jog_speed = 500.0  # Angular speed for joints
    cnc.is_ready.return_value = True
    return cnc

@pytest.fixture
def joint_manager(mock_cnc):
    """Initialize JointManager with a mock CNC controller."""
    return JointManager(mock_cnc)

# --- PARSING TESTS ---

@pytest.mark.parametrize("input_text, expected_output", [
    ("Continuous", 0.0),
    ("0.5", 0.5),
    ("invalid_val", 0.0),
    ("", 0.0)
])
def test_parse_increment(joint_manager, input_text, expected_output):
    """Verify safe conversion of increment text to float."""
    assert joint_manager._parse_increment(input_text) == expected_output

# --- JOINT MOVEMENT LOGIC TESTS ---

def test_start_jog_joint_settings(joint_manager, mock_cnc):
    """Check joint-specific settings (is_joint=True) during jog start."""
    joint_manager.start_jog(joint_idx=3, direction=1, mode_text="Continuous")
    
    # 1. Ensure switching to Joint Mode (teleop=False)
    mock_cnc.sync_mode.assert_called_with(want_teleop=False)
    
    # 2. Ensure angular speed and joint flag are used
    mock_cnc.jog.assert_called_once_with(
        3, 1, 500.0, 0.0, is_joint=True
    )

def test_start_jog_not_ready(joint_manager, mock_cnc):
    """Verify jog does not start if CNC is not ready."""
    mock_cnc.is_ready.return_value = False
    joint_manager.start_jog(0, 1, "Continuous")
    mock_cnc.jog.assert_not_called()

def test_stop_jog_only_for_continuous(joint_manager, mock_cnc):
    """Ensure stop_jog is called only in Continuous mode."""
    # Scenario 1: Continuous mode - stop should be called
    joint_manager.stop_jog(0, "Continuous")
    mock_cnc.stop_jog.assert_called_with(0, is_joint=True)
    
    # Scenario 2: Incremental mode - stop should not be called
    mock_cnc.stop_jog.reset_mock()
    joint_manager.stop_jog(0, "0.1")
    mock_cnc.stop_jog.assert_not_called()

# --- SAFETY AND SEQUENCE TESTS ---

def test_jog_sequence_safety(joint_manager, mock_cnc):
    """Verify sync_mode is called before jog for safety."""
    joint_manager.start_jog(0, 1, "Continuous")
    
    # Get the names of called methods in order
    method_names = [call[0] for call in mock_cnc.method_calls]
    
    assert 'sync_mode' in method_names
    assert 'jog' in method_names
    assert method_names.index('sync_mode') < method_names.index('jog'), \
        "sync_mode must be called BEFORE jog command"

def test_start_jog_exception_handling(joint_manager, mock_cnc):
    """Ensure internal CNC exceptions do not propagate."""
    mock_cnc.jog.side_effect = Exception("Joint Motor Timeout")
    
    # The call should not raise an exception to the test level
    try:
        joint_manager.start_jog(0, 1, "Continuous")
    except Exception as e:
        pytest.fail(f"Exception was not handled: {e}")
        
def test_joint_uses_correct_speed_type(joint_manager, mock_cnc):
    """
    Critical test: Ensure JointManager uses angular speed for joints,
    not linear speed intended for axes (XYZ).
    """
    mock_cnc.linear_jog_speed = 1000.0  # High speed for axes
    mock_cnc.angular_jog_speed = 50.0   # Low speed for joints
    
    joint_manager.start_jog(0, 1, "Continuous")
    
    # Verify that jog uses 50.0 (angular), not 1000.0 (linear)
    args = mock_cnc.jog.call_args[0]
    assert args[2] == 50.0
    assert args[2] != 1000.0

def test_joint_idx_boundaries(joint_manager, mock_cnc):
    """
    Verify correct handling of boundary joint indices (J0 and J5).
    """
    # Test first joint
    joint_manager.start_jog(0, 1, "Continuous")
    mock_cnc.jog.assert_called_with(0, 1, 500.0, 0.0, is_joint=True)
    
    mock_cnc.jog.reset_mock()
    
    # Test last joint (for 6-axis robot)
    joint_manager.start_jog(5, -1, "Continuous")
    mock_cnc.jog.assert_called_with(5, -1, 500.0, 0.0, is_joint=True)