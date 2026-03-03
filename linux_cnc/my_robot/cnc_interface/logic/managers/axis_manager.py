class AxisManager:
    """Responsible only for coordinating jog commands via CNC"""
    def __init__(self, machine_controller):
        self.cnc = machine_controller
        self.axes = ['x', 'y', 'z', 'a', 'b', 'c']

    def start_jog(self, axis_idx: int, direction: int, mode_text: str):
        if not self.cnc.is_ready():
            return

        self.cnc.sync_mode(want_teleop=True)
        
        # Safely parse jog increment from mode text
        increment = self._parse_increment(mode_text)
        
        try:
            self.cnc.jog(
                axis_idx, 
                direction, 
                self.cnc.linear_jog_speed, 
                increment, 
                is_joint=False
            )
        except Exception as e:
            print(f"ERROR: Jogging failed: {e}")

    def stop_jog(self, axis_idx: int, mode_text: str):
        # Stop jogging only if mode is Continuous
        if mode_text == "Continuous":
            self.cnc.stop_jog(axis_idx, is_joint=False)

    def _parse_increment(self, text: str) -> float:
        """
        Helper method for safe parsing of jog increment.
        Returns 0.0 for 'Continuous' mode or invalid input.
        """
        if text == "Continuous":
            return 0.0
        try:
            return float(text)
        except (ValueError, TypeError):
            print(f"WARNING: Invalid jog increment '{text}', defaulting to Continuous")
            return 0.0


class AxisUIBinder:
    """Responsible only for connecting UI elements to the logic manager"""
    def __init__(self, axis_manager, widgets):
        self.manager = axis_manager
        self.widgets = widgets

    def connect_buttons(self):
        # Uses axis list from manager; binding logic is handled here
        for i, axis in enumerate(self.manager.axes):
            self._bind_axis_pair(i, axis)

    def _bind_axis_pair(self, idx, axis_name):
        """
        Isolates logic for finding and connecting axis widgets.
        Binds press/release events for plus and minus buttons.
        """
        btn_p = getattr(self.widgets, f"btn_{axis_name}_plus", None)
        btn_m = getattr(self.widgets, f"btn_{axis_name}_minus", None)
        
        if btn_p:
            btn_p.pressed.connect(lambda: self._handle_press(idx, 1))
            btn_p.released.connect(lambda: self._handle_release(idx))
        if btn_m:
            btn_m.pressed.connect(lambda: self._handle_press(idx, -1))
            btn_m.released.connect(lambda: self._handle_release(idx))

    def _get_current_mode(self) -> str:
        # Returns current mode from combo box, defaults to 'Continuous'
        combo = getattr(self.widgets, 'combo_axis_mode', None)
        return combo.currentText() if combo else "Continuous"

    def _handle_press(self, axis_idx, direction):
        # Handles jog start on button press
        mode = self._get_current_mode()
        self.manager.start_jog(axis_idx, direction, mode)

    def _handle_release(self, axis_idx):
        # Handles jog stop on button release
        mode = self._get_current_mode()
        self.manager.stop_jog(axis_idx, mode)