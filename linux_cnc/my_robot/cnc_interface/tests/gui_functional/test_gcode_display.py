# tests/gui_functional/test_gcode_display.py
"""
Функціональні GUI-тести GCodeDisplayManager
=============================================
Реальні Qt-віджети: QPushButton, QLabel, QListView + QStandardItemModel.
cnc — MagicMock.

Групи:
  1. Cycle buttons enabled/disabled  — 8 тестів
  2. File buttons enabled/disabled   — 6 тестів
  3. Active G-codes status bar       — 5 тестів
  4. G-code display + progress       — 6 тестів
  5. Cycle button stylesheets        — 3 тести
"""

import pytest
from unittest.mock import patch, MagicMock
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QStandardItemModel, QStandardItem

from tests.gui_functional.conftest import base_states, make_cnc

_CYCLE_BUTTONS = [
    "btn_cycle_start", "btn_cycle_pause", "btn_cycle_continue",
    "btn_cycle_stop",  "btn_cycle_step",
]
_FILE_BUTTONS = [
    "btn_file_open", "btn_file_edit", "btn_file_reload", "btn_file_save_as",
]


# ---------------------------------------------------------------------------
# Реальні Qt-віджети
# ---------------------------------------------------------------------------

class GCodeWidgets(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Cycle control buttons
        self.btn_cycle_start    = QtWidgets.QPushButton("START",    self)
        self.btn_cycle_pause    = QtWidgets.QPushButton("PAUSE",    self)
        self.btn_cycle_continue = QtWidgets.QPushButton("CONTINUE", self)
        self.btn_cycle_stop     = QtWidgets.QPushButton("STOP",     self)
        self.btn_cycle_step     = QtWidgets.QPushButton("STEP",     self)
        # File buttons
        self.btn_file_open    = QtWidgets.QPushButton("Open",    self)
        self.btn_file_edit    = QtWidgets.QPushButton("Edit",    self)
        self.btn_file_reload  = QtWidgets.QPushButton("Reload",  self)
        self.btn_file_save_as = QtWidgets.QPushButton("Save as", self)
        # Status bar
        self.txt_gcodeStatusBar = QtWidgets.QLabel("", self)
        # G-code view (QListView + model)
        self.list_gcode_view = QtWidgets.QListView(self)
        # Labels
        self.lbl_filename        = QtWidgets.QLabel("No file", self)
        self.lbl_progress_percent = QtWidgets.QLabel("PROGRESS 0%", self)


def _make_model(rows=100):
    model = QStandardItemModel()
    for i in range(rows):
        model.appendRow(QStandardItem(f"N{i:03d} G0 X{i}"))
    return model


@pytest.fixture
def gcode(qtbot):
    widgets = GCodeWidgets()
    qtbot.addWidget(widgets)
    cnc = make_cnc()

    with patch("managers.ui.gcode_display.FileManager"), \
         patch("managers.ui.gcode_display.CYCLE_BUTTONS", _CYCLE_BUTTONS), \
         patch("managers.ui.gcode_display.FILE_BUTTONS",  _FILE_BUTTONS):
        from managers.ui.gcode_display import GCodeDisplayManager
        mgr = GCodeDisplayManager(cnc, widgets)
        mgr.cycle_buttons = _CYCLE_BUTTONS

    return mgr, widgets, cnc


# ---------------------------------------------------------------------------
# Група 1: Cycle buttons enabled/disabled
# ---------------------------------------------------------------------------

class TestCycleButtonsState:

    def test_start_enabled_when_idle_ready_has_file(self, gcode):
        """btn_cycle_start реально enabled: idle + ready + has_file."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states())
        assert widgets.btn_cycle_start.isEnabled()

    def test_start_disabled_when_no_file(self, gcode):
        """btn_cycle_start реально disabled: has_file=False."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states(has_file=False))
        assert not widgets.btn_cycle_start.isEnabled()

    def test_start_disabled_when_not_ready(self, gcode):
        """btn_cycle_start реально disabled: is_ready=False."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states(is_ready=False, all_homed=False))
        assert not widgets.btn_cycle_start.isEnabled()

    def test_pause_enabled_when_running(self, gcode):
        """btn_cycle_pause реально enabled при is_running=True."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states(is_idle=False, is_running=True))
        assert widgets.btn_cycle_pause.isEnabled()

    def test_pause_disabled_when_idle(self, gcode):
        """btn_cycle_pause реально disabled при idle."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states())
        assert not widgets.btn_cycle_pause.isEnabled()

    def test_continue_enabled_when_paused(self, gcode):
        """btn_cycle_continue реально enabled при is_paused=True."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(
            base_states(is_idle=False, is_paused=True, is_running=False)
        )
        assert widgets.btn_cycle_continue.isEnabled()

    def test_stop_enabled_when_running(self, gcode):
        """btn_cycle_stop реально enabled при is_running=True."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states(is_idle=False, is_running=True))
        assert widgets.btn_cycle_stop.isEnabled()

    def test_all_disabled_on_estop(self, gcode):
        """Всі cycle кнопки реально disabled при ESTOP."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(
            base_states(is_ready=False, all_homed=False,
                        is_idle=True, is_running=False, is_paused=False)
        )
        for name in _CYCLE_BUTTONS:
            btn = getattr(widgets, name)
            assert not btn.isEnabled(), f"{name} повинен бути disabled"


