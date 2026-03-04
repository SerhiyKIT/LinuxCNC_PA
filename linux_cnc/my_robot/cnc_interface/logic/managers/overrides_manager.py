from PyQt5.QtCore import QCoreApplication

class OverridesManager:
    """Відповідає тільки за передачу чистих значень у контролер CNC"""
    def __init__(self, machine_controller):
        self.cnc = machine_controller

    def set_feed(self, scale: float):
        self.cnc.set_feed_override(scale)

    def set_rapid(self, scale: float):
        self.cnc.set_rapid_override(scale)

    def set_spindle(self, scale: float):
        self.cnc.set_spindle_override(scale)

    def set_linear_speed(self, value: float):
        self.cnc.linear_jog_speed = value

    def set_angular_speed(self, value: float):
        self.cnc.angular_jog_speed = value

    def set_max_velocity(self, value: float):
        try:
            self.cnc.set_max_velocity(value)
        except Exception as e:
            print(f"ERROR: Max Velocity Update: {e}")


class OverridesUIBinder:
    """Відповідає за слайдери, масштабування значень та оновлення тексту в UI"""
    def __init__(self, overrides_manager, widgets):
        self.manager = overrides_manager
        self.widgets = widgets

    def setup_overrides(self):
        # Конфігурація: (Slider_Name, Label_Name, Divisor, Manager_Method, Unit_Template)
        self.configs = {
            'sld_feed_override': ('val_feed_override', 100.0, self.manager.set_feed, "%1 %"),
            'sld_rapid_override': ('val_rapid_override', 100.0, self.manager.set_rapid, "%1 %"),
            'sld_spindle_override': ('val_spindle_override', 100.0, self.manager.set_spindle, "%1 %"),
            'sld_linear_jog_speed': ('val_linear_jog_speed', 1000.0, self.manager.set_linear_speed, "%1 in/min"),
            'sld_angular_jog_speed': ('val_angular_jog_speed', 100.0, self.manager.set_angular_speed, "%1 deg/min"),
            'sld_max_velocity': ('val_max_velocity', 1.0, self.manager.set_max_velocity, "%1 in/min")
        }

        for sld_name, cfg in self.configs.items():
            slider = getattr(self.widgets, sld_name, None)
            if slider:
                # Використовуємо lambda, щоб передати назву конфігурації в обробник
                slider.valueChanged.connect(lambda val, name=sld_name: self._handle_change(name, val))
                # Початкове оновлення
                self._handle_change(sld_name, slider.value())

    def _handle_change(self, name, raw_value):
        label_name, divisor, manager_func, unit_tpl = self.configs[name]
        actual_value = raw_value / divisor

        # 1. Відправляємо в логіку
        manager_func(actual_value)

        # 2. Оновлюємо текст в UI
        label = getattr(self.widgets, label_name, None)
        if label:
            # Форматування: 3 знаки після коми для швидкості, інакше 0 знаків
            fmt_val = f"{actual_value:.3f}" if divisor == 1000.0 else (
                      f"{actual_value:.2f}" if divisor == 100.0 and "deg" in unit_tpl else str(int(raw_value)))
            
            template = QCoreApplication.translate("MainWindow", unit_tpl)
            label.setText(template.replace("%1", fmt_val))

    def refresh_all_labels(self):
        """Перемальовує всі лейбли на основі поточних значень слайдерів"""
        for sld_name in self.configs:
            slider = getattr(self.widgets, sld_name, None)
            if slider:
                self._handle_change(sld_name, slider.value())