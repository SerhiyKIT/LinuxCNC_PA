from config import STYLES
from PyQt5.QtWidgets import QMessageBox

class MachineDialogs:
    """Helper class for displaying UI messages (separates UI from logic)"""
    @staticmethod
    def confirm_rehome(parent_widget=None) -> bool:
        msg = QMessageBox(parent_widget)
        msg.setWindowTitle("Warning")
        msg.setText("Joint is already homed. Are you sure you want to re-home?")
        msg.setInformativeText("This will reset the current coordinates and may cause unexpected motion.")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.setStyleSheet(STYLES.get('MSGBOX', ""))
        return msg.exec_() == QMessageBox.Ok


class ControlManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        self.homing_complete_shown = False
        self.SPEED = self.cnc.speed

    def toggle_estop(self):
        """Logic for toggling the emergency stop state"""
        try:
            self.cnc.toggle_estop()
            print("DEBUG: E-STOP toggled")
        except Exception as e:
            print(f"ERROR: Failed to toggle E-STOP: {e}")

    def toggle_power(self, current_power_state: bool):
        """Logic for controlling machine power state"""
        try:
            self.cnc.poll()
            new_state = not current_power_state
            self.cnc.set_power(new_state)
            
            if not new_state:
                self.homing_complete_shown = False
            
            print(f"DEBUG: Power set to {new_state}")
        except Exception as e:
            print(f"ERROR: Failed to set power: {e}")

    def execute_homing(self):
        """Checks conditions and starts the homing process"""
        if not self.cnc.can_home():
            print("WARNING: Machine not ready for homing.")
            return

        if self.cnc.is_all_homed():
            # Show confirmation dialog via UI helper
            parent = getattr(self.widgets, 'main_window', None)
            if not MachineDialogs.confirm_rehome(parent):
                return

        self.cnc.home_all_sequence()
        print("DEBUG: Homing sequence started")

    def switch_control_mode(self, panel_type: str, is_ready: bool, all_homed: bool):
        """Switches between Axis and Joint control modes"""
        if is_ready and all_homed:
            self.cnc.manual_mode = panel_type
            is_teleop = (panel_type == "axis")
            self.cnc.set_teleop(is_teleop)
            print(f"DEBUG: Mode -> {panel_type}")

    # --- Button Handlers (proxy methods for UI buttons) ---
    
    def on_btn_estop_clicked(self):
        self.toggle_estop()

    def on_btn_power_off_clicked(self, states):
        self.toggle_power(states.get('power_on', False))
            
    def on_btn_home_all_clicked(self):
        self.execute_homing()

    def on_overlay_clicked(self, states, panel_type):
        self.switch_control_mode(
            panel_type, 
            states.get('is_ready', False), 
            states.get('all_homed', False)
        )