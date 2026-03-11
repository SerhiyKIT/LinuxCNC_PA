# logic/managers/ui/motion_display.py
from managers.style_manager import StyleManager

class MotionDisplayManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        # State to track if homing complete message has been shown
        self.last_joint_pos = {}
        
        # Limits and parameters from the machine controller
        self.limits = self.cnc.limits
        
        # Styles for jog buttons based on config
        self.style_manager = StyleManager()
        self.style_manager._set_jogging_styles()
        
    def update_coordinates(self, states):
        """Update the coordinate displays (joint and world) based on current machine state"""
        j_pos = states.get('joint_position', [])
        actual_pos = states.get('actual_position', [])
        
        # 1. Update Joint positions
        for i in range(min(6, len(j_pos))):
            val = j_pos[i]
            label = getattr(self.widgets, f"txt_j{i}_pos", None)
            
            if label:
                prev = self.last_joint_pos.get(i, None)
                
                if prev is None or abs(val - prev) > 0.00005:
                    label.setText(f"{val:.4f}")
                    self.last_joint_pos[i] = val
        
        # Call soft limit handler to update jog button states based on joint positions and limits
        self._handle_joint_soft_limits(states)

        # 2. Update World positions
        axes = self.axes = ['x', 'y', 'z', 'a', 'b', 'c']
        for i, axis in enumerate(axes):
            val = actual_pos[i] if i < len(actual_pos) else 0.0
            w = getattr(self.widgets, f'txt_{axis}_pos', None)
            
            if w:
                storage_key = f"world_{axis}"
                prev_w = self.last_joint_pos.get(storage_key, None)
                
                if prev_w is None or abs(val - prev_w) > 0.00005:
                    w.setText(f"{val:.4f}")
                    self.last_joint_pos[storage_key] = val
                    
    def _handle_joint_soft_limits(self, states):
        """Check joint positions against soft limits and disable/enable jog buttons accordingly"""
        if not states['is_ready']:
            return

        j_pos = states['joint_position']
        
        style_active = self.style_manager.STYLE_JOG_ACTIVE
        style_limited = self.style_manager.STYLE_JOG_LIMITED

        for i in range(min(6, len(j_pos))):
            limits = self.limits.get(i)
            if not limits: continue
            
            curr_pos = j_pos[i]

            # 1. Determine if we are at or beyond limits and update button states and styles
            btn_plus = getattr(self.widgets, f"btn_j{i}_plus", None)
            btn_minus = getattr(self.widgets, f"btn_j{i}_minus", None)
            
            if btn_plus:
                at_max = curr_pos >= limits["max"]
                btn_plus.setEnabled(not at_max)
                btn_plus.setStyleSheet(style_limited if at_max else style_active)
                
            if btn_minus:
                at_min = curr_pos <= limits["min"]
                btn_minus.setEnabled(not at_min)
                btn_minus.setStyleSheet(style_limited if at_min else style_active)