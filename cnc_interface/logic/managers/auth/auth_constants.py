# logic/managers/auth/auth_constants.py
"""
Константи, шляхи та стилі модуля автентифікації.
"""
from __future__ import annotations
from pathlib import Path

# ---------------------------------------------------------------------------
# Шляхи
# ---------------------------------------------------------------------------

AUTH_DIR  = Path.home() / "LinuxCNC_PA" / "db"
AUTH_DB   = AUTH_DIR / "system.db"

# ---------------------------------------------------------------------------
# Ролі — порядок від найвищої до найнижчої (пріоритет вибору: остання доступна)
# ---------------------------------------------------------------------------

ROLES: list[tuple[str, str]] = [
    ("role_admin",    "Admin"),
    ("role_engineer", "Engineer"),
    ("role_program",  "Program"),
    ("role_operator", "Operator"),
]

# Логін і id системного суперадміна
SUPERADMIN_LOGIN = "admin"
SUPERADMIN_ID    = "1"

# Пароль суперадміна за замовчуванням (тільки при першому запуску)
DEFAULT_PASSWORD = "1111"

# Таймаут бездіяльності — скидання до Operator (мілісекунди)
INACTIVITY_TIMEOUT_MS = 10 * 60 * 1000  # 10 хвилин

# Іконки ролей
ROLE_ICONS: dict[str, str] = {
    "Admin":    ":/icons/admin.png",
    "Engineer": ":/icons/engineer.png",
    "Program":  ":/icons/program.png",
    "Operator": ":/icons/operator.png",
}

# Індекс пріоритету ролі (більше = вище)
ROLE_PRIORITY: dict[str, int] = {
    "Operator": 0,
    "Program":  1,
    "Engineer": 2,
    "Admin":    3,
}

# ---------------------------------------------------------------------------
# Стилі
# ---------------------------------------------------------------------------

STYLE_DIALOG = """
QDialog {
    background:#121212; color:#F1F1F1;
}
QLabel {
    color:#F1F1F1;
}
QLineEdit {
    background:#2D2D2D; color:#F1F1F1;
    border:1px solid #333333; border-radius:8px;
    padding:6px 10px;
}
QLineEdit:focus  { border-color:#FE5C0D; }
QCheckBox {
    color:#F1F1F1; spacing:6px;
}
QCheckBox::indicator {
    width:16px; height:16px;
    border:1px solid #333333; border-radius:4px;
    background:#2D2D2D;
}
QCheckBox::indicator:checked {
    background:#FE5C0D; border-color:#FE5C0D;
}
QCheckBox::indicator:disabled {
    background:#333333; border-color:#333333;
}
QPushButton {
    background:#333333; color:#F1F1F1; border:none;
    border-radius:8px; padding:6px 18px; min-height:30px;
}
QPushButton:hover    { background:#ffffff; }
QPushButton:disabled { background:#1A1A1A; color:#5B5B5B; }
QPushButton#btn_confirm {
    background:#FE5C0D; color:#FFFFFF; font-weight:bold;
}
QPushButton#btn_confirm:hover    { background:#FF7533; }
QPushButton#btn_confirm:disabled { background:#333333; color:#9E9E9E; }
QTableWidget {
    background:#161616; color:#F1F1F1;
    border:none; gridline-color:#2D2D2D;
    font-size:13px;
}
QTableWidget::item { padding:4px 8px; }
QTableWidget::item:selected { background:#FE5C0D; color:#FFFFFF; }
QHeaderView::section {
    background:#1A1A1A; color:#9E9E9E;
    border:none; border-bottom:1px solid #333333;
    border-radius:0px; padding:4px 8px; font-size:12px;
}
QScrollBar:vertical {
    background:#1A1A1A; width:8px; border-radius:4px;
}
QScrollBar::handle:vertical {
    background:#333333; border-radius:4px;
}
QScrollBar::handle:vertical:hover { background:#FE5C0D; }
"""

STYLE_MENU = (
    "QMenu{background:#1A1A1A;color:#F1F1F1;"
    "border:1px solid #333333;border-radius:8px;padding:4px;}"
    "QMenu::item{padding:6px 20px 6px 12px;border-radius:4px;}"
    "QMenu::item:selected{background:#FE5C0D;color:#FFFFFF;}"
    "QMenu::item:disabled{color:#5B5B5B;}"
    "QMenu::separator{height:1px;background:#333333;margin:4px 0;}"
)

STYLE_BTN_PRIMARY = (
    "QPushButton{background:#FE5C0D;color:#FFFFFF;font-weight:bold;"
    "border:none;border-radius:8px;padding:6px 18px;min-height:30px;}"
    "QPushButton:hover{background:#FF7533;}"
    "QPushButton:disabled{background:#333333;color:#9E9E9E;}"
)
STYLE_BTN_SECONDARY = (
    "QPushButton{background:#333333;color:#F1F1F1;border:none;"
    "border-radius:8px;padding:6px 18px;min-height:30px;}"
    "QPushButton:hover{background:#5B5B5B;}"
    "QPushButton:disabled{background:#1A1A1A;color:#5B5B5B;}"
)
STYLE_BTN_DANGER = (
    "QPushButton{background:transparent;color:#f38ba8;border:none;"
    "border-radius:4px;padding:2px 6px;}"
    "QPushButton:hover{background:#2D2D2D;}"
    "QPushButton:disabled{color:#333333;}"
)
STYLE_MSGBOX = (
    "QMessageBox{background:#1A1A1A;color:#F1F1F1;}"
    "QMessageBox QLabel{color:#F1F1F1;font-size:13px;}"
    "QPushButton{background:#333333;color:#F1F1F1;border:none;"
    "border-radius:6px;padding:5px 18px;min-height:28px;min-width:80px;}"
    "QPushButton:hover{background:#5B5B5B;}"
    "QPushButton:default{background:#FE5C0D;color:#FFFFFF;font-weight:bold;}"
    "QPushButton:default:hover{background:#FF7533;}"
)