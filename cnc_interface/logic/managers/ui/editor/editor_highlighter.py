# logic/managers/ui/editor/editor_highlighter.py
"""
GCodeHighlighter – підсвітка синтаксису мови керування роботом.

Порядок застосування у highlightBlock (пізніше перекриває попереднє):
  1.  Ідентифікатори користувача  (змінні, підпрограми — з SymbolTable)
  2.  Числові літерали            0.0  -1.5  100
  3.  Координатні осі             X Y Z A B C (перед числом АБО змінною, з/без пробілу)
  4.  Параметри команд руху       VEL ACC TOOL BASE ORI_TYPE CIRC_TYPE ...
  5.  Ключові слова               IF WHILE FOR DEF CALL TRUE FALSE ...
  6.  Потокові команди            WAIT PAUSE STOP OFFSET
  7.  I/O команди                 SET_DO GET_DI WAIT_DI
  8.  Команди руху                PTP LIN CIRC
  9.  Плейсхолдери                [умова] [Pin] [значення]
  10. Коментарі //                (останні — гарантовано перекривають усе)

Виправлені проблеми відносно попередньої версії:
  • CLR_IDENT тепер визначено у editor_colors.py (була критична помилка імпорту)
  • CLR_PLACEHOLDER додано у editor_colors.py і використовується тут
  • Координати матчаться і без пробілу: Z-10.0, Z+5, Z home_x
  • BASE всередині CIRC_BASE більше не матчиться як окреме слово
    (motion_params розбито на дві групи з різними пріоритетами)
  • END DEF обробляється як два окремі токени (END + DEF) замість regex з \s
  • Числа зі знаком [-+] матчаться лише коли не є оператором
    (lookbehind виключає цифру/літеру/знак безпосередньо перед)
  • Ідентифікатори з крапковою нотацією: home.x, home.y, home.z
  • Плейсхолдери [умова] підсвічуються окремим кольором
  • Ідентифікатори користувача підсвічуються лише якщо не є ключовим словом
"""
from __future__ import annotations

import re
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat

from .editor_colors import (
    CLR_COMMENT,
    CLR_COORD,
    CLR_FEED,
    CLR_FLOW_CMD,
    CLR_IDENT,
    CLR_IO_CMD,
    CLR_KEYWORD,
    CLR_MOTION_CMD,
    CLR_NUMBER,
    CLR_PLACEHOLDER,
)

# ---------------------------------------------------------------------------
# Множина всіх зарезервованих слів мови — фільтр для ідентифікаторів
# ---------------------------------------------------------------------------
_RESERVED: frozenset[str] = frozenset({
    # Команди руху
    "PTP", "LIN", "CIRC",
    # Параметри руху
    "VEL", "ACC", "TOOL", "BASE", "CONT",
    "ORI_TYPE", "ORI_VAR", "ORI_CONST",
    "CIRC_TYPE", "CIRC_PATH", "CIRC_BASE",
    # Потокові
    "WAIT", "PAUSE", "STOP", "OFFSET",
    # I/O
    "SET_DO", "GET_DI", "WAIT_DI",
    # Керування потоком
    "IF", "ELSEIF", "ELSE", "ENDIF",
    "WHILE", "ENDWHILE",
    "FOR", "TO", "ENDFOR",
    "REPEAT", "ENDREPEAT",
    # Підпрограми
    "DEF", "END", "CALL", "RETURN",
    # Інше
    "TRUE", "FALSE",
    # Осі — одна літера, не є ідентифікатором користувача
    "X", "Y", "Z", "A", "B", "C",
})

# ---------------------------------------------------------------------------
# Статичні regex-патерни
# ---------------------------------------------------------------------------

# Ідентифікатори з крапковою нотацією: home, home.x, speed_slow
_RE_IDENT = re.compile(r'\b([A-Za-z_]\w*(?:\.\w+)*)\b')

# Числа: ціле або дробове, необов'язковий знак.
# (?<![A-Za-z_\d.]) — не матчить якщо число є частиною ідентифікатора
# (?![A-Za-z_])     — не матчить якщо після числа одразу літера
_RE_NUMBER = re.compile(r'(?<![A-Za-z_\d.])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])')

# Координатні осі X Y Z A B C.
# Матчить вісь якщо після неї (з/без пробілу) стоїть:
#   число, знак ±, або початок ідентифікатора
# Але НЕ матчить якщо вісь стоїть посередині слова (CIRC_BASE — B не є вісь)
_RE_COORD = re.compile(
    r'(?<!\w)([XYZABC])(?!\w)\s*(?=[-+\d]|[A-Za-z_]\w*)',
    re.IGNORECASE,
)

# Параметри команд вищого рівня (що не конфліктують з CIRC_*/ORI_*)
# BASE окремо — щоб не матчити всередині CIRC_BASE
_RE_PARAM_COMPOUND = re.compile(
    r'\b(ORI_TYPE|ORI_VAR|ORI_CONST|CIRC_TYPE|CIRC_PATH|CIRC_BASE)\b',
    re.IGNORECASE,
)
_RE_PARAM_SIMPLE = re.compile(
    r'\b(VEL|ACC|TOOL|BASE|CONT)\b(?![\w_])',
    re.IGNORECASE,
)

