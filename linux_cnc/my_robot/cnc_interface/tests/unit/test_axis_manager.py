import pytest
from unittest.mock import MagicMock
from logic.managers.axis_manager import AxisManager


@pytest.fixture
def mock_cnc():
    """Creates a mock CNC controller object with default parameters."""
    cnc = MagicMock()
    cnc.linear_jog_speed = 1200.0  # Default jogging speed
    cnc.is_ready.return_value = True
    return cnc


@pytest.fixture
def axis_manager(mock_cnc):
    """Initializes AxisManager with the mock CNC controller."""
    return AxisManager(mock_cnc)


# --- PARSING TESTS (method: _parse_increment) ---


@pytest.mark.parametrize(
    "input_text, expected_output",
    [
        ("Continuous", 0.0),
        ("0.1", 0.1),
        ("1.0", 1.0),
        ("invalid", 0.0),  # Defensive check: non-numeric string
        (None, 0.0),       # Defensive check: None value
    ],
)
def test_parse_increment(axis_manager, input_text, expected_output):
    """Verifies correct conversion of UI text input to numeric CNC value."""
    assert axis_manager._parse_increment(input_text) == expected_output


# --- JOG START TESTS (method: start_jog) ---


def test_start_jog_not_ready(axis_manager, mock_cnc):
    """Jog command should not execute if CNC is not ready (E-Stop/Power Off)."""
    mock_cnc.is_ready.return_value = False

    axis_manager.start_jog(axis_idx=0, direction=1, mode_text="Continuous")

    mock_cnc.jog.assert_not_called()


def test_start_jog_continuous(axis_manager, mock_cnc):
    """Verifies starting continuous jog mode."""
    axis_manager.start_jog(axis_idx=1, direction=-1, mode_text="Continuous")

    # Ensures sync_mode is called first for telemetry
    mock_cnc.sync_mode.assert_called_with(want_teleop=True)
    # Checks jog call parameters
    mock_cnc.jog.assert_called_once_with(1, -1, 1200.0, 0.0, is_joint=False)


def test_start_jog_incremental(axis_manager, mock_cnc):
    """Verifies starting incremental jog mode."""
    axis_manager.start_jog(axis_idx=2, direction=1, mode_text="0.5")

    mock_cnc.jog.assert_called_once_with(2, 1, 1200.0, 0.5, is_joint=False)


# --- JOG STOP TESTS (method: stop_jog) ---


def test_stop_jog_in_continuous_mode(axis_manager, mock_cnc):
    """Stop command should be sent to CNC in continuous mode."""
    axis_manager.stop_jog(axis_idx=0, mode_text="Continuous")
    mock_cnc.stop_jog.assert_called_once_with(0, is_joint=False)


def test_stop_jog_ignored_in_incremental_mode(axis_manager, mock_cnc):
    """Stop command is not required in incremental mode (CNC stops automatically)."""
    axis_manager.stop_jog(axis_idx=0, mode_text="0.1")
    mock_cnc.stop_jog.assert_not_called()


# --- EXCEPTION HANDLING TEST ---


def test_start_jog_exception_handling(axis_manager, mock_cnc):
    """Ensures CNC errors do not crash the application (handled via try-except)."""
    mock_cnc.jog.side_effect = Exception("Hardware failure")

    # The call should not terminate the test (exception must be handled)
    axis_manager.start_jog(0, 1, "Continuous")
    assert True  # If reached here, exception was handled


# Tests parsing of unusual input values
@pytest.mark.parametrize(
    "weird_input, expected",
    [
        ("", 0.0),        # Empty string
        ("   ", 0.0),     # String with spaces
        ("0,5", 0.0),     # Comma instead of dot (localization issue)
        (5, 5.0),         # Input is already a number (int)
        (0.25, 0.25),     # Input is already a number (float)
    ],
)
def test_parse_increment_edge_cases(axis_manager, weird_input, expected):
    """Verifies parser robustness for edge-case input values."""
    assert axis_manager._parse_increment(weird_input) == expected


# Tests correct method call order (safety protocol)
def test_start_jog_protocol_order(axis_manager, mock_cnc):
    """Ensures sync_mode is called before jog for safety protocol compliance."""
    axis_manager.start_jog(0, 1, "Continuous")

    # Retrieve all method calls to the mock CNC object
    calls = mock_cnc.method_calls

    # Find indices of sync_mode and jog calls
    idx_sync = -1
    idx_jog = -1

    for i, call in enumerate(calls):
        if call[0] == "sync_mode":
            idx_sync = i
        if call[0] == "jog":
            idx_jog = i

    assert idx_sync < idx_jog, "sync_mode must be called before jog!"
    assert idx_sync != -1 and idx_jog != -1

