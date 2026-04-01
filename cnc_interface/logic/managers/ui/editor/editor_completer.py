# logic/managers/ui/editor/editor_completer.py
"""
EditorCompleter – контекстне автодоповнення для GCodeEditorWidget.

Функції:
  • QCompleter — випадаючий список під курсором від 2 символів
  • Контекстне розпізнавання — SET_DO → піни, CALL → підпрограми, IF → змінні
  • Snippet-вставка — при виборі команди вставляє шаблон з [плейсхолдерами]
  • Tab-навігація — Tab переміщує курсор до наступного [плейсхолдера]

Плейсхолдери позначаються [текст].
Tab виділяє наступний [...] для перезапису.
"""
from __future__ import annotations

import logging
import re
from PyQt5.QtCore    import Qt, QStringListModel
from PyQt5.QtGui     import QTextCursor
from PyQt5.QtWidgets import QCompleter

from .editor_symbol_table import SymbolTable

logger = logging.getLogger(__name__)

_MIN_PREFIX  = 2          # мінімум символів для базового режиму
# Контекстні команди після яких список показується одразу (навіть prefix="")
_CONTEXT_SHOW_ALWAYS = frozenset({
    "SET_DO", "GET_DI", "WAIT_DI", "CALL",
})
_RE_PH       = re.compile(r'\[([^\[\]]+)\]')     # [плейсхолдер] — одинарні дужки
# Матчить контекст і prefix:
#   SET_DO [gripper  → context=SET_DO, prefix=gripper
#   SET_DO [         → context=SET_DO, prefix=""
#   SET_DO           → context=SET_DO, prefix=""
#   CALL MyR         → context=CALL,   prefix=MyR
# \[? — необов'язкова відкрита дужка після пробілу
_RE_CONTEXT  = re.compile(
    r'(?:^|[\s;])(CALL|IF|WHILE|ELSEIF|FOR|REPEAT)'
    r'\s+\[?(\w*)$',
    re.IGNORECASE,
)
_RE_PREFIX   = re.compile(r'(\w+)$')              # останнє слово перед курсором

# Snippets з [плейсхолдерами] для кожної команди
_SNIPPETS: dict[str, str] = {
    "PTP":     "PTP {X [0.0], Y [0.0], Z [0.0], A [0.0], B [0.0], C [0.0]} VEL [100.0] ACC [100.0] TOOL [1] BASE [0];",
    "LIN":     "LIN {X [0.0], Y [0.0], Z [0.0], A [0.0], B [0.0], C [0.0]} VEL [100.0] ACC [100.0] TOOL [1] BASE [0];",
    "CIRC":    "CIRC {X [0.0], Y [0.0], Z [0.0], A [0.0], B [0.0], C [0.0]} {X [0.0], Y [0.0], Z [0.0], A [0.0], B [0.0], C [0.0]} VEL [100.0] ACC [100.0] TOOL [1] BASE [0];",
    "WAIT":    "WAIT [1.0];",
    "SET_DO":  "SET_DO [Pin] [TRUE];",
    "GET_DI":  "GET_DI [Pin];",
    "WAIT_DI": "WAIT_DI [Pin] [TRUE];",
    "OFFSET":  "OFFSET ([X 0.0], [Y 0.0], [Z 0.0]);",
    "IF":      "IF [condition]\n    \nENDIF",
    "WHILE":   "WHILE [condition]\n    \nENDWHILE",
    "FOR":     "FOR [var] = [start] TO [end]\n    \nENDFOR",
    "REPEAT":  "REPEAT [count]\n    \nENDREPEAT",
    "DEF":     "DEF [MyRoutine]()\n    \nEND DEF",
    "CALL":    "CALL [MyRoutine]();",
    "PAUSE":   "PAUSE;",
    "STOP":    "STOP;",
    "RETURN":  "RETURN;",
}

_POPUP_STYLE = (
    "QListView {"
    "  background:#2D2D2D; color:#F1F1F1;"
    "  border:1px solid #FE5C0D; border-radius:4px;"
    "  font-family:Monospace; font-size:12px; outline:none;"
    "}"
    "QListView::item { padding:3px 10px; }"
    "QListView::item:selected { background:#FE5C0D; color:#FFFFFF; }"
    "QScrollBar:vertical { background:#1A1A1A; width:8px; border-radius:4px; }"
    "QScrollBar::handle:vertical { background:#FE5C0D; border-radius:4px; }"
)


