import pytest
from PyQt5.QtWidgets import QMainWindow, QPushButton, QListView, QWidget
from PyQt5.QtCore import QStringListModel

class TestFileButtons:
    @pytest.fixture
    def manager(self, qtbot):
        class MockCNC:
            def __init__(self):
                self.reload_needed = False
                self.last_file = "test.ngc"
            def get_last_file(self):
                return self.last_file

        class MockManager:
            def __init__(self, cnc):
                self.cnc = cnc
                self.widgets = type('Widgets', (), {})()
                self.file_buttons = ['btn_file_open', 'btn_file_edit', 'btn_file_reload', 'btn_file_save_as']
                
                # Створюємо кнопки
                for btn in self.file_buttons:
                    setattr(self.widgets, btn, QPushButton())
                
                # Додаємо ListView для G-коду
                self.widgets.list_gcode_view = QListView()
                
                # Mock Styles
                self.style_manager = type('Styles', (), {
                    'STYLE_GCODE_ACTIVE': 'active_style',
                    'STYLE_GCODE_INACTIVE': 'inactive_style',
                    'STYLE_GCODE_WARN': 'warning_style'
                })()

            # Вставляємо метод для тестування
            def update_file_buttons(self, states):
                is_idle = states.get('is_idle', True)
                has_file = bool(self.cnc.get_last_file())
                is_ready = states.get('is_ready', False) 

                has_content = False
                gcode_view = getattr(self.widgets, 'list_gcode_view', None)
                if gcode_view and gcode_view.model():
                    has_content = gcode_view.model().rowCount() > 0

                conditions = {
                    'btn_file_open':    is_idle and is_ready,
                    'btn_file_edit':    is_idle and has_file and is_ready,
                    'btn_file_reload':  is_idle and has_file and is_ready,
                    'btn_file_save_as': is_idle and has_content and is_ready
                }

                for btn_name in self.file_buttons:
                    btn = getattr(self.widgets, btn_name, None)
                    if not btn: continue
                    is_enabled = conditions.get(btn_name, False)
                    btn.setEnabled(is_enabled)

                    if not is_enabled:
                        target_style = self.style_manager.STYLE_GCODE_INACTIVE
                    else:
                        if btn_name == 'btn_file_reload' and getattr(self.cnc, 'reload_needed', False):
                            target_style = self.style_manager.STYLE_GCODE_WARN
                        else:
                            target_style = self.style_manager.STYLE_GCODE_ACTIVE
                    btn.setStyleSheet(target_style)

        cnc = MockCNC()
        mgr = MockManager(cnc)
        qtbot.addWidget(mgr.widgets.list_gcode_view)
        return mgr

    def test_open_button_requires_ready_state(self, manager):
        """Перевірка: кнопка Open активна лише коли машина готова (Ready) та Idle"""
        # Стан: Idle, але не Ready
        manager.update_file_buttons({'is_idle': True, 'is_ready': False})
        assert manager.widgets.btn_file_open.isEnabled() is False

        # Стан: Idle та Ready
        manager.update_file_buttons({'is_idle': True, 'is_ready': True})
        assert manager.widgets.btn_file_open.isEnabled() is True

    def test_edit_reload_require_file_loaded(self, manager):
        """Перевірка: Edit/Reload активні лише якщо файл завантажений"""
        manager.cnc.last_file = None # Файлу немає
        manager.update_file_buttons({'is_idle': True, 'is_ready': True})
        assert manager.widgets.btn_file_edit.isEnabled() is False
        assert manager.widgets.btn_file_reload.isEnabled() is False

        manager.cnc.last_file = "exists.ngc" # Файл з'явився
        manager.update_file_buttons({'is_idle': True, 'is_ready': True})
        assert manager.widgets.btn_file_edit.isEnabled() is True

    def test_reload_warning_style(self, manager):
        """Перевірка: стиль Warning якщо файл змінено ззовні"""
        manager.cnc.reload_needed = True
        manager.update_file_buttons({'is_idle': True, 'is_ready': True})
        
        assert manager.widgets.btn_file_reload.styleSheet() == "warning_style"
        # Інші кнопки мають бути просто активними
        assert manager.widgets.btn_file_edit.styleSheet() == "active_style"

    def test_save_as_requires_content_in_view(self, manager):
        """Перевірка: Save As активна лише якщо у в'ювері є текст"""
        # Модель порожня
        manager.widgets.list_gcode_view.setModel(QStringListModel([]))
        manager.update_file_buttons({'is_idle': True, 'is_ready': True})
        assert manager.widgets.btn_file_save_as.isEnabled() is False

        # Додаємо рядки в модель
        manager.widgets.list_gcode_view.setModel(QStringListModel(["G0 X1"]))
        manager.update_file_buttons({'is_idle': True, 'is_ready': True})
        assert manager.widgets.btn_file_save_as.isEnabled() is True

    def test_buttons_disabled_when_running(self, manager):
        """Перевірка: всі кнопки керування файлами вимкнені під час роботи (Running)"""
        manager.update_file_buttons({'is_idle': False, 'is_ready': True})
        for btn_name in manager.file_buttons:
            btn = getattr(manager.widgets, btn_name)
            assert btn.isEnabled() is False
            assert btn.styleSheet() == "inactive_style"