# logic/managers/ui_manager.py
from managers.ui.motion_display import MotionDisplayManager
from managers.ui.panel_manager import PanelManager
from managers.ui.gcode_display import GCodeDisplayManager
from managers.ui.logger_display import LoggerDisplayManager
from managers.ui.tool_display import ToolDisplayManager

class UIManager:
    def __init__(self, machine_controller, widgets, cycle_manager=None):
        self._cycle_manager = cycle_manager 
        self.cnc = machine_controller
        self.widgets = widgets
        
        # Initialize the motion display manager to handle coordinate updates and jog button states based on machine state
        self.motion_display_manager = MotionDisplayManager(machine_controller, widgets)
        
        # Initialize the panel manager to handle the state and styles of control panels (E-Stop, Power, Homing) based on machine status
        self.panel_manager = PanelManager(machine_controller, widgets)
        
        # Initialize the G-code display manager to manage the G-code list view and related controls based on loaded file and machine state
        self.gcode_display_manager = GCodeDisplayManager(
            machine_controller, widgets, cycle_manager
        )
        
        # Initialize the logger display manager to handle logging messages to the output panel with appropriate styles based on log level
        self.logger_display_manager = LoggerDisplayManager(machine_controller, widgets)
        
        # Initialize the tool display manager to manage the state of tool control UI elements (Arm button, Grip button, Power slider) based on machine status and safety conditions
        self.tool_display_manager = ToolDisplayManager(machine_controller, widgets)

    def update_ui(self, states):
        """Main method to update all UI elements based on the current machine status"""
        try:
            self.motion_display_manager.update_coordinates(states)
            self.panel_manager.update_status_display(states)
            self.panel_manager.update_machine_state(states)
            self.panel_manager.update_home_button_state(states)
            self.panel_manager.update_manual_controls(states)
            self.panel_manager.update_gcode_controls(states)
            self.panel_manager.update_project_manager(states)
            self.gcode_display_manager.update_cycle_buttons(states)
            self.gcode_display_manager.update_active_gcodes(states)
            self.gcode_display_manager.update_gcode_display(states)
            self.tool_display_manager.update_tool_ui_state(states)
        except Exception as e:
            print(f"DEBUG UI Error: {e}")
                