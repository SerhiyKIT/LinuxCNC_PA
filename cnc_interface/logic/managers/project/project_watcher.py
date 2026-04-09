# logic/managers/project/project_watcher.py
"""
FileWatcher і метадані проекту (таблиця projects у system.db).

Відповідальність:
  • Запуск/зупинка QFileSystemWatcher при відкритті/закритті проекту
  • Debounce оновлення last_modified (2 сек після останньої зміни)
  • CRUD метаданих проекту у таблиці projects (system.db)
  • Заповнення і очищення UI-полів інформації про проект
"""
from __future__ import annotations

import logging
import sqlite3
import uuid6
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from .project_constants import (
    CFG_DATE_FMT, DEFAULT_AUTHOR, PROJECT_DB, PROJECT_DB_DIR,
    WATCHER_IGNORE_DIRS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    author        TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL,
    last_modified TEXT NOT NULL
)
"""

# ---------------------------------------------------------------------------
# SQLite хелпери
# ---------------------------------------------------------------------------

@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(PROJECT_DB))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_projects_table() -> None:
    """Створити таблицю projects якщо не існує. Викликати при старті."""
    PROJECT_DB_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(_DDL_PROJECTS)
        conn.commit()


# ---------------------------------------------------------------------------
# CRUD метаданих проекту
# ---------------------------------------------------------------------------

def create_project_meta(project_name: str, author: str = "") -> None:
    """Створити запис метаданих для нового проекту."""
    now = datetime.now().strftime(CFG_DATE_FMT)
    author = author or DEFAULT_AUTHOR
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, author, created, last_modified) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid6.uuid7()), project_name, author, now, now),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        logger.debug("projects: '%s' вже існує, оновлюємо", project_name)
        update_last_modified(project_name)


def update_last_modified(project_name: str) -> None:
    """Оновити last_modified для проекту."""
    now = datetime.now().strftime(CFG_DATE_FMT)
    with _connect() as conn:
        conn.execute(
            "UPDATE projects SET last_modified = ? WHERE name = ?",
            (now, project_name),
        )
        conn.commit()


def get_project_meta(project_name: str) -> Optional[dict]:
    """
    Повернути метадані проекту як dict.
    Ключі: id, name, author, created, last_modified.
    None якщо проект не знайдено.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, author, created, last_modified "
            "FROM projects WHERE name = ?",
            (project_name,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id":            row["id"],
        "name":          row["name"],
        "author":        row["author"],
        "created":       row["created"],
        "last_modified": row["last_modified"],
    }


def get_project_id(project_name: str) -> Optional[str]:
    """Повернути uuid проекту за назвою. None якщо не знайдено."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE name = ?",
            (project_name,),
        ).fetchone()
    return row["id"] if row else None


def get_project_name_by_id(project_id: str) -> Optional[str]:
    """Повернути назву проекту за uuid. None якщо не знайдено."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT name FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    return row["name"] if row else None


def delete_project_meta(project_name: str) -> None:
    """Видалити інструменти проекту з таблиці tools, потім запис з projects."""
    with _connect() as conn:
        # Знайти id проекту
        row = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (project_name,)
        ).fetchone()
        if row is not None:
            project_id = row["id"]
            conn.execute(
                "DELETE FROM tools WHERE module = ?", (project_id,))
            logger.info("projects: видалено інструменти module='%s'", project_id)
        conn.execute("DELETE FROM projects WHERE name = ?", (project_name,))
        conn.commit()
    logger.info("projects: видалено метадані '%s'", project_name)


# ---------------------------------------------------------------------------
# FileWatcher
# ---------------------------------------------------------------------------

