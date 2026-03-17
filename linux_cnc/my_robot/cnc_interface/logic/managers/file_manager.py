# logic/managers/file_manager.py
from __future__ import annotations

import logging
import os
import subprocess
from typing import TYPE_CHECKING

from PyQt5.QtCore import QStringListModel
from PyQt5.QtWidgets import QAbstractItemView, QFileDialog, QScrollBar

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
        persisted automatically.  Populates the line-number sidebar
        (``list_gcode_num``) and wires scroll synchronisation between the
        two views.

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

            # Populate the line-number sidebar and wire scroll sync
            self._sync_line_numbers(len(lines))

            self._set_label("lbl_filename", os.path.basename(filepath))
            self._set_label("lbl_progress_percent", "0%")

            logger.debug("G-code завантажено у перегляд: %d рядків", len(lines))
        except Exception as exc:
            logger.error("_load_gcode_to_view: %s", exc)

    def _sync_line_numbers(self, line_count: int) -> None:
        """
        Populate ``list_gcode_num`` with sequential line numbers and
        configure the widget so its scrollbar is hidden and its vertical
        scroll is always driven by ``list_gcode_view``.

        Scroll synchronisation is established in both directions so that
        scrolling over either widget moves only the code view, which then
        notifies the number view via ``valueChanged``.

        Args:
            line_count: Total number of lines in the currently loaded file.
        """
        num_view  = getattr(self.widgets, "list_gcode_num",  None)
        code_view = getattr(self.widgets, "list_gcode_view", None)

        if num_view is None:
            return

        # Fill with "1", "2", … "N"
        num_model = QStringListModel()
        num_model.setStringList([str(i + 1) for i in range(line_count)])
        num_view.setModel(num_model)

        # Make the number column read-only and non-selectable
        num_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        num_view.setSelectionMode(QAbstractItemView.NoSelection)
        num_view.setFocusPolicy(num_view.NoFocus)

        # Hide the vertical scrollbar on the number view entirely
        num_view.setVerticalScrollBarPolicy(num_view.ScrollBarAlwaysOff)
        # Also hide horizontal scrollbar – numbers never need it
        num_view.setHorizontalScrollBarPolicy(num_view.ScrollBarAlwaysOff)

        if code_view is None:
            return

        # --- Scroll synchronisation ---
        # Drive num_view's scrollbar from code_view's scrollbar so that
        # any scroll on the code view is mirrored to the number view.
        code_vbar = code_view.verticalScrollBar()
        num_vbar  = num_view.verticalScrollBar()

        # Disconnect previous connections to avoid duplicates on reload
        try:
            code_vbar.valueChanged.disconnect(num_vbar.setValue)
        except TypeError:
            pass  # was not connected yet

        code_vbar.valueChanged.connect(num_vbar.setValue)

        # Redirect wheel events that land on num_view to code_view so
        # the user can scroll with the mouse over the number column too.
        # Re-installing an event filter on every load is safe: Qt keeps
        # only one filter per (watcher, watched) pair.
        _LineNumScrollForwarder.install(num_view, code_view)

        logger.debug("Нумерацію рядків синхронізовано: %d рядків", line_count)

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


# ---------------------------------------------------------------------------
# Scroll-forwarder event filter
# ---------------------------------------------------------------------------

from PyQt5.QtCore import QObject, QEvent  # noqa: E402  (placed after class body)


class _LineNumScrollForwarder(QObject):
    """
    Event filter that forwards ``Wheel`` events received by the line-number
    view (``list_gcode_num``) to the code view (``list_gcode_view``).

    This makes mouse-wheel scrolling work identically whether the cursor
    is positioned over the number column or the code column.

    Install via :meth:`install` rather than constructing directly so that
    only one forwarder is ever attached per (num_view, code_view) pair.
    """

    # Class-level registry: num_view id → forwarder instance.
    # Keeps the QObject alive (owned by this dict) so Qt does not
    # garbage-collect the installed filter.
    _registry: dict[int, "_LineNumScrollForwarder"] = {}

    def __init__(self, code_view: QAbstractItemView) -> None:
        super().__init__(code_view)          # parent = code_view keeps lifetime tied
        self._code_view = code_view

    # ------------------------------------------------------------------

    @classmethod
    def install(
        cls,
        num_view:  QAbstractItemView,
        code_view: QAbstractItemView,
    ) -> "_LineNumScrollForwarder":
        """
        Attach (or replace) a forwarder on *num_view* that redirects
        wheel events to *code_view*.

        Safe to call multiple times (e.g. on every file reload).
        """
        key = id(num_view)
        old = cls._registry.get(key)
        if old is not None:
            num_view.removeEventFilter(old)

        forwarder = cls(code_view)
        num_view.installEventFilter(forwarder)
        cls._registry[key] = forwarder
        return forwarder

    # ------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        """
        Intercept ``Wheel`` events on the number view and re-post them
        to the code view so the vertical scrollbar of the code view
        moves – which in turn updates the number view via the
        ``valueChanged`` connection set up in
        :meth:`FileManager._sync_line_numbers`.
        """
        if event.type() == QEvent.Wheel:
            from PyQt5.QtWidgets import QApplication
            QApplication.sendEvent(self._code_view.verticalScrollBar(), event)
            return True          # event consumed; do not let num_view scroll itself
        return False             # pass all other events through normally
