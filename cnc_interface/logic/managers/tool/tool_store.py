# logic/managers/tool/tool_store.py
"""
ToolStore — читання/запис інструментів через SQLite.

Єдина таблиця tools у ~/LinuxCNC_PA/db/system.db.
Поле module визначає належність:
  • "global"        — глобальний каталог інструментів
  • "<project_name>" — інструменти конкретного проекту

При першому запуску таблиця заповнюється дефолтними
інструментами з DEFAULT_TOOLS (module = "global").
"""
from __future__ import annotations

import logging
import sqlite3
import uuid6
from contextlib import contextmanager
from typing import Generator

from .tool_constants import (
    DEFAULT_TOOLS, MODULE_GLOBAL, TOOL_DB, TOOL_DB_DIR,
)
from .tool_models import Tool, ToolDimensions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS tools (
    id        TEXT    PRIMARY KEY,
    tool_id   TEXT    NOT NULL,
    module    TEXT    NOT NULL DEFAULT 'global',
    name      TEXT    NOT NULL,
    type      TEXT    NOT NULL DEFAULT 'Gripper',
    pocket    INTEGER NOT NULL DEFAULT 0,
    status    TEXT    NOT NULL DEFAULT 'Ready',
    mass      REAL    NOT NULL DEFAULT 0.0,
    offset    REAL    NOT NULL DEFAULT 0.0,
    length_x  REAL    NOT NULL DEFAULT 0.0,
    width_y   REAL    NOT NULL DEFAULT 0.0,
    height_z  REAL    NOT NULL DEFAULT 0.0,
    UNIQUE (tool_id, module)
)
"""

# ---------------------------------------------------------------------------
# Внутрішні хелпери
# ---------------------------------------------------------------------------

@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(TOOL_DB))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_to_tool(row: sqlite3.Row) -> Tool:
    return Tool(
        id=       row["tool_id"],
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


def _tool_to_params(tool: Tool, module: str) -> tuple:
    return (
        str(uuid6.uuid7()),
        tool.id, module, tool.name, tool.type, tool.pocket, tool.status,
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
    # Ініціалізація
    # ------------------------------------------------------------------

    @staticmethod
    def init() -> None:
        """
        Створити таблицю tools у system.db.
        Якщо глобальних інструментів немає — заповнити DEFAULT_TOOLS.
        Викликати один раз при старті програми.
        """
        TOOL_DB_DIR.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.execute(_DDL)
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) FROM tools WHERE module = ?",
                (MODULE_GLOBAL,),
            ).fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT OR IGNORE INTO tools "
                    "(id,tool_id,module,name,type,pocket,status,mass,offset,"
                    " length_x,width_y,height_z) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (str(uuid6.uuid7()), d["id"], MODULE_GLOBAL,
                         d["name"], d["type"],
                         d["pocket"], d["status"], d["mass"], d["offset"],
                         d["length_x"], d["width_y"], d["height_z"])
                        for d in DEFAULT_TOOLS
                    ],
                )
                conn.commit()
                logger.info("tools: заповнено %d дефолтних глобальних інструментів",
                            len(DEFAULT_TOOLS))

    # ------------------------------------------------------------------
    # Глобальний каталог (module = "global")
    # ------------------------------------------------------------------

    @staticmethod
    def load_global() -> list[Tool]:
        """Завантажити всі глобальні інструменти."""
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tools WHERE module = ? ORDER BY tool_id",
                (MODULE_GLOBAL,),
            ).fetchall()
        return [_row_to_tool(r) for r in rows]

    # ------------------------------------------------------------------
    # Проектні інструменти (module = project_name)
    # ------------------------------------------------------------------

    @staticmethod
    def load_project(module: str) -> list[Tool]:
        """Завантажити інструменти проекту за назвою."""
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tools WHERE module = ? ORDER BY tool_id",
                (module,),
            ).fetchall()
        return [_row_to_tool(r) for r in rows]

    @staticmethod
    def add_tool(module: str, tool: Tool) -> bool:
        """Додати інструмент до проекту (якщо ID унікальний у межах module)."""
        try:
            with _connect() as conn:
                conn.execute(
                    "INSERT INTO tools "
                    "(id,tool_id,module,name,type,pocket,status,mass,offset,"
                    " length_x,width_y,height_z) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    _tool_to_params(tool, module),
                )
                conn.commit()
            logger.info("add_tool [%s]: %s", module, tool.id)
            return True
        except sqlite3.IntegrityError:
            logger.warning("add_tool [%s]: ID %s вже існує", module, tool.id)
            return False

    @staticmethod
    def update_tool(module: str, tool: Tool) -> bool:
        """Оновити існуючий інструмент за tool_id у межах module."""
        with _connect() as conn:
            cur = conn.execute(
                "UPDATE tools SET name=?,type=?,pocket=?,status=?,"
                "mass=?,offset=?,length_x=?,width_y=?,height_z=? "
                "WHERE tool_id=? AND module=?",
                (tool.name, tool.type, tool.pocket, tool.status,
                 tool.mass, tool.offset,
                 tool.dimensions.length_x,
                 tool.dimensions.width_y,
                 tool.dimensions.height_z,
                 tool.id, module),
            )
            conn.commit()
        if cur.rowcount == 0:
            logger.warning("update_tool [%s]: ID %s не знайдено", module, tool.id)
            return False
        return True

    @staticmethod
    def save_project(module: str, tools: list[Tool]) -> bool:
        """
        Повністю замінити всі інструменти проекту.
        Використовується при масових змінах (зміна статусів, COPY тощо).
        """
        try:
            with _connect() as conn:
                conn.execute(
                    "DELETE FROM tools WHERE module = ?", (module,))
                conn.executemany(
                    "INSERT INTO tools "
                    "(id,tool_id,module,name,type,pocket,status,mass,offset,"
                    " length_x,width_y,height_z) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [_tool_to_params(t, module) for t in tools],
                )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("save_project [%s]: %s", module, exc)
            return False

    @staticmethod
    def delete_tool(module: str, tool_id: str) -> bool:
        """Видалити інструмент за tool_id у межах module."""
        with _connect() as conn:
            cur = conn.execute(
                "DELETE FROM tools WHERE tool_id=? AND module=?",
                (tool_id, module),
            )
            conn.commit()
        if cur.rowcount == 0:
            logger.warning("delete_tool [%s]: ID %s не знайдено", module, tool_id)
            return False
        logger.info("delete_tool [%s]: %s", module, tool_id)
        return True

    @staticmethod
    def next_free_id(module: str) -> str:
        """Повернути наступний вільний ID у форматі T<N>."""
        tools = ToolStore.load_project(module)
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