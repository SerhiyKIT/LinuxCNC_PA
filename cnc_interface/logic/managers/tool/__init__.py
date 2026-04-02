# logic/managers/tool/__init__.py
"""
Пакет tool — менеджер інструментів робота.

Публічний API:
  ToolPanelManager — використовується у HandlerClass
  ToolStore        — читання/запис JSON
  Tool             — модель інструмента
"""
from .tool_panel  import ToolPanelManager
from .tool_store  import ToolStore
from .tool_models import Tool, ToolDimensions

__all__ = ["ToolPanelManager", "ToolStore", "Tool", "ToolDimensions"]
