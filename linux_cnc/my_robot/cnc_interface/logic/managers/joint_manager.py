# logic/managers/joint_manager.py

class JointManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        self.speed = machine_controller.speed
        
    def connect_all_jog_buttons(self):
        for j in range(6):
            btn_p = getattr(self.widgets, f"btn_j{j}_plus", None)
            btn_m = getattr(self.widgets, f"btn_j{j}_minus", None)
            
            if btn_p:
                btn_p.pressed.connect(lambda idx=j: self.start_jog(idx, 1))
                btn_p.released.connect(lambda idx=j: self.stop_jog(idx))
            if btn_m:
                btn_m.pressed.connect(lambda idx=j: self.start_jog(idx, -1))
                btn_m.released.connect(lambda idx=j: self.stop_jog(idx))

    def start_jog(self, joint, direction):
        if not self.cnc.is_ready(): return
        
        self.cnc.sync_mode(want_teleop=False)
        
        mode_text = self.widgets.combo_joint_mode.currentText() if hasattr(self.widgets, 'combo_joint_mode') else "Continuous"
        increment = 0 if mode_text == "Continuous" else float(mode_text)
        
        self.cnc.jog(joint, direction, self.cnc.angular_jog_speed, increment, is_joint=True)

    def stop_jog(self, joint):
        mode_text = self.widgets.combo_joint_mode.currentText() if hasattr(self.widgets, 'combo_joint_mode') else "Continuous"
        if mode_text == "Continuous":
            self.cnc.stop_jog(joint, is_joint=True)