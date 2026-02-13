# logic/managers/keyboard_manager.py

class KeyboardManager:
    def __init__(self, cnc):
        self.cnc = cnc

    def handle_key_press(self, key):
        try:
            # Тут можна додати логіку для обробки різних клавіш
            if key == "start":
                self.cnc.command("cycle start")
            elif key == "stop":
                self.cnc.command("cycle stop")
            elif key == "jog_x_plus":
                self.cnc.command("jog x 1 100")  # Приклад: джог на 1 мм зі швидкістю 100 мм/хв
            elif key == "jog_x_minus":
                self.cnc.command("jog x -1 100")
            # Додайте інші клавіші та відповідні команди за потребою
        except Exception as e:
            print(f"ERROR: Не вдалося обробити натискання клавіші '{key}': {e}")