import pytest
from PyQt5.QtWidgets import QMainWindow, QLabel, QPushButton, QWidget

class TestMotionDisplay:
    @pytest.fixture
    def manager(self, qtbot):
        # 1. Mock Machine Controller з лімітами осей
        class MockCNC:
            def __init__(self):
                # Ліміти для J0 (X) та J1 (Y)
                self.limits = {
                    0: {"min": -10.0, "max": 100.0},
                    1: {"min": 0.0, "max": 50.0}
                }

        # 2. Mock StyleManager
        class MockStyles:
            def __init__(self):
                self.STYLE_JOG_ACTIVE = "background: green;"
                self.STYLE_JOG_LIMITED = "background: red;"
            def _set_jogging_styles(self): pass

        # 3. Mock UI
        class MockUI(QMainWindow):
            def __init__(self):
                super().__init__()
                self.widgets = type('Widgets', (), {})()
                # Створюємо віджети для 2-х осей (Joint та World)
                for i in range(2):
                    setattr(self.widgets, f"txt_j{i}_pos", QLabel("0.0000"))
                    setattr(self.widgets, f"btn_j{i}_plus", QPushButton())
                    setattr(self.widgets, f"btn_j{i}_minus", QPushButton())
                
                self.widgets.txt_x_pos = QLabel("0.0000")
                self.widgets.txt_y_pos = QLabel("0.0000")

        from logic.managers.ui.motion_display import MotionDisplayManager
        
        ui = MockUI()
        cnc = MockCNC()
        
        # Ініціалізація без виклику оригінального __init__
        mgr = MotionDisplayManager.__new__(MotionDisplayManager)
        mgr.cnc = cnc
        mgr.widgets = ui.widgets
        mgr.limits = cnc.limits
        mgr.style_manager = MockStyles()
        mgr.last_joint_pos = {}
        
        qtbot.addWidget(ui)
        return mgr, ui

    def test_coordinate_update_threshold(self, manager):
        """Перевірка, що текст оновлюється лише при зміні > 0.00005"""
        mgr, ui = manager
        
        # Початкове значення
        states = {'joint_position': [10.0, 0], 'actual_position': [10.0, 0], 'is_ready': True}
        mgr.update_coordinates(states)
        assert ui.widgets.txt_j0_pos.text() == "10.0000"
        
        # Зміна на 0.00001 (не має оновити текст або викликати setText)
        ui.widgets.txt_j0_pos.setText("STAY")
        states['joint_position'][0] = 10.00001
        mgr.update_coordinates(states)
        assert ui.widgets.txt_j0_pos.text() == "STAY"
        
        # Зміна на 0.0001 (має оновити)
        states['joint_position'][0] = 10.0001
        mgr.update_coordinates(states)
        assert ui.widgets.txt_j0_pos.text() == "10.0001"

    def test_soft_limits_disabling_buttons(self, manager):
        """Перевірка блокування кнопок Jog при досягненні лімітів"""
        mgr, ui = manager
        
        # Ситуація: Вісь J0 на максимумі (100.0)
        states = {
            'is_ready': True,
            'joint_position': [100.0, 25.0],
            'actual_position': [100.0, 25.0]
        }
        mgr.update_coordinates(states)
        
        # Кнопка "+" має бути вимкнена та мати стиль "Limited"
        assert ui.widgets.btn_j0_plus.isEnabled() is False
        assert ui.widgets.btn_j0_plus.styleSheet() == mgr.style_manager.STYLE_JOG_LIMITED
        
        # Кнопка "-" має бути активною
        assert ui.widgets.btn_j0_minus.isEnabled() is True
        assert ui.widgets.btn_j0_minus.styleSheet() == mgr.style_manager.STYLE_JOG_ACTIVE

    def test_soft_limits_min_boundary(self, manager):
        """Перевірка блокування кнопок Jog при досягненні мінімуму"""
        mgr, ui = manager
        
        # Ситуація: Вісь J1 на мінімумі (0.0)
        states = {
            'is_ready': True,
            'joint_position': [50.0, 0.0],
            'actual_position': [50.0, 0.0]
        }
        mgr.update_coordinates(states)
        
        assert ui.widgets.btn_j1_minus.isEnabled() is False
        assert ui.widgets.btn_j1_plus.isEnabled() is True

    def test_world_coordinates_display(self, manager):
        """Перевірка оновлення World координат (DRO)"""
        mgr, ui = manager
        states = {
            'is_ready': True,
            'joint_position': [0, 0],
            'actual_position': [123.45678, 88.99]
        }
        mgr.update_coordinates(states)
        
        assert ui.widgets.txt_x_pos.text() == "123.4568"
        assert ui.widgets.txt_y_pos.text() == "88.9900"

    def test_handle_limits_not_ready(self, manager):
        """Якщо машина не Ready, ліміти не повинні оброблятися (кнопки не змінюються)"""
        mgr, ui = manager
        ui.widgets.btn_j0_plus.setEnabled(True)
        
        # Машина не готова, позиція на ліміті
        states = {
            'is_ready': False,
            'joint_position': [100.0, 0],
            'actual_position': [100.0, 0]
        }
        mgr.update_coordinates(states)
        
        # Кнопка все ще активна, бо логіка лімітів проігнорована
        assert ui.widgets.btn_j0_plus.isEnabled() is True