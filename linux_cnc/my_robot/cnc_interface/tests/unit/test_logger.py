"""
Tests for logic/core/logger.py  –  LoggerController
=====================================================

Run with:
    pytest test_logger.py -v
"""

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from logic.core.logger import LoggerController, _TIMESTAMP_FORMAT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    """Minimal stand-in for MachineController."""
    return MagicMock()


@pytest.fixture()
def logger(mock_cnc: MagicMock) -> LoggerController:
    return LoggerController(mock_cnc)


# ===========================================================================
# Initialisation
# ===========================================================================

class TestInit:
    def test_stores_cnc_reference(self, mock_cnc):
        lc = LoggerController(mock_cnc)
        assert lc.cnc is mock_cnc

    def test_slots_prevent_arbitrary_attributes(self, logger):
        """__slots__ must block setting undeclared attributes."""
        with pytest.raises(AttributeError):
            logger.unexpected_attr = "oops"

    def test_repr_contains_class_name(self, logger):
        assert "LoggerController" in repr(logger)


# ===========================================================================
# check_for_messages
# ===========================================================================

class TestCheckForMessages:
    def test_delegates_to_poll_errors(self, logger, mock_cnc):
        """check_for_messages() must call cnc.poll_errors() exactly once."""
        mock_cnc.poll_errors.return_value = ("Joint 0 error", "error")
        logger.check_for_messages()
        mock_cnc.poll_errors.assert_called_once()

    def test_returns_error_tuple(self, logger, mock_cnc):
        payload = ("Joint 0 following error", "error")
        mock_cnc.poll_errors.return_value = payload
        assert logger.check_for_messages() == payload

    def test_returns_warning_tuple(self, logger, mock_cnc):
        payload = ("Cycle started", "warning")
        mock_cnc.poll_errors.return_value = payload
        assert logger.check_for_messages() == payload

    def test_returns_info_tuple(self, logger, mock_cnc):
        payload = ("Spindle at speed", "info")
        mock_cnc.poll_errors.return_value = payload
        assert logger.check_for_messages() == payload

    def test_returns_none_when_no_message(self, logger, mock_cnc):
        mock_cnc.poll_errors.return_value = None
        assert logger.check_for_messages() is None

    def test_passes_through_cnc_exception(self, logger, mock_cnc):
        """Exceptions from poll_errors() must propagate unchanged."""
        mock_cnc.poll_errors.side_effect = RuntimeError("NML connection lost")
        with pytest.raises(RuntimeError, match="NML connection lost"):
            logger.check_for_messages()

    def test_called_multiple_times_independently(self, logger, mock_cnc):
        """Each call should trigger a fresh poll — no result caching."""
        mock_cnc.poll_errors.side_effect = [
            ("msg 1", "info"),
            None,
            ("msg 3", "error"),
        ]
        assert logger.check_for_messages() == ("msg 1", "info")
        assert logger.check_for_messages() is None
        assert logger.check_for_messages() == ("msg 3", "error")
        assert mock_cnc.poll_errors.call_count == 3


# ===========================================================================
# get_timestamp
# ===========================================================================

class TestGetTimestamp:
    def test_returns_string(self):
        assert isinstance(LoggerController.get_timestamp(), str)

    def test_format_hh_mm_ss(self):
        ts = LoggerController.get_timestamp()
        assert len(ts) == 8, f"Expected 8 chars, got {len(ts)!r}"
        assert ts.count(":") == 2

    def test_parseable_as_time(self):
        """The returned string must be parseable back with the same format."""
        ts = LoggerController.get_timestamp()
        parsed = datetime.strptime(ts, _TIMESTAMP_FORMAT)
        assert 0 <= parsed.hour   <= 23
        assert 0 <= parsed.minute <= 59
        assert 0 <= parsed.second <= 59

    def test_fixed_value_via_mock(self):
        with patch("logic.core.logger.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "12:34:56"
            assert LoggerController.get_timestamp() == "12:34:56"

    def test_strftime_called_with_correct_format(self):
        with patch("logic.core.logger.datetime") as mock_dt:
            LoggerController.get_timestamp()
            mock_dt.now.return_value.strftime.assert_called_once_with(_TIMESTAMP_FORMAT)

    def test_callable_as_static_method(self, logger):
        """get_timestamp() must work both on the class and on an instance."""
        assert isinstance(logger.get_timestamp(), str)

    def test_two_calls_return_valid_timestamps(self):
        """Consecutive calls must each return a valid timestamp string."""
        for _ in range(2):
            ts = LoggerController.get_timestamp()
            datetime.strptime(ts, _TIMESTAMP_FORMAT)  # raises on bad format