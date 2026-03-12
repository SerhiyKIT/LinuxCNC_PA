# tests/gui/test_logger_display.py
"""
Unit-тести LoggerDisplayManager
==================================
Групи:
  1. setup_output_panel      — 3 тести
  2. log_message             — 5 тестів
  3. _copy/_reset clipboard  — 4 тести
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.gui.conftest import base_states


@pytest.fixture
def logger_mgr(mock_cnc, mock_widgets):
    # Весь Qt-шар (QListWidgetItem, QWidget, QLabel тощо) мокується,
    # щоб уникнути реального QApplication в unit-тестах.
    with patch("managers.ui.logger_display.StyleManager") as MockStyle, \
         patch("managers.ui.logger_display.QtWidgets") as MockQt,       \
         patch("managers.ui.logger_display.QtCore")   as MockQtCore:

        sm = MockStyle.return_value
        sm.STYLE_OUTPUT_VIEW    = "output_view"
        sm.STYLE_LOG_CONTAINER  = "log_container"
        sm.STYLE_MSG_TEXT       = "msg_text"
        sm.STYLE_COPY_BTN       = "copy_btn"
        sm.STYLE_CLIPBOARD      = "clipboard"
        sm.STYLE_SEPARATOR_LINE = "separator"

        MockQt.QListWidgetItem.return_value = MagicMock()
        MockQt.QWidget.return_value         = MagicMock()
        MockQt.QVBoxLayout.return_value     = MagicMock()
        MockQt.QHBoxLayout.return_value     = MagicMock()
        MockQt.QLabel.return_value          = MagicMock()
        MockQt.QPushButton.return_value     = MagicMock()
        MockQt.QFrame.return_value          = MagicMock()
        MockQt.QApplication.clipboard.return_value = MagicMock()

        from managers.ui.logger_display import LoggerDisplayManager
        mgr = LoggerDisplayManager(mock_cnc, mock_widgets)
        mgr._MockQt     = MockQt
        mgr._MockQtCore = MockQtCore
        yield mgr


# ---------------------------------------------------------------------------
# Група 1: setup_output_panel
# ---------------------------------------------------------------------------

class TestSetupOutputPanel:

    def test_sets_stylesheet(self, logger_mgr, mock_widgets):
        """setup_output_panel встановлює stylesheet на list_output_view."""
        logger_mgr.setup_output_panel()
        mock_widgets.list_output_view.setStyleSheet.assert_called_with("output_view")

    def test_disables_both_scrollbars(self, logger_mgr, mock_widgets):
        """setup_output_panel вимикає вертикальний і горизонтальний scrollbar."""
        logger_mgr.setup_output_panel()
        mock_widgets.list_output_view.setVerticalScrollBarPolicy.assert_called_once()
        mock_widgets.list_output_view.setHorizontalScrollBarPolicy.assert_called_once()

    def test_sets_spacing_zero(self, logger_mgr, mock_widgets):
        """setup_output_panel встановлює spacing=0."""
        logger_mgr.setup_output_panel()
        mock_widgets.list_output_view.setSpacing.assert_called_with(0)


# ---------------------------------------------------------------------------
# Група 2: log_message
# ---------------------------------------------------------------------------

class TestLogMessage:

    def test_no_crash_when_list_output_view_absent(self, logger_mgr, mock_widgets):
        """log_message не падає якщо list_output_view відсутній."""
        del mock_widgets.list_output_view
        logger_mgr.log_message("test", "info")

    def test_adds_item_to_list_widget(self, logger_mgr, mock_widgets):
        """log_message додає QListWidgetItem до list_output_view."""
        logger_mgr.log_message("Hello", "info")
        mock_widgets.list_output_view.addItem.assert_called_once()

    def test_scrolls_to_bottom(self, logger_mgr, mock_widgets):
        """log_message прокручує список до кінця після додавання."""
        logger_mgr.log_message("Hello", "info")
        mock_widgets.list_output_view.scrollToBottom.assert_called_once()

    def test_all_known_levels_accepted(self, logger_mgr, mock_widgets):
        """log_message приймає info, warning, error без винятків."""
        for level in ("info", "warning", "error"):
            logger_mgr.log_message("msg", level)

    def test_unknown_level_no_crash(self, logger_mgr, mock_widgets):
        """log_message з невідомим рівнем не кидає виняток (fallback колір)."""
        logger_mgr.log_message("msg", "critical")


# ---------------------------------------------------------------------------
# Група 3: _copy_to_clipboard та _reset_copy_button
# ---------------------------------------------------------------------------

class TestClipboard:

    def test_copies_text_to_clipboard(self, logger_mgr):
        """_copy_to_clipboard передає текст у clipboard."""
        btn = MagicMock()
        btn.text.return_value = "📋"
        logger_mgr._copy_to_clipboard("some text", btn)
        logger_mgr._MockQt.QApplication.clipboard.return_value \
            .setText.assert_called_with("some text")

    def test_button_changes_to_checkmark(self, logger_mgr):
        """_copy_to_clipboard змінює текст кнопки на ✓."""
        btn = MagicMock()
        btn.text.return_value = "📋"
        logger_mgr._copy_to_clipboard("text", btn)
        btn.setText.assert_called_with("✓")

    def test_button_gets_clipboard_style(self, logger_mgr):
        """_copy_to_clipboard встановлює CLIPBOARD стиль на кнопці."""
        btn = MagicMock()
        btn.text.return_value = "📋"
        logger_mgr._copy_to_clipboard("text", btn)
        btn.setStyleSheet.assert_called_with("clipboard")

    def test_reset_restores_original_text_and_style(self, logger_mgr):
        """_reset_copy_button відновлює оригінальний текст і стиль."""
        btn = MagicMock()
        logger_mgr._reset_copy_button(btn, "📋")
        btn.setText.assert_called_with("📋")
        btn.setStyleSheet.assert_called_with("copy_btn")
