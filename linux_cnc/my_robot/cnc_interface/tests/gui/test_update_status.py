import pytest
from PyQt5.QtWidgets import QMainWindow, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore import QCoreApplication

class TestUpdateStatusDisplay:
    @pytest.fixture
    def ui(self, qtbot):
        """Створюємо мінімальний екземпляр вікна для тестів"""
        class MockMainWindow(QMainWindow):
            def __init__(self):
                super().__init__()
                self.widgets = QWidget()
                self.setCentralWidget(self.widgets)
                layout = QVBoxLayout(self.widgets)
                
                # Створюємо віджет, який очікує метод
                self.widgets.txt_status_display = QLabel("INIT")
                layout.addWidget(self.widgets.txt_status_display)

            def update_status_display(self, states):
                """Метод, що тестується"""
                txt_display = getattr(self.widgets, 'txt_status_display', None)
                if not txt_display:
                    return
                
                if states['estop_off'] == False:
                    msg_key = "EMERGENCY STOP"
                elif not states['power_on']:
                    msg_key = "POWER OFF"
                elif not states['all_homed']:
                    msg_key = "HOMING REQUIRED"
                else:
                    msg_key = "SYSTEM READY"

                translated_msg = QCoreApplication.translate("MainWindow", msg_key)
                txt_display.setText(translated_msg)

        window = MockMainWindow()
        qtbot.addWidget(window)
        return window

    def test_estop_active_priority(self, ui):
        """Перевірка найвищого пріоритету E-Stop"""
        states = {'estop_off': False, 'power_on': True, 'all_homed': True}
        ui.update_status_display(states)
        assert ui.widgets.txt_status_display.text() == "EMERGENCY STOP"

    def test_power_off_over_homing(self, ui):
        """Перевірка, що Power Off важливіший за Homing"""
        states = {'estop_off': True, 'power_on': False, 'all_homed': False}
        ui.update_status_display(states)
        assert ui.widgets.txt_status_display.text() == "POWER OFF"

    def test_homing_required(self, ui):
        """Перевірка статусу потреби в базуванні (Homing)"""
        states = {'estop_off': True, 'power_on': True, 'all_homed': False}
        ui.update_status_display(states)
        assert ui.widgets.txt_status_display.text() == "HOMING REQUIRED"

    def test_system_ready(self, ui):
        """Перевірка статусу повної готовності"""
        states = {'estop_off': True, 'power_on': True, 'all_homed': True}
        ui.update_status_display(states)
        assert ui.widgets.txt_status_display.text() == "SYSTEM READY"

    def test_missing_widget_handling(self, ui):
        """Перевірка безпеки: метод не падає, якщо віджет зник"""
        ui.widgets.txt_status_display.deleteLater()
        delattr(ui.widgets, 'txt_status_display')
        
        # Не повинно викликати винятків
        ui.update_status_display({'estop_off': True, 'power_on': True, 'all_homed': True})