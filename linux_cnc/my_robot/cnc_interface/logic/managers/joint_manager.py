class JointManager:
    """Handles joint movement logic (Joint Jogging)"""
    def __init__(self, machine_controller):
        self.cnc = machine_controller
        self.num_joints = 6

    def start_jog(self, joint_idx: int, direction: int, mode_text: str):
        """Initiates joint movement"""
        if not self.cnc.is_ready():
            return

        # Switch to Joint mode (teleop=False)
        self.cnc.sync_mode(want_teleop=False)
        
        # Safely parse increment value from mode text
        increment = self._parse_increment(mode_text)
        
        try:
            self.cnc.jog(
                joint_idx, 
                direction, 
                self.cnc.angular_jog_speed, # Use angular speed
                increment, 
                is_joint=True
            )
        except Exception as e:
            print(f"ERROR: Joint jogging failed: {e}")

    def stop_jog(self, joint_idx: int, mode_text: str):
        """Stops joint movement (only for Continuous mode)"""
        if mode_text == "Continuous":
            self.cnc.stop_jog(joint_idx, is_joint=True)

    def _parse_increment(self, text: str) -> float:
        """Safely converts UI text to a numeric increment value"""
        if text == "Continuous":
            return 0.0
        try:
            return float(text)
        except (ValueError, TypeError):
            return 0.0


class JointUIBinder:
    """Binds joint control buttons to the joint logic manager"""
    def __init__(self, joint_manager, widgets):
        self.manager = joint_manager
        self.widgets = widgets

    def connect_buttons(self):
        """Connects 6 pairs of buttons (J0-J5) to their respective handlers"""
        for j in range(self.manager.num_joints):
            btn_p = getattr(self.widgets, f"btn_j{j}_plus", None)
            btn_m = getattr(self.widgets, f"btn_j{j}_minus", None)
            
            if btn_p:
                btn_p.pressed.connect(lambda idx=j: self._handle_press(idx, 1))
                btn_p.released.connect(lambda idx=j: self._handle_release(idx))
            if btn_m:
                btn_m.pressed.connect(lambda idx=j: self._handle_press(idx, -1))
                btn_m.released.connect(lambda idx=j: self._handle_release(idx))

    def _get_current_mode(self) -> str:
        """Retrieves the current joint mode from the UI"""
        combo = getattr(self.widgets, 'combo_joint_mode', None)
        return combo.currentText() if combo else "Continuous"

    def _handle_press(self, idx, direction):
        """Handles button press event for joint movement"""
        self.manager.start_jog(idx, direction, self._get_current_mode())

    def _handle_release(self, idx):
        """Handles button release event to stop joint movement"""
        self.manager.stop_jog(idx, self._get_current_mode())