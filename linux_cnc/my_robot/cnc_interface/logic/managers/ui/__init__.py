
try:
    from .motion_display import MotionDisplayManager
    from .panel_manager import PanelManager
    from .gcode_display import GCodeDisplayManager
    from .logger_display import LoggerDisplayManager
    from .tool_display import ToolDisplayManager
    import ui_mapping
except ImportError as e:
    print(f"DEBUG: Error in managers/ui/__init__.py: {e}")