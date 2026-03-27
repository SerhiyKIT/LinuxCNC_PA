# logic/managers/project/__init__.py
"""
Пакет project – менеджер проектів LinuxCNC.

Публічний API:
  ProjectManager – використовується у HandlerClass
"""
from .project_manager import ProjectManager

__all__ = ["ProjectManager"]
