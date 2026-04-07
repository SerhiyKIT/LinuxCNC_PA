# logic/managers/auth/auth_db.py
"""
AuthDB — робота з SQLite базою даних користувачів.

Таблиця users:
  id             INTEGER PRIMARY KEY
  login          TEXT UNIQUE
  password       TEXT
  role_admin     BOOLEAN
  role_engineer  BOOLEAN
  role_program   BOOLEAN
  role_operator  BOOLEAN
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

from .auth_constants import AUTH_DB, AUTH_DIR, DEFAULT_PASSWORD, SUPERADMIN_LOGIN

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Модель користувача
# ---------------------------------------------------------------------------

@dataclass
class User:
    id:            int
    login:         str
    password:      str
    role_admin:    bool
    role_engineer: bool
    role_program:  bool
    role_operator: bool

    @property
    def is_superadmin(self) -> bool:
        return self.id == 1 or self.login == SUPERADMIN_LOGIN

    def available_roles(self) -> list[str]:
        """Повертає список доступних ролей від найвищої до найнижчої."""
        from .auth_constants import ROLES
        return [label for col, label in ROLES if getattr(self, col)]

    def default_role(self) -> str:
        """Найнижча доступна роль (пріоритет: Operator)."""
        from .auth_constants import ROLES
        for col, label in reversed(ROLES):
            if getattr(self, col):
                return label
        return ""


# ---------------------------------------------------------------------------
# AuthDB
# ---------------------------------------------------------------------------

class AuthDB:
    """CRUD-операції над таблицею users."""

    # ------------------------------------------------------------------
    # Ініціалізація
    # ------------------------------------------------------------------

    @staticmethod
    def init() -> None:
        """
        Створити БД і таблицю якщо не існують.
        При порожній БД — створити суперадміна.
        """
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        with AuthDB._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    login         TEXT    NOT NULL UNIQUE,
                    password      TEXT    NOT NULL,
                    role_admin    BOOLEAN NOT NULL DEFAULT 0,
                    role_engineer BOOLEAN NOT NULL DEFAULT 0,
                    role_program  BOOLEAN NOT NULL DEFAULT 0,
                    role_operator BOOLEAN NOT NULL DEFAULT 0
                )
            """)
            conn.commit()
            # Якщо таблиця порожня — створити суперадміна
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                conn.execute(
                    "INSERT INTO users "
                    "(login, password, role_admin, role_engineer, role_program, role_operator) "
                    "VALUES (?, ?, 1, 1, 1, 1)",
                    (SUPERADMIN_LOGIN, DEFAULT_PASSWORD),
                )
                conn.commit()
                logger.info("AuthDB: створено суперадміна '%s'", SUPERADMIN_LOGIN)

    # ------------------------------------------------------------------
    # Автентифікація
    # ------------------------------------------------------------------

    @staticmethod
    def authenticate(login: str, password: str) -> Optional[User]:
        """Повернути User якщо логін/пароль коректні, інакше None."""
        with AuthDB._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE login = ? AND password = ?",
                (login.strip(), password),
            ).fetchone()
        return AuthDB._row_to_user(row) if row else None

    @staticmethod
    def verify_password(user_id: int, password: str) -> bool:
        """Перевірити пароль конкретного користувача за id."""
        with AuthDB._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE id = ? AND password = ?",
                (user_id, password),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def get_all() -> list[User]:
        with AuthDB._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY id"
            ).fetchall()
        return [AuthDB._row_to_user(r) for r in rows]

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        with AuthDB._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return AuthDB._row_to_user(row) if row else None

    @staticmethod
    def create(login: str, password: str,
               role_admin: bool, role_engineer: bool,
               role_program: bool, role_operator: bool) -> bool:
        """Створити нового користувача. False якщо логін вже існує."""
        try:
            with AuthDB._connect() as conn:
                conn.execute(
                    "INSERT INTO users "
                    "(login, password, role_admin, role_engineer, role_program, role_operator) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (login.strip(), password,
                     role_admin, role_engineer, role_program, role_operator),
                )
                conn.commit()
            logger.info("AuthDB: створено користувача '%s'", login)
            return True
        except sqlite3.IntegrityError:
            logger.warning("AuthDB: логін '%s' вже існує", login)
            return False

    @staticmethod
    def update(user_id: int, login: str, password: str,
               role_admin: bool, role_engineer: bool,
               role_program: bool, role_operator: bool) -> bool:
        """Оновити дані користувача."""
        try:
            with AuthDB._connect() as conn:
                conn.execute(
                    "UPDATE users SET login=?, password=?, "
                    "role_admin=?, role_engineer=?, role_program=?, role_operator=? "
                    "WHERE id=?",
                    (login.strip(), password,
                     role_admin, role_engineer, role_program, role_operator,
                     user_id),
                )
                conn.commit()
            logger.info("AuthDB: оновлено користувача id=%d", user_id)
            return True
        except sqlite3.IntegrityError:
            logger.warning("AuthDB: логін '%s' вже зайнятий", login)
            return False

    @staticmethod
    def delete(user_id: int) -> bool:
        """Видалити користувача. False якщо id=1 (суперадмін)."""
        if user_id == 1:
            logger.warning("AuthDB: спроба видалити суперадміна")
            return False
        with AuthDB._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        logger.info("AuthDB: видалено користувача id=%d", user_id)
        return True

    # ------------------------------------------------------------------
    # Внутрішні хелпери
    # ------------------------------------------------------------------

    @staticmethod
    @contextmanager
    def _connect() -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(AUTH_DB))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=            row["id"],
            login=         row["login"],
            password=      row["password"],
            role_admin=    bool(row["role_admin"]),
            role_engineer= bool(row["role_engineer"]),
            role_program=  bool(row["role_program"]),
            role_operator= bool(row["role_operator"]),
        )
