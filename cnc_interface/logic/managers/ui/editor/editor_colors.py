# logic/managers/ui/editor/editor_colors.py
"""
Кольорова палітра, стилі та константи редактора коду.
"""
from __future__ import annotations
from PyQt5.QtGui import QColor

# Кольори редактора
CLR_BACKGROUND  = QColor("#121212")
CLR_FOREGROUND  = QColor("#F1F1F1")
CLR_LINE_NUM_BG = QColor("#161616")
CLR_LINE_NUM_FG = QColor("#9E9E9E")
CLR_ACTIVE_LINE = QColor("#333333")
CLR_EXEC_LINE   = QColor("#333333")

# Підсвітка синтаксису
CLR_G_CODE  = QColor("#89b4fa")
CLR_M_CODE  = QColor("#a6e3a1")
CLR_COORD   = QColor("#fab387")
CLR_FEED    = QColor("#f38ba8")
CLR_COMMENT = QColor("#5B5B5B")
CLR_NUMBER  = QColor("#f9e2af")

# Константи поведінки
AUTOSAVE_DELAY_MS: int   = 800
EDITABLE_EXTS:     tuple = (".txt", ".ini", ".xml", ".log", ".parl")
POS_AXES:          tuple = ("X", "Y", "Z", "A", "B", "C")

# Стиль контекстного меню
MENU_STYLE = (
    "QMenu{background:#2D2D2D;color:#F1F1F1;border:1px solid #333333;}"
    "QMenu::item{padding:4px 20px 4px 12px;}"
    "QMenu::item:selected{background:#FE5C0D;color:#FFFFFF;}"
    "QMenu::item:disabled{color:#5B5B5B;}"
    "QMenu::separator{height:1px;background:#333333;margin:3px 0;}"
)

# Стиль діалогу команди руху
DIALOG_STYLE = """
QDialog          { background:#1E1E1E; color:#F1F1F1; }
QGroupBox        { border:1px solid #333333; border-radius:4px;
                   margin-top:8px; color:#FE5C0D; }
QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
QLabel           { color:#F1F1F1; }
QLineEdit        { background:#121212; color:#F1F1F1;
                   border:1px solid #333333; border-radius:3px;
                   padding:3px 6px; min-width:80px; }
QLineEdit:focus  { border-color:#FE5C0D; }
QLineEdit[invalid="true"] { border-color:#f38ba8; }
QComboBox        { background:#121212; color:#F1F1F1;
                   border:1px solid #333333; border-radius:3px; padding:3px 6px; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#121212; color:#F1F1F1;
                               selection-background-color:#333333; }
QCheckBox        { color:#F1F1F1; spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #333333;
                        border-radius:3px; background:#121212; }
QCheckBox::indicator:checked { background:#FE5C0D; border-color:#FE5C0D; }
QPushButton      { background:#333333; color:#F1F1F1; border:none;
                   border-radius:4px; padding:5px 14px; min-height:28px; }
QPushButton:hover   { background:#5B5B5B; }
QPushButton:pressed { background:#121212; }
QPushButton:disabled{ background:#121212; color:#9E9E9E; }
"""

INSERT_BTN_STYLE = (
    "QPushButton{background:#FE5C0D;color:#FFFFFF;"
    "border-radius:4px;padding:5px 20px;min-height:28px;}"
    "QPushButton:disabled{background:#333333;color:#9E9E9E;}"
    "QPushButton:hover:!disabled{background:#FF7533;}"
)
