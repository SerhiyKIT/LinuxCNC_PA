import pytest
from unittest.mock import MagicMock
from logic.managers.cycle_manager import CycleManager

@pytest.fixture
def mock_cnc():
    """Створюємо мок для контролера LinuxCNC"""
    cnc = MagicMock()
    # Імітуємо наявність об'єкта status для методу step_cycle
    cnc.status = MagicMock()
    return cnc

@pytest.fixture
def cycle_manager(mock_cnc):
    """Ініціалізуємо CycleManager з моком"""
    return CycleManager(mock_cnc)

# --- ТЕСТИ ОСНОВНИХ КОМАНД ---

def test_start_cycle_default(cycle_manager, mock_cnc):
    """Перевірка запуску циклу з дефолтної (нульової) лінії"""
    cycle_manager.start_cycle()
    mock_cnc.cycle_start.assert_called_once_with(0)

def test_start_cycle_from_specific_line(cycle_manager, mock_cnc):
    """Перевірка запуску з конкретного рядка (наприклад, після рестарту)"""
    cycle_manager.start_cycle(start_line=42)
    mock_cnc.cycle_start.assert_called_once_with(42)

def test_pause_and_resume_calls(cycle_manager, mock_cnc):
    """Перевірка команд паузи та продовження"""
    cycle_manager.pause_cycle()
    mock_cnc.cycle_pause.assert_called_once()
    
    cycle_manager.resume_cycle()
    mock_cnc.cycle_resume.assert_called_once()

def test_stop_cycle_call(cycle_manager, mock_cnc):
    """Перевірка команди повної зупинки програми"""
    cycle_manager.stop_cycle()
    mock_cnc.cycle_stop.assert_called_once()

# --- СПЕЦИФІЧНІ ТЕСТИ ЛОГІКИ ---

def test_step_cycle_sequence(cycle_manager, mock_cnc):
    """
    Перевірка покрокового виконання. 
    Важливо: після команди step має обов'язково викликатися poll() статусу.
    """
    cycle_manager.step_cycle()
    
    mock_cnc.cycle_step.assert_called_once()
    mock_cnc.status.poll.assert_called_once()

# --- ТЕСТИ ОБРОБКИ ПОМИЛОК (Exception Safety) ---

@pytest.mark.parametrize("method_name", [
    "start_cycle", "resume_cycle", "pause_cycle", "stop_cycle", "step_cycle"
])
def test_cycle_methods_handle_exceptions(cycle_manager, mock_cnc, method_name):
    """
    Критичний тест: якщо LinuxCNC повертає помилку (наприклад, 'Machine is OFF'),
    менеджер повинен спіймати її в try-except і не дати програмі 'впасти'.
    """
    # Налаштовуємо мок так, щоб відповідний метод викидав помилку
    target_method = getattr(mock_cnc, f"cycle_{method_name.split('_')[0]}")
    if method_name == "resume_cycle": target_method = mock_cnc.cycle_resume
    
    target_method.side_effect = Exception("LinuxCNC Error: Not in Auto mode")
    
    # Виклик методу через менеджер
    manager_method = getattr(cycle_manager, method_name)
    
    try:
        if method_name == "start_cycle":
            manager_method(0)
        else:
            manager_method()
    except Exception as e:
        pytest.fail(f"Метод {method_name} не обробив виключення: {e}")