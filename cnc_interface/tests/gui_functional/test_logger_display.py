# tests/gui_functional/test_logger_display.py
"""
Функціональні GUI-тести LoggerDisplayManager
=============================================
Реальні Qt-віджети: QListWidget (list_output_view).
Реальні Qt-операції: addItem, setItemWidget, scrollToBottom.

Групи:
  1. setup_output_panel       — 4 тести
  2. log_message — структура  — 5 тестів
  3. log_message — рівні      — 4 тести
  4. Clipboard copy button    — 4 тести
"""

import pytest
from PyQt5 import QtWidgets, QtCore

from tests.gui_functional.conftest import make_cnc


# ---------------------------------------------------------------------------
# Реальні Qt-віджети
# ---------------------------------------------------------------------------

class LoggerWidgets(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.list_output_view = QtWidgets.QListWidget(self)
        self.list_output_view.resize(400, 300)


@pytest.fixture
def logger(qtbot):
    widgets = LoggerWidgets()
    qtbot.addWidget(widgets)
    # show() + waitExposed() гарантує що Qt утримує всі child widgets
    # (включаючи container QWidget всередині item) живими впродовж всього тесту,
    # що критично для QTimer.singleShot callbacks які звертаються до QPushButton.
    widgets.show()
    qtbot.waitExposed(widgets)
    cnc = make_cnc()
    from managers.ui.logger_display import LoggerDisplayManager
    mgr = LoggerDisplayManager(cnc, widgets)
    return mgr, widgets


# ---------------------------------------------------------------------------
# Група 1: setup_output_panel
# ---------------------------------------------------------------------------

class TestSetupOutputPanel:

    def test_scrollbar_vertical_hidden(self, logger):
        """setup_output_panel вимикає вертикальний scrollbar."""
        mgr, widgets = logger
        mgr.setup_output_panel()
        assert widgets.list_output_view.verticalScrollBarPolicy() == \
               QtCore.Qt.ScrollBarAlwaysOff

    def test_scrollbar_horizontal_hidden(self, logger):
        """setup_output_panel вимикає горизонтальний scrollbar."""
        mgr, widgets = logger
        mgr.setup_output_panel()
        assert widgets.list_output_view.horizontalScrollBarPolicy() == \
               QtCore.Qt.ScrollBarAlwaysOff

    def test_spacing_is_zero(self, logger):
        """setup_output_panel встановлює spacing=0."""
        mgr, widgets = logger
        mgr.setup_output_panel()
        assert widgets.list_output_view.spacing() == 0

    def test_stylesheet_applied(self, logger):
        """setup_output_panel встановлює непорожній stylesheet."""
        mgr, widgets = logger
        mgr.setup_output_panel()
        # StyleManager stub повертає рядок — важливо що він застосований
        assert widgets.list_output_view.styleSheet() != ""


# ---------------------------------------------------------------------------
# Група 2: log_message — структура
# ---------------------------------------------------------------------------

class TestLogMessageStructure:

    def test_item_added_to_list_widget(self, logger, qtbot):
        """Після log_message кількість елементів у list_output_view = 1."""
        mgr, widgets = logger
        mgr.log_message("Test message", "info")
        assert widgets.list_output_view.count() == 1

    def test_multiple_messages_add_multiple_items(self, logger):
        """Три виклики log_message → три елементи в списку."""
        mgr, widgets = logger
        mgr.log_message("msg1", "info")
        mgr.log_message("msg2", "warning")
        mgr.log_message("msg3", "error")
        assert widgets.list_output_view.count() == 3

    def test_item_has_custom_widget(self, logger):
        """Кожен item має custom widget (setItemWidget)."""
        mgr, widgets = logger
        mgr.log_message("Test", "info")
        item = widgets.list_output_view.item(0)
        widget = widgets.list_output_view.itemWidget(item)
        assert widget is not None

    def test_custom_widget_has_container_object_name(self, logger):
        """Custom widget має objectName == 'logContainer'."""
        mgr, widgets = logger
        mgr.log_message("Test", "info")
        item = widgets.list_output_view.item(0)
        container = widgets.list_output_view.itemWidget(item)
        assert container.objectName() == "logContainer"

    def test_list_scrolls_to_bottom_after_log(self, logger, qtbot):
        """Після log_message останній елемент видимий (список прокручений вниз)."""
        mgr, widgets = logger
        # Додаємо кілька повідомлень щоб список заповнився
        for i in range(10):
            mgr.log_message(f"Message number {i}", "info")
        # Перевіряємо що viewport прокручений до останнього item
        last_item = widgets.list_output_view.item(
            widgets.list_output_view.count() - 1
        )
        rect = widgets.list_output_view.visualItemRect(last_item)
        viewport_rect = widgets.list_output_view.viewport().rect()
        assert viewport_rect.intersects(rect), \
            "Останній елемент повинен бути видимим після scrollToBottom"


# ---------------------------------------------------------------------------
# Група 3: log_message — рівні
# ---------------------------------------------------------------------------

class TestLogMessageLevels:

    def test_info_level_adds_item(self, logger):
        """log_message з рівнем 'info' додає item без винятку."""
        mgr, widgets = logger
        mgr.log_message("Info message", "info")
        assert widgets.list_output_view.count() == 1

    def test_warning_level_adds_item(self, logger):
        """log_message з рівнем 'warning' додає item без винятку."""
        mgr, widgets = logger
        mgr.log_message("Warning message", "warning")
        assert widgets.list_output_view.count() == 1

    def test_error_level_adds_item(self, logger):
        """log_message з рівнем 'error' додає item без винятку."""
        mgr, widgets = logger
        mgr.log_message("Error message", "error")
        assert widgets.list_output_view.count() == 1

    def test_unknown_level_adds_item_without_crash(self, logger):
        """log_message з невідомим рівнем не кидає виняток (fallback колір)."""
        mgr, widgets = logger
        mgr.log_message("Unknown level", "critical")
        assert widgets.list_output_view.count() == 1


# ---------------------------------------------------------------------------
# Група 4: Clipboard copy button
# ---------------------------------------------------------------------------

class TestClipboardCopyButton:

    def test_copy_button_exists_in_item_widget(self, logger, qtbot):
        """Custom widget містить QPushButton (кнопка копіювання)."""
        mgr, widgets = logger
        mgr.log_message("Test", "info")
        item = widgets.list_output_view.item(0)
        container = widgets.list_output_view.itemWidget(item)
        buttons = container.findChildren(QtWidgets.QPushButton)
        assert len(buttons) >= 1

    def test_copy_button_click_writes_to_clipboard(self, logger, qtbot, qapp):
        """Клік по кнопці копіювання записує текст у системний clipboard."""
        mgr, widgets = logger
        msg = "Hello clipboard"
        mgr.log_message(msg, "info")
        item = widgets.list_output_view.item(0)
        container = widgets.list_output_view.itemWidget(item)
        copy_btn = container.findChildren(QtWidgets.QPushButton)[0]

        qtbot.mouseClick(copy_btn, QtCore.Qt.LeftButton)

        clipboard_text = qapp.clipboard().text()
        assert msg in clipboard_text

    def test_copy_button_text_changes_to_checkmark_on_click(self, logger, qtbot):
        """Після кліку текст кнопки копіювання змінюється на '✓'."""
        mgr, widgets = logger
        mgr.log_message("Test", "info")
        item = widgets.list_output_view.item(0)
        container = widgets.list_output_view.itemWidget(item)
        copy_btn = container.findChildren(QtWidgets.QPushButton)[0]

        qtbot.mouseClick(copy_btn, QtCore.Qt.LeftButton)

        assert copy_btn.text() == "✓"

    def test_copy_button_text_restored_after_timeout(self, logger, qtbot):
        """Після 1100мс текст кнопки відновлюється на '📋'.

        Зберігаємо явне Python-посилання на container та copy_btn щоб
        запобігти їх передчасному видаленню C++ до спрацювання QTimer.
        """
        mgr, widgets = logger
        mgr.log_message("Test", "info")
        item = widgets.list_output_view.item(0)
        # Зберігаємо strong ref — без цього Qt може видалити C++ об'єкт
        container = widgets.list_output_view.itemWidget(item)
        copy_btn = container.findChildren(QtWidgets.QPushButton)[0]
        original_text = copy_btn.text()

        qtbot.mouseClick(copy_btn, QtCore.Qt.LeftButton)
        assert copy_btn.text() == "✓"

        # waitUntil запускає Qt event loop — QTimer.singleShot(1000) спрацьовує
        # всередині нього. container і copy_btn живі завдяки Python strong ref.
        def check_restored():
            assert copy_btn.text() == original_text

        qtbot.waitUntil(check_restored, timeout=1500)
