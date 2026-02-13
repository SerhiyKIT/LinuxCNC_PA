# logic/managers/file_manager.py
import linuxcnc

class FileManager:
    def __init__(self, cnc):
        self.cnc = cnc

    def load_file(self, file_path):
        try:
            self.cnc.command(f"load {file_path}")
        except Exception as e:
            print(f"ERROR: Не вдалося завантажити файл: {e}")

    def unload_file(self):
        try:
            self.cnc.command("unload")
        except Exception as e:
            print(f"ERROR: Не вдалося розвантажити файл: {e}")