# Ключові слова
_RE_KEYWORDS = re.compile(
    r'\b(IF|ELSEIF|ELSE|ENDIF'
    r'|WHILE|ENDWHILE'
    r'|FOR|TO|ENDFOR'
    r'|REPEAT|ENDREPEAT'
    r'|DEF|END|CALL|RETURN'
    r'|TRUE|FALSE)\b',
    re.IGNORECASE,
)

# Потокові команди
_RE_FLOW = re.compile(r'\b(WAIT|PAUSE|STOP|OFFSET)\b', re.IGNORECASE)

# I/O команди
_RE_IO = re.compile(r'\b(SET_DO|GET_DI|WAIT_DI)\b', re.IGNORECASE)

# Команди руху
_RE_MOTION = re.compile(r'\b(PTP|LIN|CIRC)\b', re.IGNORECASE)

# Плейсхолдери [текст] — виключає вкладені дужки і переноси рядка
_RE_PLACEHOLDER = re.compile(r'\[[^\[\]\n]+\]')

# Коментарі — від // до кінця рядка
_RE_COMMENT = re.compile(r'//.*')


class GCodeHighlighter(QSyntaxHighlighter):
    """QSyntaxHighlighter для мови керування роботом."""

    def __init__(self, document):
        super().__init__(document)
        self._user_symbols: set[str] = set()

        self._fmt_ident       = self._fmt(CLR_IDENT)
        self._fmt_number      = self._fmt(CLR_NUMBER)
        self._fmt_coord       = self._fmt(CLR_COORD,      bold=True)
        self._fmt_param       = self._fmt(CLR_FEED)
        self._fmt_keyword     = self._fmt(CLR_KEYWORD,    bold=True)
        self._fmt_flow        = self._fmt(CLR_FLOW_CMD,   bold=True)
        self._fmt_io          = self._fmt(CLR_IO_CMD,     bold=True)
        self._fmt_motion      = self._fmt(CLR_MOTION_CMD, bold=True)
        self._fmt_placeholder = self._fmt(CLR_PLACEHOLDER, italic=True)
        self._fmt_comment     = self._fmt(CLR_COMMENT,    italic=True)

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_symbols(self, variables: list[str], subroutines: list[str]) -> None:
        """
        Оновити множину символів користувача для підсвітки.
        Викликається з GCodeEditorManager після завантаження SymbolTable.
        """
        self._user_symbols = {
            s.upper() for s in (variables + subroutines) if s
        }
        self.rehighlight()

    # ------------------------------------------------------------------
    # Форматування
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(color, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:   f.setFontWeight(QFont.Bold)
        if italic: f.setFontItalic(True)
        return f

    # ------------------------------------------------------------------
    # Підсвітка рядка
    # ------------------------------------------------------------------

    def highlightBlock(self, text: str) -> None:
        # 1. Ідентифікатори користувача (змінні та підпрограми)
        #    Підсвічуємо лише якщо є у SymbolTable і не є зарезервованим словом
        if self._user_symbols:
            for m in _RE_IDENT.finditer(text):
                token = m.group(1)
                # Для крапкової нотації (home.x) перевіряємо базову частину
                base  = token.split(".")[0].upper()
                if base in self._user_symbols and token.upper() not in _RESERVED:
                    self._apply(m, self._fmt_ident)

        # 2. Числові літерали
        self._apply_all(_RE_NUMBER, text, self._fmt_number)

        # 3. Координатні осі (перекривають числа — вісь важливіша)
        self._apply_all(_RE_COORD, text, self._fmt_coord)

        # 4а. Складені параметри (CIRC_BASE, ORI_TYPE...) — спочатку!
        self._apply_all(_RE_PARAM_COMPOUND, text, self._fmt_param)

        # 4б. Прості параметри (VEL, ACC, TOOL, BASE, CONT)
        #     Після складених — BASE не потрапить в CIRC_BASE
        self._apply_all(_RE_PARAM_SIMPLE, text, self._fmt_param)

        # 5. Ключові слова
        self._apply_all(_RE_KEYWORDS, text, self._fmt_keyword)

        # 6. Потокові команди
        self._apply_all(_RE_FLOW, text, self._fmt_flow)

        # 7. I/O команди
        self._apply_all(_RE_IO, text, self._fmt_io)

        # 8. Команди руху (найвищий пріоритет серед команд)
        self._apply_all(_RE_MOTION, text, self._fmt_motion)

        # 9. Плейсхолдери [умова] [Pin]
        self._apply_all(_RE_PLACEHOLDER, text, self._fmt_placeholder)

        # 10. Коментарі — перекривають АБСОЛЮТНО ВСЕ вище
        m = _RE_COMMENT.search(text)
        if m:
            self.setFormat(m.start(), len(text) - m.start(), self._fmt_comment)

    # ------------------------------------------------------------------
    # Хелпери
    # ------------------------------------------------------------------

    def _apply(self, m: re.Match, fmt: QTextCharFormat) -> None:
        self.setFormat(m.start(), m.end() - m.start(), fmt)

    def _apply_all(self, pat: re.Pattern, text: str,
                   fmt: QTextCharFormat) -> None:
        for m in pat.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), fmt)