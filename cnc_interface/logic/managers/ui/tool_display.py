# logic/managers/ui/tool_display.py
from managers.style_manager import StyleManager

class ToolDisplayManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        self.style_manager = StyleManager()
        
        
    def update_tool_ui_state(self, states):
        """
        Update the state of tool management UI elements (Arm button, Grip button, Power slider) 
        based on machine status and safety conditions to ensure safe operation of the tool
        """
        power_on = states.get('power_on', False)
        estop_off = states.get('estop_off', False)
        all_homed = states.get('all_homed', False)
        is_running = states.get('is_running', False)
        
        # Determine if the tool is ready for manual control (armed, machine ready, not running) to allow grip/release and power adjustments
        tool_ready = power_on and estop_off and all_homed
        
        # 1. SAFETY DISARM: If E-Stop is activated, automatically disarm the tool and reset the UI to a safe state (release grip if needed, update status label)
        if not estop_off:
            if self.widgets.btn_tool_arm.isChecked():
                self.widgets.btn_tool_arm.setChecked(False)
                self.on_btn_tool_arm_clicked()

        # 2. MANUAL CONTROL: Enable or disable the Grip/Release button and Power slider based on whether the tool is ready for manual control (machine is powered on, E-Stop is off, machine is homed, and not currently running a program)
        can_manual_control = tool_ready and not is_running
        
        if hasattr(self.widgets, 'btn_tool_action'):
            self.widgets.btn_tool_action.setEnabled(can_manual_control)
        
        if hasattr(self.widgets, 'sld_tool_power'):
            self.widgets.sld_tool_power.setEnabled(can_manual_control)

        if hasattr(self.widgets, 'btn_tool_arm'):
            self.widgets.btn_tool_arm.setEnabled(power_on and estop_off)