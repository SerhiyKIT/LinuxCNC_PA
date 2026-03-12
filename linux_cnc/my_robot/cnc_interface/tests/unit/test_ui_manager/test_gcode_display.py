# tests/gui/test_gcode_display.py
"""
Unit-тести GCodeDisplayManager
================================
Групи:
  1. update_cycle_buttons  — 11 тестів
  2. update_file_buttons   —  7 тестів
  3. update_active_gcodes  —  6 тестів
  4. update_gcode_display  —  7 тестів
  5. _set_btn_state        —  3 тести
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.gui.conftest import base_states

# ---------------------------------------------------------------------------
# Константи що патчаться замість config
# ---------------------------------------------------------------------------

_CYCLE_BUTTONS = [
    "btn_cycle_start", "btn_cycle_pause", "btn_cycle_continue",
    "btn_cycle_stop",  "btn_cycle_step",
]
_FILE_BUTTONS = [
    "btn_file_open", "btn_file_edit", "btn_file_reload", "btn_file_save_as",
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def gcode_mgr(mock_cnc, mock_widgets):
    # rowCount() має повертати int, інакше `> 0` кидає TypeError
    mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0

    with patch("managers.ui.gcode_display.StyleManager") as MockStyle, \
         patch("managers.ui.gcode_display.FileManager"),               \
         patch("managers.ui.gcode_display.CYCLE_BUTTONS", _CYCLE_BUTTONS), \
         patch("managers.ui.gcode_display.FILE_BUTTONS",  _FILE_BUTTONS):
        MockStyle.return_value.STYLE_GCODE_ACTIVE   = "active"
        MockStyle.return_value.STYLE_GCODE_INACTIVE = "inactive"
        MockStyle.return_value.STYLE_GCODE_WARN     = "warn"
        from managers.ui.gcode_display import GCodeDisplayManager
        mgr = GCodeDisplayManager(mock_cnc, mock_widgets)
        # CYCLE_BUTTONS читається у __init__ до патчу — перезаписуємо на instance
        mgr.cycle_buttons = _CYCLE_BUTTONS
        yield mgr


# ---------------------------------------------------------------------------
# Група 1: update_cycle_buttons
# ---------------------------------------------------------------------------

class TestUpdateCycleButtons:

    def test_start_enabled_when_idle_ready_has_file(self, gcode_mgr, mock_widgets):
        """START увімкнений: is_idle=True, is_ready=True, has_file=True."""
        gcode_mgr.update_cycle_buttons(base_states())
        mock_widgets.btn_cycle_start.setEnabled.assert_called_with(True)

    def test_start_disabled_when_no_file(self, gcode_mgr, mock_widgets):
        """START вимкнений якщо файл не завантажений."""
        gcode_mgr.update_cycle_buttons(base_states(has_file=False))
        mock_widgets.btn_cycle_start.setEnabled.assert_called_with(False)

    def test_start_disabled_when_not_ready(self, gcode_mgr, mock_widgets):
        """START вимкнений якщо машина не готова (is_ready=False)."""
        gcode_mgr.update_cycle_buttons(base_states(is_ready=False, all_homed=False))
        mock_widgets.btn_cycle_start.setEnabled.assert_called_with(False)

    def test_pause_enabled_only_when_running(self, gcode_mgr, mock_widgets):
        """PAUSE увімкнений тільки під час виконання."""
        gcode_mgr.update_cycle_buttons(base_states(is_idle=False, is_running=True))
        mock_widgets.btn_cycle_pause.setEnabled.assert_called_with(True)

    def test_pause_disabled_when_idle(self, gcode_mgr, mock_widgets):
        """PAUSE вимкнений коли idle."""
        gcode_mgr.update_cycle_buttons(base_states())
        mock_widgets.btn_cycle_pause.setEnabled.assert_called_with(False)

    def test_continue_enabled_only_when_paused(self, gcode_mgr, mock_widgets):
        """CONTINUE увімкнений тільки при is_paused=True."""
        gcode_mgr.update_cycle_buttons(
            base_states(is_idle=False, is_paused=True, is_running=False)
        )
        mock_widgets.btn_cycle_continue.setEnabled.assert_called_with(True)

    def test_continue_disabled_when_running(self, gcode_mgr, mock_widgets):
        """CONTINUE вимкнений якщо is_running=True (не чиста пауза)."""
        gcode_mgr.update_cycle_buttons(
            base_states(is_idle=False, is_paused=True, is_running=True)
        )
        mock_widgets.btn_cycle_continue.setEnabled.assert_called_with(False)

    def test_stop_enabled_when_running(self, gcode_mgr, mock_widgets):
        """STOP увімкнений при is_running=True."""
        gcode_mgr.update_cycle_buttons(base_states(is_idle=False, is_running=True))
        mock_widgets.btn_cycle_stop.setEnabled.assert_called_with(True)

    def test_stop_disabled_when_idle(self, gcode_mgr, mock_widgets):
        """STOP вимкнений при is_idle=True."""
        gcode_mgr.update_cycle_buttons(base_states())
        mock_widgets.btn_cycle_stop.setEnabled.assert_called_with(False)

    def test_step_enabled_when_has_file_and_ready(self, gcode_mgr, mock_widgets):
        """STEP увімкнений при has_file=True і ready=True."""
        gcode_mgr.update_cycle_buttons(base_states())
        mock_widgets.btn_cycle_step.setEnabled.assert_called_with(True)

    def test_all_buttons_disabled_when_estop(self, gcode_mgr, mock_widgets):
        """Всі кнопки вимкнені при ESTOP."""
        gcode_mgr.update_cycle_buttons(
            base_states(is_ready=False, all_homed=False,
                        is_idle=True, is_running=False, is_paused=False)
        )
        for name in ("btn_cycle_start", "btn_cycle_pause",
                     "btn_cycle_continue", "btn_cycle_stop"):
            getattr(mock_widgets, name).setEnabled.assert_called_with(False)


# ---------------------------------------------------------------------------
# Група 2: update_file_buttons
# ---------------------------------------------------------------------------

class TestUpdateFileButtons:

    def test_open_enabled_when_idle_and_ready(self, gcode_mgr, mock_widgets):
        """btn_file_open увімкнений при idle+ready."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
        gcode_mgr.update_file_buttons(base_states())
        mock_widgets.btn_file_open.setEnabled.assert_called_with(True)

    def test_open_disabled_when_not_idle(self, gcode_mgr, mock_widgets):
        """btn_file_open вимкнений якщо interpreter зайнятий."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
        gcode_mgr.update_file_buttons(base_states(is_idle=False, is_running=True))
        mock_widgets.btn_file_open.setEnabled.assert_called_with(False)

    def test_edit_reload_disabled_when_no_file(self, gcode_mgr, mock_widgets):
        """Edit і Reload вимкнені якщо файл не завантажений."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
        gcode_mgr.cnc.get_last_file.return_value = None
        gcode_mgr.update_file_buttons(base_states())
        mock_widgets.btn_file_edit.setEnabled.assert_called_with(False)
        mock_widgets.btn_file_reload.setEnabled.assert_called_with(False)

    def test_edit_reload_enabled_when_file_and_idle(self, gcode_mgr, mock_widgets):
        """Edit і Reload увімкнені при наявності файлу та idle."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
        gcode_mgr.cnc.get_last_file.return_value = "/tmp/test.ngc"
        gcode_mgr.update_file_buttons(base_states())
        mock_widgets.btn_file_edit.setEnabled.assert_called_with(True)
        mock_widgets.btn_file_reload.setEnabled.assert_called_with(True)

    def test_reload_gets_warn_style_when_reload_needed(self, gcode_mgr, mock_widgets):
        """btn_file_reload отримує WARN стиль коли reload_needed=True."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
        gcode_mgr.cnc.get_last_file.return_value = "/tmp/test.ngc"
        gcode_mgr.cnc.reload_needed = True
        mock_widgets.btn_file_reload.isEnabled.return_value = False
        mock_widgets.btn_file_reload.styleSheet.return_value = ""
        gcode_mgr.update_file_buttons(base_states())
        mock_widgets.btn_file_reload.setStyleSheet.assert_called_with("warn")

    def test_save_as_disabled_when_no_gcode_content(self, gcode_mgr, mock_widgets):
        """btn_file_save_as вимкнений якщо rowCount=0."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
        gcode_mgr.update_file_buttons(base_states())
        mock_widgets.btn_file_save_as.setEnabled.assert_called_with(False)

    def test_save_as_enabled_when_has_content(self, gcode_mgr, mock_widgets):
        """btn_file_save_as увімкнений якщо rowCount > 0."""
        mock_widgets.list_gcode_view.model.return_value.rowCount.return_value = 10
        gcode_mgr.cnc.get_last_file.return_value = "/tmp/test.ngc"
        mock_widgets.btn_file_save_as.isEnabled.return_value = False
        mock_widgets.btn_file_save_as.styleSheet.return_value = ""
        gcode_mgr.update_file_buttons(base_states())
        mock_widgets.btn_file_save_as.setEnabled.assert_called_with(True)


# ---------------------------------------------------------------------------
# Група 3: update_active_gcodes
# ---------------------------------------------------------------------------

class TestUpdateActiveGcodes:

    def test_formats_gcodes_correctly(self, gcode_mgr, mock_widgets):
        """G-коди форматуються як G20, G90 (code / 10)."""
        mock_widgets.txt_gcodeStatusBar.text.return_value = ""
        gcode_mgr.update_active_gcodes(
            base_states(gcodes=[200, 900, -1], mcodes=[-1], settings=[0, 0, 0])
        )
        text = mock_widgets.txt_gcodeStatusBar.setText.call_args[0][0]
        assert "G20" in text and "G90" in text

    def test_formats_mcodes_correctly(self, gcode_mgr, mock_widgets):
        """M-коди форматуються як M5."""
        mock_widgets.txt_gcodeStatusBar.text.return_value = ""
        gcode_mgr.update_active_gcodes(
            base_states(mcodes=[5, -1], gcodes=[-1], settings=[0, 0, 0])
        )
        assert "M5" in mock_widgets.txt_gcodeStatusBar.setText.call_args[0][0]

    def test_formats_feed_spindle_settings(self, gcode_mgr, mock_widgets):
        """Відображає F і S зі settings[1] і settings[2]."""
        mock_widgets.txt_gcodeStatusBar.text.return_value = ""
        gcode_mgr.update_active_gcodes(
            base_states(gcodes=[-1], mcodes=[-1], settings=[0, 250.0, 1000.0])
        )
        text = mock_widgets.txt_gcodeStatusBar.setText.call_args[0][0]
        assert "F250" in text and "S1000" in text

    def test_skips_minus1_codes(self, gcode_mgr, mock_widgets):
        """code==-1 пропускається."""
        mock_widgets.txt_gcodeStatusBar.text.return_value = ""
        gcode_mgr.update_active_gcodes(
            base_states(gcodes=[-1, -1], mcodes=[-1], settings=[0, 0, 0])
        )
        assert "G-1" not in mock_widgets.txt_gcodeStatusBar.setText.call_args[0][0]

    def test_no_update_when_text_unchanged(self, gcode_mgr, mock_widgets):
        """setText НЕ викликається якщо текст не змінився."""
        states = base_states(gcodes=[-1], mcodes=[-1], settings=[0, 0.0, 0.0])
        mock_widgets.txt_gcodeStatusBar.text.return_value = ""
        gcode_mgr.update_active_gcodes(states)
        expected = mock_widgets.txt_gcodeStatusBar.setText.call_args[0][0]
        mock_widgets.txt_gcodeStatusBar.text.return_value = expected
        mock_widgets.txt_gcodeStatusBar.setText.reset_mock()
        gcode_mgr.update_active_gcodes(states)
        mock_widgets.txt_gcodeStatusBar.setText.assert_not_called()

    def test_no_crash_when_status_bar_absent(self, gcode_mgr, mock_widgets):
        """update_active_gcodes не падає коли txt_gcodeStatusBar відсутній."""
        del mock_widgets.txt_gcodeStatusBar
        gcode_mgr.update_active_gcodes(base_states())


# ---------------------------------------------------------------------------
# Група 4: update_gcode_display
# ---------------------------------------------------------------------------

class TestUpdateGcodeDisplay:

    def _model(self, mock_widgets, rows=50):
        m = MagicMock()
        m.rowCount.return_value = rows
        mock_widgets.list_gcode_view.model.return_value = m
        return m

    def test_clears_view_when_file_removed(self, gcode_mgr, mock_widgets):
        """current_file=None → setModel(None) і lbl_filename='No file'."""
        mock_widgets.list_gcode_view.model.return_value = None
        gcode_mgr.last_loaded_file = "/tmp/old.ngc"
        gcode_mgr.update_gcode_display(base_states(current_file=None))
        mock_widgets.list_gcode_view.setModel.assert_called_with(None)
        mock_widgets.lbl_filename.setText.assert_called_with("No file")

    def test_loads_new_file_when_changed(self, gcode_mgr, mock_widgets):
        """Новий файл → _load_gcode_to_view викликається."""
        self._model(mock_widgets)
        gcode_mgr.last_loaded_file = "/tmp/old.ngc"
        gcode_mgr.update_gcode_display(base_states(current_file="/tmp/new.ngc"))
        gcode_mgr.file_manager._load_gcode_to_view.assert_called_once_with("/tmp/new.ngc")

    def test_no_reload_when_file_unchanged(self, gcode_mgr, mock_widgets):
        """Файл не змінився → _load_gcode_to_view НЕ викликається."""
        self._model(mock_widgets)
        gcode_mgr.last_loaded_file = "/tmp/test.ngc"
        gcode_mgr.update_gcode_display(base_states(current_file="/tmp/test.ngc"))
        gcode_mgr.file_manager._load_gcode_to_view.assert_not_called()

    def test_highlights_active_line_when_running(self, gcode_mgr, mock_widgets):
        """Під час виконання — setCurrentIndex і scrollTo викликаються."""
        self._model(mock_widgets, rows=50)
        gcode_mgr.last_loaded_file = "/tmp/test.ngc"
        gcode_mgr.update_gcode_display(base_states(is_idle=False, motion_line=10))
        mock_widgets.list_gcode_view.setCurrentIndex.assert_called_once()
        mock_widgets.list_gcode_view.scrollTo.assert_called_once()

    def test_progress_is_0_at_start(self, gcode_mgr, mock_widgets):
        """progress=0% коли idle і motion_line=0."""
        self._model(mock_widgets, rows=100)
        gcode_mgr.last_loaded_file = "/tmp/test.ngc"
        gcode_mgr.update_gcode_display(base_states(motion_line=0))
        assert "0" in mock_widgets.lbl_progress_percent.setText.call_args[0][0]

    def test_progress_is_100_at_end(self, gcode_mgr, mock_widgets):
        """progress=100% коли idle і motion_line >= total-2."""
        self._model(mock_widgets, rows=10)
        gcode_mgr.last_loaded_file = "/tmp/test.ngc"
        gcode_mgr.update_gcode_display(base_states(motion_line=9))
        assert "100" in mock_widgets.lbl_progress_percent.setText.call_args[0][0]

    def test_progress_calculated_during_run(self, gcode_mgr, mock_widgets):
        """progress=(motion_line+1)/total*100 під час виконання."""
        self._model(mock_widgets, rows=100)
        gcode_mgr.last_loaded_file = "/tmp/test.ngc"
        gcode_mgr.update_gcode_display(base_states(is_idle=False, motion_line=49))
        assert "50" in mock_widgets.lbl_progress_percent.setText.call_args[0][0]


# ---------------------------------------------------------------------------
# Група 5: _set_btn_state
# ---------------------------------------------------------------------------

class TestSetBtnState:

    def test_enables_button_and_applies_active_style(self, gcode_mgr, mock_widgets):
        """_set_btn_state(True) → setEnabled(True) + ACTIVE style."""
        gcode_mgr._set_btn_state("btn_cycle_start", True)
        mock_widgets.btn_cycle_start.setEnabled.assert_called_with(True)
        mock_widgets.btn_cycle_start.setStyleSheet.assert_called_with("active")

    def test_disables_button_and_applies_inactive_style(self, gcode_mgr, mock_widgets):
        """_set_btn_state(False) → setEnabled(False) + INACTIVE style."""
        gcode_mgr._set_btn_state("btn_cycle_start", False)
        mock_widgets.btn_cycle_start.setEnabled.assert_called_with(False)
        mock_widgets.btn_cycle_start.setStyleSheet.assert_called_with("inactive")

    def test_no_crash_when_button_absent(self, gcode_mgr):
        """_set_btn_state не падає коли кнопка відсутня (spec=[])."""
        gcode_mgr.widgets = MagicMock(spec=[])
        gcode_mgr._set_btn_state("btn_nonexistent", True)
