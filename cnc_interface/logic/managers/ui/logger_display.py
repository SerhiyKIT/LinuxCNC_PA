# logic/managers/ui/logger_display.py
"""
LoggerDisplayManager – панель повідомлень з трьома вкладками.

  tab_live_stream    → list_output_view   – всі події в реальному часі
  tab_project_status → list_output_view_2 – події поточної сесії проекту
  tab_log_history    → list_output_view_3 – повна історія з файлів логів

Логіка:
  • live_stream    — завжди активна
  • project_status — активна лише коли проект відкритий, очищається
                     при зміні проекту
  • log_history    — завантажується з диска один раз при відкритті проекту,
                     нові записи додаються через on_new_entry callback
                     без перечитування файлу і без таймера
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtWidgets, sip

from managers import StyleManager


class LoggerDisplayManager:

    def __init__(self, machine_controller, widgets):
        self.cnc     = machine_controller
        self.widgets = widgets

        self.style_manager = StyleManager()
        self.style_manager._set_logger_styles()

        self._current_project: Optional[Path] = None
        self._project_logger                  = None

    # ------------------------------------------------------------------
    # Ініціалізація
    # ------------------------------------------------------------------

    def setup_output_panel(self) -> None:
        """Налаштувати всі три списки і стан вкладок."""
        for view_name in ("list_output_view",
                          "list_output_view_2",
                          "list_output_view_3"):
            view = getattr(self.widgets, view_name, None)
            if view is None:
                continue
            view.setStyleSheet(self.style_manager.STYLE_OUTPUT_VIEW)
            view.setSpacing(0)
            view.setContentsMargins(0, 0, 0, 0)
            if hasattr(view, "viewport"):
                view.viewport().setContentsMargins(0, 0, 0, 0)
            view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # Початковий стан: live_stream активна, решта — заблоковані
        tab_widget = getattr(self.widgets, "tabWidget_logs", None)
        if tab_widget is not None:
            tab_widget.setCurrentIndex(0)
            # При перемиканні вкладки — примусово оновити геометрію списку.
            # QListWidget не перераховує висоти кастомних елементів поки
            # вкладка прихована. Без цього елементи "підтягуються" лише
            # коли з'являється наступний новий запис.
            tab_widget.currentChanged.connect(self._on_tab_changed)

        self._set_project_tabs_enabled(False)

    def set_project_logger(self, project_logger) -> None:
        """
        Зареєструвати ProjectLogger і підписатися на on_new_entry.
        Для передачі між потоками використовуємо QTimer.singleShot(0)
        — планує виклик у UI потоці через event loop.
        """
        self._project_logger = project_logger
        if project_logger is not None:
            project_logger.set_on_new_entry(self._on_new_entry_from_thread)

    # ------------------------------------------------------------------
    # Керування проектом
    # ------------------------------------------------------------------

    def set_project(self, project_path: Optional[Path]) -> None:
        """
        Повідомити про зміну активного проекту.

        None → заблокувати вкладки, очистити їх вміст.
        Path → активувати вкладки, очистити project_status,
               завантажити log_history з файлів одним разом.
        """
        self._current_project = project_path

        if project_path is None:
            self._set_project_tabs_enabled(False)
            self._clear_view("list_output_view_2")
            self._clear_view("list_output_view_3")
            return

        # Новий проект — очищаємо тільки поточну сесію
        self._clear_view("list_output_view_2")
        self._set_project_tabs_enabled(True)

        # Завантажуємо повну історію з файлів один раз
        self._load_history_from_disk(project_path)

        # Перемикаємо на project_status
        self._switch_to_tab("tab_project_status")

    # ------------------------------------------------------------------
    # Основний метод логування (UI потік)
    # ------------------------------------------------------------------

    def log_message(self, message: str, level: str = "info",
                    module: str = "") -> None:
        """
        Відобразити повідомлення у live_stream і project_status.
        module — назва проекту або "system", відображається у live_stream.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # live_stream — завжди, з міткою module
        self._add_entry(
            "list_output_view", message, level, timestamp,
            prefix=f'<span style="color:#FE5C0D;">[{module}]</span> ' if module else ""
        )

        # project_status — без мітки module (і так зрозуміло який проект)
        if self._current_project is not None:
            self._add_entry("list_output_view_2", message, level, timestamp)

    # ------------------------------------------------------------------
    # Callback з фонового потоку (новий запис у файл)
    # ------------------------------------------------------------------

    def _on_new_entry_from_thread(self, entry: dict) -> None:
        """
        Викликається з фонового потоку після запису на диск.
        QTimer.singleShot(0, lambda) планує виконання у UI потоці
        через event loop — безпечна передача між потоками у PyQt5.
        """
        # Копіюємо entry щоб уникнути race condition
        entry_copy = dict(entry)
        QtCore.QTimer.singleShot(
            0, lambda: self._append_history_entry_ui(entry_copy)
        )

    def _append_history_entry_ui(self, entry: dict) -> None:
        """Додати один запис у log_history. Виконується в UI потоці."""
        # Показуємо лише якщо запис стосується поточного проекту
        if self._current_project is None:
            return
        module = entry.get("module", "")
        if module != self._current_project.name:
            return
        self._display_history_entry(entry)

    # ------------------------------------------------------------------
    # Завантаження history з диска
    # ------------------------------------------------------------------

    def _load_history_from_disk(self, project_path: Path) -> None:
        """Зчитати всі записи з файлів і відобразити у list_output_view_3."""
        self._clear_view("list_output_view_3")
        if self._project_logger is None:
            return
        entries = self._project_logger.read_project_log(project_path)
        for entry in entries:
            self._display_history_entry(entry)

    def _display_history_entry(self, entry: dict) -> None:
        """Відобразити один запис у list_output_view_3."""
        ts      = entry.get("timestamp", "")[:19].replace("T", " ")
        level   = entry.get("level", "INFO").lower()
        module  = entry.get("module", "")
        message = entry.get("message", "")
        prefix  = f"[{module}] " if module and module != "system" else ""
        self._add_entry("list_output_view_3", message, level, ts, prefix=prefix)

    # ------------------------------------------------------------------
    # Приватні хелпери UI
    # ------------------------------------------------------------------

    def _add_entry(self, view_name: str, message: str,
                   level: str, timestamp: str,
                   prefix: str = "") -> None:
        """Додати рядок повідомлення у QListWidget."""
        view = getattr(self.widgets, view_name, None)
        if view is None:
            return

        colors    = {"info": "#DCDCDC", "warning": "#FE5C0D", "error": "#FF0000"}
        color     = colors.get(level.lower(), "#FFFFFF")
        # Для буферу обміну — чистий текст без HTML тегів
        plain_prefix = re.sub(r"<[^>]+>", "", prefix)
        full_text = f"[{timestamp}] {level.upper()}: {plain_prefix}{message}"

        item      = QtWidgets.QListWidgetItem(view)
        container = QtWidgets.QWidget()
        container.setObjectName("logContainer")
        container.setStyleSheet(self.style_manager.STYLE_LOG_CONTAINER)

        v = QtWidgets.QVBoxLayout(container)
        v.setContentsMargins(5, 2, 5, 2)
        v.setSpacing(0)

        h = QtWidgets.QHBoxLayout()
        h.setSpacing(10)

        label = QtWidgets.QLabel(
            f'<span style="color:#666666;">[{timestamp}]</span> '
            f'<b style="color:{color};">{level.upper()}:</b> '
            f'{prefix}{message}'
        )
        label.setWordWrap(True)
        label.setFixedWidth(view.width() - 60)
        label.setStyleSheet(self.style_manager.STYLE_MSG_TEXT)

        btn = QtWidgets.QPushButton("📋")
        btn.setFixedSize(24, 24)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setStyleSheet(self.style_manager.STYLE_COPY_BTN)
        btn.clicked.connect(lambda _, t=full_text, b=btn: self._copy(t, b))

        h.addWidget(label, 1)
        h.addWidget(btn, 0)
        v.addLayout(h)

        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(self.style_manager.STYLE_SEPARATOR_LINE)
        v.addWidget(line)

        view.addItem(item)
        view.setItemWidget(item, container)
        item.setSizeHint(container.sizeHint())
        view.scrollToBottom()

    def _clear_view(self, view_name: str) -> None:
        view = getattr(self.widgets, view_name, None)
        if view is not None:
            view.clear()

    def _set_project_tabs_enabled(self, enabled: bool) -> None:
        tab_widget = getattr(self.widgets, "tabWidget_logs", None)
        if tab_widget is None:
            return
        for i in range(tab_widget.count()):
            name = tab_widget.widget(i).objectName()
            if name in ("tab_project_status", "tab_log_history"):
                tab_widget.setTabEnabled(i, enabled)
        if not enabled:
            current = tab_widget.currentWidget()
            if current and current.objectName() in (
                "tab_project_status", "tab_log_history"
            ):
                self._switch_to_tab("tab_live_stream")

    def _switch_to_tab(self, tab_name: str) -> None:
        tab_widget = getattr(self.widgets, "tabWidget_logs", None)
        if tab_widget is None:
            return
        for i in range(tab_widget.count()):
            if tab_widget.widget(i).objectName() == tab_name:
                tab_widget.setCurrentIndex(i)
                return

    def _on_tab_changed(self, index: int) -> None:
        """
        Примусово оновити геометрію всіх елементів активного списку.

        Проблема: QListWidget не перераховує висоти кастомних QWidget
        елементів поки вкладка прихована (isVisible() == False).
        Коли вкладка стає видимою — елементи вже є в моделі але їхні
        sizeHint не застосовані, тому вигляд "зламаний" доки не
        з'явиться наступний елемент що тригерить перерахунок.

        Рішення: при кожному перемиканні вкладки викликаємо
        scheduleDelayedItemsLayout() + scrollToBottom() для активного
        списку — це примушує Qt перерахувати всі розміри.
        """
        tab_widget = getattr(self.widgets, "tabWidget_logs", None)
        if tab_widget is None:
            return

        tab = tab_widget.widget(index)
        if tab is None:
            return

        # Визначаємо який список належить активній вкладці
        tab_to_view = {
            "tab_live_stream":    "list_output_view",
            "tab_project_status": "list_output_view_2",
            "tab_log_history":    "list_output_view_3",
        }
        view_name = tab_to_view.get(tab.objectName())
        if view_name is None:
            return

        view = getattr(self.widgets, view_name, None)
        if view is None:
            return

        # scheduleDelayedItemsLayout — планує повний перерахунок геометрії
        view.scheduleDelayedItemsLayout()
        # Невелика затримка щоб layout встиг застосуватися перед scroll
        QtCore.QTimer.singleShot(50, view.scrollToBottom)

    def _copy(self, text: str, btn: QtWidgets.QPushButton) -> None:
        QtWidgets.QApplication.clipboard().setText(text)
        old = btn.text()
        btn.setText("✓")
        btn.setStyleSheet(self.style_manager.STYLE_CLIPBOARD)
        QtCore.QTimer.singleShot(1000, lambda: self._reset_btn(btn, old))

    def _reset_btn(self, btn: QtWidgets.QPushButton, old: str) -> None:
        if sip.isdeleted(btn):
            return
        btn.setText(old)
        btn.setStyleSheet(self.style_manager.STYLE_COPY_BTN)