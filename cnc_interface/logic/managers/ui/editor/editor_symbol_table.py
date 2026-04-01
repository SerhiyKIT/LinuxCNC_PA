# logic/managers/ui/editor/editor_symbol_table.py
"""
SymbolTable – таблиця символів проекту для автодоповнення.

Джерела символів:
  • data/variables.json  — змінні проекту  { "name": value, ... }
  • data/io_config.json  — I/O піни        { "DO": {"1": "label"}, "DI": {...} }
  • src/*.txt / *.parl   — DEF підпрограми (скануються регекспом)

Оновлення:
  set_project(path)   — при відкритті проекту (повне перезавантаження)
  refresh_file(path)  — при auto-save (оновлює лише підпрограми з файлу)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_RE_SUBROUTINE = re.compile(
    r'^\s*DEF\s+([A-Za-z_]\w*)\s*\(', re.MULTILINE | re.IGNORECASE
)

# Повний список ключових слів мови
LANGUAGE_KEYWORDS: tuple[str, ...] = (
    "PTP", "LIN", "CIRC",
    "VEL", "ACC", "TOOL", "BASE", "CONT",
    "ORI_TYPE", "ORI_VAR", "ORI_CONST",
    "CIRC_TYPE", "CIRC_PATH", "CIRC_BASE",
    "WAIT", "PAUSE", "STOP", "OFFSET",
    "SET_DO", "GET_DI", "WAIT_DI",
    "IF", "ELSEIF", "ELSE", "ENDIF",
    "WHILE", "ENDWHILE",
    "FOR", "TO", "ENDFOR",
    "REPEAT", "ENDREPEAT",
    "DEF", "CALL", "RETURN",
    "TRUE", "FALSE",
)


class SymbolTable:
    """Зберігає символи проекту і надає контекстно-залежні підказки."""

    def __init__(self) -> None:
        self._project_path: Path | None = None
        self._variables:   list[str] = []
        self._do_pins:     list[str] = []
        self._di_pins:     list[str] = []
        self._file_subroutines: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Завантаження
    # ------------------------------------------------------------------

    def set_project(self, project_path: Path | None) -> None:
        """Завантажити всі символи при відкритті проекту."""
        self._project_path = project_path
        self._variables.clear()
        self._do_pins.clear()
        self._di_pins.clear()
        self._file_subroutines.clear()

        if project_path is None:
            return

        self._load_variables(project_path)
        self._load_io_config(project_path)
        self._scan_subroutines(project_path)

        logger.debug(
            "SymbolTable: %d змінних, %d підпрограм, %d DO, %d DI",
            len(self._variables), len(self._subroutines),
            len(self._do_pins),   len(self._di_pins),
        )

    def refresh_file(self, filepath: str) -> None:
        """
        Повністю замінити підпрограми з конкретного файлу після auto-save.
        Ігнорує файли що не належать до поточного проекту.
        """
        if self._project_path is None:
            return
        path = Path(filepath).resolve()
        # Перевіряємо що файл належить до поточного проекту
        try:
            path.relative_to(self._project_path.resolve())
        except ValueError:
            return  # файл з іншого проекту — ігноруємо

        if not path.is_file() or path.suffix not in (".txt", ".parl"):
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        self._file_subroutines[str(path)] = _RE_SUBROUTINE.findall(text)

    # ------------------------------------------------------------------
    # Публічний API для completer
    # ------------------------------------------------------------------

    def get_completions(self, context: str, prefix: str) -> list[str]:
        """
        Повернути список підказок для поточного контексту і префіксу.

        context — ключове слово перед курсором (SET_DO, CALL, IF...)
        prefix  — вже надрукований префікс (фільтр)
        """
        candidates = self._by_context(context)
        pfx = prefix.lower()
        return [c for c in candidates if c.lower().startswith(pfx)]

    # ------------------------------------------------------------------
    # Завантажувачі
    # ------------------------------------------------------------------

    def _load_variables(self, project_path: Path) -> None:
        """
        Зчитати змінні з data/variables.json.

        Підтримувані формати значень:
          "speed_slow": 30.0          → "speed_slow"
          "home": {"x": 0.0, ...}     → "home", "home.x", "home.y", "home.z"
        """
        path = project_path / "data" / "variables.json"
        if not path.exists():
            logger.debug("variables.json не знайдено: %s", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("variables.json — помилка парсингу: %s", exc)
            return
        except OSError as exc:
            logger.warning("variables.json — помилка читання: %s", exc)
            return

        for key, value in data.items():
            self._variables.append(str(key))
            # Розгортаємо вкладені об'єкти: home.x, home.y, home.z
            if isinstance(value, dict):
                for sub_key in value:
                    self._variables.append(f"{key}.{sub_key}")

    def _load_io_config(self, project_path: Path) -> None:
        """
        Зчитати I/O піни з data/io_config.json.

        Формат:
          { "DO": {"1": "gripper_open"}, "DI": {"1": "sensor_home"} }
        """
        path = project_path / "data" / "io_config.json"
        if not path.exists():
            logger.debug("io_config.json не знайдено: %s", path)
            return
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("io_config.json — помилка парсингу (trailing comma?): %s", exc)
            return
        except OSError as exc:
            logger.warning("io_config.json — помилка читання: %s", exc)
            return

        for pin_id, label in cfg.get("DO", {}).items():
            self._do_pins.append(
                f"{pin_id} ({label})" if label else str(pin_id))
        for pin_id, label in cfg.get("DI", {}).items():
            self._di_pins.append(
                f"{pin_id} ({label})" if label else str(pin_id))

    def _scan_subroutines(self, project_path: Path) -> None:
        src = project_path / "src"
        scan_root = src if src.exists() else project_path
        for p in scan_root.rglob("*"):
            if p.suffix in (".txt", ".parl") and p.is_file():
                try:
                    text = p.read_text(encoding="utf-8")
                    names = _RE_SUBROUTINE.findall(text)
                    if names:
                        # resolve() — той самий ключ що і в refresh_file()
                        self._file_subroutines[str(p.resolve())] = names
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Агрегований список підпрограм з усіх файлів
    # ------------------------------------------------------------------

    @property
    def _subroutines(self) -> list[str]:
        """Унікальні підпрограми з усіх файлів проекту."""
        seen: set[str] = set()
        result: list[str] = []
        for names in self._file_subroutines.values():
            for name in names:
                if name not in seen:
                    seen.add(name)
                    result.append(name)
        return result

    # ------------------------------------------------------------------
    # Контекстна фільтрація
    # ------------------------------------------------------------------

    def _by_context(self, context: str) -> list[str]:
        ctx = context.upper()
        if ctx == "SET_DO":
            return self._do_pins
        if ctx in ("GET_DI", "WAIT_DI"):
            return self._di_pins
        if ctx == "CALL":
            return self._subroutines
        if ctx in ("IF", "ELSEIF", "WHILE", "FOR", "REPEAT"):
            return self._variables + ["TRUE", "FALSE"]
        # Базовий режим — ключові слова + змінні + підпрограми
        return (list(LANGUAGE_KEYWORDS)
                + self._variables
                + self._subroutines)