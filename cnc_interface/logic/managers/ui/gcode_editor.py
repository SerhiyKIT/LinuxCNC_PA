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
    QCheckBox, QComboBox, QDialog,
    QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit,
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
_CLR_BACKGROUND  = QColor("#121212")
_CLR_FOREGROUND  = QColor("#F1F1F1")
_CLR_LINE_NUM_BG = QColor("#161616")
_CLR_LINE_NUM_FG = QColor("#9E9E9E")
_CLR_ACTIVE_LINE = QColor("#333333")
_CLR_EXEC_LINE   = QColor("#333333")
_CLR_G_CODE      = QColor("#89b4fa")
_CLR_M_CODE      = QColor("#a6e3a1")
_CLR_COORD       = QColor("#fab387")
_CLR_FEED        = QColor("#f38ba8")
_CLR_COMMENT     = QColor("#5B5B5B")
_CLR_NUMBER      = QColor("#f9e2af")

_TEMPLATES: dict[str, str] = {
    "PTP (Point-to-Point)": (
        "PTP {POS} [CONT] [VEL] [ACC] [TOOL] [BASE];"
    ),
    "LIN (Linear)": (
        "LIN {POS} [CONT] [ORI_TYPE] [VEL] [ACC] [TOOL] [BASE];"
    ),
    "CIRC (Circular)": (
        "CIRC {AUX_POS} {TARGET_POS} [CONT] [ORI_TYPE] [CIRC_TYPE] [VEL] [ACC] [TOOL] [BASE];"
    ),
}


# ===========================================================================
# 0. Діалог вставки команди руху (PTP / LIN / CIRC)
# ===========================================================================

_DIALOG_STYLE = """
QDialog          { background:#1E1E1E; color:#F1F1F1; }
QGroupBox        { border:1px solid #333333; border-radius:4px;
                   margin-top:8px; color:#FE5C0D; }
QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
QLabel           { color:#F1F1F1; }
QLineEdit        { background:#121212; color:#F1F1F1;
                   border:1px solid #333333; border-radius:3px;
                   padding:3px 6px; min-width:80px; }
QLineEdit:focus  { border-color:#FE5C0D; }
QLineEdit[invalid="true"] { border-color:#f38ba8; }
QComboBox        { background:#121212; color:#F1F1F1;
                   border:1px solid #333333; border-radius:3px; padding:3px 6px; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#121212; color:#F1F1F1;
                               selection-background-color:#333333; }
QCheckBox        { color:#F1F1F1; spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #333333;
                        border-radius:3px; background:#121212; }
QCheckBox::indicator:checked { background:#FE5C0D; border-color:#FE5C0D; }
QPushButton      { background:#333333; color:#F1F1F1; border:none;
                   border-radius:4px; padding:5px 14px; min-height:28px; }
QPushButton:hover   { background:#5B5B5B; }
QPushButton:pressed { background:#121212; }
QPushButton:disabled{ background:#121212; color:#9E9E9E; }
QDialogButtonBox QPushButton[text="Insert"] { background:#FE5C0D; color:#1E1E1E;}
QDialogButtonBox QPushButton[text="Insert"]:disabled { background:#333333; color:#9E9E9E; }
"""

_POS_AXES = ("X", "Y", "Z", "A", "B", "C")


