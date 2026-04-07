# logic/managers/tool/tool_constants.py
"""
Константи, шляхи та стилі менеджера інструментів.
"""
from __future__ import annotations
from pathlib import Path

# ---------------------------------------------------------------------------
# Шляхи
# ---------------------------------------------------------------------------

GLOBAL_TOOL_DIR = Path.home() / "LinuxCNC_PA" / "db"
GLOBAL_TOOL_DB  = GLOBAL_TOOL_DIR / "tool.db"    # окремий файл від users.db

PROJECTS_ROOT    = Path.home() / "ProjectLinuxCNC"
PROJECT_TOOL_DIR  = "tool"
PROJECT_TOOL_DB   = "tools.db"

# ---------------------------------------------------------------------------
# Дефолтні інструменти — вставляються при першому запуску якщо таблиця порожня
# ---------------------------------------------------------------------------

DEFAULT_TOOLS: list[dict] = [
    {
        "id": "T10", "name": "Pneumatic Gripper 2-Finger",
        "type": "Gripper", "pocket": 10, "status": "Ready",
        "mass": 1.25, "offset": 0.0,
        "length_x": 165.0, "width_y": 80.0, "height_z": 60.0,
    },
    {
        "id": "T11", "name": "Vacuum Suction Pad 80mm",
        "type": "Vacuum", "pocket": 11, "status": "Ready",
        "mass": 0.45, "offset": 5.0,
        "length_x": 95.0, "width_y": 80.0, "height_z": 80.0,
    },
    {
        "id": "T12", "name": "MIG Welding Torch",
        "type": "Welding", "pocket": 0, "status": "Ready",
        "mass": 2.1, "offset": 12.5,
        "length_x": 210.0, "width_y": 30.0, "height_z": 30.0,
    },
]

# ---------------------------------------------------------------------------
# Enum-подібні константи
# ---------------------------------------------------------------------------

TOOL_TYPES    = ("Gripper", "Vacuum", "Welding", "Milling")
TOOL_STATUSES = ("Ready", "Active", "Wear", "Error")

STATUS_COLORS: dict[str, str] = {
    "Ready":  "#F1F1F1",
    "Active": "#FE5C0D",
    "Wear":   "#f9e2af",
    "Error":  "#f38ba8",
}

# ---------------------------------------------------------------------------
# Стилі (без змін)
# ---------------------------------------------------------------------------

STYLE_TABLE = """
QTableWidget {
    background:#161616; color:#F1F1F1;
    border:none; outline:none;
    gridline-color:#2D2D2D;
    font-size:13px;
}
QTableWidget::item {
    padding:4px 8px;
    border:none;
}
QTableWidget::item:selected {
    background:#FE5C0D; color:#FFFFFF;
}
QHeaderView::section {
    background:#1A1A1A; color:#9E9E9E;
    border:none; border-bottom:1px solid #333333;
    border-radius:0px;
    padding:4px 8px;
    font-size:12px;
}
QScrollBar:vertical {
    background:#1A1A1A; width:8px; border-radius:4px;
}
QScrollBar::handle:vertical {
    background:#333333; border-radius:4px;
}
QScrollBar::handle:vertical:hover { background:#FE5C0D; }
"""

STYLE_INPUT = """
QLineEdit {
    background:#2D2D2D; color:#F1F1F1;
    border:1px solid #333333; border-radius:6px;
    padding:4px 8px;
}
QLineEdit:focus  { border-color:#FE5C0D; }
QLineEdit:disabled { background:#1A1A1A; color:#5B5B5B; }
QComboBox {
    background:#2D2D2D; color:#F1F1F1;
    border:1px solid #333333; border-radius:6px;
    padding:4px 8px;
}
QComboBox:focus { border-color:#FE5C0D; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView {
    background:#2D2D2D; color:#F1F1F1;
    selection-background-color:#FE5C0D;
}
"""

STYLE_BTN_ACTIVE = (
    "QPushButton{background:#FE5C0D;color:#FFFFFF;border:none;"
    "border-radius:6px;padding:5px 14px;min-height:28px;}"
    "QPushButton:hover{background:#FF7533;}"
    "QPushButton:disabled{background:#333333;color:#9E9E9E;}"
)
STYLE_BTN_INACTIVE = (
    "QPushButton{background:#333333;color:#F1F1F1;border:none;"
    "border-radius:6px;padding:5px 14px;min-height:28px;}"
    "QPushButton:hover{background:#5B5B5B;}"
    "QPushButton:disabled{background:#1A1A1A;color:#5B5B5B;}"
)

STYLE_DIALOG = """
QDialog          { background:#121212; color:#F1F1F1; }
QLabel           { color:#F1F1F1; }
QGroupBox        { border:1px solid #333333; border-radius:6px;
                   margin-top:8px; color:#FE5C0D; }
QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
QLineEdit        { background:#2D2D2D; color:#F1F1F1;
                   border:1px solid #333333; border-radius:6px;
                   padding:4px 8px; }
QLineEdit:focus  { border-color:#FE5C0D; }
QLineEdit:read-only { background:#1A1A1A; color:#9E9E9E; }
QPushButton      { background:#333333; color:#F1F1F1; border:none;
                   border-radius:6px; padding:5px 14px; min-height:28px; }
QPushButton:hover { background:#5B5B5B; }
QPushButton#btn_confirm { background:#FE5C0D; color:#FFFFFF; font-weight:bold; }
QPushButton#btn_confirm:hover { background:#FF7533; }
"""

STYLE_MENU = (
    "QMenu{background:#1A1A1A;color:#F1F1F1;"
    "border:1px solid #333333;border-radius:6px;}"
    "QMenu::item{padding:5px 20px 5px 12px;}"
    "QMenu::item:selected{background:#FE5C0D;color:#FFFFFF;}"
)