def start_watcher(manager, project_path: Path) -> None:
    """
    Запустити QFileSystemWatcher для проекту.

    Два рівні:
      • Папки — зміна структури (додано/видалено/перейменовано)
      • Файли — зміна вмісту (auto-save, ручне збереження)

    Папки/файли з WATCHER_IGNORE_DIRS виключаються.
    """
    stop_watcher(manager)

    dirs_to_watch:  list[str] = []
    files_to_watch: list[str] = []

    for item in project_path.rglob("*"):
        try:
            relative = item.relative_to(project_path)
        except ValueError:
            continue
        top_dir = relative.parts[0] if relative.parts else ""
        if top_dir in WATCHER_IGNORE_DIRS:
            continue
        if item.is_dir():
            dirs_to_watch.append(str(item))
        elif item.is_file():
            files_to_watch.append(str(item))

    dirs_to_watch.append(str(project_path))

    if dirs_to_watch:
        manager._watcher.addPaths(dirs_to_watch)
    if files_to_watch:
        manager._watcher.addPaths(files_to_watch)

    logger.debug("FileWatcher: %d папок, %d файлів",
                 len(dirs_to_watch), len(files_to_watch))


def stop_watcher(manager) -> None:
    """Зняти всі шляхи і зупинити debounce-таймер."""
    watched = manager._watcher.directories() + manager._watcher.files()
    if watched:
        manager._watcher.removePaths(watched)
    manager._modified_timer.stop()


def on_dir_changed(manager, path: str) -> None:
    """Директорія проекту змінилась."""
    if manager._current_project is None:
        return
    changed = Path(path)
    try:
        relative = changed.relative_to(manager._current_project)
        top_dir  = relative.parts[0] if relative.parts else ""
        if top_dir in WATCHER_IGNORE_DIRS:
            return
    except ValueError:
        pass
    if manager._modified_timer.isActive():
        return
    manager._modified_timer.start()


def on_file_changed(manager, path: str) -> None:
    """
    Файл змінився. Після атомарного збереження Qt знімає файл зі
    спостереження — повторно реєструємо.
    """
    if manager._current_project is None:
        return
    changed = Path(path)
    try:
        relative = changed.relative_to(manager._current_project)
        top_dir  = relative.parts[0] if relative.parts else ""
        if top_dir in WATCHER_IGNORE_DIRS:
            return
    except ValueError:
        return
    if changed.suffix == ".tmp":
        return
    # Повторно реєструємо після атомарного запису (tmp → replace)
    if changed.exists() and str(changed) not in manager._watcher.files():
        manager._watcher.addPath(str(changed))
    if manager._modified_timer.isActive():
        return
    manager._modified_timer.start()


def flush_modified_update(manager) -> None:
    """Debounce callback — 2 сек після останньої зміни."""
    if manager._current_project is None:
        return
    project_name = manager._current_project.name
    update_last_modified(project_name)
    now = datetime.now().strftime(CFG_DATE_FMT)
    _set_widget_text(manager, "txt_last_modified", now)
    logger.debug("last_modified оновлено: %s", now)


# ---------------------------------------------------------------------------
# UI — завантаження / очищення полів
# ---------------------------------------------------------------------------

def load_project_info(manager, project_path: Path) -> None:
    """
    Зчитати метадані з БД і заповнити UI-поля.
    Якщо запису немає — створити автоматично з поточним автором.
    """
    meta = get_project_meta(project_path.name)
    if meta is None:
        author = getattr(manager, "_current_author", "") or DEFAULT_AUTHOR
        create_project_meta(project_path.name, author)
        meta = get_project_meta(project_path.name)

    if meta is None:
        return

    for widget_name, value in (
        ("txt_project_name",  meta["name"]),
        ("txt_author",        meta["author"]),
        ("txt_created",       meta["created"]),
        ("txt_last_modified", meta["last_modified"]),
    ):
        _set_widget_text(manager, widget_name, value)


def clear_project_info(manager) -> None:
    """Очистити поля інформації — при скиданні до початкового стану."""
    for widget_name in ("txt_project_name", "txt_author",
                        "txt_created", "txt_last_modified"):
        _set_widget_text(manager, widget_name, "")


# ---------------------------------------------------------------------------
# Хелпер
# ---------------------------------------------------------------------------

def _set_widget_text(manager, widget_name: str, value: str) -> None:
    w = manager._w(widget_name)
    if w is None:
        return
    if hasattr(w, "setText"):
        w.setText(value)
    elif hasattr(w, "setPlainText"):
        w.setPlainText(value)