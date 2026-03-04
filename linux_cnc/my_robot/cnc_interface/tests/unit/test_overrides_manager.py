import pytest
from unittest.mock import MagicMock
from logic.managers.overrides_manager import OverridesManager

@pytest.fixture
def mock_cnc():
    """Створюємо мок контролера CNC"""
    return MagicMock()

@pytest.fixture
def manager(mock_cnc):
    """Ініціалізуємо OverridesManager з моком"""
    return OverridesManager(mock_cnc)

# --- ТЕСТИ ПЕРЕДАЧІ ЗНАЧЕНЬ (Override Scales) ---

def test_set_feed_override(manager, mock_cnc):
    """Перевірка передачі коефіцієнта подачі (Feed)"""
    manager.set_feed(1.25)  # 125%
    mock_cnc.set_feed_override.assert_called_once_with(1.25)

def test_set_rapid_override(manager, mock_cnc):
    """Перевірка передачі коефіцієнта швидких переміщень (Rapid)"""
    manager.set_rapid(0.5)  # 50%
    mock_cnc.set_rapid_override.assert_called_once_with(0.5)

def test_set_spindle_override(manager, mock_cnc):
    """Перевірка передачі коефіцієнта обертів шпинделя (Spindle)"""
    manager.set_spindle(1.0) # 100%
    mock_cnc.set_spindle_override.assert_called_once_with(1.0)

# --- ТЕСТИ ШВИДКОСТІ (Jog Speeds) ---

def test_set_linear_speed(manager, mock_cnc):
    """Перевірка прямого встановлення лінійної швидкості"""
    manager.set_linear_speed(1500.0)
    assert mock_cnc.linear_jog_speed == 1500.0

def test_set_angular_speed(manager, mock_cnc):
    """Перевірка прямого встановлення кутової швидкості"""
    manager.set_angular_speed(45.5)
    assert mock_cnc.angular_jog_speed == 45.5

# --- ТЕСТИ МАКСИМАЛЬНОЇ ШВИДКОСТІ ТА ПОМИЛОК ---

def test_set_max_velocity_success(manager, mock_cnc):
    """Перевірка встановлення обмеження максимальної швидкості"""
    manager.set_max_velocity(600.0)
    mock_cnc.set_max_velocity.assert_called_once_with(600.0)

def test_set_max_velocity_exception_safety(manager, mock_cnc):
    """
    Перевірка стійкості до помилок.
    Якщо CNC відхиляє значення (наприклад, занадто високе), менеджер не має 'падати'.
    """
    mock_cnc.set_max_velocity.side_effect = Exception("Value out of range")
    
    # Виклик має пройти успішно завдяки try-except всередині менеджера
    try:
        manager.set_max_velocity(999999.0)
    except Exception as e:
        pytest.fail(f"OverridesManager failed to handle CNC exception: {e}")

# --- ТЕСТ ВЗАЄМОДІЇ З BINDER (МАТЕМАТИКА ТА МАСШТАБУВАННЯ) ---

def test_ui_math_scaling():
    """
    Цей тест симулює логіку Binder'а, щоб перевірити, 
    чи правильно ми розрахували дільники (100.0, 1000.0).
    """
    mock_cnc = MagicMock()
    manager = OverridesManager(mock_cnc)
    
    # Симулюємо значення слайдера 1234 (для лінійної швидкості дільник 1000)
    raw_slider_val = 1234
    actual_val = raw_slider_val / 1000.0
    manager.set_linear_speed(actual_val)
    
    assert mock_cnc.linear_jog_speed == 1.234
    
    # Симулюємо значення слайдера 150 (для подачі дільник 100)
    raw_feed_val = 150
    manager.set_feed(raw_feed_val / 100.0)
    
    mock_cnc.set_feed_override.assert_called_with(1.5)