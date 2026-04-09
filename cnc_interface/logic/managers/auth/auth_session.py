# logic/managers/auth/auth_session.py
"""
AuthSession — поточна сесія користувача (singleton).
Зберігає активного User і обрану роль.
"""
from __future__ import annotations
from typing import Optional
from .auth_db import User


class AuthSession:
    """Singleton поточної сесії."""

    _user:         Optional[User] = None
    _active_role:  str            = ""

    # ------------------------------------------------------------------

    @classmethod
    def login(cls, user: User) -> None:
        """Зберегти користувача і встановити пріоритетну роль."""
        cls._user        = user
        cls._active_role = user.default_role()

    @classmethod
    def logout(cls) -> None:
        """Скинути сесію."""
        cls._user        = None
        cls._active_role = ""

    # ------------------------------------------------------------------

    @classmethod
    def user(cls) -> Optional[User]:
        return cls._user

    @classmethod
    def is_authenticated(cls) -> bool:
        return cls._user is not None

    @classmethod
    def active_role(cls) -> str:
        return cls._active_role

    @classmethod
    def set_active_role(cls, role: str) -> None:
        cls._active_role = role

    @classmethod
    def is_admin(cls) -> bool:
        return cls._user is not None and cls._user.role_admin

    @classmethod
    def role_priority(cls, role: str) -> int:
        """Повернути числовий пріоритет ролі (0=Operator, 3=Admin)."""
        from .auth_constants import ROLE_PRIORITY
        return ROLE_PRIORITY.get(role, 0)