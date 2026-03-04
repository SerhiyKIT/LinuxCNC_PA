class CycleManager:
    """Відповідає виключно за логіку керування циклом виконання програми (G-code)"""
    def __init__(self, machine_controller):
        self.cnc = machine_controller

    def start_cycle(self, start_line=0, *args, **kwargs):
        line = start_line if isinstance(start_line, int) else 0
        
        try:
            self.cnc.cycle_start(line)
            print(f"DEBUG: Cycle started from line {line}")
        except Exception as e:
            print(f"WARNING: Failed to start cycle: {e}")

    def resume_cycle(self):
        try:
            self.cnc.cycle_resume()
            print("DEBUG: Cycle resumed")
        except Exception as e:
            print(f"ERROR: Resume failed: {e}")

    def pause_cycle(self):
        try:
            self.cnc.cycle_pause()
            print("DEBUG: Pause (Feed Hold) activated")
        except Exception as e:
            print(f"ERROR: Pause failed: {e}")

    def stop_cycle(self):
        try:
            self.cnc.cycle_stop()
            print("DEBUG: Program stopped")
        except Exception as e:
            print(f"ERROR: Stop failed: {e}")

    def step_cycle(self):
        try:
            self.cnc.cycle_step()
            self.cnc.status.poll() # Оновлюємо статус після кроку
            print("DEBUG: Single step executed")
        except Exception as e:
            print(f"WARNING: Step execution unavailable: {e}")


class CycleUIBinder:
    """Відповідає за прив'язку кнопок керування циклом до менеджера логіки"""
    def __init__(self, cycle_manager, widgets):
        self.manager = cycle_manager
        self.widgets = widgets

    def connect_buttons(self):
        """З'єднує події 'clicked' з відповідними методами логіки"""
        mapping = {
            'btn_cycle_start': self.manager.start_cycle,
            'btn_cycle_pause': self.manager.pause_cycle,
            'btn_cycle_continue': self.manager.resume_cycle,
            'btn_cycle_stop': self.manager.stop_cycle,
            'btn_cycle_step': self.manager.step_cycle
        }
        
        for btn_name, method in mapping.items():
            btn = getattr(self.widgets, btn_name, None)
            if btn:
                # Використовуємо просту прив'язку, оскільки аргументи не передаються через UI клік
                btn.clicked.connect(method)