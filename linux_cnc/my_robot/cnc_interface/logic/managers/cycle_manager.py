# logic/managers/cycle_manager.py

class CycleManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets

    def connect_cycle_buttons(self):
        """Connect cycle control buttons (Start, Pause, Continue, Stop, Step) to their respective handlers"""
        mapping = {
            'btn_cycle_start': self.on_btn_cycle_start_clicked,
            'btn_cycle_pause': self.on_btn_cycle_pause_clicked,
            'btn_cycle_continue': self.on_btn_cycle_continue_clicked,
            'btn_cycle_stop': self.on_btn_cycle_stop_clicked,
            'btn_cycle_step': self.on_btn_cycle_step_clicked
        }
        for btn_name, handler in mapping.items():
            btn = getattr(self.widgets, btn_name, None)
            if btn:
                btn.clicked.connect(handler)

    def on_btn_cycle_start_clicked(self):
        try:
            self.cnc.cycle_start(0)
            print("DEBUG: Цикл запущено")
        except Exception as e:
            print(f"WARNING: Не вдалося почати цикл: {e}")

    def on_btn_cycle_continue_clicked(self):
        try:
            self.cnc.cycle_resume()
            print("DEBUG: Виконання продовжено")
        except Exception as e:
            print(f"ERROR: Помилка продовження: {e}")

    def on_btn_cycle_pause_clicked(self):
        try:
            self.cnc.cycle_pause()
            print("DEBUG: Пауза (Feed Hold)")
        except Exception as e:
            print(f"ERROR: Помилка паузи: {e}")

    def on_btn_cycle_stop_clicked(self):
        try:
            self.cnc.cycle_stop()
            print("DEBUG: Програму зупинено")
        except Exception as e:
            print(f"ERROR: Помилка зупинки: {e}")

    def on_btn_cycle_step_clicked(self):
        try:
            self.cnc.cycle_step()
            self.cnc.status.poll()
            print("DEBUG: Виконано один крок (Step)")
        except Exception as e:
            print(f"WARNING: Покрокове виконання недоступне: {e}")