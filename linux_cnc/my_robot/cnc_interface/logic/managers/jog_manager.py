# logic/managers/jog_manager.py
from config import DEFAULT_SPEED

class JogManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        self.speed = DEFAULT_SPEED
        
    def _connect_jog_buttons(self):
        """Connects the jog buttons to their respective handlers"""
        for j in range(6):
            btn_p = getattr(self.widgets, f"btn_j{j}_plus", None)
            btn_m = getattr(self.widgets, f"btn_j{j}_minus", None)
            
            if btn_p:
                btn_p.pressed.connect(lambda index=j: self.handle_jog_start(index, 1, True))
                btn_p.released.connect(lambda index=j: self.handle_jog_stop(index, True))
            if btn_m:
                btn_m.pressed.connect(lambda index=j: self.handle_jog_start(index, -1, True))
                btn_m.released.connect(lambda index=j: self.handle_jog_stop(index, True))
        
    def _make_jog_handler(self, index, direction, is_joint):
        """Creates a function handler for button press"""
        return lambda: self.handle_jog_start(index, direction, is_joint)

    def _make_stop_handler(self, index, is_joint):
        """Creates a function handler for button release"""
        return lambda: self.handle_jog_stop(index, is_joint)

    def handle_jog_start(self, index, direction, is_joint):
        """Base logic for starting a jog movement"""
        states = self.cnc.get_states()
        if not states['is_ready']:
            return

        mode_text = "Continuous"
        combo = getattr(self.widgets, 'combo_joint_mode', None)
        if combo:
            mode_text = combo.currentText()

        increment = 0 if mode_text == "Continuous" else float(mode_text)
            
        try:
            self.cnc.jog(index, direction, self.speed, increment, is_joint)
            print(f"DEBUG: JOG {'J' if is_joint else 'Axis'}{index} | Mode: {mode_text}")
        except Exception as e:
            print(f"ERROR: Jog start failed: {e}")

    def handle_jog_stop(self, index, is_joint):
        """Logic for stopping a jog movement"""
        mode_text = "Continuous"
        combo = getattr(self.widgets, 'combo_joint_mode', None)
        if combo:
            mode_text = combo.currentText()
            
        if mode_text == "Continuous":
            try:
                self.cnc.stop_jog(index, is_joint)
            except Exception as e:
                print(f"ERROR: Jog stop failed: {e}")