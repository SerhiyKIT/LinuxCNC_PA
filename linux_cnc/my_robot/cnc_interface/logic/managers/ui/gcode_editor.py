# logic/managers/ui/gcode_editor.py
"""
GCodeEditor – повноцінний редактор G-коду на базі QPlainTextEdit.

Класи:
  GCodeHighlighter   – QSyntaxHighlighter
  _LineNumberArea    – бічна панель нумерації
  GCodeEditorWidget  – QPlainTextEdit з усіма можливостями
  _SearchReplaceBar  – панель Ctrl+H/F
  _EditorContainer   – обгортка (редактор + пошук)
  GCodeEditorManager – фасад стану редактора

GCodeEditorManager НЕ підключає кнопки і НЕ відкриває діалоги.
Це робить HandlerClass._connect_file_buttons().
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import TYPE_CHECKING

from PyQt5.QtCore    import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui     import (
    QColor, QFont, QPainter, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QTextDocument, QTextFormat,
)
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPlainTextEdit, QPushButton,
    QShortcut, QTextEdit, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------

_GCODE_EXTENSIONS  = (".ngc", ".txt", ".gcode")
_FALLBACK_EXT      = ".ngc"
_AUTOSAVE_DELAY_MS = 800

# Палітра
_CLR_BACKGROUND  = QColor("#1e1e2e")
_CLR_FOREGROUND  = QColor("#cdd6f4")
_CLR_LINE_NUM_BG = QColor("#181825")
_CLR_LINE_NUM_FG = QColor("#6c7086")
_CLR_ACTIVE_LINE = QColor("#313244")
_CLR_EXEC_LINE   = QColor("#45475a")
_CLR_G_CODE      = QColor("#89b4fa")
_CLR_M_CODE      = QColor("#a6e3a1")
_CLR_COORD       = QColor("#fab387")
_CLR_FEED        = QColor("#f38ba8")
_CLR_COMMENT     = QColor("#6c7086")
_CLR_NUMBER      = QColor("#f9e2af")

_TEMPLATES: dict[str, str] = {
    "Шапка програми": (
        "%\nO0001 (НАЗВА ПРОГРАМИ)\n"
        "G21 G17 G90 G94\n"
        "G28 G91 Z0.\nG90\n"
    ),
    "Зміна інструменту": (
        "M5\nG28 G91 Z0.\nG90\n"
        "T{n} M6\nG43 H{n}\nS{rpm} M3\n"
    ),
    "Завершення (M30)": (
        "M5\nM9\n"
        "G28 G91 Z0.\nG90\n"
        "G28 G91 X0. Y0.\nG90\n"
        "M30\n%\n"
    ),
}


# ===========================================================================
# 1. Підсвітка синтаксису
# ===========================================================================

class GCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    def _fmt(self, color, bold=False, italic=False):
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:   f.setFontWeight(QFont.Bold)
        if italic: f.setFontItalic(True)
        return f

    def _build_rules(self):
        a = self._rules.append
        a((re.compile(r'\(.*?\)'),                            self._fmt(_CLR_COMMENT, italic=True)))
        a((re.compile(r';.*'),                                self._fmt(_CLR_COMMENT, italic=True)))
        a((re.compile(r'\bG\d+\.?\d*\b', re.IGNORECASE),     self._fmt(_CLR_G_CODE, bold=True)))
        a((re.compile(r'\bM\d+\b',        re.IGNORECASE),    self._fmt(_CLR_M_CODE, bold=True)))
        a((re.compile(r'\b[XYZABCIJK](?=[-\d.])', re.IGNORECASE), self._fmt(_CLR_COORD, bold=True)))
        a((re.compile(r'\b[FST](?=[-\d.])', re.IGNORECASE),  self._fmt(_CLR_FEED)))
        a((re.compile(r'[-+]?\d+\.?\d*'),                    self._fmt(_CLR_NUMBER)))

    def highlightBlock(self, text: str):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ===========================================================================
# 2. Бічна панель нумерації
# ===========================================================================

class _LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)


# ===========================================================================
# 3. Основний віджет редактора
# ===========================================================================

class GCodeEditorWidget(QPlainTextEdit):
    """QPlainTextEdit з нумерацією, підсвіткою синтаксису та debounce."""

    contentChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._exec_line: int    = -1
        self._is_locked: bool   = False
        self._search_bar_ref    = None
        self._pending_next_line = None

        # Підсвітка синтаксису
        self._highlighter = GCodeHighlighter(self.document())

        # Нумерація
        self._lna = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_lna_width)
        self.updateRequest.connect(self._update_lna)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._update_lna_width(0)
        self._highlight_line()

        # Debounce
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_AUTOSAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.contentChanged)
        self.document().contentsChanged.connect(self._save_timer.start)

        QShortcut("Ctrl+H", self).activated.connect(self._show_search)
        QShortcut("Ctrl+F", self).activated.connect(self._show_search)

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def apply_default_theme(self) -> None:
        """
        Застосувати вбудовану темну тему (шрифт + палітра).

        Викликати явно тільки якщо Qt Designer НЕ задає зовнішній вигляд.
        Якщо стилі задані у .ui файлі — цей метод не викликати.
        """
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        pal = self.palette()
        pal.setColor(pal.Base, _CLR_BACKGROUND)
        pal.setColor(pal.Text, _CLR_FOREGROUND)
        self.setPalette(pal)

    def load_text(self, text: str) -> None:
        """Завантажити текст без тригерингу auto-save."""
        self._save_timer.stop()
        self.document().contentsChanged.disconnect(self._save_timer.start)
        self.setPlainText(text)
        self.document().contentsChanged.connect(self._save_timer.start)

    def set_exec_line(self, line_no: int) -> None:
        if self._exec_line == line_no:
            return
        self._exec_line = line_no
        self._highlight_line()
        if line_no >= 0:
            block = self.document().findBlockByNumber(line_no)
            if block.isValid():
                self.setTextCursor(QTextCursor(block))
                self.centerCursor()

    def set_locked(self, locked: bool) -> None:
        if self._is_locked == locked:
            return
        self._is_locked = locked
        self.setReadOnly(locked)
        if locked:
            self._save_timer.stop()

    def is_locked(self) -> bool:
        return self._is_locked

    def set_search_bar(self, bar) -> None:
        self._search_bar_ref = bar

    def take_pending_next_line(self):
        val = self._pending_next_line
        self._pending_next_line = None
        return val

    # ------------------------------------------------------------------
    # Нумерація рядків
    # ------------------------------------------------------------------

    def line_number_area_width(self) -> int:
        digits = max(1, len(str(self.document().blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_lna_width(self, _=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_lna(self, rect: QRect, dy: int):
        if dy:
            self._lna.scroll(0, dy)
        else:
            self._lna.update(0, rect.y(), self._lna.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_lna_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._lna.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter   = QPainter(self._lna)
        painter.fillRect(event.rect(), _CLR_LINE_NUM_BG)
        block     = self.firstVisibleBlock()
        num       = block.blockNumber()
        top       = round(self.blockBoundingGeometry(block)
                          .translated(self.contentOffset()).top())
        bottom    = top + round(self.blockBoundingRect(block).height())
        fm_h      = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if num == self._exec_line:
                    painter.fillRect(QRect(0, top, self._lna.width(), fm_h), _CLR_EXEC_LINE)
                    painter.setPen(_CLR_FOREGROUND)
                else:
                    painter.setPen(_CLR_LINE_NUM_FG)
                painter.drawText(
                    0, top, self._lna.width() - 4, fm_h,
                    Qt.AlignRight | Qt.AlignVCenter, str(num + 1))
            block  = block.next()
            top    = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num   += 1

    # ------------------------------------------------------------------
    # Підсвітка рядків
    # ------------------------------------------------------------------

    def _highlight_line(self):
        sels = []
        if not self._is_locked:
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(_CLR_ACTIVE_LINE)
            s.format.setProperty(QTextFormat.FullWidthSelection, True)
            s.cursor = self.textCursor()
            s.cursor.clearSelection()
            sels.append(s)
        if self._exec_line >= 0:
            block = self.document().findBlockByNumber(self._exec_line)
            if block.isValid():
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(_CLR_EXEC_LINE)
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = QTextCursor(block)
                s.cursor.clearSelection()
                sels.append(s)
        self.setExtraSelections(sels)

    # ------------------------------------------------------------------
    # Контекстне меню
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#313244;color:#cdd6f4;border:1px solid #45475a;}"
            "QMenu::item:selected{background:#45475a;}")

        has_sel = self.textCursor().hasSelection()
        a = menu.addAction("Вирізати");  a.setEnabled(has_sel and not self._is_locked); a.triggered.connect(self.cut)
        a = menu.addAction("Копіювати"); a.setEnabled(has_sel);                          a.triggered.connect(self.copy)
        a = menu.addAction("Вставити");  a.setEnabled(not self._is_locked);              a.triggered.connect(self.paste)
        menu.addSeparator()

        a = menu.addAction("▶  Виконати з цього рядка (Set Next Line)")
        a.triggered.connect(self._on_set_next_line)
        menu.addSeparator()

        a = menu.addAction("//  Закоментувати"); a.setEnabled(not self._is_locked); a.triggered.connect(lambda: self._toggle_comment(True))
        a = menu.addAction("    Розкоментувати"); a.setEnabled(not self._is_locked); a.triggered.connect(lambda: self._toggle_comment(False))
        menu.addSeparator()

        menu.addAction("🔍  Пошук та заміна  (Ctrl+H)").triggered.connect(self._show_search)
        menu.addSeparator()

        tm = menu.addMenu("📋  Вставити шаблон")
        for name, code in _TEMPLATES.items():
            a = tm.addAction(name)
            a.setEnabled(not self._is_locked)
            a.triggered.connect(lambda checked, c=code: self._insert_template(c))

        menu.exec_(event.globalPos())

    def _on_set_next_line(self):
        self._pending_next_line = self.textCursor().blockNumber()
        logger.debug("Set Next Line → рядок %d", self._pending_next_line + 1)

    def _toggle_comment(self, comment: bool):
        cur    = self.textCursor()
        doc    = self.document()
        b_s    = doc.findBlock(cur.selectionStart()).blockNumber()
        b_e    = doc.findBlock(cur.selectionEnd()).blockNumber()
        cur.beginEditBlock()
        for bn in range(b_s, b_e + 1):
            block = doc.findBlockByNumber(bn)
            bc    = QTextCursor(block)
            text  = block.text()
            if comment:
                bc.insertText("; ")
            else:
                m = re.match(r'^;\s?', text)
                if m:
                    bc.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, m.end())
                    bc.removeSelectedText()
        cur.endEditBlock()

    def _insert_template(self, code: str):
        cur = self.textCursor()
        cur.beginEditBlock()
        cur.insertText("\n" + code)
        cur.endEditBlock()

    def _show_search(self):
        if self._search_bar_ref is not None:
            self._search_bar_ref.show()
            self._search_bar_ref.focus_search()


# ===========================================================================
# 4. Панель пошуку/заміни
# ===========================================================================

class _SearchReplaceBar(QWidget):
    def __init__(self, editor: GCodeEditorWidget, parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.Window, QColor("#313244"))
        self.setPalette(pal)

        self._sf = QLineEdit(placeholderText="Пошук…")
        self._rf = QLineEdit(placeholderText="Замінити на…")
        self._li = QLabel("", styleSheet="color:#6c7086")

        _b = ("QPushButton{background:#45475a;color:#cdd6f4;border:none;"
              "border-radius:3px;padding:0 8px;min-height:24px;}"
              "QPushButton:hover{background:#585b70;}")
        _f = ("QLineEdit{background:#1e1e2e;color:#cdd6f4;"
              "border:1px solid #45475a;border-radius:3px;padding:2px 6px;}")

        bp = QPushButton("↑"); bn = QPushButton("↓")
        br = QPushButton("Замінити"); ba = QPushButton("Замінити всі")
        bc = QPushButton("✕")
        for b in (bp, bn, br, ba, bc): b.setStyleSheet(_b)
        for f in (self._sf, self._rf): f.setStyleSheet(_f)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4); row.setSpacing(6)
        row.addWidget(QLabel("🔍", styleSheet="color:#89b4fa"))
        row.addWidget(self._sf); row.addWidget(self._rf)
        row.addWidget(bp); row.addWidget(bn)
        row.addWidget(br); row.addWidget(ba)
        row.addWidget(self._li); row.addStretch(); row.addWidget(bc)

        bn.clicked.connect(self._find_next)
        bp.clicked.connect(self._find_prev)
        br.clicked.connect(self._replace_one)
        ba.clicked.connect(self._replace_all)
        bc.clicked.connect(self.hide)
        self._sf.returnPressed.connect(self._find_next)
        self.hide()

    def focus_search(self):
        self._sf.setFocus()
        self._sf.selectAll()

    def _find(self, backward=False) -> bool:
        needle = self._sf.text()
        if not needle:
            return False
        flags = (QTextDocument.FindBackward
                 if backward else QTextDocument.FindFlag(0))
        found = self._editor.find(needle, flags)
        if not found:
            cur = self._editor.textCursor()
            cur.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            self._editor.setTextCursor(cur)
            found = self._editor.find(needle, flags)
        self._li.setText("" if found else "Не знайдено")
        return found

    def _find_next(self): self._find(False)
    def _find_prev(self): self._find(True)

    def _replace_one(self):
        if not self._find():
            return
        cur = self._editor.textCursor()
        if cur.hasSelection():
            cur.insertText(self._rf.text())

    def _replace_all(self):
        needle = self._sf.text()
        if not needle:
            return
        content = self._editor.document().toPlainText()
        count   = content.count(needle)
        if count:
            self._editor.load_text(content.replace(needle, self._rf.text()))
            self._li.setText(f"Замінено: {count}")
        else:
            self._li.setText("Не знайдено")


# ===========================================================================
# 5. Контейнер
# ===========================================================================

class _EditorContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.editor      = GCodeEditorWidget(self)
        self._search_bar = _SearchReplaceBar(self.editor, self)
        self.editor.set_search_bar(self._search_bar)

        layout.addWidget(self.editor)
        layout.addWidget(self._search_bar)


# ===========================================================================
# 6. GCodeEditorManager – фасад стану редактора
# ===========================================================================

class GCodeEditorManager:
    """
    Відповідає за:
      • монтування GCodeEditorWidget у layout
      • відстеження _current_file
      • делегування читання файлу у FileManager.load_file_into_editor()
      • auto-save + cnc.open_program() після debounce
      • Safety Lock
      • підсвітку виконуваного рядка
      • Set Next Line → cycle_manager.start_cycle()

    НЕ підключає кнопки і НЕ відкриває діалоги — це HandlerClass.
    """

    def __init__(
        self,
        machine_controller: "MachineController",
        file_manager,       # FileManager — для load_file_into_editor()
        widgets: object,
        cycle_manager=None,
    ) -> None:
        self.cnc           = machine_controller
        self.file_manager  = file_manager
        self.widgets       = widgets
        self.cycle_manager = cycle_manager

        self._current_file: str | None = None
        self._last_exec_line: int      = -1

        # ── Знайти / ініціалізувати редактор ─────────────────────────────
        container = getattr(widgets, "list_gcode_edit", None)

        # Визначаємо тип через ім'я класу і наявність методів —
        # уникаємо isinstance щоб не залежати від шляху імпорту
        # (logic.managers... vs managers... — Python вважає різними класами)
        cls_name  = type(container).__name__ if container is not None else ""
        is_editor    = hasattr(container, "load_text") and hasattr(container, "set_exec_line")
        is_container = hasattr(container, "editor") and hasattr(getattr(container, "editor", None), "load_text")

        if is_container:
            # list_gcode_edit є _EditorContainer
            self._container = container
            self._editor: GCodeEditorWidget = container.editor

        elif is_editor:
            # list_gcode_edit є GCodeEditorWidget напряму —
            # використовуємо його БЕЗ загортання щоб зберегти розміри з Qt Designer
            self._container = None
            self._editor = container

            # _SearchReplaceBar як overlay поверх редактора
            parent_w = container.parent()
            self._search_bar_overlay = _SearchReplaceBar(container, parent_w)
            self._search_bar_overlay.hide()
            container.set_search_bar(self._search_bar_overlay)

            def _reposition():
                r   = container.geometry()
                bar = self._search_bar_overlay
                bh  = bar.sizeHint().height() or 32
                bar.setFixedWidth(r.width())
                bar.move(r.x(), r.y() + r.height() - bh)
                bar.raise_()

            _orig_show = self._search_bar_overlay.show
            def _show_and_position():
                _reposition()
                _orig_show()
            self._search_bar_overlay.show = _show_and_position

            _orig_resize = container.resizeEvent
            def _resize_and_reposition(event):
                _orig_resize(event)
                if not self._search_bar_overlay.isHidden():
                    _reposition()
            container.resizeEvent = _resize_and_reposition

        elif container is not None:
            # Звичайний QWidget-placeholder — замінюємо на _EditorContainer
            parent_w   = container.parent()
            parent_lay = parent_w.layout() if parent_w else None
            self._container = _EditorContainer(parent_w)
            self._container.setSizePolicy(container.sizePolicy())
            self._container.setMinimumSize(container.minimumSize())
            self._container.setMaximumSize(container.maximumSize())
            if parent_lay:
                parent_lay.replaceWidget(container, self._container)
            container.hide()
            self._editor = self._container.editor
            try:
                setattr(widgets, "list_gcode_edit", self._editor)
            except AttributeError:
                pass

        else:
            logger.warning("list_gcode_edit не знайдено — редактор без layout")
            self._container = _EditorContainer()
            self._editor = self._container.editor
        self._editor.contentChanged.connect(self._on_content_changed)

        # Таймер перевірки Set Next Line
        self._snl_timer = QTimer()
        self._snl_timer.setInterval(100)
        self._snl_timer.timeout.connect(self._check_set_next_line)
        self._snl_timer.start()

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def load_file(self, filepath: str) -> None:
        """Завантажити файл через FileManager і зберегти поточний шлях."""
        self.file_manager.load_file_into_editor(filepath)
        self._current_file = filepath

    def update_exec_line(self, line_no: int) -> None:
        if line_no != self._last_exec_line:
            self._last_exec_line = line_no
            self._editor.set_exec_line(line_no)

    def set_edit_lock(self, locked: bool) -> None:
        self._editor.set_locked(locked)

    def set_cycle_manager(self, cm) -> None:
        self.cycle_manager = cm

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    def update(self, states: dict) -> None:
        current_file = states.get("current_file")
        is_idle      = states.get("is_idle", True)
        motion_line  = states.get("motion_line", 0)

        # Новий файл відкрито у LinuxCNC
        if current_file and current_file != self._current_file:
            self.load_file(current_file)

        # LinuxCNC закрив файл (не чіпаємо тимчасові файли)
        if not current_file and self._current_file is not None:
            if not self._current_file.startswith(tempfile.gettempdir()):
                self._current_file = None
                self._editor.load_text("")
                lbl = getattr(self.widgets, "lbl_filename", None)
                if lbl:
                    lbl.setText("Файл не завантажено")

        self.set_edit_lock(not is_idle)
        self.update_exec_line(motion_line if not is_idle else -1)

    # ------------------------------------------------------------------
    # Auto-save
    # ------------------------------------------------------------------

    def _on_content_changed(self) -> None:
        if self._editor.is_locked():
            return
        content = self._editor.toPlainText()
        if not content.strip():
            return
        if not self._current_file:
            self._current_file = _make_temp_file()
            logger.debug("Auto-save: тимчасовий файл %s", self._current_file)
        try:
            with open(self._current_file, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.cnc.open_program(self._current_file)
            self.cnc.reload_needed = False
            logger.debug("Auto-saved → %s", os.path.basename(self._current_file))
        except Exception as exc:
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
            logger.error("Set Next Line збереження: %s", exc)
            return
        try:
            self.cycle_manager.start_cycle(line)
            logger.info("Set Next Line → рядок %d", line + 1)
        except Exception as exc:
            logger.error("Set Next Line запуск: %s", exc)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}"
                f"(file={self._current_file!r}, locked={self._editor.is_locked()})")


# ---------------------------------------------------------------------------
# Утиліти
# ---------------------------------------------------------------------------

def _make_temp_file() -> str:
    fd, path = tempfile.mkstemp(suffix=_FALLBACK_EXT, prefix="gcode_tmp_")
    os.close(fd)
    return path