# logic/managers/ui/editor/editor_search.py
"""
_SearchReplaceBar – overlay-панель пошуку і заміни тексту.
"""
from __future__ import annotations
from PyQt5.QtCore    import QCoreApplication
from PyQt5.QtGui     import QColor, QTextCursor, QTextDocument
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget,
)
from .editor_widget import GCodeEditorWidget

_BTN = ("QPushButton{background:#333333;color:#F1F1F1;border:none;"
        "border-radius:3px;padding:0 8px;min-height:24px;}"
        "QPushButton:hover{background:#5B5B5B;}")
_FLD = ("QLineEdit{background:#121212;color:#F1F1F1;"
        "border:1px solid #333333;border-radius:3px;padding:2px 6px;}")

def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class _SearchReplaceBar(QWidget):
    def __init__(self, editor: GCodeEditorWidget, parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.Window, QColor("#2D2D2D"))
        self.setPalette(pal)

        self._sf  = QLineEdit(placeholderText=_tr("Search…"))
        self._rf  = QLineEdit(placeholderText=_tr("Replace with…"))
        self._lbl = QLabel("", styleSheet="color:#9E9E9E;font-size:11px;")

        bp = QPushButton("↑")
        bn = QPushButton("↓")
        br = QPushButton(_tr("Replace"))
        ba = QPushButton(_tr("Replace all"))
        bc = QPushButton("✕")

        for b in (bp, bn, br, ba, bc):
            b.setStyleSheet(_BTN)
            b.setAutoDefault(False)
        for f in (self._sf, self._rf):
            f.setStyleSheet(_FLD)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)
        row.addWidget(QLabel("🔍", styleSheet="color:#FE5C0D"))
        row.addWidget(self._sf)
        row.addWidget(self._rf)
        row.addWidget(bp)
        row.addWidget(bn)
        row.addWidget(br)
        row.addWidget(ba)
        row.addWidget(self._lbl)
        row.addStretch()
        row.addWidget(bc)

        bn.clicked.connect(self._find_next)
        bp.clicked.connect(self._find_prev)
        br.clicked.connect(self._replace_one)
        ba.clicked.connect(self._replace_all)
        bc.clicked.connect(self.hide)
        self._sf.returnPressed.connect(self._find_next)
        self.hide()

    def focus_search(self) -> None:
        self._sf.setFocus()
        self._sf.selectAll()

    def _find(self, backward: bool = False) -> bool:
        needle = self._sf.text()
        if not needle:
            return False
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlag(0)
        found = self._editor.find(needle, flags)
        if not found:
            cur = self._editor.textCursor()
            cur.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            self._editor.setTextCursor(cur)
            found = self._editor.find(needle, flags)
        self._lbl.setText("" if found else _tr("Not found"))
        return found

    def _find_next(self) -> None: self._find(False)
    def _find_prev(self) -> None: self._find(True)

    def _replace_one(self) -> None:
        if self._find():
            cur = self._editor.textCursor()
            if cur.hasSelection():
                cur.insertText(self._rf.text())

    def _replace_all(self) -> None:
        needle = self._sf.text()
        if not needle:
            return
        content = self._editor.document().toPlainText()
        count   = content.count(needle)
        if count:
            self._editor.load_text(content.replace(needle, self._rf.text()))
            self._lbl.setText(_tr(f"Replaced: {count}"))
        else:
            self._lbl.setText(_tr("Not found"))
