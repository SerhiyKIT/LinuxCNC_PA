# logic/managers/tool/tool_store.py
"""
ToolStore — читання/запис інструментів через SQLite.

Два рівні зберігання:
  • Глобальний  ~/LinuxCNC_PA/db/users.db        — таблиця global_tools
  • Проектний   ~/ProjectLinuxCNC/<n>/tool/tools.db — таблиця tools

При першому запуску глобальна таблиця заповнюється дефолтними
інструментами з DEFAULT_TOOLS (еквівалент tool.json).

Публічний API не змінився — tool_panel.py і tool_dialogs.py
не потребують жодних правок.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from .tool_constants import (
    DEFAULT_TOOLS, GLOBAL_TOOL_DB, GLOBAL_TOOL_DIR,
    PROJECT_TOOL_DIR, PROJECT_TOOL_DB,
)
from .tool_models import Tool, ToolDimensions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    id        TEXT    PRIMARY KEY,
    name      TEXT    NOT NULL,
    type      TEXT    NOT NULL DEFAULT 'Gripper',
    pocket    INTEGER NOT NULL DEFAULT 0,
    status    TEXT    NOT NULL DEFAULT 'Ready',
    mass      REAL    NOT NULL DEFAULT 0.0,
    offset    REAL    NOT NULL DEFAULT 0.0,
    length_x  REAL    NOT NULL DEFAULT 0.0,
    width_y   REAL    NOT NULL DEFAULT 0.0,
    height_z  REAL    NOT NULL DEFAULT 0.0
)
"""

# ---------------------------------------------------------------------------
# Внутрішні хелпери
# ---------------------------------------------------------------------------

