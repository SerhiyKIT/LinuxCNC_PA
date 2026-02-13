# logic/managers/cycle_manager.py

class CycleManager:
    def __init__(self, cnc):
        self.cnc = cnc

    def start_cycle(self):
        try:
            self.cnc.command("cycle start")
        except Exception as e:
            print(f"ERROR: Не вдалося запустити цикл: {e}")

    def stop_cycle(self):
        try:
            self.cnc.command("cycle stop")
        except Exception as e:
            print(f"ERROR: Не вдалося зупинити цикл: {e}")