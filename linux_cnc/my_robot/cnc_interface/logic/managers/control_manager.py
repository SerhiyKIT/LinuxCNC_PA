# logic/managers/control_manager.py
from config import STYLES
from PyQt5.QtWidgets import QMessageBox

class ControlManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        # State to track if homing complete message has been shown
        self.homing_complete_shown = False
        
        # Default speed for jogging, can be adjusted via config
        self.SPEED = self.cnc.speed

    def on_btn_estop_clicked(self):
        """Handler for E-Stop button click. Toggles E-Stop state and logs the action"""
        print("DEBUG: E-STOP button clicked")
        try:
            self.cnc.toggle_estop()
        except Exception as e:
            print(f"ERROR in on_btn_estop_clicked: {e}")

    def on_btn_power_off_clicked(self, states):
        """Handler for Power button click. Toggles power state and logs the action"""
        print("DEBUG: Power button clicked")
        try:
            self.cnc.poll()
            is_on = (states['power_on'] == True)
            
            if is_on:
                self.cnc.set_power(False)
                self.homing_complete_shown = False
            else:
                self.cnc.set_power(True)
                
        except Exception as e:
            print(f"ERROR in on_btn_power_off_clicked: {e}")
            
    def on_btn_home_all_clicked(self):
        """Handler for Home All button click. Checks machine state and prompts user if already homed"""
        
        # 1. Check if machine is ready for homing (powered on, E-Stop released)
        if not self.cnc.can_home():
            print("WARNING: Machine not ready for homing. Ensure power is on and E-Stop is released")
            return

        # 2. Check if already homed - if so, ask for confirmation before re-homing
        if self.cnc.is_all_homed():
            if not self._show_rehome_confirmation():
                return 

        # 3. Execute homing sequence
        print("DEBUG: Starting home all sequence...")
        self.cnc.home_all_sequence()

    def on_overlay_clicked(self, states, panel_type):
        """
        Handler for clicking on the overlay to switch between Axis and Joint mode.
         - panel_type: "axis" or "joint"
         - Checks if machine is ready and homed before allowing mode switch
        """
        
        if states['is_ready'] and states['all_homed']:
            self.cnc.manual_mode = panel_type
            is_teleop = (panel_type == "axis")
            self.cnc.set_teleop(is_teleop)
            
            print(f"DEBUG: Mode -> {panel_type}, Teleop -> {is_teleop}")
    
    def _show_rehome_confirmation(self):
        """Dialog to confirm re-homing if already homed"""
        msg = QMessageBox(self.widgets.main_window if hasattr(self.widgets, 'main_window') else None)
        msg.setWindowTitle("Warning")
        msg.setText("Joint is already homed, are you sure you want to re-home?")
        msg.setInformativeText("This will reset current coordinates and may cause unexpected motion.")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.setStyleSheet(STYLES.get('MSGBOX', ""))
        
        return msg.exec_() == QMessageBox.Yes