@contextmanager
def _connect(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure_table(db_path: Path, table: str) -> None:
    """Створити таблицю якщо не існує."""
    with _connect(db_path) as conn:
        conn.execute(_DDL.format(table=table))
        conn.commit()


def _row_to_tool(row: sqlite3.Row) -> Tool:
    return Tool(
        id=       row["id"],
        name=     row["name"],
        type=     row["type"],
        pocket=   int(row["pocket"]),
        status=   row["status"],
        mass=     float(row["mass"]),
        offset=   float(row["offset"]),
        dimensions=ToolDimensions(
            length_x=float(row["length_x"]),
            width_y= float(row["width_y"]),
            height_z=float(row["height_z"]),
        ),
    )


def _tool_to_params(tool: Tool) -> tuple:
    return (
        tool.id, tool.name, tool.type, tool.pocket, tool.status,
        tool.mass, tool.offset,
        tool.dimensions.length_x,
        tool.dimensions.width_y,
        tool.dimensions.height_z,
    )


# ---------------------------------------------------------------------------
# ToolStore
# ---------------------------------------------------------------------------

class ToolStore:
    """Статичні методи читання та запису Tool-об'єктів через SQLite."""

    # ------------------------------------------------------------------
    # Ініціалізація глобальної БД
    # ------------------------------------------------------------------

    @staticmethod
    def init_global() -> None:
        """
        Створити таблицю global_tools у спільній БД (users.db).
        Якщо таблиця порожня — заповнити DEFAULT_TOOLS.
        Викликати один раз при старті програми.
        """
        GLOBAL_TOOL_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_table(GLOBAL_TOOL_DB, "global_tools")

        with _connect(GLOBAL_TOOL_DB) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM global_tools").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT OR IGNORE INTO global_tools "
                    "(id,name,type,pocket,status,mass,offset,"
                    " length_x,width_y,height_z) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [
                        (d["id"], d["name"], d["type"], d["pocket"],
                         d["status"], d["mass"], d["offset"],
                         d["length_x"], d["width_y"], d["height_z"])
                        for d in DEFAULT_TOOLS
                    ],
                )
                conn.commit()
                logger.info("global_tools: заповнено %d дефолтних інструментів",
                            len(DEFAULT_TOOLS))

    # ------------------------------------------------------------------
    # Глобальний каталог
    # ------------------------------------------------------------------

    @staticmethod
    def load_global() -> list[Tool]:
        """Завантажити всі інструменти з глобальної таблиці."""
        _ensure_table(GLOBAL_TOOL_DB, "global_tools")
        with _connect(GLOBAL_TOOL_DB) as conn:
            rows = conn.execute(
                "SELECT * FROM global_tools ORDER BY id").fetchall()
        return [_row_to_tool(r) for r in rows]

    # ------------------------------------------------------------------
    # Проектна БД
    # ------------------------------------------------------------------

    @staticmethod
    def _project_db(project_path: Path) -> Path:
        return project_path / PROJECT_TOOL_DIR / PROJECT_TOOL_DB

    @staticmethod
    def _ensure_project_db(project_path: Path) -> Path:
        """Створити БД і таблицю проекту якщо не існують."""
        db = ToolStore._project_db(project_path)
        _ensure_table(db, "tools")
        return db

    @staticmethod
    def load_project(project_path: Path) -> list[Tool]:
        """Завантажити інструменти проекту. Повертає [] якщо БД відсутня."""
        db = ToolStore._project_db(project_path)
        if not db.exists():
            return []
        _ensure_table(db, "tools")
        with _connect(db) as conn:
            rows = conn.execute(
                "SELECT * FROM tools ORDER BY id").fetchall()
        return [_row_to_tool(r) for r in rows]

    @staticmethod
    def add_tool(project_path: Path, tool: Tool) -> bool:
        """Додати інструмент до проекту (якщо ID унікальний)."""
        db = ToolStore._ensure_project_db(project_path)
        try:
            with _connect(db) as conn:
                conn.execute(
                    "INSERT INTO tools "
                    "(id,name,type,pocket,status,mass,offset,"
                    " length_x,width_y,height_z) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    _tool_to_params(tool),
                )
                conn.commit()
            logger.info("add_tool: %s", tool.id)
            return True
        except sqlite3.IntegrityError:
            logger.warning("add_tool: ID %s вже існує", tool.id)
            return False

    @staticmethod
    def update_tool(project_path: Path, tool: Tool) -> bool:
        """Оновити існуючий інструмент за ID."""
        db = ToolStore._ensure_project_db(project_path)
        with _connect(db) as conn:
            cur = conn.execute(
                "UPDATE tools SET name=?,type=?,pocket=?,status=?,"
                "mass=?,offset=?,length_x=?,width_y=?,height_z=? "
                "WHERE id=?",
                (tool.name, tool.type, tool.pocket, tool.status,
                 tool.mass, tool.offset,
                 tool.dimensions.length_x,
                 tool.dimensions.width_y,
                 tool.dimensions.height_z,
                 tool.id),
            )
            conn.commit()
        if cur.rowcount == 0:
            logger.warning("update_tool: ID %s не знайдено", tool.id)
            return False
        return True

    @staticmethod
    def save_project(project_path: Path, tools: list[Tool]) -> bool:
        """
        Повністю замінити всі інструменти проекту.
        Використовується при масових змінах (зміна статусів, COPY тощо).
        """
        db = ToolStore._ensure_project_db(project_path)
        try:
            with _connect(db) as conn:
                conn.execute("DELETE FROM tools")
                conn.executemany(
                    "INSERT INTO tools "
                    "(id,name,type,pocket,status,mass,offset,"
                    " length_x,width_y,height_z) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [_tool_to_params(t) for t in tools],
                )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("save_project: %s", exc)
            return False

    @staticmethod
    def delete_tool(project_path: Path, tool_id: str) -> bool:
        """Видалити інструмент за ID."""
        db = ToolStore._ensure_project_db(project_path)
        with _connect(db) as conn:
            cur = conn.execute(
                "DELETE FROM tools WHERE id=?", (tool_id,))
            conn.commit()
        if cur.rowcount == 0:
            logger.warning("delete_tool: ID %s не знайдено", tool_id)
            return False
        logger.info("delete_tool: %s", tool_id)
        return True

    @staticmethod
    def next_free_id(project_path: Path) -> str:
        """Повернути наступний вільний ID у форматі T<N>."""
        tools = ToolStore.load_project(project_path)
        used: set[int] = set()
        for t in tools:
            if t.id.upper().startswith("T"):
                try:
                    used.add(int(t.id[1:]))
                except ValueError:
                    pass
        n = 1
        while n in used:
            n += 1
        return f"T{n}"