# ---------------------------------------------------------------------------
# Група 2: File buttons enabled/disabled
# ---------------------------------------------------------------------------

class TestFileButtonsState:

    def test_open_enabled_when_idle_and_ready(self, gcode):
        """btn_file_open реально enabled при idle + ready."""
        mgr, widgets, cnc = gcode
        cnc.get_last_file.return_value = None
        mgr.update_file_buttons(base_states())
        assert widgets.btn_file_open.isEnabled()

    def test_open_disabled_when_running(self, gcode):
        """btn_file_open реально disabled при is_idle=False."""
        mgr, widgets, cnc = gcode
        mgr.update_file_buttons(base_states(is_idle=False, is_running=True))
        assert not widgets.btn_file_open.isEnabled()

    def test_edit_disabled_when_no_file(self, gcode):
        """btn_file_edit реально disabled якщо файл не завантажено."""
        mgr, widgets, cnc = gcode
        cnc.get_last_file.return_value = None
        mgr.update_file_buttons(base_states())
        assert not widgets.btn_file_edit.isEnabled()

    def test_edit_enabled_when_file_present(self, gcode):
        """btn_file_edit реально enabled при наявності файлу."""
        mgr, widgets, cnc = gcode
        cnc.get_last_file.return_value = "/tmp/test.ngc"
        mgr.update_file_buttons(base_states())
        assert widgets.btn_file_edit.isEnabled()

    def test_save_as_disabled_when_view_empty(self, gcode):
        """btn_file_save_as реально disabled коли model порожній."""
        mgr, widgets, cnc = gcode
        model = QStandardItemModel()   # 0 рядків
        widgets.list_gcode_view.setModel(model)
        mgr.update_file_buttons(base_states())
        assert not widgets.btn_file_save_as.isEnabled()

    def test_save_as_enabled_when_view_has_content(self, gcode):
        """btn_file_save_as реально enabled коли model не порожній."""
        mgr, widgets, cnc = gcode
        cnc.get_last_file.return_value = "/tmp/test.ngc"
        widgets.list_gcode_view.setModel(_make_model(5))
        mgr.update_file_buttons(base_states())
        assert widgets.btn_file_save_as.isEnabled()


# ---------------------------------------------------------------------------
# Група 3: Active G-codes status bar
# ---------------------------------------------------------------------------

class TestActiveGcodesStatusBar:

    def test_status_bar_shows_gcode_labels(self, gcode):
        """txt_gcodeStatusBar.text() містить G20 і G90."""
        mgr, widgets, _ = gcode
        mgr.update_active_gcodes(
            base_states(gcodes=[200, 900, -1], mcodes=[-1], settings=[0, 0, 0])
        )
        text = widgets.txt_gcodeStatusBar.text()
        assert "G20" in text
        assert "G90" in text

    def test_status_bar_shows_mcode(self, gcode):
        """txt_gcodeStatusBar.text() містить M5."""
        mgr, widgets, _ = gcode
        mgr.update_active_gcodes(
            base_states(gcodes=[-1], mcodes=[5, -1], settings=[0, 0, 0])
        )
        assert "M5" in widgets.txt_gcodeStatusBar.text()

    def test_status_bar_shows_feed_and_spindle(self, gcode):
        """txt_gcodeStatusBar.text() містить F і S значення."""
        mgr, widgets, _ = gcode
        mgr.update_active_gcodes(
            base_states(gcodes=[-1], mcodes=[-1], settings=[0, 300.0, 800.0])
        )
        text = widgets.txt_gcodeStatusBar.text()
        assert "F300" in text
        assert "S800" in text

    def test_status_bar_excludes_minus1_codes(self, gcode):
        """txt_gcodeStatusBar не містить 'G-1' або 'M-1'."""
        mgr, widgets, _ = gcode
        mgr.update_active_gcodes(
            base_states(gcodes=[-1, -1], mcodes=[-1], settings=[0, 0, 0])
        )
        text = widgets.txt_gcodeStatusBar.text()
        assert "G-1" not in text
        assert "M-1" not in text

    def test_status_bar_not_updated_when_unchanged(self, gcode):
        """Повторний виклик з тим самим станом не змінює текст QLabel."""
        mgr, widgets, _ = gcode
        states = base_states(gcodes=[-1], mcodes=[-1], settings=[0, 0.0, 0.0])
        mgr.update_active_gcodes(states)
        text_first = widgets.txt_gcodeStatusBar.text()
        mgr.update_active_gcodes(states)
        assert widgets.txt_gcodeStatusBar.text() == text_first


