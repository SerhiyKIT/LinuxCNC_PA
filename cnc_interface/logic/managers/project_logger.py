# logic/managers/project_logger.py
"""
ProjectLogger – система логування подій у SQLite.

Всі записи зберігаються в єдиній таблиці system_log у ~/LinuxCNC_PA/db/system.db.
Поле module містить назву проекту або "system" для системних повідомлень.
Для отримання логів конкретного проекту використовується фільтрація по module.

on_new_entry callback — миттєве сповіщення LoggerDisplayManager без таймера.
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import uuid6
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Generator, Optional

logger = logging.getLogger(__name__)

_GLOBAL_DB_DIR  = Path.home() / "LinuxCNC_PA" / "db"
_GLOBAL_DB_FILE = _GLOBAL_DB_DIR / "system.db"
_MODULE_SYSTEM  = "system"
_TZ_KYIV        = timezone(timedelta(hours=3))

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_SYSTEM_LOG = """
CREATE TABLE IF NOT EXISTS system_log (
    id        TEXT    PRIMARY KEY,
    seq       INTEGER NOT NULL,
    timestamp TEXT    NOT NULL,
    level     TEXT    NOT NULL,
    module    TEXT    NOT NULL,
    message   TEXT    NOT NULL
)
"""


class ProjectLogger:
    """
    Єдине сховище логів — таблиця system_log у system.db.

    Поле module:
      • назва проекту (project_path.name) — для проектних записів
      • "system" — для системних повідомлень LinuxCNC

    Читання:
      • read_project_log(module)   — записи конкретного проекту
      • read_global_log()          — усі записи (або з фільтром)

    on_new_entry callback — миттєве сповіщення після кожного запису.
    """

    def __init__(self) -> None:
        self._project_name: Optional[str]                    = None
        self._lock          = threading.Lock()
        self._queue: queue.Queue                             = queue.Queue()
        self._stop_event    = threading.Event()
        self._on_new_entry: Optional[Callable[[dict], None]] = None

        self._worker = threading.Thread(
            target=self._writer_loop,
            name="ProjectLoggerWorker",
            daemon=True,
        )
        self._worker.start()
        self._init_db()

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_project(self, project_id: Optional[str]) -> None:
        """Встановити активний проект (module = project_id з таблиці projects)."""
        with self._lock:
            self._project_name = project_id

    def detach_project(self, project_name: str = "") -> None:
        """Flush черги і від'єднати від проекту."""
        if self._project_name is None:
            return
        self._queue.join()
        with self._lock:
            self._project_name = None

    def set_on_new_entry(self, callback: Optional[Callable[[dict], None]]) -> None:
        """
        Підписатися на нові записи для миттєвого оновлення history.
        callback(entry) викликається у фоновому потоці після запису в БД.
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
            module = self._project_name or _MODULE_SYSTEM

        entry = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + tz_iso,
            "level":     level.upper(),
            "module":    module,
            "message":   message,
        }
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            pass

    def log_system_message(self, message: str, level: str = "INFO") -> None:
        """Записати системне повідомлення LinuxCNC. Пише завжди."""
        self.log(message, level.upper())

    def close(self) -> None:
        """Flush і зупинити потік."""
        self._queue.join()
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Читання логів
    # ------------------------------------------------------------------

    @staticmethod
    def read_project_log(module: str,
                         limit: int = 500, offset: int = 0) -> list[dict]:
        """
        Зчитати записи конкретного проекту (WHERE module = ?).
        Повертає список dict у хронологічному порядку.
        """
        try:
            with ProjectLogger._connect_db() as conn:
                rows = conn.execute(
                    "SELECT timestamp, level, module, message "
                    "FROM system_log WHERE module = ? "
                    "ORDER BY seq DESC LIMIT ? OFFSET ?",
                    (module, limit, offset),
                ).fetchall()
            return [
                {"timestamp": r["timestamp"], "level": r["level"],
                 "module": r["module"], "message": r["message"]}
                for r in reversed(rows)
            ]
        except Exception as exc:
            logger.error("read_project_log: %s", exc)
            return []

    @staticmethod
    def read_global_log(limit: int = 500, offset: int = 0) -> list[dict]:
        """
        Зчитати всі записи з таблиці system_log.
        Повертає список dict у хронологічному порядку.
        """
        try:
            with ProjectLogger._connect_db() as conn:
                rows = conn.execute(
                    "SELECT timestamp, level, module, message "
                    "FROM system_log ORDER BY seq DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [
                {"timestamp": r["timestamp"], "level": r["level"],
                 "module": r["module"], "message": r["message"]}
                for r in reversed(rows)
            ]
        except Exception as exc:
            logger.error("read_global_log: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Фоновий потік
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                entry = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._insert(entry)
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

    # ------------------------------------------------------------------
    # SQLite
    # ------------------------------------------------------------------

    @staticmethod
    @contextmanager
    def _connect_db() -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(_GLOBAL_DB_FILE))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _init_db() -> None:
        """Створити таблицю system_log якщо не існує."""
        _GLOBAL_DB_DIR.mkdir(parents=True, exist_ok=True)
        with ProjectLogger._connect_db() as conn:
            conn.execute(_DDL_SYSTEM_LOG)
            conn.commit()

    @staticmethod
    def _insert(entry: dict) -> None:
        """Вставити запис у таблицю system_log."""
        try:
            with ProjectLogger._connect_db() as conn:
                seq = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM system_log"
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO system_log (id, seq, timestamp, level, module, message) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid6.uuid7()), seq, entry["timestamp"],
                     entry["level"], entry["module"], entry["message"]),
                )
                conn.commit()
        except Exception as exc:
            logger.error("system_log insert: %s", exc)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(module={self._project_name!r})"