import pytest
from PyQt5 import QtCore, QtWidgets

class TestLoggerDisplay:
    @pytest.fixture
    def manager(self, qtbot):
        # 1. Mock-класи для залежностей
        class MockStyles:
            def __init__(self):
                self.STYLE_OUTPUT_VIEW = "background: #1e1e1e;"
                self.STYLE_LOG_CONTAINER = "padding: 2px;"
                self.STYLE_MSG_TEXT = "color: white;"
                self.STYLE_COPY_BTN = "border: none;"
                self.STYLE_SEPARATOR_LINE = "background: #333;"
                self.STYLE_CLIPBOARD = "color: green;"
            def _set_logger_styles(self): pass

        # 2. Mock UI
        class MockUI(QtWidgets.QMainWindow):
            def __init__(self):
                super().__init__()
                self.widgets = type('Widgets', (), {})()
                self.widgets.list_output_view = QtWidgets.QListWidget()
                self.widgets.list_output_view.setFixedWidth(400)

        # 3. Налаштування менеджера
        from logic.managers.ui.logger_display import LoggerDisplayManager
        
        ui = MockUI()
        
        # Створюємо об'єкт без виклику __init__, щоб уникнути імпорту real StyleManager
        mgr = LoggerDisplayManager.__new__(LoggerDisplayManager)
        mgr.widgets = ui.widgets
        mgr.style_manager = MockStyles()
        
        qtbot.addWidget(ui)
        return mgr, ui

    def test_setup_output_panel_config(self, manager):
        """Перевірка конфігурації панелі (вимкнення скролбарів)"""
        mgr, ui = manager
        mgr.setup_output_panel()
        
        view = ui.widgets.list_output_view
        assert view.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff
        assert view.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff

    def test_log_message_levels_colors(self, manager):
        """Перевірка правильного кодування кольорів для рівнів логування"""
        mgr, ui = manager
        
        # Перевірка ERROR (червоний #FF0000)
        mgr.log_message("Error msg", level="error")
        item = ui.widgets.list_output_view.item(0)
        container = ui.widgets.list_output_view.itemWidget(item)
        label = container.findChild(QtWidgets.QLabel)
        assert "#FF0000" in label.text()
        assert "ERROR:" in label.text()

        # Перевірка WARNING (помаранчевий #FE5C0D)
        mgr.log_message("Warn msg", level="warning")
        item_w = ui.widgets.list_output_view.item(1)
        container_w = ui.widgets.list_output_view.itemWidget(item_w)
        label_w = container_w.findChild(QtWidgets.QLabel)
        assert "#FE5C0D" in label_w.text()

    def test_copy_to_clipboard_logic(self, manager, qtbot):
        """Тест копіювання в буфер обміну та зміни тексту кнопки"""
        mgr, ui = manager
        mgr.log_message("Secret code", level="info")
        
        item = ui.widgets.list_output_view.item(0)
        container = ui.widgets.list_output_view.itemWidget(item)
        btn_copy = container.findChild(QtWidgets.QPushButton)
        
        # Імітуємо клік
        qtbot.mouseClick(btn_copy, QtCore.Qt.LeftButton)
        
        clipboard = QtWidgets.QApplication.clipboard()
        assert "INFO: Secret code" in clipboard.text()
        assert btn_copy.text() == "✓"
        
        # Перевірка повернення іконки через QTimer
        qtbot.wait(1100)
        assert btn_copy.text() == "📋"

    def test_label_width_calculation(self, manager):
        """Перевірка обмеження ширини тексту (фікс AttributeError)"""
        mgr, ui = manager
        mgr.log_message("Long text message")
        
        item = ui.widgets.list_output_view.item(0)
        container = ui.widgets.list_output_view.itemWidget(item)
        label = container.findChild(QtWidgets.QLabel)
        
        # Оскільки ми викликали setFixedWidth(340), 
        # перевіряємо через maximumWidth() або width()
        assert label.maximumWidth() == 340
        assert label.wordWrap() is True
        
    def test_auto_scroll_to_bottom(self, manager):
        """Перевірка, що список автоматично прокручується до останнього повідомлення"""
        mgr, ui = manager
        for i in range(10):
            mgr.log_message(f"Msg {i}")
            
        scrollbar = ui.widgets.list_output_view.verticalScrollBar()
        assert scrollbar.value() == scrollbar.maximum()