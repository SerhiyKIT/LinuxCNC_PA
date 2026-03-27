# logic/managers/project/project_constants.py
"""
Константи, шляхи та стилі менеджера проектів.
Єдине місце де визначаються всі рядки конфігурації, CSS і шляхи.
"""
from __future__ import annotations
from pathlib import Path

# ---------------------------------------------------------------------------
# Шляхи і структура
# ---------------------------------------------------------------------------

PROJECTS_ROOT = Path.home() / "ProjectLinuxCNC"

PROJECT_STRUCTURE: dict[str, list[str]] = {
    "src":  ["program.txt"],
    "bin":  ["main.parl"],
    "data": ["variables.json"],
    "logs": ["execution.json"],
}
PROJECT_ROOT_FILES = ["config.ini"]
DEFAULT_OPEN_FILE  = Path("src") / "program.txt"
EDITABLE_EXTS      = (".txt", ".ini", ".json", ".parl")
HIDDEN_FOLDERS     = {"bin", "logs"}
WATCHER_IGNORE_DIRS = {"logs"}

# ---------------------------------------------------------------------------
# config.ini
# ---------------------------------------------------------------------------

CFG_SECTION    = "project"
CFG_NAME       = "name"
CFG_AUTHOR     = "author"
CFG_CREATED    = "created"
CFG_MODIFIED   = "last_modified"
CFG_DATE_FMT   = "%Y-%m-%d %H:%M"
DEFAULT_AUTHOR = "Admin_User"

# ---------------------------------------------------------------------------
# Стилі
# ---------------------------------------------------------------------------

STYLE_DIALOG = """
QDialog          { background:#121212; color:#FFFFFF; }
QLabel           { color:#F1F1F1; }
QLineEdit        { background:#2D2D2D; color:#FFFFFF;
                   border:1px solid #333333; border-radius:10px;
                   padding:4px 8px; }
QLineEdit:focus  { border-color:#FE5C0D; }
QLineEdit[invalid="true"] { border-color:#FF0000; }
QPushButton      { background:#333333; color:#F1F1F1; border:none;
                   border-radius:10px; padding:5px 16px; min-height:28px; }
QPushButton:hover    { background:#5B5B5B; }
QPushButton:disabled { background:#1A1A1A; color:#9E9E9E; }
QPushButton#btn_confirm { background:#FE5C0D; color:#FFFFFF; font-weight:bold; }
QPushButton#btn_confirm:hover    { background:#FF7533; }
QPushButton#btn_confirm:disabled { background:#333333; color:#9E9E9E; }
QPushButton#btn_delete_confirm   { background:#FF0000; color:#FFFFFF; font-weight:bold; }
QPushButton#btn_delete_confirm:hover    { background:#F50000; }
QPushButton#btn_delete_confirm:disabled { background:#333333; color:#9E9E9E; }
QCheckBox        { color:#F1F1F1; spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #333333;
                        border-radius:10px; background:#2D2D2D; }
QCheckBox::indicator:checked { background:#FE5C0D; border-color:#FEAE0D; }
QTreeView        { background:#161616; color:#F1F1F1;
                   border:1px solid #333333; border-radius:10px; }
QTreeView::item:selected { background:#FE5C0D; color:#FFFFFF; }
QTreeView::item:hover    { background:#2D2D2D; }
"""

STYLE_TREE = """
QTreeView        { background:#161616; color:#F1F1F1; border:none;
                   outline:none; font-size:16px; padding: 5px;}
QTreeView::item  { padding:3px 4px; }
QTreeView::item:selected { background:#FE5C0D; color:#FFFFFF; }
QTreeView::item:hover    { background:#2D2D2D; color:#FFFFFF; }
QTreeView::branch { background:#161616; }
"""

STYLE_MENU = (
    "QMenu{background:#1A1A1A;color:#F1F1F1;"
    "border:1px solid #333333;border-radius:10px;}"
    "QMenu::item{padding:5px 20px 5px 12px;}"
    "QMenu::item:selected{background:#FE5C0D;color:#FFFFFF;}"
    "QMenu::separator{height:1px;background:#333333;margin:3px 0;}"
)
