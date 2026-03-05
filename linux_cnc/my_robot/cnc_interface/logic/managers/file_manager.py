# logic/managers/file_manager.py
from __future__ import annotations

import logging
import os
import subprocess
from typing import TYPE_CHECKING

from PyQt5.QtCore import QStringListModel
from PyQt5.QtWidgets import QAbstractItemView, QFileDialog

from config import STYLES

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_GCODE_DIR  = os.path.expanduser("~/linuxcnc-dev/configs/sim/axis/nc_files")
_GCODE_FILTER       = "G-Code Files (*.ngc *.txt *.gcode);;All Files (*)"
_SAVE_FILTER        = "G-Code Files (*.ngc *.txt)"
_GCODE_EXTENSIONS   = (".ngc", ".txt")
_FALLBACK_EXTENSION = ".ngc"
_CANDIDATE_EDITORS  = ("gedit", "mousepad", "leafpad", "xed", "nano")

_BTN_METHOD_MAP: tuple[tuple[str, str], ...] = (
    ("btn_file_open",    "on_btn_file_open_clicked"),
    ("btn_file_save_as", "on_btn_file_save_as_clicked"),
    ("btn_file_reload",  "on_btn_file_reload_clicked"),
    ("btn_file_edit",    "on_btn_file_edit_clicked"),
)

_EDIT_TRIGGERS = QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed


# ---------------------------------------------------------------------------
# FileManager
# ---------------------------------------------------------------------------

