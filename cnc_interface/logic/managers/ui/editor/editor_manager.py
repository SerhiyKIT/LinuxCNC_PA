# logic/managers/ui/editor/editor_manager.py
"""
GCodeEditorManager – фасад стану редактора коду.

Відповідає за:
  • монтування GCodeEditorWidget у layout (duck typing)
  • читання файлів з диска та відображення
  • відстеження _current_file
  • auto-save при кожній зміні тексту (debounce)
  • Safety Lock (заблокований без проекту)
  • підсвітку виконуваного рядка
  • Set Next Line → cycle_manager.start_cycle()
"""
from __future__ import annotations
import logging
import os
from typing import TYPE_CHECKING
from PyQt5.QtCore import QTimer
from .editor_colors    import EDITABLE_EXTS
from .editor_container import _EditorContainer
from .editor_search    import _SearchReplaceBar
from .editor_widget    import GCodeEditorWidget

if TYPE_CHECKING:
    from core.machine import MachineController

logger = logging.getLogger(__name__)


class GCodeEditorManager:
    """Фасад редактора коду. Не залежить від FileManager."""

    def __init__(
        self,
        machine_controller: "MachineController",
        widgets: object,
        cycle_manager=None,
    ) -> None:
        self.cnc           = machine_controller
        self.widgets       = widgets
        self.cycle_manager = cycle_manager

        self._current_file: str | None = None
        self._last_exec_line: int      = -1

        self._editor = self._mount_editor(widgets)
        self._editor.set_cnc(machine_controller)
        self._editor.contentChanged.connect(self._on_content_changed)
        self._editor.set_locked(True)

        self._snl_timer = QTimer()
        self._snl_timer.setInterval(100)
        self._snl_timer.timeout.connect(self._check_set_next_line)
        self._snl_timer.start()

    # ------------------------------------------------------------------
    # Монтування (duck typing — без isinstance)
    # ------------------------------------------------------------------

    def _mount_editor(self, widgets: object) -> GCodeEditorWidget:
        container = getattr(widgets, "list_gcode_edit", None)

        is_editor    = (container is not None
                        and hasattr(container, "load_text")
                        and hasattr(container, "set_exec_line"))
        is_container = (container is not None
                        and hasattr(container, "editor")
                        and hasattr(getattr(container, "editor", None), "load_text"))

        if is_container:
            return container.editor

        if is_editor:
            parent_w = container.parent()
            bar = _SearchReplaceBar(container, parent_w)
            bar.hide()
            container.set_search_bar(bar)

            orig_show = bar.show
            def _show():
                self._reposition_bar(container, bar)
                orig_show()
            bar.show = _show

            orig_resize = container.resizeEvent
            def _resize(e):
                orig_resize(e)
                if not bar.isHidden():
                    self._reposition_bar(container, bar)
            container.resizeEvent = _resize
            return container

        if container is not None:
            parent_w   = container.parent()
            parent_lay = parent_w.layout() if parent_w else None
            wrap = _EditorContainer(parent_w)
            wrap.setSizePolicy(container.sizePolicy())
            wrap.setMinimumSize(container.minimumSize())
            wrap.setMaximumSize(container.maximumSize())
            if parent_lay:
                parent_lay.replaceWidget(container, wrap)
            container.hide()
            try:
                setattr(widgets, "list_gcode_edit", wrap.editor)
            except AttributeError:
                pass
            return wrap.editor

        logger.warning("list_gcode_edit не знайдено — редактор без layout")
        return _EditorContainer().editor

    @staticmethod
    def _reposition_bar(editor: GCodeEditorWidget,
                         bar: _SearchReplaceBar) -> None:
        r  = editor.geometry()
        bh = bar.sizeHint().height() or 32
        bar.setFixedWidth(r.width())
        bar.move(r.x(), r.y() + r.height() - bh)
        bar.raise_()

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def load_file(self, filepath: str, read_only: bool = False) -> None:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in EDITABLE_EXTS:
            logger.debug("load_file: тип %s не підтримується", ext)
            return
        if not os.path.isfile(filepath):
            logger.error("load_file: не знайдено: %s", filepath)
            return
        try:
            with open(filepath, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            logger.error("load_file: %s", exc)
            return

        self._editor.load_text(text)
        self._current_file = filepath
        self._editor.set_locked(read_only)

        lbl = getattr(self.widgets, "lbl_filename", None)
        if lbl:
            lbl.setText(os.path.basename(filepath))

        logger.debug("load_file: %s (read_only=%s)", os.path.basename(filepath), read_only)

    def clear_editor(self) -> None:
        self._current_file   = None
        self._last_exec_line = -1
        self._editor.reset()
        lbl = getattr(self.widgets, "lbl_filename", None)
        if lbl:
            lbl.setText("")
        logger.debug("clear_editor: виконано")

    def set_project_active(self, active: bool) -> None:
        if not active:
            self.clear_editor()

    def set_current_file(self, filepath: str) -> None:
        self._current_file = filepath

    def update_exec_line(self, line_no: int) -> None:
        if line_no != self._last_exec_line:
            self._last_exec_line = line_no
            self._editor.set_exec_line(line_no)

    def set_edit_lock(self, locked: bool) -> None:
        if not self._current_file and not locked:
            return
        self._editor.set_locked(locked)

    def set_cycle_manager(self, cm) -> None:
        self.cycle_manager = cm

    def update(self, states: dict) -> None:
        self.update_exec_line(-1)

    # ------------------------------------------------------------------
    # Auto-save
    # ------------------------------------------------------------------

    def _on_content_changed(self) -> None:
        if self._editor.is_locked():
            return
        if not self._current_file:
            return
        if not os.path.isfile(self._current_file):
            self._current_file = None
            return
        ext = os.path.splitext(self._current_file)[1].lower()
        if ext not in EDITABLE_EXTS:
            return
        try:
            with open(self._current_file, "w", encoding="utf-8") as fh:
                fh.write(self._editor.toPlainText())
            logger.debug("Auto-saved → %s", os.path.basename(self._current_file))
        except OSError as exc:
            logger.error("Auto-save: %s", exc)

    # ------------------------------------------------------------------
    # Set Next Line
    # ------------------------------------------------------------------

    def _check_set_next_line(self) -> None:
        line = self._editor.take_pending_next_line()
        if line is None:
            return
        if self.cycle_manager is None:
            logger.warning("Set Next Line: CycleManager не підключено")
            return
        if not self.cnc.is_interpreter_idle():
            logger.warning("Set Next Line: станок не IDLE")
            return
        if not self._current_file:
            logger.warning("Set Next Line: файл не завантажено")
            return
        try:
            with open(self._current_file, "w", encoding="utf-8") as fh:
                fh.write(self._editor.toPlainText())
            self.cnc.open_program(self._current_file)
        except Exception as exc:
            logger.error("Set Next Line save: %s", exc)
            return
        try:
            self.cycle_manager.start_cycle(line)
            logger.info("Set Next Line → %d", line + 1)
        except Exception as exc:
            logger.error("Set Next Line start: %s", exc)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}"
                f"(file={self._current_file!r}, locked={self._editor.is_locked()})")