class _PosGroup(QGroupBox):
    """Група з 6 полями координат + кнопка Get Current POS."""

    def __init__(self, title: str, cnc=None, limits: dict | None = None, parent=None):
        super().__init__(title, parent)
        self._cnc    = cnc
        # limits: {'X': (min, max), 'Y': (min, max), ...}
        # якщо None — перевіряємо лише що значення є float
        self._limits = limits or {}
        self._fields: dict[str, QLineEdit] = {}

        grid = QHBoxLayout(self)
        grid.setSpacing(8)

        for axis in _POS_AXES:
            col = QVBoxLayout()
            col.setSpacing(2)

            lo, hi = self._limits.get(axis, (None, None))
            tooltip = f"{axis}: [{lo}, {hi}]" if lo is not None else axis
            lbl = QLabel(axis)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setToolTip(tooltip)

            fld = QLineEdit("0.0")
            fld.setAlignment(Qt.AlignRight)
            fld.setToolTip(tooltip)
            # Вимикаємо autoDefault щоб Enter не тригерив кнопку Insert
            fld.setFocusPolicy(Qt.StrongFocus)
            fld.textChanged.connect(lambda _, f=fld, ax=axis: self._mark_validity(f, ax))

            col.addWidget(lbl)
            col.addWidget(fld)
            grid.addLayout(col)
            self._fields[axis] = fld

        btn = QPushButton("Поточні коорд.")
        btn.setToolTip("Зчитати поточні координати з LinuxCNC")
        btn.setAutoDefault(False)   # Enter не активує кнопку
        btn.setDefault(False)
        btn.clicked.connect(self._get_current_pos)
        btn.setEnabled(cnc is not None)
        grid.addWidget(btn)

    # ------------------------------------------------------------------

    def _in_range(self, axis: str, value: float) -> bool:
        lo, hi = self._limits.get(axis, (None, None))
        if lo is None:
            return True
        return lo <= value <= hi

    def _mark_validity(self, field: QLineEdit, axis: str) -> None:
        ok = self._field_valid(field, axis)
        field.setProperty("invalid", "" if ok else "true")
        field.style().unpolish(field)
        field.style().polish(field)

    def _field_valid(self, field: QLineEdit, axis: str) -> bool:
        try:
            val = float(field.text())
            return self._in_range(axis, val)
        except ValueError:
            return False

    def _get_current_pos(self) -> None:
        if self._cnc is None:
            return
        try:
            self._cnc.poll()
            pos = self._cnc.status.actual_position
            for i, axis in enumerate(_POS_AXES):
                if i < len(pos):
                    self._fields[axis].setText(f"{pos[i]:.4f}")
        except Exception as exc:
            logger.error("Get Current POS помилка: %s", exc)

    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        return all(
            self._field_valid(f, ax)
            for ax, f in self._fields.items()
        )

    def is_empty(self) -> bool:
        return any(f.text().strip() == "" for f in self._fields.values())

    def to_pos_string(self) -> str:
        parts = ", ".join(
            f"{ax} {self._fields[ax].text()}" for ax in _POS_AXES
        )
        return "{" + parts + "}"


