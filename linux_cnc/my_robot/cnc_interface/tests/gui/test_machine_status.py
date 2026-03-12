import pytest
from PyQt5.QtWidgets import QMainWindow, QPushButton, QLabel, QWidget
from PyQt5.QtCore import QCoreApplication

class TestMachineStatus:
    @pytest.fixture
    def ui(self, qtbot):
        class MockUI(QMainWindow):
            def __init__(self):
                super().__init__()
                self.widgets = type('Widgets', (), {})()
                self.widgets.btn_estop = QPushButton()
                self.widgets.btn_power_off = QPushButton()
                self.widgets.txt_status_display = QLabel()
                
                self.style_manager = type('Styles', (), {
                    'STYLE_ESTOP_ON': 'background: red', 'STYLE_ESTOP_OFF': 'background: gray',
                    'STYLE_POWER_ON': 'color: green', 'STYLE_POWER_OFF': 'color: black'
                })()

            # Імпортуємо методи безпосередньо з вашого класу або копіюємо для тесту
            def update_machine_state(self, states):
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
                    btn_power.setStyleSheet(self.style_manager.STYLE_POWER_ON if is_active else self.style_manager.STYLE_POWER_OFF)

            def update_status_display(self, states):
                txt_display = getattr(self.widgets, 'txt_status_display', None)
                if not txt_display: return
                if states['estop_off'] == False: msg_key = "EMERGENCY STOP"
                elif not states['power_on']: msg_key = "POWER OFF"
                elif not states['all_homed']: msg_key = "HOMING REQUIRED"
                else: msg_key = "SYSTEM READY"
                txt_display.setText(QCoreApplication.translate("MainWindow", msg_key))

        win = MockUI()
        qtbot.addWidget(win)
        return win

    def test_update_machine_state_logic(self, ui):
        ui.update_machine_state({'estop_off': False, 'power_on': False})
        assert ui.widgets.btn_power_off.isEnabled() == False
        assert ui.widgets.btn_estop.styleSheet() == ui.style_manager.STYLE_ESTOP_ON

    def test_update_status_display_priority(self, ui):
        ui.update_status_display({'estop_off': False, 'power_on': True, 'all_homed': True})
        assert ui.widgets.txt_status_display.text() == "EMERGENCY STOP"