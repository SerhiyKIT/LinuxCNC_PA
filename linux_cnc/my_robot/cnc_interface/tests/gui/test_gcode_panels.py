import pytest
from PyQt5.QtWidgets import QMainWindow, QLabel, QFrame, QWidget

class TestGCodePanels:
    @pytest.fixture
    def ui(self, qtbot):
        class MockUI(QMainWindow):
            def __init__(self):
                super().__init__()
                # Створюємо імітацію контейнера віджетів
                self.widgets = type('Widgets', (), {})()
                self.widgets.lbl_gcode_control = QLabel()
                self.widgets.frm_gcode_control = QFrame()
                self.widgets.gcode_control_overlay = QWidget()
                
                # Імітація менеджера стилів
                self.style_manager = type('Styles', (), {
                    'PANEL_LABEL_ACTIVE': 'act_lbl_style', 
                    'PANEL_LABEL_INACTIVE': 'inact_lbl_style',
                    'PANEL_FRAME_ACTIVE': 'act_frm_style', 
                    'PANEL_FRAME_INACTIVE': 'inact_frm_style'
                })()

            def _apply_panel_style(self, prefix, is_active):
                """Внутрішня логіка стилізації панелей (копія оригіналу)"""
                lbl = getattr(self.widgets, f"lbl_{prefix}", None)
                if lbl:
                    style = self.style_manager.PANEL_LABEL_ACTIVE if is_active else self.style_manager.PANEL_LABEL_INACTIVE
                    lbl.setStyleSheet(style)

                frm = getattr(self.widgets, f"frm_{prefix}", None)
                if frm:
                    style = self.style_manager.PANEL_FRAME_ACTIVE if is_active else self.style_manager.PANEL_FRAME_INACTIVE
                    frm.setStyleSheet(style)

            def update_gcode_controls(self, states):
                """Логіка керування панеллю G-коду (копія оригіналу)"""
                is_ready = states['is_ready']
                
                # 1. Стилізуємо панель
                self._apply_panel_style('gcode_control', is_ready)
                
                # 2. Керуємо оверлеєм-блокувальником
                if hasattr(self.widgets, 'gcode_control_overlay'):
                    self.widgets.gcode_control_overlay.setVisible(not is_ready)

        win = MockUI()
        qtbot.addWidget(win)
        return win

    def test_gcode_overlay_behavior(self, ui):
        """Тест: оверлей блокує взаємодію, якщо машина не готова"""
        # Стан: не готова
        ui.update_gcode_controls({'is_ready': False})
        assert ui.widgets.gcode_control_overlay.isVisible() == True
        
        # Стан: готова
        ui.update_gcode_controls({'is_ready': True})
        assert ui.widgets.gcode_control_overlay.isVisible() == False

    def test_apply_panel_style_consistency(self, ui):
        """Тест: перевірка, що стиль рамки та мітки змінюється синхронно"""
        # Активуємо панель
        ui._apply_panel_style('gcode_control', True)
        assert ui.widgets.lbl_gcode_control.styleSheet() == "act_lbl_style"
        assert ui.widgets.frm_gcode_control.styleSheet() == "act_frm_style"
        
        # Деактивуємо панель
        ui._apply_panel_style('gcode_control', False)
        assert ui.widgets.lbl_gcode_control.styleSheet() == "inact_lbl_style"
        assert ui.widgets.frm_gcode_control.styleSheet() == "inact_frm_style"