class EditorCompleter:
    """
    Прив'язується до GCodeEditorWidget.
    Викликається з keyPressEvent і textChanged.
    """

    def __init__(self, editor, symbol_table: SymbolTable) -> None:
        self._editor  = editor
        self._symbols = symbol_table

        self._model     = QStringListModel()
        self._completer = QCompleter(self._model, editor)
        self._completer.setWidget(editor)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchStartsWith)
        self._completer.popup().setStyleSheet(_POPUP_STYLE)
        self._completer.activated.connect(self._on_selected)

    # ------------------------------------------------------------------
    # Інтеграція з editor
    # ------------------------------------------------------------------

    def handle_key_press(self, event) -> bool:
        """
        Викликати з keyPressEvent до super().
        Повертає True якщо подію оброблено — тоді super() НЕ викликати.
        """
        key = event.key()
        popup_visible = self._completer.popup().isVisible()

        # Tab — навігація по плейсхолдерах (або підтвердження у списку)
        if key == Qt.Key_Tab:
            if popup_visible:
                self._confirm_from_popup()
                return True
            return self._jump_to_placeholder()

        # Escape — закрити список
        if key == Qt.Key_Escape and popup_visible:
            self._completer.popup().hide()
            return True

        # Enter/Return — підтвердити у списку
        if key in (Qt.Key_Return, Qt.Key_Enter) and popup_visible:
            self._confirm_from_popup()
            return True

        return False

    def update_completions(self) -> None:
        """
        Оновити список після кожного введеного символу.
        Викликати з сигналу textChanged або cursorPositionChanged.
        """
        if self._editor.is_locked():
            self._completer.popup().hide()
            return

        prefix, context = self._get_prefix_and_context()

        # Для контекстних команд (SET_DO, CALL...) показуємо список одразу
        # навіть якщо prefix порожній — щоб піни/підпрограми були видні.
        # Для базового режиму — чекаємо мінімум _MIN_PREFIX символів.
        if context.upper() not in _CONTEXT_SHOW_ALWAYS and len(prefix) < _MIN_PREFIX:
            self._completer.popup().hide()
            return

        candidates = self._symbols.get_completions(context, prefix)
        if not candidates:
            self._completer.popup().hide()
            return

        self._model.setStringList(candidates)
        self._completer.setCompletionPrefix(prefix)

        cr = self._editor.cursorRect()
        cr.setWidth(
            self._completer.popup().sizeHintForColumn(0)
            + self._completer.popup().verticalScrollBar().sizeHint().width()
            + 24
        )
        self._completer.complete(cr)

    # ------------------------------------------------------------------
    # Аналіз рядка
    # ------------------------------------------------------------------

    def _get_prefix_and_context(self) -> tuple[str, str]:
        """Повернути (префікс, контекст) для поточної позиції курсора."""
        cur  = self._editor.textCursor()
        line = cur.block().text()[: cur.positionInBlock()]

        m = _RE_CONTEXT.search(line)
        if m:
            return m.group(2), m.group(1)

        m = _RE_PREFIX.search(line)
        return (m.group(1) if m else ""), ""

    # ------------------------------------------------------------------
    # Вставка при виборі
    # ------------------------------------------------------------------

    def _confirm_from_popup(self) -> None:
        popup = self._completer.popup()
        idx   = popup.currentIndex()
        popup.hide()
        if idx.isValid():
            word = self._completer.completionModel().data(idx)
            self._on_selected(word)

    def _on_selected(self, word: str) -> None:
        """Вставити обраний елемент, видаливши вже надрукований префікс і [ якщо є."""
        if not word:
            return

        cur = self._editor.textCursor()

        # Видаляємо надрукований префікс
        prefix, _ = self._get_prefix_and_context()
        for _ in range(len(prefix)):
            cur.deletePreviousChar()

        # Видаляємо відкриту [ якщо вона стоїть перед префіксом
        # (користувач написав SET_DO [ або SET_DO [part)
        pos_in_block = cur.positionInBlock()
        line_before  = cur.block().text()[:pos_in_block]
        if line_before.endswith("["):
            cur.deletePreviousChar()
            cur.deletePreviousChar()

        # Шукаємо snippet (лише для команд верхнього рівня)
        # Для пінів і змінних вставляємо слово напряму
        snippet = _SNIPPETS.get(word.upper())
        if snippet:
            cur.beginEditBlock()
            cur.insertText(snippet)
            cur.endEditBlock()
            self._editor.setTextCursor(cur)
            self._jump_to_placeholder()
        else:
            cur.insertText(word)
            self._editor.setTextCursor(cur)

        self._completer.popup().hide()

    # ------------------------------------------------------------------
    # Tab-навігація між [плейсхолдерами]
    # ------------------------------------------------------------------

    def _jump_to_placeholder(self) -> bool:
        """
        Знайти наступний [плейсхолдер] після курсора і виділити його.
        При досягненні кінця — wraparound на початок документа.
        Повертає True якщо плейсхолдер знайдений.
        """
        doc  = self._editor.document()
        text = doc.toPlainText()
        pos  = self._editor.textCursor().position()

        # Шукаємо після поточної позиції
        m = _RE_PH.search(text, pos)

        # Wraparound — шукаємо з початку
        if not m:
            m = _RE_PH.search(text, 0)

        if not m:
            return False

        # Виділяємо [плейсхолдер] включно з дужками
        sel = QTextCursor(doc)
        sel.setPosition(m.start())
        sel.setPosition(m.end(), QTextCursor.KeepAnchor)
        self._editor.setTextCursor(sel)
        return True