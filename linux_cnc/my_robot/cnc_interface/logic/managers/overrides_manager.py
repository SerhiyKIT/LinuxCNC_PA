# logic/managers/overrides_manager.py

class OverridesManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
    def setup_overrides(self):
        """Configure sliders for overrides and jogging speeds, and connect them to handlers"""
        override_configs = {
            'sld_feed_override': (0, 200, self.on_sld_feed_override_changed),
            'sld_rapid_override': (0, 100, self.on_sld_rapid_override_changed),
            'sld_spindle_override': (0, 200, self.on_sld_spindle_override_changed),
            'sld_linear_jog_speed': (1, 593000, self.on_sld_linear_changed),
            'sld_angular_jog_speed': (1, 605900, self.on_sld_angular_changed),
            'sld_max_velocity': (0, 600, self.on_sld_max_velocity_changed)
        }

        for name, (min_v, max_v, callback) in override_configs.items():
            slider = getattr(self.widgets, name, None)
            if slider:
                slider.setMinimum(min_v)
                slider.setMaximum(max_v)
                slider.valueChanged.connect(callback)
                callback(slider.value())

    # --- Handlers ---

    def on_sld_feed_override_changed(self, value):
        self.cnc.set_feed_override(value / 100.0)
        label = getattr(self.widgets, 'val_feed_override', None)
        if label: label.setText(f"{value} %")

    def on_sld_rapid_override_changed(self, value):
        self.cnc.set_rapid_override(value / 100.0)
        label = getattr(self.widgets, 'val_rapid_override', None)
        if label: label.setText(f"{value} %")

    def on_sld_spindle_override_changed(self, value):
        self.cnc.set_spindle_override(value / 100.0)
        label = getattr(self.widgets, 'val_spindle_override', None)
        if label: label.setText(f"{value} %")

    def on_sld_linear_changed(self, value):
        actual_value = value / 1000.0
        self.cnc.linear_jog_speed = actual_value 
        label = getattr(self.widgets, 'val_linear_jog_speed', None)
        if label: label.setText(f"{actual_value:.3f} in/min")

    def on_sld_angular_changed(self, value):
        actual_value = value / 100.0
        self.cnc.angular_jog_speed = actual_value
        label = getattr(self.widgets, 'val_angular_jog_speed', None)
        if label: label.setText(f"{actual_value:.2f} deg/min")

    def on_sld_max_velocity_changed(self, value):
        try:
            self.cnc.set_max_velocity(float(value))
            label = getattr(self.widgets, 'val_max_velocity', None)
            if label: label.setText(f"{value} in/min")
        except Exception as e:
            print(f"ERROR: Max Velocity Update: {e}")