from PyQt5 import QtCore, QtWidgets
import config

class KeyboardManager:
    def __init__(self, widgets, managers_map):
        self.widgets = widgets
        self.managers = managers_map

    def processed_key_event(self, event, is_pressed):
        """Handler for key events. It checks if the event matches any configured hotkeys and calls the corresponding manager method."""
        if not is_pressed:
            return

        key = event.key()
        modifiers = event.modifiers()

        # 1. Check if focus is on an input widget - if so, only process Escape to clear focus, otherwise ignore hotkeys
        focus_widget = QtWidgets.QApplication.focusWidget()
        if isinstance(focus_widget, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            if key == QtCore.Qt.Key_Escape:
                focus_widget.clearFocus()
            return

        # 2. Check hotkeys
        hk = config.HOTKEYS

        # System controls
        if self._match(key, modifiers, hk["ESTOP"]):
            self._call(config.MGR_CONTROL, 'on_btn_estop_clicked')
        elif self._match(key, modifiers, hk["POWER"]):
            self._call(config.MGR_CONTROL, 'on_btn_power_off_clicked')
        elif self._match(key, modifiers, hk["HOME_ALL"]):
            self._call(config.MGR_CONTROL, 'on_btn_home_all_clicked')
            
        # File operations
        elif self._match(key, modifiers, hk["OPEN_FILE"]):
            self._call(config.MGR_FILE, 'on_btn_file_open_clicked')
        elif self._match(key, modifiers, hk["SAVE_AS"]):
            self._call(config.MGR_FILE, 'on_btn_file_save_as_clicked')
        elif self._match(key, modifiers, hk["RELOAD"]):
            self._call(config.MGR_FILE, 'on_btn_file_reload_clicked')

        # Cycle controls
        elif self._match(key, modifiers, hk["RUN"]):
            self._call(config.MGR_CYCLE, 'start_cycle')
        elif self._match(key, modifiers, hk["STOP"]):
            self._call(config.MGR_CYCLE, 'stop_cycle')
        elif self._match(key, modifiers, hk["PAUSE"]):
            self._call(config.MGR_CYCLE, 'pause_cycle')
        elif self._match(key, modifiers, hk["RESUME"]):
            self._call(config.MGR_CYCLE, 'resume_cycle')
        elif self._match(key, modifiers, hk["STEP"]):
            self._call(config.MGR_CYCLE, 'step_cycle')

    def _match(self, key, current_mods, target):
        """
        Перевіряє, чи збігається натиснута клавіша з ціллю з конфігу.
        Підтримує як поодинокі клавіші, так і кортежі (клавіша, модифікатор).
        """
        if isinstance(target, tuple):
            target_key, target_mod = target
            return key == target_key and bool(current_mods & target_mod)
        else:
            return key == target and current_mods == QtCore.Qt.NoModifier

    def _call(self, mgr_key, func_name):
        """Calls the specified function from the manager identified by mgr_key, passing the current CNC states if available. It also handles cases where the manager or method might not exist."""
        manager = self.managers.get(mgr_key)
        if manager and hasattr(manager, func_name):
            method = getattr(manager, func_name)
        
            # 1. Get current CNC states if the manager has a reference to the CNC controller, otherwise pass empty dict
            states = {}
            if hasattr(manager, 'cnc'):
                states = manager.cnc.get_states()
        
            # 2. Try calling the method with states, but if it fails due to unexpected arguments (e.g., old method signature), call it without arguments
            try:
                method(states)
                print(f"DEBUG: Keyboard call {mgr_key}.{func_name}(states) successful")
            except TypeError as e:
                method()
                print(f"DEBUG: Keyboard call {mgr_key}.{func_name}() (no states)")
        else:
            print(f"DEBUG: Manager or method not found: {mgr_key}.{func_name}")