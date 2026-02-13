# logic/managers/axis_manager.py

class AxisManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        self.axes = ['x', 'y', 'z', 'a', 'b', 'c']
        
        self.speed = machine_controller.speed

    def connect_all_axis_buttons(self):
        for i, axis in enumerate(self.axes):
            btn_p = getattr(self.widgets, f"btn_{axis}_plus", None)
            btn_m = getattr(self.widgets, f"btn_{axis}_minus", None)
            
            if btn_p:
                btn_p.pressed.connect(lambda idx=i: self.start_axis_jog(idx, 1))
                btn_p.released.connect(lambda idx=i: self.stop_axis_jog(idx))
            if btn_m:
                btn_m.pressed.connect(lambda idx=i: self.start_axis_jog(idx, -1))
                btn_m.released.connect(lambda idx=i: self.stop_axis_jog(idx))

    def start_axis_jog(self, axis_idx, direction):
        if not self.cnc.is_ready(): return

        self.cnc.sync_mode(want_teleop=True)
        
        combo = getattr(self.widgets, 'combo_axis_mode', None)
        mode_text = combo.currentText() if combo else "Continuous"
        increment = 0 if mode_text == "Continuous" else float(mode_text)
        
        self.cnc.jog(axis_idx, direction, self.cnc.linear_jog_speed, increment, is_joint=False)

    def stop_axis_jog(self, axis_idx):
        combo = getattr(self.widgets, 'combo_axis_mode', None)
        mode_text = combo.currentText() if combo else "Continuous"
        
        if mode_text == "Continuous":
            self.cnc.stop_jog(axis_idx, is_joint=False)