class FileManager:
    """
    Manages G-code file operations: open, save-as, reload, and edit.

    Bridges the file system and external editors with the LinuxCNC
    controller and the G-code list view widget.  All Qt dialogs and widget
    interactions are confined to this class so that the rest of the
    application remains UI-agnostic.

    Attributes:
        cnc:             Reference to the active machine controller.
        widgets:         UI widget container.
        STYLE_GCODE_WARN: Stylesheet string applied to the reload button
                          when unsaved edits are pending.
    """

    __slots__ = ("cnc", "widgets", "STYLE_GCODE_WARN", "__weakref__")

    def __init__(
        self,
        machine_controller: MachineController,
        widgets: object,
    ) -> None:
        self.cnc             = machine_controller
        self.widgets         = widgets
        self.STYLE_GCODE_WARN = STYLES.get("GCODE_WARN", "")

    # ------------------------------------------------------------------
    # Button wiring
    # ------------------------------------------------------------------

    def connect_file_buttons(self) -> None:
        """
        Connect each file-operation button's ``clicked`` signal to its
        handler method.

        Buttons absent from the widget container are silently skipped so
        that partial UI layouts do not raise errors.
        """
        for btn_name, method_name in _BTN_METHOD_MAP:
            btn = getattr(self.widgets, btn_name, None)
            if btn is not None:
                btn.clicked.connect(getattr(self, method_name))

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_btn_file_open_clicked(self) -> None:
        """
        Open a G-code file via a file dialog and load it into the
        controller and list view.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Open G-Code File",
            _DEFAULT_GCODE_DIR,
            _GCODE_FILTER,
        )
        if not file_path:
            return

        try:
            self.cnc.open_program(file_path)
            self._load_gcode_to_view(file_path)
        except Exception as exc:
            logger.error("Не вдалося завантажити файл: %s", exc)

    def on_btn_file_save_as_clicked(self) -> None:
        """
        Save the current G-code content under a new path chosen via a
        file dialog, then load the new file into the controller.

        Blocked when the interpreter is busy or the view model is empty.
        """
        if not self.cnc.is_interpreter_idle():
            logger.warning("Save-as відхилено: інтерпретатор зайнятий")
            return

        model = self._get_gcode_model()
        if model is None or model.rowCount() == 0:
            return

        last_file   = self.cnc.get_last_file()
        initial_dir = os.path.dirname(last_file) if last_file else os.path.expanduser("~")

        new_path, _ = QFileDialog.getSaveFileName(
            None, "Save G-Code as...", initial_dir, _SAVE_FILTER
        )
        if not new_path:
            return

        if not new_path.endswith(_GCODE_EXTENSIONS):
            new_path += _FALLBACK_EXTENSION

        try:
            self._write_model_to_file(model, new_path)
            self.cnc.open_program(new_path)
            self._load_gcode_to_view(new_path)
            logger.debug("Збережено та завантажено: %s", new_path)
        except Exception as exc:
            logger.error("Помилка збереження: %s", exc)

    def on_btn_file_reload_clicked(self) -> None:
        """
        Reload the last loaded file from disk into the controller and
        list view.

        Blocked when no file is recorded or the interpreter is busy.
        Clears the reload-warning stylesheet on success.
        """
        last_file = self.cnc.get_last_file()
        if not last_file or not self.cnc.is_interpreter_idle():
            logger.warning("Reload неможливий: файл не знайдено або станок працює")
            return

        try:
            self.cnc.open_program(last_file)
            self._load_gcode_to_view(last_file)
            self.cnc.reload_needed = False
            self._set_reload_style("")
            logger.debug("%s оновлено", os.path.basename(last_file))
        except Exception as exc:
            logger.error("Помилка релоаду: %s", exc)

    def on_btn_file_edit_clicked(self) -> None:
        """
        Open the current G-code file in the first available text editor.

        Tries each editor in :data:`_CANDIDATE_EDITORS` in order and
        launches the first one found.  Marks the file as requiring a
        reload by setting the warning stylesheet on the reload button.

        Blocked when no file is recorded or the interpreter is busy.
        """
        last_file = self.cnc.get_last_file()
        if not last_file or not self.cnc.is_interpreter_idle():
            return

        editor = self._find_editor()
        if editor is None:
            logger.warning("Жоден редактор не знайдено: %s", _CANDIDATE_EDITORS)
            return

        subprocess.Popen([editor, last_file])
        self.cnc.reload_needed = True
        self._set_reload_style(self.STYLE_GCODE_WARN)
        logger.debug("Файл відкрито в %s: %s", editor, last_file)

    # ------------------------------------------------------------------
    # Private helpers – G-code view
    # ------------------------------------------------------------------

    def _load_gcode_to_view(self, filepath: str) -> None:
        """
        Read *filepath* from disk and populate the G-code list view.

        Also resets the filename label and progress indicator.  Connects
        the model's ``dataChanged`` signal so that in-place edits are
        persisted automatically.

        Args:
            filepath: Absolute path to the G-code file to load.
        """
        if not os.path.exists(filepath):
            logger.error("Файл не знайдено: %s", filepath)
            return

        try:
            lines = self._read_lines(filepath)
            model = QStringListModel()
            model.setStringList(lines)

            view = getattr(self.widgets, "list_gcode_view", None)
            if view is not None:
                view.setModel(model)
                view.setEditTriggers(_EDIT_TRIGGERS)
                model.dataChanged.connect(self._on_gcode_edited)

            self._set_label("lbl_filename", os.path.basename(filepath))
            self._set_label("lbl_progress_percent", "0%")

            logger.debug("G-code завантажено у перегляд: %d рядків", len(lines))
        except Exception as exc:
            logger.error("_load_gcode_to_view: %s", exc)

    def _on_gcode_edited(self, top_left, bottom_right, roles) -> None:
        """
        Persist in-place G-code edits back to disk and re-sync LinuxCNC.

        Called automatically via the ``dataChanged`` signal of the list
        view model.  Blocked when the interpreter is busy.  Clears the
        reload-warning stylesheet on success.
        """
        if not self.cnc.is_interpreter_idle():
            logger.warning("Редагування заблоковано: програма виконується")
            return

        last_file = self.cnc.get_last_file()
        if not last_file or not os.path.exists(last_file):
            return

        try:
            model = self._get_gcode_model()
            if model is None:
                return

            self._write_lines_to_file(model.stringList(), last_file)
            self.cnc.open_program(last_file)
            self.cnc.reload_needed = False
            self._set_reload_style("")
            logger.debug(
                "Зміни збережено та синхронізовано: %s",
                os.path.basename(last_file),
            )
        except Exception as exc:
            logger.error("Не вдалося зберегти зміни: %s", exc)

    # ------------------------------------------------------------------
    # Private helpers – widgets
    # ------------------------------------------------------------------

    def _get_gcode_model(self) -> QStringListModel | None:
        """Return the model attached to the G-code list view, or ``None``."""
        view = getattr(self.widgets, "list_gcode_view", None)
        return view.model() if view is not None else None

    def _set_label(self, attr: str, text: str) -> None:
        """Set *text* on a label widget if it exists."""
        label = getattr(self.widgets, attr, None)
        if label is not None:
            label.setText(text)

    def _set_reload_style(self, stylesheet: str) -> None:
        """Apply *stylesheet* to the reload button if it exists."""
        btn = getattr(self.widgets, "btn_file_reload", None)
        if btn is not None:
            btn.setStyleSheet(stylesheet)

    # ------------------------------------------------------------------
    # Private helpers – file I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _read_lines(filepath: str) -> list[str]:
        """Read *filepath* and return a list of stripped lines."""
        with open(filepath, encoding="utf-8") as fh:
            return [line.strip() for line in fh]

    @staticmethod
    def _write_lines_to_file(lines: list[str], filepath: str) -> None:
        """Write *lines* to *filepath*, joining with newlines."""
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    @staticmethod
    def _write_model_to_file(model: QStringListModel, filepath: str) -> None:
        """Extract all rows from *model* and write them to *filepath*."""
        content = [model.index(i, 0).data() for i in range(model.rowCount())]
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(content))

    @staticmethod
    def _find_editor() -> str | None:
        """
        Return the name of the first available editor from
        :data:`_CANDIDATE_EDITORS`, or ``None`` if none are found.
        """
        for editor in _CANDIDATE_EDITORS:
            result = subprocess.call(
                ["which", editor],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result == 0:
                return editor
        return None

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"