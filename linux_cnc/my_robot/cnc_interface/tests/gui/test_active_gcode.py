import pytest
from PyQt5.QtWidgets import QMainWindow, QLabel, QWidget

class TestGCodeStatus:
    @pytest.fixture
    def manager(self, qtbot):
        class MockManager:
            def __init__(self):
                self.widgets = type('Widgets', (), {})()
                self.widgets.txt_gcodeStatusBar = QLabel("Initial")

            # Метод, що тестується
            def update_active_gcodes(self, states):
                status_bar = getattr(self.widgets, 'txt_gcodeStatusBar', None)
                if not status_bar:
                    return

                # 1. G-codes (code/10.0:g)
                active_gcodes = []
                for code in states.get('gcodes', []):
                    if code == -1: continue
                    g_prefix = f"G{code/10.0:g}"
                    active_gcodes.append(g_prefix)
            
                # 2. M-codes
                active_mcodes = []
                for m_code in states.get('mcodes', []):
                    if m_code == -1: continue
                    active_mcodes.append(f"M{m_code}")

                # 3. Settings (F, S)
                settings = states.get('settings', [0, 0, 0])
                f_set = settings[1]
                s_set = settings[2]
            
                g_str = " ".join(active_gcodes)
                m_str = " ".join(active_mcodes)
                fs_str = f"F{f_set:.0f} S{s_set:.0f}"

                full_status = f"{g_str} | {m_str} | {fs_str}"
            
                if status_bar.text() != full_status:
                    status_bar.setText(full_status)

        mgr = MockManager()
        qtbot.addWidget(mgr.widgets.txt_gcodeStatusBar)
        return mgr

    def test_gcode_conversion_logic(self, manager):
        """Перевірка математичного перетворення кодів (10 -> G1, 540 -> G54)"""
        states = {
            'gcodes': [0, 10, 170, 540, 900], # G0, G1, G17, G54, G90
            'mcodes': [],
            'settings': [0, 0, 0]
        }
        manager.update_active_gcodes(states)
        # Очікуємо: G0 G1 G17 G54 G90
        assert "G0 G1 G17 G54 G90" in manager.widgets.txt_gcodeStatusBar.text()

    def test_ignore_minus_one_values(self, manager):
        """Перевірка ігнорування значень -1 (пусті слоти в LinuxCNC)"""
        states = {
            'gcodes': [10, -1, 540],
            'mcodes': [3, -1, 8],
            'settings': [0, 100, 1500]
        }
        manager.update_active_gcodes(states)
        # Має бути "G1 G54 | M3 M8 | F100 S1500"
        expected = "G1 G54 | M3 M8 | F100 S1500"
        assert manager.widgets.txt_gcodeStatusBar.text() == expected

    def test_feed_and_spindle_formatting(self, manager):
        """Перевірка округлення значень подачі та обертів"""
        states = {
            'gcodes': [0],
            'mcodes': [5],
            'settings': [0, 125.7, 2000.4] # Float значення
        }
        manager.update_active_gcodes(states)
        # Має бути округлено до цілих: F126 S2000 (або F126 S2000 залежно від .0f)
        # У вашому коді f"{f_set:.0f}" округлює до найближчого цілого
        assert "F126 S2000" in manager.widgets.txt_gcodeStatusBar.text()

    def test_unnecessary_ui_updates_skipped(self, manager):
        """Перевірка, що setText не викликається, якщо текст не змінився (оптимізація)"""
        states = {
            'gcodes': [10],
            'mcodes': [3],
            'settings': [0, 100, 1000]
        }
        manager.update_active_gcodes(states)
        original_text = manager.widgets.txt_gcodeStatusBar.text()
        
        # Підміняємо setText, щоб перевірити чи він викличеться вдруге
        called = False
        def mock_set_text(t):
            nonlocal called
            called = True
        
        manager.widgets.txt_gcodeStatusBar.setText = mock_set_text
        manager.update_active_gcodes(states) # Ті самі дані
        
        assert called is False, "setText був викликаний попри те, що дані не змінилися"

    def test_missing_status_bar_graceful_exit(self, manager):
        """Перевірка стійкості до відсутності віджета"""
        manager.widgets.txt_gcodeStatusBar.deleteLater()
        delattr(manager.widgets, 'txt_gcodeStatusBar')
        
        # Не повинно бути помилок
        manager.update_active_gcodes({'gcodes': [10], 'mcodes': [3], 'settings': [0, 0, 0]})