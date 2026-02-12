# logic/managers/__init__.py
"""
Exporting all manager classes for easy import in other parts of the application. This allows us to import managers like:
from logic.managers import ControlManager, CycleManager, ToolManager, JogManager, FileManager, KeyboardManager, OverrideManager, StyleManager, UIManager
"""

try:
    from .control_manager import ControlManager
    from .cycle_manager import CycleManager
    from .tool_manager import ToolManager
    from .jog_manager import JogManager
    from .file_manager import FileManager
    from .keyboard_manager import KeyboardManager
    from .overrides_manager import OverrideManager
    from .style_manager import StyleManager
    from .ui_manager import UIManager
except ImportError as e:
    print(f"DEBUG: Error in managers/__init__.py: {e}")

__all__ = [
    'ControlManager',
    'CycleManager',
    'ToolManager',
    'JogManager',
    'FileManager',
    'KeyboardManager',
    'OverrideManager',
    'StyleManager',
    'UIManager'
]