import pytest
from PyQt5.QtWidgets import QMainWindow, QPushButton, QWidget

class TestCycleButtons:
    @pytest.fixture
    def manager(self, qtbot):
        class MockManager:
            def __init__(self):
                self.widgets = type('Widgets', (), {})()
                self.cycle_buttons = [
                    'btn_cycle_start', 'btn_cycle_pause', 
                    'btn_cycle_continue', 'btn_cycle_stop', 'btn_cycle_step'
                ]
                # Створюємо кнопки
                for btn in self.cycle_buttons:
                    setattr(self.widgets, btn, QPushButton())
                
                # Імітуємо стилі
                self.style_manager = type('Styles', (), {
                    'STYLE_GCODE_ACTIVE': 'active',
                    'STYLE_GCODE_INACTIVE': 'inactive'
                })()

            # Копіюємо методи для тестування (або імпортуємо їх)
            def update_cycle_buttons(self, states):
                ready = states.get('is_ready', False) and states.get('all_homed', False)
                is_idle = states.get('is_idle', False)
                is_paused = states.get('is_paused', False)
                is_running = states.get('is_running', False)
                has_file = states.get('has_file', False)

                can_step = has_file and ready and (is_idle or is_paused or is_running)
                can_continue = is_paused and not is_running
                can_pause = is_running and ready

                conditions = {
                    'btn_cycle_start':    is_idle and has_file and ready,
                    'btn_cycle_pause':    can_pause,
                    'btn_cycle_continue': can_continue,
                    'btn_cycle_stop':     (is_running or is_paused) and ready,
                    'btn_cycle_step':     can_step
                }

                for btn_name in self.cycle_buttons:
                    self._set_btn_state(btn_name, conditions.get(btn_name, False))

            def _set_btn_state(self, btn_name, is_enabled):
                btn = getattr(self.widgets, btn_name, None)
                if btn:
                    btn.setEnabled(is_enabled)
                    btn.setStyleSheet(
                        self.style_manager.STYLE_GCODE_ACTIVE if is_enabled else self.style_manager.STYLE_GCODE_INACTIVE
                    )

        mgr = MockManager()
        # Додаємо віджети в qtbot для коректного оброблення циклу подій
        for btn_name in mgr.cycle_buttons:
            qtbot.addWidget(getattr(mgr.widgets, btn_name))
        return mgr

    def test_start_button_only_when_ready_and_idle(self, manager):
        """1. Тест кнопки START: файл є, машина готова, стан IDLE"""
        states = {
            'is_ready': True, 
            'all_homed': True, 
            'is_idle': True, 
            'has_file': True
        }
        manager.update_cycle_buttons(states)
        assert manager.widgets.btn_cycle_start.isEnabled() is True
        assert manager.widgets.btn_cycle_pause.isEnabled() is False

    def test_pause_active_during_run(self, manager):
        """2. Тест кнопки PAUSE: активна тільки під час виконання"""
        states = {
            'is_ready': True, 
            'all_homed': True, 
            'is_idle': False, 
            'is_running': True,
            'has_file': True
        }
        manager.update_cycle_buttons(states)
        assert manager.widgets.btn_cycle_pause.isEnabled() is True
        assert manager.widgets.btn_cycle_start.isEnabled() is False

    def test_continue_and_stop_during_pause(self, manager):
        """3. Тест кнопок CONTINUE та STOP у стані паузи"""
        states = {
            'is_ready': True, 
            'all_homed': True, 
            'is_idle': False, 
            'is_paused': True,
            'is_running': False,
            'has_file': True
        }
        manager.update_cycle_buttons(states)
        assert manager.widgets.btn_cycle_continue.isEnabled() is True
        assert manager.widgets.btn_cycle_stop.isEnabled() is True
        assert manager.widgets.btn_cycle_pause.isEnabled() is False

    def test_no_file_disables_start_and_step(self, manager):
        """4. Тест: якщо файл не завантажено, START та STEP мають бути вимкнені"""
        states = {
            'is_ready': True, 
            'all_homed': True, 
            'is_idle': True, 
            'has_file': False
        }
        manager.update_cycle_buttons(states)
        assert manager.widgets.btn_cycle_start.isEnabled() is False
        assert manager.widgets.btn_cycle_step.isEnabled() is False

    def test_not_homed_disables_all(self, manager):
        """5. Тест: якщо верстат не забазований, керування циклом заборонено"""
        states = {
            'is_ready': True, 
            'all_homed': False, 
            'is_idle': True, 
            'has_file': True
        }
        manager.update_cycle_buttons(states)
        for btn in manager.cycle_buttons:
            assert manager.widgets.__getattribute__(btn).isEnabled() is False