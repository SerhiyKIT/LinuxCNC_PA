# logic/managers/project_logger.py
"""
ProjectLogger – автономна система логування подій проекту у JSON формат.

Ротація ЛИШЕ за розміром > 5 МБ — НЕ при кожному відкритті проекту.
on_new_entry callback — миттєве сповіщення LoggerDisplayManager без таймера.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_LOG_FILENAME    = "execution.json"
_MAX_SIZE_BYTES  = 5 * 1024 * 1024
_MAX_ARCHIVES    = 10
_ARCHIVE_PREFIX  = "execution_"
_ARCHIVE_SUFFIX  = ".json"
_GLOBAL_LOG_DIR  = Path.home() / "LinuxCNC_PA"
_GLOBAL_LOG_FILE = _GLOBAL_LOG_DIR / "system_log.json"
_MODULE_SYSTEM   = "system"
_TZ_KYIV         = timezone(timedelta(hours=3))


class ProjectLogger:
    """
    Два рівні запису:
      • Проектний: [Project_Root]/logs/execution.json
      • Глобальний: ~/LinuxCNC_PA/system_log.json (завжди, без ротації)

    Ротація — лише за розміром > 5 МБ, не при відкритті проекту.
    on_new_entry callback — миттєве сповіщення після кожного запису.
    """

    def __init__(self) -> None:
        self._project_path: Optional[Path]             = None
        self._log_file:     Optional[Path]             = None
        self._lock          = threading.Lock()
        self._queue: queue.Queue                       = queue.Queue()
        self._stop_event    = threading.Event()
        self._on_new_entry: Optional[Callable[[dict], None]] = None

        self._worker = threading.Thread(
            target=self._writer_loop,
            name="ProjectLoggerWorker",
            daemon=True,
        )
        self._worker.start()
        _GLOBAL_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_project(self, project_path: Optional[Path]) -> None:
        """
        Встановити активний проект. НЕ архівує при відкритті.
        Ротація відбувається лише коли файл перевищує 5 МБ.
        """
        with self._lock:
            self._project_path = project_path
            self._log_file = (
                project_path / "logs" / _LOG_FILENAME
                if project_path is not None else None
            )
        if project_path is not None:
            (project_path / "logs").mkdir(parents=True, exist_ok=True)

    def detach_project(self, project_name: str = "") -> None:
        """Flush черги і від'єднати від проекту перед видаленням."""
        if self._project_path is None:
            return
        self._queue.join()
        with self._lock:
            self._project_path = None
            self._log_file     = None

    def set_on_new_entry(self, callback: Optional[Callable[[dict], None]]) -> None:
        """
        Підписатися на нові записи для миттєвого оновлення history.
        callback(entry) викликається у фоновому потоці після запису на диск.
        Qt-виклики всередині callback мають йти через QMetaObject.invokeMethod.
        """
        with self._lock:
            self._on_new_entry = callback

    def log(self, message: str, level: str = "INFO") -> None:
        """Поставити запис у чергу. Не блокує UI потік."""
        now    = datetime.now(_TZ_KYIV)
        tz_str = now.strftime("%z")
        tz_iso = tz_str[:-2] + ":" + tz_str[-2:]

        with self._lock:
            project_path = self._project_path
            log_file     = self._log_file

        entry = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + tz_iso,
            "level":     level.upper(),
            "module":    project_path.name if project_path else _MODULE_SYSTEM,
            "message":   message,
        }
        try:
            self._queue.put_nowait((entry, log_file))
        except queue.Full:
            pass

    def log_system_message(self, message: str, level: str = "INFO") -> None:
        """Записати системне повідомлення LinuxCNC. Пише завжди."""
        self.log(message, level.upper())

    def close(self) -> None:
        """Flush і зупинити потік."""
        self._queue.join()
        self._stop_event.set()

    def read_project_log(self, project_path: Path) -> list[dict]:
        """
        Зчитати всі записи з диска для history.
        Порядок: архіви за назвою (хронологічно) → поточний файл.
        """
        log_dir = project_path / "logs"
        if not log_dir.exists():
            return []
        entries: list[dict] = []
        for f in sorted(log_dir.glob(f"{_ARCHIVE_PREFIX}*{_ARCHIVE_SUFFIX}")):
            entries.extend(self._read_json(f))
        current = log_dir / _LOG_FILENAME
        if current.exists():
            entries.extend(self._read_json(current))
        return entries

    # ------------------------------------------------------------------
    # Фоновий потік
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                entry, project_log_file = item
                self._append_to_file(_GLOBAL_LOG_FILE, entry)
                if project_log_file is not None:
                    self._append_to_file(project_log_file, entry)
                    try:
                        if project_log_file.stat().st_size > _MAX_SIZE_BYTES:
                            self._archive(project_log_file)
                    except OSError:
                        pass
                with self._lock:
                    cb = self._on_new_entry
                if cb is not None:
                    try:
                        cb(entry)
                    except Exception:
                        pass
            except Exception as exc:
                logger.error("ProjectLogger write error: %s", exc)
            finally:
                self._queue.task_done()

    def _append_to_file(self, log_file: Path, entry: dict) -> None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        entries: list[dict] = []
        if log_file.exists() and log_file.stat().st_size > 0:
            try:
                with open(log_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                entries = []
        entries.append(entry)
        tmp = log_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, ensure_ascii=False, indent=2)
            tmp.replace(log_file)
        except OSError as exc:
            logger.error("write [%s]: %s", log_file.name, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _archive(self, log_file: Path) -> None:
        if not log_file.exists():
            return
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive = log_file.parent / f"{_ARCHIVE_PREFIX}{ts}{_ARCHIVE_SUFFIX}"
        try:
            shutil.move(str(log_file), str(archive))
        except OSError as exc:
            logger.error("archive: %s", exc)
            return
        archives = sorted(
            log_file.parent.glob(f"{_ARCHIVE_PREFIX}*{_ARCHIVE_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
        )
        while len(archives) > _MAX_ARCHIVES:
            try:
                archives.pop(0).unlink()
            except OSError:
                pass

    @staticmethod
    def _read_json(path: Path) -> list[dict]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(project={self._project_path!r})"