# logic/managers/project/project_watcher.py
"""
FileWatcher і метадані проекту (config.ini).

Відповідальність:
  • Запуск/зупинка QFileSystemWatcher при відкритті/закритті проекту
  • Debounce оновлення last_modified (2 сек після останньої зміни)
  • Захист від циклу: запис config.ini → watcher → запис...
  • Читання/запис метаданих у config.ini
  • Заповнення і очищення UI-полів інформації про проект
"""
from __future__ import annotations
import configparser
import logging
from datetime import datetime
from pathlib import Path

from .project_constants import (
    CFG_AUTHOR, CFG_CREATED, CFG_DATE_FMT, CFG_MODIFIED,
    CFG_NAME, CFG_SECTION, DEFAULT_AUTHOR, WATCHER_IGNORE_DIRS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FileWatcher
# ---------------------------------------------------------------------------

def start_watcher(manager, project_path: Path) -> None:
    """
    Запустити QFileSystemWatcher для проекту.

    Два рівні:
      • Папки — зміна структури (додано/видалено/перейменовано)
      • Файли — зміна вмісту (auto-save, ручне збереження)

    Папки/файли з WATCHER_IGNORE_DIRS і config.ini виключаються.
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
        elif item.is_file() and item.name != "config.ini":
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
    """
    Директорія проекту змінилась.
    Ігноруємо: системні папки і події від власного _write_config.
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
        pass
    # Якщо таймер активний — подія від _write_config → ігноруємо
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
    if changed.suffix == ".tmp" or changed.name == "config.ini":
        return
    # Повторно реєструємо після атомарного запису (tmp → replace)
    if changed.exists() and str(changed) not in manager._watcher.files():
        manager._watcher.addPath(str(changed))
    if manager._modified_timer.isActive():
        return
    manager._modified_timer.start()


def flush_modified_update(manager) -> None:
    """
    Debounce callback — 2 сек після останньої зміни.
    Disconnect сигналів під час запису щоб уникнути циклу.
    """
    if manager._current_project is None:
        return
    manager._watcher.directoryChanged.disconnect(manager._on_project_dir_changed)
    manager._watcher.fileChanged.disconnect(manager._on_project_file_changed)
    try:
        write_config(manager._current_project, created=False)
        now = datetime.now().strftime(CFG_DATE_FMT)
        _set_widget_text(manager, "txt_last_modified", now)
        logger.debug("last_modified оновлено: %s", now)
    finally:
        manager._watcher.directoryChanged.connect(manager._on_project_dir_changed)
        manager._watcher.fileChanged.connect(manager._on_project_file_changed)


# ---------------------------------------------------------------------------
# config.ini — метадані проекту
# ---------------------------------------------------------------------------

def write_config(project_path: Path, created: bool = False) -> None:
    """
    Записати метадані у config.ini.
    created=True  → встановлює created і last_modified.
    created=False → оновлює лише last_modified.
    """
    cfg_path = project_path / "config.ini"
    cfg = configparser.ConfigParser()
    if cfg_path.exists():
        cfg.read(cfg_path, encoding="utf-8")
    if not cfg.has_section(CFG_SECTION):
        cfg.add_section(CFG_SECTION)

    now = datetime.now().strftime(CFG_DATE_FMT)
    cfg.set(CFG_SECTION, CFG_NAME,     project_path.name)
    cfg.set(CFG_SECTION, CFG_AUTHOR,   DEFAULT_AUTHOR)
    cfg.set(CFG_SECTION, CFG_MODIFIED, now)

    if created or not cfg.get(CFG_SECTION, CFG_CREATED, fallback=""):
        cfg.set(CFG_SECTION, CFG_CREATED, now)

    try:
        with open(cfg_path, "w", encoding="utf-8") as fh:
            cfg.write(fh)
    except OSError as exc:
        logger.error("config.ini запис: %s", exc)


def load_project_info(manager, project_path: Path) -> None:
    """
    Зчитати config.ini і заповнити UI-поля.
    Якщо секції немає — генерує config.ini автоматично.
    """
    cfg_path = project_path / "config.ini"
    cfg = configparser.ConfigParser()
    if cfg_path.exists():
        cfg.read(cfg_path, encoding="utf-8")
    if not cfg.has_section(CFG_SECTION):
        write_config(project_path, created=True)
        cfg.read(cfg_path, encoding="utf-8")

    get = lambda key: cfg.get(CFG_SECTION, key, fallback="")
    for widget_name, value in (
        ("txt_project_name",  get(CFG_NAME)),
        ("txt_author",        get(CFG_AUTHOR)),
        ("txt_created",       get(CFG_CREATED)),
        ("txt_last_modified", get(CFG_MODIFIED)),
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
