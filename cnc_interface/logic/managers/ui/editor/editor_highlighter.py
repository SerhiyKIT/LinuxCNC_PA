# logic/managers/ui/editor/editor_highlighter.py
"""
GCodeHighlighter – підсвітка синтаксису мови керування роботом.

Групи підсвітки (пріоритет зверху вниз):
  1. Коментарі        ; ...  та  ( ... )
  2. Команди руху     PTP  LIN  CIRC
  3. I/O команди      SET_DO  GET_DI  WAIT_DI
  4. Потокові команди WAIT  PAUSE  STOP  OFFSET
  5. Ключові слова    IF ELSEIF ELSE ENDIF
                      WHILE ENDWHILE  FOR TO ENDFOR  REPEAT ENDREPEAT
                      DEF CALL RETURN  CONT
                      TOOL BASE ORI_TYPE CIRC_TYPE ORI_VAR ORI_CONST
                                        CIRC_PATH CIRC_BASE
                      TRUE FALSE
  6. Параметри VEL ACC
  7. Координати X Y Z A B C + значення
  8. Числові літерали
"""
from __future__ import annotations
import re
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat
from .editor_colors import (
    CLR_COMMENT,
    CLR_COORD,
    CLR_FLOW_CMD,
    CLR_IO_CMD,
    CLR_KEYWORD,
    CLR_MOTION_CMD,
    CLR_NUMBER,
    CLR_FEED,
)


class GCodeHighlighter(QSyntaxHighlighter):
    """QSyntaxHighlighter для мови керування роботом."""

    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    # ------------------------------------------------------------------

    def _fmt(self, color, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:   f.setFontWeight(QFont.Bold)
        if italic: f.setFontItalic(True)
        return f

    def _build_rules(self) -> None:
        a = self._rules.append

        # 1. Команди руху
        a((re.compile(r'\b(PTP|LIN|CIRC)\b', re.IGNORECASE),
           self._fmt(CLR_MOTION_CMD, bold=True)))

        # 2. I/O команди
        a((re.compile(r'\b(SET_DO|GET_DI|WAIT_DI)\b', re.IGNORECASE),
           self._fmt(CLR_IO_CMD, bold=True)))

        # 3. Потокові команди та функції
        a((re.compile(r'\b(WAIT|PAUSE|STOP|OFFSET)\b', re.IGNORECASE),
           self._fmt(CLR_FLOW_CMD, bold=True)))

        # 4. Ключові слова керування потоком
        keywords = (
            r'IF|ELSEIF|ELSE|ENDIF|'
            r'WHILE|ENDWHILE|'
            r'FOR|TO|ENDFOR|'
            r'REPEAT|ENDREPEAT|'
            r'DEF|CALL|RETURN|'
            r'CONT|TRUE|FALSE'
        )
        a((re.compile(rf'\b({keywords})\b', re.IGNORECASE),
           self._fmt(CLR_KEYWORD, bold=True)))

        # 5. Параметри команд руху (VEL ACC TOOL BASE ORI_TYPE CIRC_TYPE тощо)
        motion_params = (
            r'VEL|ACC|TOOL|BASE|'
            r'ORI_TYPE|CIRC_TYPE|'
            r'ORI_VAR|ORI_CONST|'
            r'CIRC_PATH|CIRC_BASE'
        )
        a((re.compile(rf'\b({motion_params})\b', re.IGNORECASE),
           self._fmt(CLR_FEED)))

        # 6. Координатні осі X Y Z A B C + наступне число
        a((re.compile(r'\b[XYZABC](?=\s*[-\d.])', re.IGNORECASE),
           self._fmt(CLR_COORD, bold=True)))

        # 7. Числові літерали (цілі, дробові, зі знаком)
        a((re.compile(r'[-+]?\d+\.?\d*'),
           self._fmt(CLR_NUMBER)))
        
        # 8. Коментарі — останні, перекривають усе вище
        a((re.compile(r'//.*'),       self._fmt(CLR_COMMENT, italic=True)))

    # ------------------------------------------------------------------

    def highlightBlock(self, text: str) -> None:
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
