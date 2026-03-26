# logic/managers/ui/editor/editor_highlighter.py
"""
GCodeHighlighter – підсвітка синтаксису G/M-кодів.
"""
from __future__ import annotations
import re
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat
from .editor_colors import (
    CLR_COMMENT, CLR_COORD, CLR_FEED,
    CLR_G_CODE, CLR_M_CODE, CLR_NUMBER,
)


class GCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    def _fmt(self, color, bold=False, italic=False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:   f.setFontWeight(QFont.Bold)
        if italic: f.setFontItalic(True)
        return f

    def _build_rules(self) -> None:
        a = self._rules.append
        a((re.compile(r'\(.*?\)'),                                 self._fmt(CLR_COMMENT, italic=True)))
        a((re.compile(r';.*'),                                     self._fmt(CLR_COMMENT, italic=True)))
        a((re.compile(r'\bG\d+\.?\d*\b',       re.IGNORECASE),    self._fmt(CLR_G_CODE,  bold=True)))
        a((re.compile(r'\bM\d+\b',             re.IGNORECASE),    self._fmt(CLR_M_CODE,  bold=True)))
        a((re.compile(r'\b[XYZABCIJK](?=[-\d.])', re.IGNORECASE), self._fmt(CLR_COORD,   bold=True)))
        a((re.compile(r'\b[FST](?=[-\d.])',    re.IGNORECASE),    self._fmt(CLR_FEED)))
        a((re.compile(r'[-+]?\d+\.?\d*'),                         self._fmt(CLR_NUMBER)))

    def highlightBlock(self, text: str) -> None:
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