# ---------------------------------------------------------------------------
# Група 4: G-code display та progress
# ---------------------------------------------------------------------------

class TestGcodeDisplayAndProgress:

    def test_clears_label_when_no_file(self, gcode):
        """lbl_filename.text() == 'No file' при current_file=None."""
        mgr, widgets, _ = gcode
        mgr.last_loaded_file = "/tmp/old.ngc"
        mgr.update_gcode_display(base_states(current_file=None))
        assert widgets.lbl_filename.text() == "No file"

    def test_clears_model_when_no_file(self, gcode):
        """list_gcode_view.model() is None при current_file=None."""
        mgr, widgets, _ = gcode
        widgets.list_gcode_view.setModel(_make_model(10))
        mgr.last_loaded_file = "/tmp/old.ngc"
        mgr.update_gcode_display(base_states(current_file=None))
        assert widgets.list_gcode_view.model() is None

    def test_progress_label_shows_0_at_start(self, gcode):
        """lbl_progress_percent містить '0' при motion_line=0 і idle."""
        mgr, widgets, _ = gcode
        widgets.list_gcode_view.setModel(_make_model(100))
        mgr.last_loaded_file = "/tmp/test.ngc"
        mgr.update_gcode_display(base_states(motion_line=0))
        assert "0" in widgets.lbl_progress_percent.text()

    def test_progress_label_shows_100_at_end(self, gcode):
        """lbl_progress_percent містить '100' при motion_line >= total-2."""
        mgr, widgets, _ = gcode
        widgets.list_gcode_view.setModel(_make_model(10))
        mgr.last_loaded_file = "/tmp/test.ngc"
        mgr.update_gcode_display(base_states(motion_line=9))
        assert "100" in widgets.lbl_progress_percent.text()

    def test_progress_midpoint_during_run(self, gcode):
        """lbl_progress_percent містить '50' при motion_line=49 з 100."""
        mgr, widgets, _ = gcode
        widgets.list_gcode_view.setModel(_make_model(100))
        mgr.last_loaded_file = "/tmp/test.ngc"
        mgr.update_gcode_display(base_states(is_idle=False, motion_line=49))
        assert "50" in widgets.lbl_progress_percent.text()

    def test_scroll_triggered_when_running(self, gcode, qtbot):
        """Під час виконання активна лінія видима (scrollTo не кидає виняток)."""
        mgr, widgets, _ = gcode
        widgets.list_gcode_view.setModel(_make_model(100))
        mgr.last_loaded_file = "/tmp/test.ngc"
        # Перевіряємо що виклик не падає і рядок виділений
        mgr.update_gcode_display(base_states(is_idle=False, motion_line=10))
        idx = widgets.list_gcode_view.currentIndex()
        assert idx.row() == 10


# ---------------------------------------------------------------------------
# Група 5: Cycle button stylesheets
# ---------------------------------------------------------------------------

class TestCycleButtonStylesheets:

    def test_enabled_button_gets_active_style(self, gcode):
        """Enabled кнопка отримує stylesheet відмінний від disabled."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states())
        style_enabled = widgets.btn_cycle_start.styleSheet()

        mgr.update_cycle_buttons(base_states(has_file=False))
        style_disabled = widgets.btn_cycle_start.styleSheet()

        assert style_enabled != style_disabled

    def test_all_disabled_buttons_have_same_style(self, gcode):
        """Всі disabled cycle кнопки мають однаковий inactive stylesheet."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(
            base_states(is_ready=False, all_homed=False,
                        is_idle=True, is_running=False, is_paused=False)
        )
        styles = {getattr(widgets, n).styleSheet() for n in _CYCLE_BUTTONS}
        assert len(styles) == 1, "Всі inactive кнопки повинні мати однаковий стиль"

    def test_stylesheet_restored_after_re_enable(self, gcode):
        """Після повторного вмикання кнопка отримує active stylesheet назад."""
        mgr, widgets, _ = gcode
        mgr.update_cycle_buttons(base_states())
        style_active = widgets.btn_cycle_start.styleSheet()

        mgr.update_cycle_buttons(base_states(has_file=False))
        mgr.update_cycle_buttons(base_states())

        assert widgets.btn_cycle_start.styleSheet() == style_active
