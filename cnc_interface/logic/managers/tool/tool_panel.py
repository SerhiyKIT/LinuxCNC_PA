# logic/managers/tool/tool_panel.py
"""
ToolPanelManager — менеджер панелі інструментів.

Відповідає за:
  • Таблицю table_tools (список інструментів проекту)
  • Форму властивостей (txt_tool_*)
  • Кнопки ADD / DELETE / COPY / SAVE / CANCEL
  • Читання/запис через ToolStore
  • Активацію інструмента (подвійний клік → статус Active у JSON)
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

from PyQt5.QtCore    import QCoreApplication, Qt
from PyQt5.QtGui     import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QHeaderView,
    QMessageBox, QTableWidget, QTableWidgetItem,
)

from .tool_constants import (
    STATUS_COLORS, STYLE_BTN_ACTIVE, STYLE_BTN_INACTIVE,
    STYLE_TABLE, TOOL_STATUSES, TOOL_TYPES,
)
from .tool_dialogs import _AddToolDialog
from .tool_models  import Tool
from .tool_store   import ToolStore

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class ToolPanelManager:
    """Фасад панелі Tool Manager."""

    _TABLE_COLS = ("ID", "Name", "Pocket", "Status")

    def __init__(self, widgets: object) -> None:
        self.widgets          = widgets
        self._w               = lambda n: getattr(self.widgets, n, None)
        self._project_path:   Optional[Path] = None
        self._tools:          list[Tool]     = []
        self._selected_tool:  Optional[Tool] = None
        self._original_tool:  Optional[Tool] = None  # для CANCEL

        self._setup_table()
        self._setup_form()
        self._connect_buttons()
        self._set_form_enabled(False)
        self._set_buttons_no_project()

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_project(self, project_path: Optional[Path]) -> None:
        """Викликати при відкритті/закритті проекту."""
        self._project_path   = project_path
        self._selected_tool  = None
        self._original_tool  = None

        if project_path is None:
            self._tools = []
            self._refresh_table()
            self._clear_form()
            self._set_form_enabled(False)
            self._set_buttons_no_project()
        else:
            self._tools = ToolStore.load_project(project_path)
            self._refresh_table()
            self._set_buttons_no_selection()

    def connect_buttons(self) -> None:
        """Підключити кнопки (викликати після ініціалізації)."""
        self._connect_buttons()

    # ------------------------------------------------------------------
    # Ініціалізація UI
    # ------------------------------------------------------------------

    def _setup_table(self) -> None:
        table: QTableWidget = self._w("table_tools")
        if table is None:
            return
        table.setStyleSheet(STYLE_TABLE)
        table.setColumnCount(len(self._TABLE_COLS))
        table.setHorizontalHeaderLabels(list(self._TABLE_COLS))
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.itemSelectionChanged.connect(self._on_row_selected)
        table.itemDoubleClicked.connect(self._on_row_double_clicked)

    def _setup_form(self) -> None:
        """Налаштувати QComboBox статусу якщо він присутній у .ui."""
        status_w = self._w("txt_tool_status")
        if isinstance(status_w, QComboBox):
            status_w.clear()
            status_w.addItems(TOOL_STATUSES)

    def _connect_buttons(self) -> None:
        btns = {
            "btn_add_tool":    self._on_add,
            "btn_delete_tool": self._on_delete,
            "btn_copy_tool":   self._on_copy,
            "btn_save_tool":   self._on_save,
            "btn_cancel_tool": self._on_cancel,
        }
        for name, handler in btns.items():
            btn = self._w(name)
            if btn is None:
                continue
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(handler)

    # ------------------------------------------------------------------
    # Стан кнопок
    # ------------------------------------------------------------------

    def _set_buttons_no_project(self) -> None:
        """Всі кнопки неактивні — проект не відкритий."""
        for name in ("btn_add_tool", "btn_delete_tool",
                     "btn_copy_tool", "btn_save_tool", "btn_cancel_tool"):
            self._set_btn(name, False)

    def _set_buttons_no_selection(self) -> None:
        """Проект відкритий але нічого не вибрано."""
        self._set_btn("btn_add_tool",    True)
        self._set_btn("btn_delete_tool", False)
        self._set_btn("btn_copy_tool",   False)
        self._set_btn("btn_save_tool",   False)
        self._set_btn("btn_cancel_tool", False)

    def _set_buttons_with_selection(self) -> None:
        """Є вибраний інструмент."""
        self._set_btn("btn_add_tool",    True)
        self._set_btn("btn_delete_tool", True)
        self._set_btn("btn_copy_tool",   True)
        self._set_btn("btn_save_tool",   True)
        self._set_btn("btn_cancel_tool", True)

    def _set_btn(self, name: str, active: bool) -> None:
        btn = self._w(name)
        if btn is None:
            return
        btn.setEnabled(active)
        btn.setStyleSheet(STYLE_BTN_ACTIVE if active else STYLE_BTN_INACTIVE)

    # ------------------------------------------------------------------
    # Таблиця
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        table: QTableWidget = self._w("table_tools")
        if table is None:
            return
        table.blockSignals(True)
        table.setRowCount(0)
        for tool in self._tools:
            row = table.rowCount()
            table.insertRow(row)
            for col, text in enumerate((
                tool.id, tool.name, str(tool.pocket), tool.status
            )):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter if col != 1
                                      else Qt.AlignLeft | Qt.AlignVCenter)
                if col == 3:  # Status — колір
                    item.setForeground(
                        QColor(STATUS_COLORS.get(tool.status, "#F1F1F1")))
                table.setItem(row, col, item)
        table.blockSignals(False)

    def _select_row_by_id(self, tool_id: str) -> None:
        table: QTableWidget = self._w("table_tools")
        if table is None:
            return
        for row in range(table.rowCount()):
            if table.item(row, 0) and table.item(row, 0).text() == tool_id:
                table.selectRow(row)
                return

    def _current_table_row(self) -> int:
        table: QTableWidget = self._w("table_tools")
        if table is None:
            return -1
        rows = table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    # ------------------------------------------------------------------
    # Форма
    # ------------------------------------------------------------------

    def _load_form(self, tool: Tool) -> None:
        self._set_field("txt_tool_id",     tool.id)
        self._set_field("txt_tool_name",   tool.name)
        self._set_field("txt_tool_mass",   str(tool.mass))
        self._set_field("txt_tool_offset", str(tool.offset))
        self._set_field("txt_tool_pocket", str(tool.pocket))
        self._set_field("txt_tool_x",      str(tool.dimensions.length_x))
        self._set_field("txt_tool_y",      str(tool.dimensions.width_y))
        self._set_field("txt_tool_z",      str(tool.dimensions.height_z))

        status_w = self._w("txt_tool_status")
        if isinstance(status_w, QComboBox):
            idx = status_w.findText(tool.status)
            if idx >= 0:
                status_w.setCurrentIndex(idx)
        elif status_w is not None:
            status_w.setText(tool.status)

    def _read_form(self) -> dict:
        """Зчитати поточні значення форми у dict."""
        status_w = self._w("txt_tool_status")
        status = (status_w.currentText()
                  if isinstance(status_w, QComboBox)
                  else (status_w.text() if status_w else "Ready"))
        return {
            "id":       self._get_field("txt_tool_id"),
            "name":     self._get_field("txt_tool_name"),
            "mass":     self._get_field("txt_tool_mass"),
            "offset":   self._get_field("txt_tool_offset"),
            "pocket":   self._get_field("txt_tool_pocket"),
            "status":   status,
            "length_x": self._get_field("txt_tool_x"),
            "width_y":  self._get_field("txt_tool_y"),
            "height_z": self._get_field("txt_tool_z"),
        }

    def _clear_form(self) -> None:
        for name in ("txt_tool_id", "txt_tool_name", "txt_tool_mass",
                     "txt_tool_offset", "txt_tool_pocket",
                     "txt_tool_x", "txt_tool_y", "txt_tool_z"):
            self._set_field(name, "")
        status_w = self._w("txt_tool_status")
        if isinstance(status_w, QComboBox):
            status_w.setCurrentIndex(0)
        elif status_w:
            status_w.setText("")

    def _set_form_enabled(self, enabled: bool) -> None:
        for name in ("txt_tool_id", "txt_tool_name", "txt_tool_mass",
                     "txt_tool_offset", "txt_tool_pocket",
                     "txt_tool_x", "txt_tool_y", "txt_tool_z",
                     "txt_tool_status"):
            w = self._w(name)
            if w:
                w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Обробники подій таблиці
    # ------------------------------------------------------------------

    def _on_row_selected(self) -> None:
        row = self._current_table_row()
        if row < 0 or row >= len(self._tools):
            self._selected_tool = None
            self._original_tool = None
            self._clear_form()
            self._set_form_enabled(False)
            self._set_buttons_no_selection()
            return

        tool = self._tools[row]
        self._selected_tool = tool
        self._original_tool = tool.copy()
        self._load_form(tool)
        self._set_form_enabled(True)
        self._set_buttons_with_selection()

    def _on_row_double_clicked(self, item) -> None:
        """Подвійний клік — встановити статус Active."""
        row = self._current_table_row()
        if row < 0 or row >= len(self._tools) or self._project_path is None:
            return
        tool = self._tools[row]
        if tool.status == "Active":
            return
        # Скидаємо попередній Active
        for t in self._tools:
            if t.status == "Active":
                t.status = "Ready"
        tool.status = "Active"
        ToolStore.save_project(self._project_path, self._tools)
        self._refresh_table()
        self._select_row_by_id(tool.id)
        self._load_form(tool)
        logger.info("Активовано інструмент: %s", tool.id)

    # ------------------------------------------------------------------
    # Обробники кнопок
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        existing_ids = {t.id for t in self._tools}
        dlg = _AddToolDialog(existing_ids, parent=self._w("table_tools"))
        if dlg.exec_() != dlg.Accepted:
            return
        tool = dlg.selected_tool
        if tool is None:
            return
        if self._project_path is None:
            return
        if ToolStore.add_tool(self._project_path, tool):
            self._tools = ToolStore.load_project(self._project_path)
            self._refresh_table()
            self._select_row_by_id(tool.id)
            logger.info("Додано інструмент: %s", tool.id)
        else:
            self._show_error(_tr("Failed to add tool."))

    def _on_delete(self) -> None:
        if self._selected_tool is None or self._project_path is None:
            return
        tool = self._selected_tool
        if tool.status == "Active":
            reply = QMessageBox.question(
                self._w("table_tools"),
                _tr("Delete Active Tool"),
                _tr(f'Tool "{tool.name}" is currently Active.\n'
                    f'Are you sure you want to delete it?'),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        else:
            reply = QMessageBox.question(
                self._w("table_tools"),
                _tr("Delete Tool"),
                _tr(f'Delete "{tool.name}" ({tool.id})?'),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        if ToolStore.delete_tool(self._project_path, tool.id):
            self._tools = ToolStore.load_project(self._project_path)
            self._selected_tool = None
            self._original_tool = None
            self._refresh_table()
            self._clear_form()
            self._set_form_enabled(False)
            self._set_buttons_no_selection()
            logger.info("Видалено інструмент: %s", tool.id)
        else:
            self._show_error(_tr("Failed to delete tool."))

    def _on_copy(self) -> None:
        if self._selected_tool is None or self._project_path is None:
            return
        new_tool        = self._selected_tool.copy()
        new_tool.id     = ToolStore.next_free_id(self._project_path)
        new_tool.status = "Ready"
        if ToolStore.add_tool(self._project_path, new_tool):
            self._tools = ToolStore.load_project(self._project_path)
            self._refresh_table()
            self._select_row_by_id(new_tool.id)
            logger.info("Скопійовано інструмент → %s", new_tool.id)
        else:
            self._show_error(_tr("Failed to copy tool."))

    def _on_save(self) -> None:
        if self._selected_tool is None or self._project_path is None:
            return
        data   = self._read_form()
        errors = Tool.validate(data)
        if errors:
            self._show_error("\n".join(errors))
            return

        tool = self._selected_tool
        old_id = tool.id

        tool.id     = data["id"].strip()
        tool.name   = data["name"].strip()
        tool.status = data["status"]
        try:
            tool.mass             = float(data["mass"])
            tool.offset           = float(data["offset"])
            tool.pocket           = int(data["pocket"])
            tool.dimensions.length_x = float(data["length_x"])
            tool.dimensions.width_y  = float(data["width_y"])
            tool.dimensions.height_z = float(data["height_z"])
        except (ValueError, TypeError) as exc:
            self._show_error(str(exc))
            return

        # Якщо ID змінився — оновити у списку
        if tool.id != old_id:
            for t in self._tools:
                if t.id == old_id:
                    t.id = tool.id
                    break

        if ToolStore.save_project(self._project_path, self._tools):
            self._original_tool = tool.copy()
            self._refresh_table()
            self._select_row_by_id(tool.id)
            logger.info("Збережено інструмент: %s", tool.id)
        else:
            self._show_error(_tr("Failed to save tool."))

    def _on_cancel(self) -> None:
        if self._original_tool is None:
            return
        self._selected_tool = self._original_tool.copy()
        self._load_form(self._selected_tool)

    # ------------------------------------------------------------------
    # Хелпери
    # ------------------------------------------------------------------

    def _set_field(self, name: str, value: str) -> None:
        """Записати значення у поле незалежно від типу віджета."""
        w = self._w(name)
        if w is None:
            return
        if hasattr(w, "setText"):          # QLineEdit, QLabel
            w.setText(value)
        elif hasattr(w, "setPlainText"):   # QPlainTextEdit
            w.setPlainText(value)
        elif hasattr(w, "setHtml"):        # QTextEdit
            w.setPlainText(value)

    def _get_field(self, name: str) -> str:
        """Зчитати значення з поля незалежно від типу віджета."""
        w = self._w(name)
        if w is None:
            return ""
        if hasattr(w, "text"):             # QLineEdit
            return w.text().strip()
        if hasattr(w, "toPlainText"):      # QPlainTextEdit / QTextEdit
            return w.toPlainText().strip()
        return ""

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(
            self._w("table_tools"), _tr("Error"), message)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}"
                f"(project={self._project_path!r}, "
                f"tools={len(self._tools)})")