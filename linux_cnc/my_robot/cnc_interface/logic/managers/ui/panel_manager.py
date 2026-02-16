# logic/managers/ui/panel_manager.py
from managers.style_manager import StyleManager

class PanelManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        self.style_manager = StyleManager()
        self.style_manager._set_emergency_stop_styles()
        self.style_manager._set_power_styles()
        self.style_manager._set_homing_styles()
        self.style_manager._set_panel_styles()
        
    def update_machine_state(self, states):
        """Update the visual state of machine control buttons (E-Stop, Power) based on current status"""
        estop_active = (states['estop_off'] == False)
        power_on = (states['power_on'] == True)

        # Update E-Stop button
        btn_estop = getattr(self.widgets, 'btn_estop', None)
        if btn_estop:
            style = self.style_manager.STYLE_ESTOP_ON if estop_active else self.style_manager.STYLE_ESTOP_OFF
            btn_estop.setStyleSheet(style)

        # Update Power button
        btn_power = getattr(self.widgets, 'btn_power_off', None)
        if btn_power:
            btn_power.setEnabled(not estop_active)
            
            is_active = power_on and not estop_active
            style = self.style_manager.STYLE_POWER_ON if is_active else self.style_manager.STYLE_POWER_OFF
            
            btn_power.setStyleSheet(style)
            btn_power.setText("ON" if is_active else "OFF")
            
    def update_status_display(self, states):
        """Update the main status display text based on machine state (E-Stop, Power, Homing)"""
        txt_display = getattr(self.widgets, 'txt_status_display', None)
        if not txt_display:
            return
        
        if states['estop_off'] == False:
            msg = "EMERGENCY STOP"
        elif not states['power_on']:
            msg = "POWER OFF"
        elif not states['all_homed']:
            msg = "HOMING REQUIRED"
        else:
            msg = "SYSTEM READY"

        txt_display.setText(msg)

    def update_home_button_state(self, states):
        """Update the state and style of the 'Home All' button based on machine readiness"""
        btn = getattr(self.widgets, 'btn_home_all', None)
        if btn:
            btn.setEnabled(states['is_ready'])
            
            style = self.style_manager.STYLE_HOME_READY if states['is_ready'] else self.style_manager.STYLE_HOME_INACTIVE
            btn.setStyleSheet(style)

    def update_manual_controls(self, states):
        """Logic to show/hide manual control panels based on machine state and homing status"""
        show_joints = False
        show_axis = False

        current_mode = states.get('manual_mode', 'axis')

        if states['is_ready'] and not states['is_running']:
            if not states['all_homed']:
                show_joints = True 
            else:
                show_joints = (current_mode == "joint")
                show_axis = (current_mode == "axis")
                
        self._apply_panel_style('joint_control', show_joints)
        if hasattr(self.widgets, 'joint_control_overlay'):
            self.widgets.joint_control_overlay.setVisible(not show_joints)

        self._apply_panel_style('axis_control', show_axis)
        if hasattr(self.widgets, 'axis_control_overlay'):
            self.widgets.axis_control_overlay.setVisible(not show_axis)
    
    def update_gcode_controls(self, states):
        """Update G-code control panel based on machine state (Power, E-Stop)"""
        is_ready = states['is_ready'] #and states['all_homed']
        
        # 1. Style the entire G-code control panel
        self._apply_panel_style('gcode_control', is_ready)
        
        # 2. Optionally show an overlay to block interaction when not ready
        if hasattr(self.widgets, 'gcode_control_overlay'):
            self.widgets.gcode_control_overlay.setVisible(not is_ready)
            
    def _apply_panel_style(self, prefix, is_active):
        """
        Complex method to update the style of a panel group (main panel, label, frame) based on a common prefix.
        """
        # 1. Title label of the panel
        lbl = getattr(self.widgets, f"lbl_{prefix}", None)
        if lbl:
            lbl.setStyleSheet(self.style_manager.PANEL_LABEL_ACTIVE if is_active else self.style_manager.PANEL_LABEL_INACTIVE)

        # 2. Border frame of the panel
        frm = getattr(self.widgets, f"frm_{prefix}", None)
        if frm:
            frm.setStyleSheet(self.style_manager.PANEL_FRAME_ACTIVE if is_active else self.style_manager.PANEL_FRAME_INACTIVE)