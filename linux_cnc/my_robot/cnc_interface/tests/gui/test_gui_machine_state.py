import pytest
from unittest.mock import MagicMock
from PyQt5.QtWidgets import QMainWindow, QPushButton, QWidget, QVBoxLayout
from PyQt5.QtCore import QCoreApplication

# Припустимо, ваш головний клас називається CNCWindow
# Якщо він в іншому файлі, імпортуйте його: 
# from your_module import CNCWindow

class TestMachineState:
    @pytest.fixture
    def app(self, qtbot):
        """Фікстура для створення вікна з необхідними віджетами"""
        class MockStyleManager:
            STYLE_ESTOP_ON = "background-color: red;"
            STYLE_ESTOP_OFF = "background-color: gray;"
            STYLE_POWER_ON = "background-color: green;"
            STYLE_POWER_OFF = "background-color: black;"

        class DummyWindow(QMainWindow):
            def __init__(self):
                super().__init__()
                self.style_manager = MockStyleManager()
                self.widgets = QWidget()
                layout = QVBoxLayout()
                
                # Створюємо кнопки, які шукає ваша функція
                self.widgets.btn_estop = QPushButton("E-Stop")
                self.widgets.btn_power_off = QPushButton("Power")
                
                layout.addWidget(self.widgets.btn_estop)
                layout.addWidget(self.widgets.btn_power_off)
                self.widgets.setLayout(layout)

            def update_machine_state(self, states):
                # Сюди вставляємо вашу оригінальну функцію для тестування
                estop_active = (states['estop_off'] == False)
                power_on = (states['power_on'] == True)

                btn_estop = getattr(self.widgets, 'btn_estop', None)
                if btn_estop:
                    style = self.style_manager.STYLE_ESTOP_ON if estop_active else self.style_manager.STYLE_ESTOP_OFF
                    btn_estop.setStyleSheet(style)

                btn_power = getattr(self.widgets, 'btn_power_off', None)
                if btn_power:
                    btn_power.setEnabled(not estop_active)
                    is_active = power_on and not estop_active
                    style = self.style_manager.STYLE_POWER_ON if is_active else self.style_manager.STYLE_POWER_OFF
                    btn_power.setStyleSheet(style)
                    status_key = "ON" if is_active else "OFF"
                    translated_text = QCoreApplication.translate("MainWindow", status_key)
                    btn_power.setText(translated_text)

        window = DummyWindow()
        qtbot.addWidget(window)
        return window

    def test_state_estop_active(self, app):
        """1. Тест: Активний E-Stop (машина в аварійному стані)"""
        states = {'estop_off': False, 'power_on': False}
        
        app.update_machine_state(states)
        
        # Перевірка кнопки E-Stop
        assert "red" in app.widgets.btn_estop.styleSheet()
        
        # Перевірка кнопки Power (має бути заблокована)
        assert app.widgets.btn_power_off.isEnabled() is False
        assert "black" in app.widgets.btn_power_off.styleSheet()
        assert app.widgets.btn_power_off.text() == "OFF"

    def test_state_power_ready(self, app):
        """2. Тест: E-Stop вимкнено, машина готова до ввімкнення живлення"""
        states = {'estop_off': True, 'power_on': False}
        
        app.update_machine_state(states)
        
        assert "gray" in app.widgets.btn_estop.styleSheet()
        assert app.widgets.btn_power_off.isEnabled() is True
        assert app.widgets.btn_power_off.text() == "OFF"

    def test_state_machine_on(self, app):
        """3. Тест: Живлення ввімкнено (Normal Operation)"""
        states = {'estop_off': True, 'power_on': True}
        
        app.update_machine_state(states)
        
        assert app.widgets.btn_power_off.isEnabled() is True
        assert "green" in app.widgets.btn_power_off.styleSheet()
        assert app.widgets.btn_power_off.text() == "ON"

    def test_power_stays_off_if_estop_triggered_while_on(self, app):
        """4. Тест: Сценарій безпеки - натискання E-Stop при ввімкненому живленні"""
        # Спочатку вмикаємо
        app.update_machine_state({'estop_off': True, 'power_on': True})
        # Раптово спрацьовує E-Stop (наприклад, оператор натиснув грибок)
        app.update_machine_state({'estop_off': False, 'power_on': True})
        
        # Кнопка Power повинна миттєво стати неактивною і змінити текст на OFF
        # (відповідно до вашої логіки: is_active = power_on and not estop_active)
        assert app.widgets.btn_power_off.isEnabled() is False
        assert app.widgets.btn_power_off.text() == "OFF"