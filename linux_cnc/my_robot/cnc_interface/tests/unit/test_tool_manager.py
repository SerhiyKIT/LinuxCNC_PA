import pytest
from unittest.mock import MagicMock
from logic.managers.tool_manager import ToolManager

@pytest.fixture
def mock_cnc():
    """Створюємо мок контролера з базовим станом статусів"""
    cnc = MagicMock()
    # Імітуємо, що за замовчуванням всі осі вдома (homed)
    cnc.status.homed = [1, 1, 1, 0, 0, 0] 
    cnc.send_mdi.return_value = True
    return cnc

@pytest.fixture
def tool_manager(mock_cnc):
    """Ініціалізуємо ToolManager"""
    return ToolManager(mock_cnc)

# --- ТЕСТИ БЕЗПЕКИ (Interlocks) ---

def test_perform_action_denied_when_not_armed(tool_manager, mock_cnc):
    """Перевірка: не можна виконувати дії, якщо інструмент не озброєний (Armed)"""
    # is_grip=True, is_armed=False
    success = tool_manager.perform_action(True, False)
    
    assert success is False
    mock_cnc.send_mdi.assert_not_called()

def test_perform_action_denied_when_not_homed(tool_manager, mock_cnc):
    """Перевірка: не можна виконувати дії, якщо осі XYZ не вдома"""
    mock_cnc.status.homed = [0, 0, 0, 0, 0, 0] # Не вдома
    
    # is_grip=True, is_armed=True
    success = tool_manager.perform_action(True, True)
    
    assert success is False
    mock_cnc.send_mdi.assert_not_called()

def test_perform_action_allowed_when_safe(tool_manager, mock_cnc):
    """Перевірка: команда M101 надсилається, якщо все готово"""
    # is_grip=True, is_armed=True, homed=[1,1,1] (вже в фікстурі)
    success = tool_manager.perform_action(True, True)
    
    assert success is True
    mock_cnc.send_mdi.assert_called_once_with("M101")

# --- ТЕСТИ ОЗБРОЄННЯ (Arming/Disarming) ---

def test_arm_tool_safety_release(tool_manager, mock_cnc):
    """Перевірка: при знятті з озброєння надсилається M102 (відкрити) для безпеки"""
    tool_manager.arm_tool(False)
    
    mock_cnc.send_mdi.assert_called_once_with("M102")

def test_arm_tool_no_action_if_not_homed(tool_manager, mock_cnc):
    """Перевірка: Disarm не шле M102, якщо верстат не вдома (щоб не викликати помилку CNC)"""
    mock_cnc.status.homed = [0, 0, 0]
    tool_manager.arm_tool(False)
    
    mock_cnc.send_mdi.assert_not_called()

# --- ТЕСТИ ПОТУЖНОСТІ (Power/Force) ---

@pytest.mark.parametrize("input_percent, expected_float", [
    (10, 0.1),
    (50, 0.5),
    (100, 1.0)
])
def test_set_power_conversion(tool_manager, mock_cnc, input_percent, expected_float):
    """Перевірка конвертації цілого числа зі слайдера у float для CNC"""
    result = tool_manager.set_power(input_percent)
    
    assert result == expected_float
    mock_cnc.set_gripper_force.assert_called_once_with(expected_float)

# --- ТЕСТ КОМАНД (M-Codes) ---

def test_perform_action_commands(tool_manager, mock_cnc):
    """Перевірка вибору правильного M-коду для затискання та розтискання"""
    # Затиснути
    tool_manager.perform_action(True, True)
    mock_cnc.send_mdi.assert_called_with("M101")
    
    # Розтиснути
    tool_manager.perform_action(False, True)
    mock_cnc.send_mdi.assert_called_with("M102")