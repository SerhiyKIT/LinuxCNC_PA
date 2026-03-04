import pytest
from unittest.mock import MagicMock, patch
from logic.core.logger import LoggerController

# Додаємо фікстуру сюди, якщо conftest.py не бачиться
@pytest.fixture
def mock_cnc():
    """Мок для MachineController"""
    return MagicMock()

@pytest.fixture
def logger(mock_cnc):
    """Створюємо екземпляр логера з моком CNC"""
    return LoggerController(mock_cnc)

# --- Далі ваші тести без змін ---

def test_check_for_messages_calls_poll_errors(logger, mock_cnc):
    expected_message = ("CRITICAL", "Emergency Stop Pressed")
    mock_cnc.poll_errors.return_value = expected_message
    result = logger.check_for_messages()
    mock_cnc.poll_errors.assert_called_once()
    assert result == expected_message

def test_get_timestamp_format():
    timestamp = LoggerController.get_timestamp()
    assert len(timestamp) == 8
    assert ":" in timestamp
    assert timestamp.count(":") == 2

@patch('logic.core.logger.datetime')
def test_get_timestamp_fixed_value(mock_datetime):
    mock_datetime.now.return_value.strftime.return_value = "12:34:56"
    timestamp = LoggerController.get_timestamp()
    assert timestamp == "12:34:56"

def test_check_for_messages_handles_no_errors(logger, mock_cnc):
    mock_cnc.poll_errors.return_value = None
    result = logger.check_for_messages()
    assert result is None