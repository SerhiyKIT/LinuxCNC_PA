"""
Tests for logic/managers/file_manager.py  –  FileManager
=========================================================

Run with:
    pytest test_file_manager.py -v

PyQt5 and config are mocked at module level so the suite runs without a
display server.  File I/O uses pytest's ``tmp_path`` fixture so no real
paths are hard-coded.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Mock PyQt5 and config before importing the module under test
# ---------------------------------------------------------------------------

_qt_core_mock    = MagicMock()
_qt_widgets_mock = MagicMock()

# QStringListModel needs a usable stub so _load_gcode_to_view can build one
_string_list_model_cls        = MagicMock()
_qt_core_mock.QStringListModel = _string_list_model_cls

# QAbstractItemView edit-trigger constants
_qt_widgets_mock.QAbstractItemView.DoubleClicked  = 2
_qt_widgets_mock.QAbstractItemView.EditKeyPressed = 16

sys.modules.setdefault("PyQt5",             MagicMock())
sys.modules.setdefault("PyQt5.QtCore",      _qt_core_mock)
sys.modules.setdefault("PyQt5.QtWidgets",   _qt_widgets_mock)
sys.modules.setdefault("config",            MagicMock(STYLES={"GCODE_WARN": "border: 1px solid red;"}))

from logic.managers.file_manager import (  # noqa: E402
    FileManager,
    _BTN_METHOD_MAP,
    _CANDIDATE_EDITORS,
    _FALLBACK_EXTENSION,
    _GCODE_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    cnc = MagicMock()
    cnc.is_interpreter_idle.return_value = True
    cnc.get_last_file.return_value       = None
    cnc.reload_needed                    = False
    return cnc


@pytest.fixture()
def mock_widgets() -> MagicMock:
    widgets = MagicMock()
    # Pre-create all buttons so connect_file_buttons always finds them
    for btn_name, _ in _BTN_METHOD_MAP:
        btn = MagicMock()
        btn.clicked = MagicMock()
        setattr(widgets, btn_name, btn)
    # G-code view and labels
    widgets.list_gcode_view        = MagicMock()
    widgets.lbl_filename           = MagicMock()
    widgets.lbl_progress_percent   = MagicMock()
    widgets.btn_file_reload        = MagicMock()
    return widgets


@pytest.fixture()
def manager(mock_cnc, mock_widgets) -> FileManager:
    return FileManager(mock_cnc, mock_widgets)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gcode_file(tmp_path, content: str = "G0 X0\nG0 Y0\n") -> str:
    """Write a minimal G-code file and return its absolute path."""
    p = tmp_path / "test.ngc"
    p.write_text(content, encoding="utf-8")
    return str(p)


# ===========================================================================
# Initialisation
# ===========================================================================

class TestInit:
    def test_stores_cnc_reference(self, mock_cnc, mock_widgets):
        m = FileManager(mock_cnc, mock_widgets)
        assert m.cnc is mock_cnc

    def test_stores_widgets_reference(self, mock_cnc, mock_widgets):
        m = FileManager(mock_cnc, mock_widgets)
        assert m.widgets is mock_widgets

    def test_style_loaded_from_config(self, mock_cnc, mock_widgets):
        import logic.managers.file_manager as _mod
        with patch.object(_mod, "STYLES", {"GCODE_WARN": "border: 1px solid red;"}):
            m = FileManager(mock_cnc, mock_widgets)
        assert m.STYLE_GCODE_WARN == "border: 1px solid red;"

    def test_slots_prevent_arbitrary_attributes(self, manager):
        with pytest.raises(AttributeError):
            manager.unexpected = "oops"

    def test_repr_contains_class_name(self, manager):
        assert "FileManager" in repr(manager)


# ===========================================================================
# connect_file_buttons
# ===========================================================================

class TestConnectFileButtons:
    def test_all_buttons_connected(self, manager, mock_widgets):
        manager.connect_file_buttons()
        for btn_name, _ in _BTN_METHOD_MAP:
            btn = getattr(mock_widgets, btn_name)
            btn.clicked.connect.assert_called_once()

    def test_each_button_connected_to_correct_handler(self, manager, mock_widgets):
        manager.connect_file_buttons()
        for btn_name, method_name in _BTN_METHOD_MAP:
            btn = getattr(mock_widgets, btn_name)
            expected = getattr(manager, method_name)
            btn.clicked.connect.assert_called_once_with(expected)

    def test_missing_button_skipped_silently(self, mock_cnc):
        """Absent buttons must not raise — partial layouts are valid."""
        widgets = MagicMock(spec=[])
        m = FileManager(mock_cnc, widgets)
        m.connect_file_buttons()   # must not raise


# ===========================================================================
# on_btn_file_open_clicked
# ===========================================================================

class TestOnBtnFileOpenClicked:
    def test_no_op_when_dialog_cancelled(self, manager, mock_cnc):
        with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
                   return_value=("", "")):
            manager.on_btn_file_open_clicked()
        mock_cnc.open_program.assert_not_called()

    def test_opens_program_on_valid_path(self, manager, mock_cnc, tmp_path):
        path = _make_gcode_file(tmp_path)
        with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_open_clicked()
        mock_cnc.open_program.assert_called_once_with(path)

    def test_loads_gcode_view_on_success(self, manager, tmp_path):
        path = _make_gcode_file(tmp_path)
        with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_load_gcode_to_view") as mock_load:
            manager.on_btn_file_open_clicked()
        mock_load.assert_called_once_with(path)

    def test_exception_from_open_program_is_swallowed(self, manager, mock_cnc, tmp_path):
        path = _make_gcode_file(tmp_path)
        mock_cnc.open_program.side_effect = Exception("NML error")
        with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_open_clicked()   # must not raise

    def test_exception_is_logged_as_error(self, manager, mock_cnc, tmp_path):
        path = _make_gcode_file(tmp_path)
        mock_cnc.open_program.side_effect = Exception("err")
        with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_load_gcode_to_view"), \
             patch("logic.managers.file_manager.logger") as mock_log:
            manager.on_btn_file_open_clicked()
        mock_log.error.assert_called_once()


# ===========================================================================
# on_btn_file_save_as_clicked
# ===========================================================================

class TestOnBtnFileSaveAsClicked:
    def _setup_model(self, manager, rows: list[str]) -> MagicMock:
        model = MagicMock()
        model.rowCount.return_value = len(rows)
        model.index.side_effect = lambda i, _: MagicMock(
            **{"data.return_value": rows[i]}
        )
        manager.widgets.list_gcode_view.model.return_value = model
        return model

    def test_blocked_when_interpreter_busy(self, manager, mock_cnc):
        mock_cnc.is_interpreter_idle.return_value = False
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName") as dlg:
            manager.on_btn_file_save_as_clicked()
        dlg.assert_not_called()

    def test_blocked_when_model_is_none(self, manager):
        manager.widgets.list_gcode_view.model.return_value = None
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName") as dlg:
            manager.on_btn_file_save_as_clicked()
        dlg.assert_not_called()

    def test_blocked_when_model_is_empty(self, manager):
        model = MagicMock()
        model.rowCount.return_value = 0
        manager.widgets.list_gcode_view.model.return_value = model
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName") as dlg:
            manager.on_btn_file_save_as_clicked()
        dlg.assert_not_called()

    def test_no_op_when_dialog_cancelled(self, manager):
        self._setup_model(manager, ["G0 X0"])
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
                   return_value=("", "")), \
             patch.object(FileManager, "_write_model_to_file") as mock_write:
            manager.on_btn_file_save_as_clicked()
        mock_write.assert_not_called()

    def test_appends_fallback_extension_when_missing(self, manager, mock_cnc, tmp_path):
        self._setup_model(manager, ["G0 X0"])
        raw_path = str(tmp_path / "output")   # no extension
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
                   return_value=(raw_path, "")), \
             patch.object(FileManager, "_write_model_to_file"), \
             patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_save_as_clicked()
        mock_cnc.open_program.assert_called_once_with(raw_path + _FALLBACK_EXTENSION)

    @pytest.mark.parametrize("ext", list(_GCODE_EXTENSIONS))
    def test_does_not_append_extension_when_already_present(
        self, manager, mock_cnc, tmp_path, ext
    ):
        self._setup_model(manager, ["G0 X0"])
        path = str(tmp_path / f"output{ext}")
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_write_model_to_file"), \
             patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_save_as_clicked()
        mock_cnc.open_program.assert_called_once_with(path)

    def test_writes_model_and_loads_view(self, manager, mock_cnc, tmp_path):
        self._setup_model(manager, ["G0 X0"])
        path = str(tmp_path / "out.ngc")
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_write_model_to_file") as mock_write, \
             patch.object(FileManager, "_load_gcode_to_view") as mock_load:
            manager.on_btn_file_save_as_clicked()
        mock_write.assert_called_once()
        mock_load.assert_called_once_with(path)

    def test_exception_is_swallowed_and_logged(self, manager, mock_cnc, tmp_path):
        self._setup_model(manager, ["G0 X0"])
        path = str(tmp_path / "out.ngc")
        mock_cnc.open_program.side_effect = Exception("write error")
        with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
                   return_value=(path, "")), \
             patch.object(FileManager, "_write_model_to_file"), \
             patch.object(FileManager, "_load_gcode_to_view"), \
             patch("logic.managers.file_manager.logger") as mock_log:
            manager.on_btn_file_save_as_clicked()
        mock_log.error.assert_called_once()


# ===========================================================================
# on_btn_file_reload_clicked
# ===========================================================================

class TestOnBtnFileReloadClicked:
    def test_blocked_when_no_last_file(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = None
        manager.on_btn_file_reload_clicked()
        mock_cnc.open_program.assert_not_called()

    def test_blocked_when_interpreter_busy(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value       = "/tmp/job.ngc"
        mock_cnc.is_interpreter_idle.return_value = False
        manager.on_btn_file_reload_clicked()
        mock_cnc.open_program.assert_not_called()

    def test_opens_program_on_success(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_reload_clicked()
        mock_cnc.open_program.assert_called_once_with("/tmp/job.ngc")

    def test_loads_gcode_view_on_success(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_load_gcode_to_view") as mock_load:
            manager.on_btn_file_reload_clicked()
        mock_load.assert_called_once_with("/tmp/job.ngc")

    def test_clears_reload_needed_flag(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        mock_cnc.reload_needed = True
        with patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_reload_clicked()
        assert mock_cnc.reload_needed is False

    def test_clears_reload_button_style(self, manager, mock_cnc, mock_widgets):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_load_gcode_to_view"):
            manager.on_btn_file_reload_clicked()
        mock_widgets.btn_file_reload.setStyleSheet.assert_called_with("")

    def test_exception_is_swallowed_and_logged(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        mock_cnc.open_program.side_effect   = Exception("reload error")
        with patch("logic.managers.file_manager.logger") as mock_log:
            manager.on_btn_file_reload_clicked()
        mock_log.error.assert_called_once()


# ===========================================================================
# on_btn_file_edit_clicked
# ===========================================================================

class TestOnBtnFileEditClicked:
    def test_no_op_when_no_last_file(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = None
        with patch("logic.managers.file_manager.subprocess.Popen") as mock_popen:
            manager.on_btn_file_edit_clicked()
        mock_popen.assert_not_called()

    def test_no_op_when_interpreter_busy(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value       = "/tmp/job.ngc"
        mock_cnc.is_interpreter_idle.return_value = False
        with patch("logic.managers.file_manager.subprocess.Popen") as mock_popen:
            manager.on_btn_file_edit_clicked()
        mock_popen.assert_not_called()

    def test_no_op_when_no_editor_found(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_find_editor", return_value=None), \
             patch("logic.managers.file_manager.subprocess.Popen") as mock_popen:
            manager.on_btn_file_edit_clicked()
        mock_popen.assert_not_called()

    def test_launches_found_editor(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_find_editor", return_value="gedit"), \
             patch("logic.managers.file_manager.subprocess.Popen") as mock_popen:
            manager.on_btn_file_edit_clicked()
        mock_popen.assert_called_once_with(["gedit", "/tmp/job.ngc"])

    def test_sets_reload_needed_flag(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_find_editor", return_value="gedit"), \
             patch("logic.managers.file_manager.subprocess.Popen"):
            manager.on_btn_file_edit_clicked()
        assert mock_cnc.reload_needed is True

    def test_sets_warning_stylesheet_on_reload_button(
        self, manager, mock_cnc, mock_widgets
    ):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        manager.STYLE_GCODE_WARN = "border: 1px solid red;"
        with patch.object(FileManager, "_find_editor", return_value="gedit"), \
             patch("logic.managers.file_manager.subprocess.Popen"):
            manager.on_btn_file_edit_clicked()
        mock_widgets.btn_file_reload.setStyleSheet.assert_called_with(
            "border: 1px solid red;"
        )

    def test_no_editor_found_logs_warning(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/tmp/job.ngc"
        with patch.object(FileManager, "_find_editor", return_value=None), \
             patch("logic.managers.file_manager.logger") as mock_log:
            manager.on_btn_file_edit_clicked()
        mock_log.warning.assert_called_once()


# ===========================================================================
# _load_gcode_to_view
# ===========================================================================

class TestLoadGcodeToView:
    def test_no_op_when_file_missing(self, manager):
        with patch("logic.managers.file_manager.logger") as mock_log:
            manager._load_gcode_to_view("/no/such/file.ngc")
        mock_log.error.assert_called_once()

    def test_sets_model_on_view(self, manager, tmp_path):
        path = _make_gcode_file(tmp_path, "G0 X0\nG0 Y0\n")
        manager._load_gcode_to_view(path)
        manager.widgets.list_gcode_view.setModel.assert_called_once()

    def test_sets_filename_label(self, manager, tmp_path, mock_widgets):
        path = _make_gcode_file(tmp_path, "G0 X0\n")
        manager._load_gcode_to_view(path)
        mock_widgets.lbl_filename.setText.assert_called_with("test.ngc")

    def test_resets_progress_label(self, manager, tmp_path, mock_widgets):
        path = _make_gcode_file(tmp_path, "G0 X0\n")
        manager._load_gcode_to_view(path)
        mock_widgets.lbl_progress_percent.setText.assert_called_with("0%")

    def test_sets_edit_triggers(self, manager, tmp_path):
        path = _make_gcode_file(tmp_path, "G0 X0\n")
        manager._load_gcode_to_view(path)
        manager.widgets.list_gcode_view.setEditTriggers.assert_called_once()

    def test_exception_is_swallowed_and_logged(self, manager, tmp_path):
        path = _make_gcode_file(tmp_path, "G0 X0\n")
        manager.widgets.list_gcode_view.setModel.side_effect = Exception("Qt error")
        with patch("logic.managers.file_manager.logger") as mock_log:
            manager._load_gcode_to_view(path)
        mock_log.error.assert_called_once()

    def test_skips_view_when_absent(self, manager, mock_cnc, tmp_path):
        """_load_gcode_to_view must not raise when list_gcode_view is absent."""
        path    = _make_gcode_file(tmp_path, "G0 X0\n")
        widgets = MagicMock(spec=["lbl_filename", "lbl_progress_percent"])
        widgets.lbl_filename         = MagicMock()
        widgets.lbl_progress_percent = MagicMock()
        m = FileManager(mock_cnc, widgets)
        m._load_gcode_to_view(path)   # must not raise


# ===========================================================================
# _on_gcode_edited
# ===========================================================================

class TestOnGcodeEdited:
    def test_blocked_when_interpreter_busy(self, manager, mock_cnc):
        mock_cnc.is_interpreter_idle.return_value = False
        manager._on_gcode_edited(None, None, None)
        mock_cnc.open_program.assert_not_called()

    def test_blocked_when_no_last_file(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = None
        manager._on_gcode_edited(None, None, None)
        mock_cnc.open_program.assert_not_called()

    def test_blocked_when_file_not_on_disk(self, manager, mock_cnc):
        mock_cnc.get_last_file.return_value = "/no/such/file.ngc"
        manager._on_gcode_edited(None, None, None)
        mock_cnc.open_program.assert_not_called()

    def test_saves_and_syncs_on_success(self, manager, mock_cnc, tmp_path):
        path  = _make_gcode_file(tmp_path, "G0 X0\n")
        mock_cnc.get_last_file.return_value = path

        model = MagicMock()
        model.stringList.return_value = ["G0 X0", "G0 Y0"]
        manager.widgets.list_gcode_view.model.return_value = model

        manager._on_gcode_edited(None, None, None)

        mock_cnc.open_program.assert_called_once_with(path)

    def test_clears_reload_needed_flag(self, manager, mock_cnc, tmp_path):
        path  = _make_gcode_file(tmp_path)
        mock_cnc.get_last_file.return_value = path
        mock_cnc.reload_needed = True

        model = MagicMock()
        model.stringList.return_value = ["G0 X0"]
        manager.widgets.list_gcode_view.model.return_value = model

        manager._on_gcode_edited(None, None, None)
        assert mock_cnc.reload_needed is False

    def test_clears_reload_button_style(self, manager, mock_cnc, mock_widgets, tmp_path):
        path  = _make_gcode_file(tmp_path)
        mock_cnc.get_last_file.return_value = path

        model = MagicMock()
        model.stringList.return_value = ["G0 X0"]
        manager.widgets.list_gcode_view.model.return_value = model

        manager._on_gcode_edited(None, None, None)
        mock_widgets.btn_file_reload.setStyleSheet.assert_called_with("")

    def test_exception_is_swallowed_and_logged(self, manager, mock_cnc, tmp_path):
        path = _make_gcode_file(tmp_path)
        mock_cnc.get_last_file.return_value = path
        mock_cnc.open_program.side_effect   = Exception("sync error")

        model = MagicMock()
        model.stringList.return_value = ["G0 X0"]
        manager.widgets.list_gcode_view.model.return_value = model

        with patch("logic.managers.file_manager.logger") as mock_log:
            manager._on_gcode_edited(None, None, None)
        mock_log.error.assert_called_once()


# ===========================================================================
# Static helpers – file I/O
# ===========================================================================

class TestReadLines:
    def test_returns_stripped_lines(self, tmp_path):
        p = tmp_path / "f.ngc"
        p.write_text("  G0 X0  \n  G0 Y0  \n", encoding="utf-8")
        assert FileManager._read_lines(str(p)) == ["G0 X0", "G0 Y0"]

    def test_empty_file_returns_empty_list(self, tmp_path):
        p = tmp_path / "f.ngc"
        p.write_text("", encoding="utf-8")
        assert FileManager._read_lines(str(p)) == []


class TestWriteLinesToFile:
    def test_writes_joined_lines_with_trailing_newline(self, tmp_path):
        p = tmp_path / "out.ngc"
        FileManager._write_lines_to_file(["G0 X0", "G0 Y0"], str(p))
        assert p.read_text(encoding="utf-8") == "G0 X0\nG0 Y0\n"

    def test_empty_list_writes_only_newline(self, tmp_path):
        p = tmp_path / "out.ngc"
        FileManager._write_lines_to_file([], str(p))
        assert p.read_text(encoding="utf-8") == "\n"


class TestWriteModelToFile:
    def test_writes_model_rows(self, tmp_path):
        p     = tmp_path / "out.ngc"
        model = MagicMock()
        model.rowCount.return_value = 2
        rows  = ["G0 X0", "G0 Y10"]
        model.index.side_effect = lambda i, _: MagicMock(
            **{"data.return_value": rows[i]}
        )
        FileManager._write_model_to_file(model, str(p))
        assert p.read_text(encoding="utf-8") == "G0 X0\nG0 Y10"


# ===========================================================================
# Static helper – _find_editor
# ===========================================================================

class TestFindEditor:
    def test_returns_first_available_editor(self):
        def _which(cmd, **_):
            return 0 if cmd[1] == _CANDIDATE_EDITORS[0] else 1

        with patch("logic.managers.file_manager.subprocess.call",
                   side_effect=_which):
            assert FileManager._find_editor() == _CANDIDATE_EDITORS[0]

    def test_skips_unavailable_editors(self):
        """First two editors absent, third present."""
        target = _CANDIDATE_EDITORS[2]

        def _which(cmd, **_):
            return 0 if cmd[1] == target else 1

        with patch("logic.managers.file_manager.subprocess.call",
                   side_effect=_which):
            assert FileManager._find_editor() == target

    def test_returns_none_when_no_editor_found(self):
        with patch("logic.managers.file_manager.subprocess.call", return_value=1):
            assert FileManager._find_editor() is None

    def test_calls_which_for_each_candidate_until_found(self):
        """_find_editor must stop searching after the first hit."""
        with patch("logic.managers.file_manager.subprocess.call",
                   return_value=0) as mock_call:
            FileManager._find_editor()
        # Only one 'which' call should have been made
        assert mock_call.call_count == 1