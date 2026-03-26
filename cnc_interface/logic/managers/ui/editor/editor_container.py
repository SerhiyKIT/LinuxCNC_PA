# logic/managers/ui/editor/editor_container.py
"""
_EditorContainer – QWidget-обгортка: редактор + панель пошуку у layout.
"""
from __future__ import annotations
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from .editor_search import _SearchReplaceBar
from .editor_widget import GCodeEditorWidget


class _EditorContainer(QWidget):
    """Вертикальний контейнер: GCodeEditorWidget + _SearchReplaceBar."""

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