class MotionCommandDialog(QDialog):
    """
    Модальний діалог для формування команди PTP / LIN / CIRC.

    Параметри
    ---------
    motion_type : 'PTP' | 'LIN' | 'CIRC'
    cnc         : MachineController або None
    """

    # Діапазони числових параметрів
    _VEL_MIN, _VEL_MAX = 0.0, 100.0
    _ACC_MIN, _ACC_MAX = 0.0, 100.0

    def __init__(self, motion_type: str, cnc=None, parent=None):
        super().__init__(parent)
        self._motion_type = motion_type.upper()
        self._cnc         = cnc

        # Витягуємо ліміти осей з MachineController
        # Структура cnc.limits: {0: {"min": -360.0, "max": 360.0}, 1: {...}, ...}
        # де індекс відповідає осі: 0=X, 1=Y, 2=Z, 3=A, 4=B, 5=C
        limits: dict = {}
        if cnc is not None and hasattr(cnc, "limits"):
            raw = cnc.limits
            if isinstance(raw, dict):
                for idx, axis in enumerate(_POS_AXES):
                    joint = raw.get(idx)
                    if isinstance(joint, dict):
                        lo = joint.get("min")
                        hi = joint.get("max")
                        if lo is not None and hi is not None:
                            limits[axis] = (float(lo), float(hi))

        self.setWindowTitle(f"Вставити команду {self._motion_type}")
        self.setMinimumWidth(720)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setModal(True)

        # КРИТИЧНО: вимикаємо поведінку Enter = Accept для всього діалогу
        # Перший QPushButton у діалозі стає default — тому встановлюємо
        # це явно нижче після створення кнопок
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(14, 14, 14, 14)

        # ── Координатні групи ─────────────────────────────────────────
        if self._motion_type == "CIRC":
            self._aux_pos    = _PosGroup("Проміжна точка",    cnc, limits, self)
            self._target_pos = _PosGroup("Цільова точка",  cnc, limits, self)
            root.addWidget(self._aux_pos)
            root.addWidget(self._target_pos)
        else:
            self._pos = _PosGroup("Цільова точка", cnc, limits, self)
            root.addWidget(self._pos)

        # ── Параметри руху ────────────────────────────────────────────
        params_box = QGroupBox("Параметри руху")
        params_lay = QFormLayout(params_box)
        params_lay.setSpacing(8)
        params_lay.setLabelAlignment(Qt.AlignRight)

        # CONT
        self._cont = QCheckBox("(не зупинятись у точці)")
        params_lay.addRow("Безперервний рух:", self._cont)

        # ORI_TYPE — тільки для LIN і CIRC
        if self._motion_type in ("LIN", "CIRC"):
            self._ori_type = QComboBox()
            self._ori_type.addItems(["ORI_VAR", "ORI_CONST"])
            params_lay.addRow("Тип орієнтації:", self._ori_type)
        else:
            self._ori_type = None

        # CIRC_TYPE — тільки для CIRC
        if self._motion_type == "CIRC":
            self._circ_type = QComboBox()
            self._circ_type.addItems(["CIRC_PATH", "CIRC_BASE"])
            params_lay.addRow("Тип кругової орієнтації:", self._circ_type)
        else:
            self._circ_type = None

        # VEL
        self._vel = QLineEdit("100.0")
        self._vel.setToolTip(f"Швидкість: {self._VEL_MIN}…{self._VEL_MAX}")
        self._vel.textChanged.connect(self._on_param_changed)
        params_lay.addRow(f"Швидкість:", self._vel)

        # ACC
        self._acc = QLineEdit("100.0")
        self._acc.setToolTip(f"Прискорення: {self._ACC_MIN}…{self._ACC_MAX}")
        self._acc.textChanged.connect(self._on_param_changed)
        params_lay.addRow(f"Прискорення:", self._acc)

        # TOOL
        self._tool = QLineEdit("1")
        self._tool.setToolTip("Номер інструменту (ціле число ≥ 0)")
        self._tool.textChanged.connect(self._on_param_changed)
        params_lay.addRow("Інструмент:", self._tool)

        # BASE
        self._base = QLineEdit("0")
        self._base.setToolTip("Система координат (ціле число ≥ 0)")
        self._base.textChanged.connect(self._on_param_changed)
        params_lay.addRow("Система координат:", self._base)

        root.addWidget(params_box)

        # ── Превʼю рядка ─────────────────────────────────────────────
        preview_box = QGroupBox("Результат")
        preview_lay = QVBoxLayout(preview_box)
        self._preview = QLabel("")
        self._preview.setStyleSheet(
            "font-family:Monospace; font-size:12px; color:#F1F1F1;"
            "padding:6px; background:#121212; border-radius:3px;"
        )
        self._preview.setWordWrap(True)
        preview_lay.addWidget(self._preview)
        root.addWidget(preview_box)

        # ── Кнопки ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_cancel = QPushButton("Скасувати")
        self._btn_cancel.setAutoDefault(False)
        self._btn_cancel.setDefault(False)
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_insert = QPushButton("Вставити")
        self._btn_insert.setAutoDefault(False)   # Enter НЕ активує Insert
        self._btn_insert.setDefault(False)        # Enter НЕ активує Insert
        self._btn_insert.setEnabled(False)
        self._btn_insert.setStyleSheet(
            "QPushButton{background:#FE5C0D;color:#FFFFFF;"
            "border-radius:4px;padding:5px 20px;min-height:28px;}"
            "QPushButton:disabled{background:#333333;color:#9E9E9E;}"
            "QPushButton:hover:!disabled{background:#FF7533;}"
        )
        self._btn_insert.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_insert)
        root.addLayout(btn_row)

        # Підключаємо сигнали і запускаємо першу валідацію
        self._connect_pos_signals()
        self._on_param_changed()

    # ------------------------------------------------------------------
    # Перехоплення Enter — не закривати діалог
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        # Блокуємо Enter і Return щоб вони не тригерили жодну кнопку
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Підключення сигналів
    # ------------------------------------------------------------------

    def _connect_pos_signals(self) -> None:
        if self._motion_type == "CIRC":
            for fld in self._aux_pos._fields.values():
                fld.textChanged.connect(self._on_param_changed)
            for fld in self._target_pos._fields.values():
                fld.textChanged.connect(self._on_param_changed)
        else:
            for fld in self._pos._fields.values():
                fld.textChanged.connect(self._on_param_changed)
        if self._ori_type:
            self._ori_type.currentIndexChanged.connect(self._on_param_changed)
        if self._circ_type:
            self._circ_type.currentIndexChanged.connect(self._on_param_changed)
        self._cont.stateChanged.connect(self._on_param_changed)

    # ------------------------------------------------------------------
    # Валідація
    # ------------------------------------------------------------------

    def _in_range(self, text: str, lo: float, hi: float) -> bool:
        try:
            v = float(text)
            return lo < v <= hi   # lo < v (строго більше нуля для VEL/ACC)
        except ValueError:
            return False

    @staticmethod
    def _is_non_negative_int(text: str) -> bool:
        try:
            return int(text) >= 0
        except ValueError:
            return False

    def _mark_field(self, field: QLineEdit, ok: bool) -> None:
        field.setProperty("invalid", "" if ok else "true")
        field.style().unpolish(field)
        field.style().polish(field)

    def _validate(self) -> bool:
        ok = True

        # Координати
        if self._motion_type == "CIRC":
            if not self._aux_pos.is_valid() or self._aux_pos.is_empty():
                ok = False
            if not self._target_pos.is_valid() or self._target_pos.is_empty():
                ok = False
        else:
            if not self._pos.is_valid() or self._pos.is_empty():
                ok = False

        # VEL: 0 < v ≤ 100
        vel_ok = self._in_range(self._vel.text(), self._VEL_MIN, self._VEL_MAX)
        self._mark_field(self._vel, vel_ok)
        if not vel_ok:
            ok = False

        # ACC: 0 < v ≤ 100
        acc_ok = self._in_range(self._acc.text(), self._ACC_MIN, self._ACC_MAX)
        self._mark_field(self._acc, acc_ok)
        if not acc_ok:
            ok = False

        # TOOL і BASE: int >= 0
        tool_ok = self._is_non_negative_int(self._tool.text())
        self._mark_field(self._tool, tool_ok)
        if not tool_ok:
            ok = False

        base_ok = self._is_non_negative_int(self._base.text())
        self._mark_field(self._base, base_ok)
        if not base_ok:
            ok = False

        return ok

    # ------------------------------------------------------------------
    # Генерація рядка команди
    # ------------------------------------------------------------------

    def build_command(self) -> str:
        parts = [self._motion_type]

        if self._motion_type == "CIRC":
            parts.append(self._aux_pos.to_pos_string())
            parts.append(self._target_pos.to_pos_string())
        else:
            parts.append(self._pos.to_pos_string())

        if self._cont.isChecked():
            parts.append("CONT")

        if self._ori_type is not None:
            parts.append(self._ori_type.currentText())

        if self._circ_type is not None:
            parts.append(self._circ_type.currentText())

        parts.append(f"VEL {self._vel.text()}")
        parts.append(f"ACC {self._acc.text()}")
        parts.append(f"TOOL {self._tool.text()}")
        parts.append(f"BASE {self._base.text()}")

        return " ".join(parts) + ";"

    # ------------------------------------------------------------------

    def _on_param_changed(self) -> None:
        ok = self._validate()
        self._btn_insert.setEnabled(ok)
        if ok:
            self._preview.setText(self.build_command())
        else:
            self._preview.setText("⚠  Заповніть усі поля коректно (червоні поля — поза діапазоном)")


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
        self._cnc               = None   # встановлюється з GCodeEditorManager

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

    def set_cnc(self, cnc) -> None:
        """Передати посилання на MachineController для Get Current POS."""
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
            "QMenu{background:#2D2D2D;color:#F1F1F1;border:1px solid #333333;}"
            "QMenu::item:selected{background:#333333;}")

        has_sel = self.textCursor().hasSelection()
        a = menu.addAction("Вирізати (Ctrl+X)");  a.setEnabled(has_sel and not self._is_locked); a.triggered.connect(self.cut)
        a = menu.addAction("Копіювати (Ctrl+C)"); a.setEnabled(has_sel);                          a.triggered.connect(self.copy)
        a = menu.addAction("Вставити (Ctrl+V)");  a.setEnabled(not self._is_locked);              a.triggered.connect(self.paste)
        menu.addSeparator()

        a = menu.addAction("▶  Виконати з цього рядка")
        a.triggered.connect(self._on_set_next_line)
        menu.addSeparator()

        a = menu.addAction("Закоментувати"); a.setEnabled(not self._is_locked); a.triggered.connect(lambda: self._toggle_comment(True))
        a = menu.addAction("Розкоментувати"); a.setEnabled(not self._is_locked); a.triggered.connect(lambda: self._toggle_comment(False))
        menu.addSeparator()

        menu.addAction("Пошук та заміна  (Ctrl+H)").triggered.connect(self._show_search)
        menu.addSeparator()

        fold_menu = menu.addMenu("Вставити команду руху")
        for motion_type in ("PTP", "LIN", "CIRC"):
            a = fold_menu.addAction(motion_type)
            a.setEnabled(not self._is_locked)
            a.triggered.connect(
                lambda checked, mt=motion_type: self._open_motion_dialog(mt)
            )

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

    def _open_motion_dialog(self, motion_type: str) -> None:
        """Відкрити діалог вставки команди руху і вставити результат."""
        dlg = MotionCommandDialog(motion_type, cnc=self._cnc, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            cmd = dlg.build_command()
            cur = self.textCursor()
            cur.beginEditBlock()
            # Вставляємо на новому рядку після поточного
            cur.movePosition(QTextCursor.EndOfLine)
            cur.insertText("\n" + cmd)
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
        pal.setColor(pal.Window, QColor("#2D2D2D"))
        self.setPalette(pal)

        self._sf = QLineEdit(placeholderText="Пошук…")
        self._rf = QLineEdit(placeholderText="Замінити на…")
        self._li = QLabel("", styleSheet="color:#F1F1F1")

        _b = ("QPushButton{background:#333333;color:#F1F1F1;border:none;"
              "border-radius:3px;padding:0 8px;min-height:24px;}"
              "QPushButton:hover{background:#333333;}")
        _f = ("QLineEdit{background:#121212;color:#F1F1F1;"
              "border:1px solid #333333;border-radius:3px;padding:2px 6px;}")

        bp = QPushButton("↑"); bn = QPushButton("↓")
        br = QPushButton("Замінити"); ba = QPushButton("Замінити всі")
        bc = QPushButton("✕")
        for b in (bp, bn, br, ba, bc): b.setStyleSheet(_b)
        for f in (self._sf, self._rf): f.setStyleSheet(_f)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4); row.setSpacing(6)
        row.addWidget(QLabel("🔍", styleSheet="color:#F1F1F1"))
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
      • читання файлів з диска та відображення у редакторі
      • відстеження _current_file
      • auto-save при кожній зміні тексту
      • Safety Lock
      • підсвітку виконуваного рядка
      • Set Next Line → cycle_manager.start_cycle()

    НЕ залежить від FileManager.
    Підключення кнопок — HandlerClass._connect_file_buttons().
    """

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
        self._editor: GCodeEditorWidget = self._container.editor if self._container else self._editor
        self._editor.set_cnc(machine_controller)
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
        """
        Зчитати файл з диска, відобразити у редакторі та зберегти шлях.
        Не тригерить auto-save (load_text зупиняє debounce-таймер).
        Оновлює мітку lbl_filename.
        """
        if not os.path.isfile(filepath):
            logger.error("load_file: файл не знайдено: %s", filepath)
            return
        try:
            with open(filepath, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            logger.error("load_file: помилка читання: %s", exc)
            return

        self._editor.load_text(text)
        self._current_file = filepath

        # Оновлюємо мітку імені файлу
        lbl = getattr(self.widgets, "lbl_filename", None)
        if lbl:
            lbl.setText(os.path.basename(filepath))

        logger.debug("load_file: завантажено %s", os.path.basename(filepath))

    def set_current_file(self, filepath: str) -> None:
        """
        Встановити поточний файл БЕЗ перечитування з диска.
        Використовується коли текст вже завантажений у редактор ззовні.
        """
        self._current_file = filepath
        logger.debug("set_current_file → %s", filepath)

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

        # Новий G-код файл відкрито у LinuxCNC
        if current_file and current_file != self._current_file:
            self.load_file(current_file)

        # LinuxCNC не має файлу — очищуємо лише якщо це був G-код або
        # тимчасовий файл. Файли проекту (.txt, .ini тощо) LinuxCNC не
        # реєструє у status.file — не чіпаємо редактор у такому разі.
        if not current_file and self._current_file is not None:
            is_temp    = self._current_file.startswith(tempfile.gettempdir())
            ext        = os.path.splitext(self._current_file)[1].lower()
            is_gcode   = ext in (".ngc", ".gcode") or is_temp
            if is_gcode:
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
        """
        Спрацьовує після debounce (800 мс) при будь-якій зміні тексту.

        Завжди зберігає вміст на диск — для файлів проекту (.txt, .ini)
        і для G-код файлів (.ngc).
        cnc.open_program() викликається лише для G-код файлів щоб
        оновити Backplot, але не для файлів проекту.
        """
        if self._editor.is_locked():
            return
        content = self._editor.toPlainText()
        if not content.strip():
            return

        # Якщо файл не встановлений — створюємо тимчасовий .ngc
        if not self._current_file:
            self._current_file = _make_temp_file()
            logger.debug("Auto-save: тимчасовий файл %s", self._current_file)

        # Завжди записуємо на диск
        try:
            with open(self._current_file, "w", encoding="utf-8") as fh:
                fh.write(content)
            logger.debug("Auto-saved → %s", os.path.basename(self._current_file))
        except Exception as exc:
            logger.error("Auto-save запис: %s", exc)
            return

        # Оновлюємо LinuxCNC лише для G-код файлів
        ext = os.path.splitext(self._current_file)[1].lower()
        is_gcode = ext in (".ngc", ".gcode") or self._current_file.startswith(
            tempfile.gettempdir()
        )
        if is_gcode:
            try:
                self.cnc.open_program(self._current_file)
                self.cnc.reload_needed = False
            except Exception as exc:
                logger.debug("Auto-save cnc.open_program: %s", exc)

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