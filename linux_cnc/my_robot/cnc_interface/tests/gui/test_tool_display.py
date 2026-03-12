import pytest
from PyQt5.QtWidgets import QMainWindow, QPushButton, QSlider, QWidget

class TestToolDisplay:
    @pytest.fixture
    def manager(self, qtbot):
        # 1. Mock StyleManager
        class MockStyles:
            def __init__(self): pass

        # 2. Mock UI
        class MockUI(QMainWindow):
            def __init__(self):
                super().__init__()
                self.widgets = type('Widgets', (), {})()
                
                # Кнопка підготовки (Arm) - перемикач (Checkable)
                self.widgets.btn_tool_arm = QPushButton()
                self.widgets.btn_tool_arm.setCheckable(True)
                
                # Кнопка дії (Grip) та повзунок потужності
                self.widgets.btn_tool_action = QPushButton()
                self.widgets.sld_tool_power = QSlider()
                
                # Прапор для відстеження виклику методу обробки кліку
                self.arm_clicked_called = False
                
            def on_btn_tool_arm_clicked(self):
                self.arm_clicked_called = True

        from logic.managers.ui.tool_display import ToolDisplayManager
        
        ui = MockUI()
        # Ініціалізація без виклику оригінального __init__
        mgr = ToolDisplayManager.__new__(ToolDisplayManager)
        mgr.widgets = ui.widgets
        # Підміняємо метод менеджера на метод нашого MockUI для тесту
        mgr.on_btn_tool_arm_clicked = ui.on_btn_tool_arm_clicked
        mgr.style_manager = MockStyles()
        
        qtbot.addWidget(ui)
        return mgr, ui

    def test_estop_disarms_tool(self, manager):
        """Тест безпеки: Активація E-Stop повинна автоматично вимкнути 'Arm'"""
        mgr, ui = manager
        
        # Попередньо зводимо інструмент (Arm)
        ui.widgets.btn_tool_arm.setChecked(True)
        
        # Стан: E-Stop активовано (estop_off=False)
        states = {
            'power_on': True,
            'estop_off': False,
            'all_homed': True,
            'is_running': False
        }
        
        mgr.update_tool_ui_state(states)
        
        # Перевіряємо, що кнопка віджалася автоматично
        assert ui.widgets.btn_tool_arm.isChecked() is False
        # Перевіряємо, що викликався обробник скидання логіки
        assert ui.arm_clicked_called is True

    def test_manual_control_blocking_during_run(self, manager):
        """Ручне керування (Grip/Power) має бути вимкнено під час роботи програми"""
        mgr, ui = manager
        
        # Стан: Машина готова, але працює (Running)
        states = {
            'power_on': True,
            'estop_off': True,
            'all_homed': True,
            'is_running': True
        }
        
        mgr.update_tool_ui_state(states)
        
        assert ui.widgets.btn_tool_action.isEnabled() is False
        assert ui.widgets.sld_tool_power.isEnabled() is False

    def test_manual_control_enabling(self, manager):
        """Керування дозволено лише при повному базуванні та живленні"""
        mgr, ui = manager
        
        # Сценарій: Машина не забазована (not homed)
        states = {
            'power_on': True,
            'estop_off': True,
            'all_homed': False,
            'is_running': False
        }
        mgr.update_tool_ui_state(states)
        assert ui.widgets.btn_tool_action.isEnabled() is False
        
        # Сценарій: Машина забазована і готова
        states['all_homed'] = True
        mgr.update_tool_ui_state(states)
        assert ui.widgets.btn_tool_action.isEnabled() is True

    def test_arm_button_requires_power(self, manager):
        """Кнопка Arm активна тільки якщо подано живлення та немає E-Stop"""
        mgr, ui = manager
        
        # Живлення вимкнено
        mgr.update_tool_ui_state({'power_on': False, 'estop_off': True})
        assert ui.widgets.btn_tool_arm.isEnabled() is False
        
        # Живлення є, але натиснуто E-Stop
        mgr.update_tool_ui_state({'power_on': True, 'estop_off': False})
        assert ui.widgets.btn_tool_arm.isEnabled() is False
        
        # Все ок
        mgr.update_tool_ui_state({'power_on': True, 'estop_off': True})
        assert ui.widgets.btn_tool_arm.isEnabled() is True