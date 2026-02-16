# logic/managers/tool_manager.py
from config import STYLES

class ToolManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        self.STYLE_TOOL_ARMED = STYLES.get('TOOL_ARMED', '')
        self.STYLE_TOOL_DISARMED = STYLES.get('TOOL_DISARMED', '')
        self.STYLE_GRIP_ACTIVE = STYLES.get('GRIP_ACTIVE', '')
        self.STYLE_GRIP_INACTIVE = STYLES.get('GRIP_INACTIVE', '')

    def connect_tool_buttons(self):
        """Connect tool management buttons with their handlers"""
        if hasattr(self.widgets, 'btn_tool_arm'):
            self.widgets.btn_tool_arm.setCheckable(True)
            self.widgets.btn_tool_arm.clicked.connect(self.on_btn_tool_arm_clicked)

        if hasattr(self.widgets, 'btn_tool_action'):
            self.widgets.btn_tool_action.setCheckable(True)
            self.widgets.btn_tool_action.clicked.connect(self.on_btn_tool_action_clicked)

        if hasattr(self.widgets, 'sld_tool_power'):
            self.widgets.sld_tool_power.setMinimum(10)
            self.widgets.sld_tool_power.setMaximum(100)
            self.widgets.sld_tool_power.valueChanged.connect(self.on_sld_tool_power_changed)

    def on_btn_tool_arm_clicked(self):
        """Handler for the Arm/Disarm button. When disarming, it also attempts to release the tool if it was gripping, and updates the UI accordingly."""
        btn = self.widgets.btn_tool_arm
        is_armed = btn.isChecked()
        
        btn.setText("ARMED" if is_armed else "DISARMED")
        btn.setStyleSheet(self.STYLE_TOOL_ARMED if is_armed else self.STYLE_TOOL_DISARMED)
        
        if not is_armed:
            print("DEBUG: [GRIPPER] Safety Trigger: Disarming tool")
            if hasattr(self.widgets, 'btn_tool_action'):
                self.widgets.btn_tool_action.setChecked(False)
                self._update_action_button_ui(False)
            
            if all(self.cnc.status.homed[:3]):
                self.cnc.send_mdi("M102")
            else:
                print("DEBUG: [GRIPPER] Skip M102: Machine not homed")
                
            if hasattr(self.widgets, 'lbl_tool_status'):
                self.widgets.lbl_tool_status.setText("STATUS: LOCKED")
        else:
            if hasattr(self.widgets, 'lbl_tool_status'):
                self.widgets.lbl_tool_status.setText("STATUS: READY")

    def on_btn_tool_action_clicked(self):
        """Handler for the Grip/Release button. It checks safety conditions before sending the appropriate M-code to grip or release, and updates the UI accordingly."""
        # 1. Check if tool is armed
        if not self.widgets.btn_tool_arm.isChecked():
            print("WARNING: [GRIPPER] Access Denied: Arm Tool first!")
            self.widgets.btn_tool_action.setChecked(False)
            return

        # 2. Check if machine is homed (safety check before allowing grip/release)
        if not all(self.cnc.status.homed[:3]):
            print("WARNING: [GRIPPER] Access Denied: Home joints first!")
            self.widgets.btn_tool_action.setChecked(False)
            return

        is_grip = self.widgets.btn_tool_action.isChecked()
        cmd = "M101" if is_grip else "M102"
        
        if self.cnc.send_mdi(cmd):
            self._update_action_button_ui(is_grip)
            print(f"DEBUG: [GRIPPER] {cmd} sent successfully")

    def on_sld_tool_power_changed(self, value):
        """Handler for the power slider. It converts the slider value (10-100) to a force percentage (0.1-1.0) and sends it to the CNC controller, while also updating the UI label."""
        force_float = value / 100.0
        self.cnc.set_gripper_force(force_float)
        
        if hasattr(self.widgets, 'lbl_tool_power_val'):
            self.widgets.lbl_tool_power_val.setText(f"{value} %")
        
        if value % 10 == 0:
            print(f"DEBUG: [GRIPPER] Force: {value}%")

    def _update_action_button_ui(self, is_grip):
        """Update the Grip/Release button text and style based on whether it's gripping or not, and also update the status label if it exists."""
        btn = getattr(self.widgets, 'btn_tool_action', None)
        lbl = getattr(self.widgets, 'lbl_tool_status', None)
        if not btn: return

        if is_grip:
            btn.setText("RELEASE")
            btn.setStyleSheet(self.STYLE_GRIP_ACTIVE)
            if lbl: lbl.setText("STATUS: HOLDING")
        else:
            btn.setText("GRIP")
            btn.setStyleSheet(self.STYLE_GRIP_INACTIVE)
            if lbl: lbl.setText("STATUS: OPEN")