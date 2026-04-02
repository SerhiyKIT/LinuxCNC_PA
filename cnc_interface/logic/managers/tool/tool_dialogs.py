# logic/managers/tool/tool_dialogs.py
"""
_AddToolDialog — діалог вибору інструмента з глобального каталогу.
Ліва частина: список доступних інструментів.
Права частина: властивості обраного інструмента (read-only).
"""
from __future__ import annotations
import logging
from PyQt5.QtCore    import QCoreApplication, Qt
from PyQt5.QtGui     import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)
from .tool_constants  import STATUS_COLORS, STYLE_DIALOG, STYLE_BTN_ACTIVE, STYLE_BTN_INACTIVE
from .tool_models     import Tool
from .tool_store      import ToolStore

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class _AddToolDialog(QDialog):
    """
    Діалог вибору інструмента з глобального каталогу.
    Повертає обраний Tool або None при скасуванні.
    """

    def __init__(self, existing_ids: set[str], parent=None):
        super().__init__(parent)
        self._existing_ids = existing_ids
        self._selected: Tool | None = None
        self._global_tools: list[Tool] = ToolStore.load_global()

        self.setWindowTitle(_tr("Add Tool from Global Catalog"))
        self.setMinimumSize(700, 480)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # ── Ліва частина: список ─────────────────────────────────────
        left = QVBoxLayout()
        lbl = QLabel(_tr("Available Tools"))
        lbl.setStyleSheet("color:#FE5C0D; font-weight:bold; font-size:13px;")
        left.addWidget(lbl)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget{background:#161616;color:#F1F1F1;"
            "border:1px solid #333333;border-radius:6px;font-size:13px;}"
            "QListWidget::item{padding:6px 10px;}"
            "QListWidget::item:selected{background:#FE5C0D;color:#FFFFFF;}"
            "QListWidget::item:hover{background:#2D2D2D;}"
        )
        self._list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._list.currentRowChanged.connect(self._on_selection)
        left.addWidget(self._list)
        root.addLayout(left, stretch=1)

        # ── Права частина: властивості ───────────────────────────────
        right = QVBoxLayout()
        lbl2 = QLabel(_tr("Tool Properties"))
        lbl2.setStyleSheet("color:#FE5C0D; font-weight:bold; font-size:13px;")
        right.addWidget(lbl2)

        props_box = QGroupBox()
        props_box.setStyleSheet(
            "QGroupBox{border:1px solid #333333;border-radius:6px;"
            "background:#161616;}"
        )
        pf = QFormLayout(props_box)
        pf.setSpacing(8)
        pf.setContentsMargins(12, 12, 12, 12)
        pf.setLabelAlignment(Qt.AlignRight)

        def _ro_field() -> QLineEdit:
            f = QLineEdit()
            f.setReadOnly(True)
            f.setStyleSheet(
                "QLineEdit{background:#1A1A1A;color:#9E9E9E;"
                "border:1px solid #2D2D2D;border-radius:4px;padding:3px 6px;}")
            return f

        self._f_id     = _ro_field()
        self._f_name   = _ro_field()
        self._f_type   = _ro_field()
        self._f_pocket = _ro_field()
        self._f_status = _ro_field()
        self._f_mass   = _ro_field()
        self._f_offset = _ro_field()
        self._f_x      = _ro_field()
        self._f_y      = _ro_field()
        self._f_z      = _ro_field()

        pf.addRow(_tr("ID:"),       self._f_id)
        pf.addRow(_tr("Name:"),     self._f_name)
        pf.addRow(_tr("Type:"),     self._f_type)
        pf.addRow(_tr("Pocket:"),   self._f_pocket)
        pf.addRow(_tr("Status:"),   self._f_status)
        pf.addRow(_tr("Mass (kg):"),   self._f_mass)
        pf.addRow(_tr("Offset (mm):"), self._f_offset)
        pf.addRow(_tr("Length X (mm):"), self._f_x)
        pf.addRow(_tr("Width Y (mm):"),  self._f_y)
        pf.addRow(_tr("Height Z (mm):"), self._f_z)

        right.addWidget(props_box)
        right.addStretch()

        # ── Кнопки ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton(_tr("Cancel"))
        self._btn_cancel.setStyleSheet(STYLE_BTN_INACTIVE)
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_add = QPushButton(_tr("Add to Project"))
        self._btn_add.setStyleSheet(STYLE_BTN_ACTIVE)
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_add)
        right.addLayout(btn_row)

        root.addLayout(right, stretch=1)

        self._populate_list()

    # ------------------------------------------------------------------

    def _populate_list(self) -> None:
        self._list.clear()
        for tool in self._global_tools:
            already = tool.id in self._existing_ids
            item = QListWidgetItem(
                f"{tool.id}  —  {tool.name}"
                + (_tr("  [already in project]") if already else "")
            )
            if already:
                item.setForeground(QColor("#5B5B5B"))
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            self._list.addItem(item)

    def _on_selection(self, row: int) -> None:
        if row < 0 or row >= len(self._global_tools):
            self._btn_add.setEnabled(False)
            return
        tool = self._global_tools[row]
        already = tool.id in self._existing_ids
        self._btn_add.setEnabled(not already)

        self._f_id.setText(tool.id)
        self._f_name.setText(tool.name)
        self._f_type.setText(tool.type)
        self._f_pocket.setText(str(tool.pocket))
        self._f_status.setText(tool.status)
        self._f_mass.setText(str(tool.mass))
        self._f_offset.setText(str(tool.offset))
        self._f_x.setText(str(tool.dimensions.length_x))
        self._f_y.setText(str(tool.dimensions.width_y))
        self._f_z.setText(str(tool.dimensions.height_z))

        color = STATUS_COLORS.get(tool.status, "#F1F1F1")
        self._f_status.setStyleSheet(
            f"QLineEdit{{background:#1A1A1A;color:{color};"
            "border:1px solid #2D2D2D;border-radius:4px;padding:3px 6px;}")

        self._selected = tool if not already else None

    # ------------------------------------------------------------------

    @property
    def selected_tool(self) -> Tool | None:
        return self._selected
