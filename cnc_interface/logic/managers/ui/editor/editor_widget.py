# logic/managers/ui/editor/editor_widget.py
"""
GCodeEditorWidget – QPlainTextEdit з нумерацією рядків, підсвіткою,
debounce auto-save і контекстним меню.
_LineNumberArea   – бічна панель номерів рядків.
"""
from __future__ import annotations
import logging
import re
from PyQt5.QtCore  import QCoreApplication, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui   import QFont, QPainter, QTextCursor, QTextFormat
from PyQt5.QtWidgets import QDialog, QMenu, QPlainTextEdit, QShortcut, QTextEdit, QWidget
from .editor_colors import (
    AUTOSAVE_DELAY_MS, CLR_ACTIVE_LINE, CLR_BACKGROUND,
    CLR_EXEC_LINE, CLR_FOREGROUND, CLR_LINE_NUM_BG, CLR_LINE_NUM_FG,
    MENU_STYLE,
)
from .editor_highlighter import GCodeHighlighter

logger = logging.getLogger(__name__)

def _tr(text: str) -> str:
    return QCoreApplication.translate("MainWindow", text)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "GCodeEditorWidget"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.line_number_area_paint_event(event)


class GCodeEditorWidget(QPlainTextEdit):
    """
    QPlainTextEdit з:
      • нумерацією рядків
      • підсвіткою синтаксису G-коду
      • підсвіткою активного і виконуваного рядків
      • debounce-сигналом contentChanged
      • контекстним меню (read-only: лише копіювання)
    """
    contentChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._exec_line: int    = -1
        self._is_locked: bool   = False
        self._search_bar_ref    = None
        self._pending_next_line = None
        self._cnc               = None

        self._highlighter = GCodeHighlighter(self.document())
        self._lna = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_lna_width)
        self.updateRequest.connect(self._update_lna)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._update_lna_width(0)
        self._highlight_line()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.contentChanged)
        self.document().contentsChanged.connect(self._save_timer.start)

        QShortcut("Ctrl+H", self).activated.connect(self._show_search)
        QShortcut("Ctrl+F", self).activated.connect(self._show_search)

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def apply_default_theme(self) -> None:
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        pal = self.palette()
        pal.setColor(pal.Base, CLR_BACKGROUND)
        pal.setColor(pal.Text, CLR_FOREGROUND)
        self.setPalette(pal)

    def load_text(self, text: str) -> None:
        """Завантажити текст без тригерингу auto-save."""
        self._save_timer.stop()
        self.document().contentsChanged.disconnect(self._save_timer.start)
        self.setPlainText(text)
        self.document().contentsChanged.connect(self._save_timer.start)

    def reset(self) -> None:
        """Скинути стан: зупинити таймер, очистити, заблокувати."""
        self._save_timer.stop()
        self._save_timer.timeout.disconnect(self.contentChanged)
        try:
            self.document().contentsChanged.disconnect(self._save_timer.start)
        except TypeError:
            pass
        self.setPlainText("")
        self.document().contentsChanged.connect(self._save_timer.start)
        self._save_timer.timeout.connect(self.contentChanged)
        self._is_locked = True
        self.setReadOnly(True)
        self._exec_line = -1
        self._pending_next_line = None

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

    def set_cnc(self, cnc) -> None:
        self._cnc = cnc

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
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_lna_width(self, _=0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_lna(self, rect: QRect, dy: int) -> None:
        if dy:
            self._lna.scroll(0, dy)
        else:
            self._lna.update(0, rect.y(), self._lna.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_lna_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._lna.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self._lna)
        painter.fillRect(event.rect(), CLR_LINE_NUM_BG)
        block  = self.firstVisibleBlock()
        num    = block.blockNumber()
        top    = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        fm_h   = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if num == self._exec_line:
                    painter.fillRect(QRect(0, top, self._lna.width(), fm_h), CLR_EXEC_LINE)
                    painter.setPen(CLR_FOREGROUND)
                else:
                    painter.setPen(CLR_LINE_NUM_FG)
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

    def _highlight_line(self) -> None:
        sels = []
        if not self._is_locked:
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(CLR_ACTIVE_LINE)
            s.format.setProperty(QTextFormat.FullWidthSelection, True)
            s.cursor = self.textCursor()
            s.cursor.clearSelection()
            sels.append(s)
        if self._exec_line >= 0:
            block = self.document().findBlockByNumber(self._exec_line)
            if block.isValid():
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(CLR_EXEC_LINE)
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = QTextCursor(block)
                s.cursor.clearSelection()
                sels.append(s)
        self.setExtraSelections(sels)

    # ------------------------------------------------------------------
    # Контекстне меню
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        has_sel = self.textCursor().hasSelection()

        if self._is_locked:
            a = menu.addAction(_tr("Копіювати (Ctrl+C)"))
            a.setEnabled(has_sel)
            a.triggered.connect(self.copy)
            menu.exec_(event.globalPos())
            return

        # ── Буфер обміну ────────────────────────────────────────────────
        a = menu.addAction(_tr("Вирізати (Ctrl+X)"))
        a.setEnabled(has_sel)
        a.triggered.connect(self.cut)

        a = menu.addAction(_tr("Копіювати (Ctrl+C)"))
        a.setEnabled(has_sel)
        a.triggered.connect(self.copy)

        menu.addAction(_tr("Вставити (Ctrl+V)")).triggered.connect(self.paste)
        menu.addSeparator()

        # ── Виконання ───────────────────────────────────────────────────
        menu.addAction(_tr("▶  Виконати з цього рядка")).triggered.connect(
            self._on_set_next_line)
        menu.addSeparator()

        # ── Редагування тексту ──────────────────────────────────────────
        menu.addAction(_tr("Закоментувати")).triggered.connect(
            lambda: self._toggle_comment(True))
        menu.addAction(_tr("Розкоментувати")).triggered.connect(
            lambda: self._toggle_comment(False))
        menu.addSeparator()

        menu.addAction(_tr("Пошук та заміна  (Ctrl+H)")).triggered.connect(
            self._show_search)
        menu.addSeparator()

        # ── Вставка команд (структуровано по категоріях) ────────────────
        self._build_snippets_menu(menu)

        menu.exec_(event.globalPos())

    def _build_snippets_menu(self, parent_menu: QMenu) -> None:
        """
        Побудувати ієрархічне підменю вставки команд.
        Команди руху (PTP/LIN/CIRC) відкривають MotionCommandDialog,
        всі інші вставляють текстовий шаблон напряму.
        """
        from .editor_snippets import get_snippets

        snippets = get_snippets()
        motion_category = _tr("Команди руху")

        for category, commands in snippets.items():
            cat_menu = parent_menu.addMenu(category)
            for name, template in commands.items():
                if category == motion_category:
                    # PTP / LIN / CIRC → діалог з параметрами
                    cat_menu.addAction(name).triggered.connect(
                        lambda checked, mt=name: self._open_motion_dialog(mt))
                else:
                    cat_menu.addAction(name).triggered.connect(
                        lambda checked, t=template: self._insert_snippet(t))

    def _on_set_next_line(self) -> None:
        self._pending_next_line = self.textCursor().blockNumber()
        logger.debug("Set Next Line → рядок %d", self._pending_next_line + 1)

    def _toggle_comment(self, add: bool) -> None:
        cur = self.textCursor()
        doc = self.document()
        b_s = doc.findBlock(cur.selectionStart()).blockNumber()
        b_e = doc.findBlock(cur.selectionEnd()).blockNumber()
        cur.beginEditBlock()
        for bn in range(b_s, b_e + 1):
            block = doc.findBlockByNumber(bn)
            bc    = QTextCursor(block)
            if add:
                bc.insertText("; ")
            else:
                m = re.match(r"^;\s?", block.text())
                if m:
                    bc.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, m.end())
                    bc.removeSelectedText()
        cur.endEditBlock()

    def _open_motion_dialog(self, motion_type: str) -> None:
        from .editor_motion_dialog import MotionCommandDialog
        dlg = MotionCommandDialog(motion_type, cnc=self._cnc, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            cur = self.textCursor()
            cur.beginEditBlock()
            cur.movePosition(QTextCursor.EndOfLine)
            cur.insertText("\n" + dlg.build_command())
            cur.endEditBlock()

    def _insert_snippet(self, template: str) -> None:
        """
        Вставити текстовий шаблон після поточного рядка.
        Курсор переміщується на перший рядок вставленого блоку.
        """
        cur = self.textCursor()
        cur.beginEditBlock()
        cur.movePosition(QTextCursor.EndOfLine)
        cur.insertText("\n" + template)
        cur.endEditBlock()
        # Переміщуємо курсор на початок вставленого блоку
        lines = template.split("\n")
        cur.movePosition(QTextCursor.Up,
                         QTextCursor.MoveAnchor,
                         len(lines) - 1)
        cur.movePosition(QTextCursor.EndOfLine)
        self.setTextCursor(cur)

    def _show_search(self) -> None:
        if self._search_bar_ref is not None:
            self._search_bar_ref.show()
            self._search_bar_ref.focus_search()
