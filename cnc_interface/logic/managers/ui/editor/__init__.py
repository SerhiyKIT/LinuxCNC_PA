# logic/managers/ui/editor/__init__.py
"""
Пакет editor – редактор G-коду для LinuxCNC UI.

Публічний API:
  GCodeEditorManager  – використовується у HandlerClass
  GCodeEditorWidget   – якщо потрібен прямий доступ до віджета
  GCodeHighlighter    – підсвітка синтаксису
  MotionCommandDialog – діалог PTP/LIN/CIRC
"""
from .editor_manager        import GCodeEditorManager
from .editor_widget         import GCodeEditorWidget
from .editor_highlighter    import GCodeHighlighter
from .editor_motion_dialog  import MotionCommandDialog

__all__ = [
    "GCodeEditorManager",
    "GCodeEditorWidget",
    "GCodeHighlighter",
    "MotionCommandDialog",
]
