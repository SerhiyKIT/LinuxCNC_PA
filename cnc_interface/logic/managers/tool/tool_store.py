# logic/managers/tool/tool_store.py
"""
ToolStore — читання/запис JSON-файлів інструментів.

Два рівні зберігання:
  • Глобальний  ~/LinuxCNC_PA/tool.json         — каталог всіх інструментів
  • Проектний   ~/ProjectLinuxCNC/<name>/tool/tools.json — інструменти проекту
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from .tool_constants import (
    GLOBAL_TOOL_FILE, PROJECT_TOOL_DIR, PROJECT_TOOL_FILE,
)
from .tool_models import Tool

logger = logging.getLogger(__name__)


class ToolStore:
    """Статичні методи читання та запису Tool-об'єктів."""

    # ------------------------------------------------------------------
    # Глобальний каталог
    # ------------------------------------------------------------------

    @staticmethod
    def load_global() -> list[Tool]:
        """Завантажити всі інструменти з глобального файлу."""
        return ToolStore._read(GLOBAL_TOOL_FILE)

    # ------------------------------------------------------------------
    # Проектний файл
    # ------------------------------------------------------------------

    @staticmethod
    def project_file(project_path: Path) -> Path:
        return project_path / PROJECT_TOOL_DIR / PROJECT_TOOL_FILE

    @staticmethod
    def load_project(project_path: Path) -> list[Tool]:
        """Завантажити інструменти проекту. Повертає [] якщо файл відсутній."""
        path = ToolStore.project_file(project_path)
        if not path.exists():
            return []
        return ToolStore._read(path)

    @staticmethod
    def save_project(project_path: Path, tools: list[Tool]) -> bool:
        """Зберегти список інструментів у файл проекту."""
        path = ToolStore.project_file(project_path)
        return ToolStore._write(path, tools)

    @staticmethod
    def add_tool(project_path: Path, tool: Tool) -> bool:
        """Додати інструмент до проекту (якщо ID унікальний)."""
        tools = ToolStore.load_project(project_path)
        if any(t.id == tool.id for t in tools):
            logger.warning("add_tool: ID %s вже існує", tool.id)
            return False
        tools.append(tool)
        return ToolStore.save_project(project_path, tools)

    @staticmethod
    def update_tool(project_path: Path, tool: Tool) -> bool:
        """Оновити існуючий інструмент за ID."""
        tools = ToolStore.load_project(project_path)
        for i, t in enumerate(tools):
            if t.id == tool.id:
                tools[i] = tool
                return ToolStore.save_project(project_path, tools)
        logger.warning("update_tool: ID %s не знайдено", tool.id)
        return False

    @staticmethod
    def delete_tool(project_path: Path, tool_id: str) -> bool:
        """Видалити інструмент за ID."""
        tools = ToolStore.load_project(project_path)
        new   = [t for t in tools if t.id != tool_id]
        if len(new) == len(tools):
            logger.warning("delete_tool: ID %s не знайдено", tool_id)
            return False
        return ToolStore.save_project(project_path, new)

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

    # ------------------------------------------------------------------
    # Внутрішні хелпери
    # ------------------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> list[Tool]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                logger.warning("_read: очікується список, файл: %s", path)
                return []
            return [Tool.from_dict(d) for d in data]
        except json.JSONDecodeError as exc:
            logger.error("_read JSON: %s — %s", path, exc)
            return []
        except OSError as exc:
            logger.error("_read OS: %s — %s", path, exc)
            return []

    @staticmethod
    def _write(path: Path, tools: list[Tool]) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps([t.to_dict() for t in tools],
                           indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except OSError as exc:
            logger.error("_write: %s — %s", path, exc)
            return False
