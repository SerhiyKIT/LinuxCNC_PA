# logic/managers/project_logger.py
"""
ProjectLogger – автономна система логування подій проекту у JSON формат.

Архітектура:
  • Повністю незалежний модуль — не змінює LoggerController і LoggerDisplayManager.
  • Записує події у [Project_Root]/logs/execution.json.
  • Асинхронний запис через окремий потік (queue + worker thread).
  • Автоматична ротація: тригер — розмір > 5 МБ або новий сеанс проекту.
  • Глибина архіву: 10 файлів (11-й → видалення найстарішого).

Підключення (HandlerClass.initialized__()):
    self.project_logger = ProjectLogger()
    self.project_manager.set_project_logger(self.project_logger)
    # Логування повідомлень з UI-панелі:
    self.project_logger.patch_logger_display(
        self.ui_manager.logger_display_manager
    )

Події що фіксуються автоматично:
  • Відкриття / закриття проекту
  • Всі повідомлення з logger_display (INFO / WARNING / ERROR)
  • Компіляція (виклик open_program)
  • Зміна координат (через patch або виклик log())
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------

_LOG_FILENAME   = "execution.json"
_MAX_SIZE_BYTES = 5 * 1024 * 1024
_MAX_ARCHIVES   = 10
_ARCHIVE_PREFIX = "execution_"
_ARCHIVE_SUFFIX = ".json"
# Київський час: UTC+3 (зимовий EET) / UTC+2 (літній EEST)
# Використовуємо фіксований UTC+3 — без залежності від tzdata/pytz
_TZ_KYIV = timezone(timedelta(hours=3))


# ---------------------------------------------------------------------------
# ProjectLogger
# ---------------------------------------------------------------------------

class ProjectLogger:
    """
    Система логування подій проекту у JSON формат з ротацією.

    Використання:
        pl = ProjectLogger()
        pl.set_project(Path("/home/user/ProjectLinuxCNC/MyProject"))
        pl.log("Project opened", "INFO")
        pl.close()
    """

    def __init__(self) -> None:
        self._project_path: Optional[Path] = None
        self._log_file:     Optional[Path] = None
        self._lock          = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._stop_event    = threading.Event()
        self._worker        = threading.Thread(
            target=self._writer_loop,
            name="ProjectLoggerWorker",
            daemon=True,           # завершується разом з процесом
        )
        self._worker.start()

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_project(self, project_path: Optional[Path]) -> None:
        """
        Встановити активний проект.
        Виконує ротацію «новий сеанс» — архівує поточний лог.
        """
        with self._lock:
            self._project_path = project_path
            self._log_file     = (
                project_path / "logs" / _LOG_FILENAME
                if project_path is not None else None
            )

        if project_path is None:
            return

        # Забезпечуємо існування папки logs
        log_dir = project_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # Ротація «новий сеанс» — архівуємо поточний лог
        self._rotate_on_new_session()

    def detach_project(self, project_name: str = "") -> None:
        """
        Від'єднати logger від проекту перед його видаленням з диска.
        Очікує завершення всіх записів у черзі, потім обнуляє _log_file.
        """
        if self._project_path is None:
            return

        # Чекаємо щоб усі записи з черги потрапили на диск
        self._queue.join()

        # Обнуляємо шлях — фоновий потік більше нічого не записує
        with self._lock:
            self._project_path = None
            self._log_file     = None

    def log(self, message: str, level: str = "INFO") -> None:
        """
        Поставити запис у чергу асинхронного запису.

        Args:
            message: Текстовий опис події (англійською).
            level:   "INFO" | "WARNING" | "ERROR"
        """
        if self._log_file is None:
            return

        now    = datetime.now(_TZ_KYIV)
        tz_str = now.strftime("%z")               # +0300
        tz_iso = tz_str[:-2] + ":" + tz_str[-2:] # +03:00
        entry = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + tz_iso,
            "level":   level.upper(),
            "message": message,
        }
        # Неблокуюче додавання у чергу
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            pass   # ніколи не блокуємо UI потік

    def close(self) -> None:
        """
        Коректно завершити роботу logger-а.
        Дочекатися запису всіх повідомлень із черги.
        """
        self.log("Logger shutdown", "INFO")
        self._queue.join()
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Патч LoggerDisplayManager
    # ------------------------------------------------------------------

    def log_system_message(self, message: str, level: str = "INFO") -> None:
        """
        Записати системне повідомлення LinuxCNC у лог проекту.

        Викликається виключно з HandlerClass.check_system_messages()
        — лише повідомлення що прийшли через cnc.poll_errors().
        """
        self.log(message, level.upper())

    # ------------------------------------------------------------------
    # Внутрішній потік запису
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """
        Фоновий потік що читає чергу і записує записи на диск.
        Запускається один раз при ініціалізації.
        """
        while not self._stop_event.is_set():
            try:
                entry = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._write_entry(entry)
            except Exception as exc:
                logger.error("ProjectLogger write error: %s", exc)
            finally:
                self._queue.task_done()

    def _write_entry(self, entry: dict) -> None:
        """
        Записати один запис у JSON файл.

        Формат файлу — JSON масив що зростає (append-режим):
          [
            { "timestamp": "...", "level": "...", "message": "..." },
            ...
          ]

        Перевіряє розмір файлу після запису — якщо > 5 МБ, запускає ротацію.
        """
        with self._lock:
            log_file = self._log_file

        if log_file is None:
            return

        # Переконуємося що папка існує
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Читаємо існуючий масив або починаємо новий
        entries: list[dict] = []
        if log_file.exists() and log_file.stat().st_size > 0:
            try:
                with open(log_file, "r", encoding="utf-8") as fh:
                    entries = json.load(fh)
                if not isinstance(entries, list):
                    entries = []
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(entry)

        # Атомарний запис: спочатку у тимчасовий файл, потім replace
        tmp_file = log_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, ensure_ascii=False, indent=2)
            tmp_file.replace(log_file)
        except OSError as exc:
            logger.error("ProjectLogger atomic write failed: %s", exc)
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)
            return

        # Перевірка ротації за розміром
        try:
            if log_file.stat().st_size > _MAX_SIZE_BYTES:
                self._rotate_by_size(log_file)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Ротація
    # ------------------------------------------------------------------

    def _rotate_on_new_session(self) -> None:
        """
        Ротація при відкритті нового сеансу проекту.
        Архівує поточний execution.json якщо він не порожній.
        """
        with self._lock:
            log_file = self._log_file

        if log_file is None or not log_file.exists():
            return
        if log_file.stat().st_size == 0:
            return

        self._archive(log_file)

    def _rotate_by_size(self, log_file: Path) -> None:
        """
        Ротація за розміром: архівує поточний файл коли > 5 МБ.
        """
        self._archive(log_file)

    def _archive(self, log_file: Path) -> None:
        """
        Архівувати поточний log_file:
          1. Перейменувати у execution_YYYYMMDD_HHMMSS.json
          2. Якщо архівів > 10 — видалити найстаріший за датою створення
        """
        if not log_file.exists():
            return

        log_dir   = log_file.parent
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive   = log_dir / f"{_ARCHIVE_PREFIX}{timestamp}{_ARCHIVE_SUFFIX}"

        try:
            shutil.move(str(log_file), str(archive))
            logger.debug("ProjectLogger: archived → %s", archive.name)
        except OSError as exc:
            logger.error("ProjectLogger archive error: %s", exc)
            return

        # Прибираємо надлишкові архіви
        self._cleanup_archives(log_dir)

    def _cleanup_archives(self, log_dir: Path) -> None:
        """
        Видалити найстаріші архіви якщо їх більше _MAX_ARCHIVES.
        Сортуємо за датою модифікації (найстаріші — перші).
        """
        archives = sorted(
            log_dir.glob(f"{_ARCHIVE_PREFIX}*{_ARCHIVE_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
        )
        while len(archives) > _MAX_ARCHIVES:
            oldest = archives.pop(0)
            try:
                oldest.unlink()
                logger.debug("ProjectLogger: removed old archive %s", oldest.name)
            except OSError as exc:
                logger.error("ProjectLogger cleanup error: %s", exc)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(project={self._project_path!r})"
        )