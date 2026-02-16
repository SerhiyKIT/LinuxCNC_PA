# logic/managers/ui/logger_display.py
from PyQt5 import QtCore, QtWidgets
from datetime import datetime
from managers import StyleManager

class LoggerDisplayManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        # Initialize the style manager to access styles for log display
        self.style_manager = StyleManager()
        self.style_manager._set_logger_styles()
        
    def setup_output_panel(self):
        """Initial setup for the output log panel to ensure it has the correct styles and behavior for displaying log messages."""
        view = self.widgets.list_output_view
        view.setStyleSheet(self.style_manager.STYLE_OUTPUT_VIEW)
        view.setSpacing(0)
        view.setContentsMargins(0, 0, 0, 0)
        
        if hasattr(view, 'viewport'):
            view.viewport().setContentsMargins(0, 0, 0, 0)
            
        view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

    def log_message(self, message, level="info"):
        """Log a message to the output panel with a timestamp and appropriate styling based on the message level (info, warning, error)."""
        if not hasattr(self.widgets, 'list_output_view'):
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {"info": "#DCDCDC", "warning": "#FE5C0D", "error": "#FF0000"}
        color = colors.get(level, "#FFFFFF")
        full_log_text = f"[{timestamp}] {level.upper()}: {message}"

        # Create a custom widget for the log entry
        item = QtWidgets.QListWidgetItem(self.widgets.list_output_view)
        container = QtWidgets.QWidget()
        container.setObjectName("logContainer")
        container.setStyleSheet(self.style_manager.STYLE_LOG_CONTAINER)
        
        v_layout = QtWidgets.QVBoxLayout(container)
        v_layout.setContentsMargins(5, 2, 5, 2)
        v_layout.setSpacing(0)

        h_layout = QtWidgets.QHBoxLayout()
        h_layout.setSpacing(10)

        # Styled label for the log message
        label = QtWidgets.QLabel(
            f'<span style="color: #666666;">[{timestamp}]</span> '
            f'<b style="color: {color};">{level.upper()}:</b> {message}'
        )
        label.setWordWrap(True)
        # Fix the width to prevent it from expanding indefinitely and ensure proper text wrapping within the output panel
        label.setFixedWidth(self.widgets.list_output_view.width() - 60)
        label.setStyleSheet(self.style_manager.STYLE_MSG_TEXT)
        
        # Copy button to copy the log message to clipboard
        btn_copy = QtWidgets.QPushButton("📋")
        btn_copy.setFixedSize(24, 24)
        btn_copy.setCursor(QtCore.Qt.PointingHandCursor)
        btn_copy.setStyleSheet(self.style_manager.STYLE_COPY_BTN)
        
        btn_copy.clicked.connect(lambda: self._copy_to_clipboard(full_log_text, btn_copy))

        h_layout.addWidget(label, 1)
        h_layout.addWidget(btn_copy, 0)
        v_layout.addLayout(h_layout)

        # Separator line below each log entry for better visual separation
        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(self.style_manager.STYLE_SEPARATOR_LINE)
        v_layout.addWidget(line)

        self.widgets.list_output_view.addItem(item)
        self.widgets.list_output_view.setItemWidget(item, container)
        item.setSizeHint(container.sizeHint())
        self.widgets.list_output_view.scrollToBottom()

    def _copy_to_clipboard(self, text, button):
        """"Copy the provided text to the system clipboard and provide visual feedback on the copy button"""
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        
        old_text = button.text()
        button.setText("✓")
        button.setStyleSheet(self.style_manager.STYLE_CLIPBOARD)
        QtCore.QTimer.singleShot(1000, lambda: self._reset_copy_button(button, old_text))

    def _reset_copy_button(self, button, old_text):
        """"Reset the copy button to its original state after showing feedback"""
        button.setText(old_text)
        button.setStyleSheet(self.style_manager.STYLE_COPY_BTN)