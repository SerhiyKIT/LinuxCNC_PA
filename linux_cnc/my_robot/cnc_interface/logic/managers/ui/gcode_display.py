# logic/managers/ui/gcode_display.py
from managers.style_manager import StyleManager
from managers.file_manager import FileManager
from config import CYCLE_BUTTONS, FILE_BUTTONS
from PyQt5.QtWidgets import QAbstractItemView

class GCodeDisplayManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        # Track the last loaded file to detect changes
        self.last_loaded_file = self.cnc.get_last_file()
        
         # Cycle buttons
        self.cycle_buttons = CYCLE_BUTTONS
        
        # File buttons
        self.file_buttons = FILE_BUTTONS
        
        # Initialize state variables
        self.file_manager = FileManager(self.cnc, self.widgets)
        
        self.style_manager = StyleManager()
        self.style_manager._set_gcode_button_styles()
        
    def update_cycle_buttons(self, states):
        """Update the enabled state and styles of cycle control buttons (Start, Pause, Continue, Stop, Step) based on current machine status and file state"""
        ready = states.get('is_ready', False) and states.get('all_homed', False)
        is_idle = states.get('is_idle', False)
        is_idle = states.get('is_idle', False)
        is_paused = states.get('is_paused', False)
        is_running = states.get('is_running', False)
        has_file = states.get('has_file', False)

        # 1. START and STEP buttons can only be active if we have a file loaded, machine is ready, and we are either idle, paused, or running (for step)
        can_step = has_file and ready and (is_idle or is_paused or is_running)

        # 2. CONTINUE can only be active if we are currently paused and machine is ready (we allow continue from paused state even if not idle, to let users resume after a pause)
        can_continue = is_paused and not is_running

        # 3. PAUSE can only be active if we are currently running and machine is ready
        can_pause = is_running and ready

        conditions = {
            'btn_cycle_start':    is_idle and has_file and ready,
            'btn_cycle_pause':    can_pause,
            'btn_cycle_continue': can_continue,
            'btn_cycle_stop':     (is_running or is_paused) and ready,
            'btn_cycle_step':     can_step
        }

        for btn_name in self.cycle_buttons:
            self._set_btn_state(btn_name, conditions.get(btn_name, False))
            
    def update_file_buttons(self, states):
        """Update the state and style of file management buttons based on machine state and file status"""
        is_idle = states.get('is_idle', True)
        has_file = bool(self.cnc.get_last_file())
        is_ready = states.get('is_ready', False) 

        # 1. Determine conditions for each file button
    
        can_open = is_idle and is_ready
    
        can_edit_reload = is_idle and has_file and is_ready
    
        has_content = False
        gcode_view = getattr(self.widgets, 'list_gcode_view', None)
        if gcode_view and gcode_view.model():
            has_content = gcode_view.model().rowCount() > 0
        can_save = is_idle and has_content and is_ready

        # 2. Update button states and styles based on conditions
        conditions = {
            'btn_file_open':    can_open,
            'btn_file_edit':    can_edit_reload,
            'btn_file_reload':  can_edit_reload,
            'btn_file_save_as': can_save
        }

        file_buttons = ['btn_file_open', 'btn_file_edit', 'btn_file_reload', 'btn_file_save_as']

        for btn_name in file_buttons:
            btn = getattr(self.widgets, btn_name, None)
            if not btn:
                continue
        
            is_enabled = conditions.get(btn_name, False)

            if btn.isEnabled() != is_enabled:
                btn.setEnabled(is_enabled)

            # 3. Apply styles based on enabled state and specific conditions (e.g., reload warning)
            target_style = ""
        
            if not is_enabled:
                target_style = self.style_manager.STYLE_GCODE_INACTIVE
            else:
                if btn_name == 'btn_file_reload' and getattr(self.cnc, 'reload_needed', False):
                    target_style = self.style_manager.STYLE_GCODE_WARN
                else:
                    target_style = self.style_manager.STYLE_GCODE_ACTIVE

            if btn.styleSheet() != target_style:
                btn.setStyleSheet(target_style)
            
    def update_active_gcodes(self, states):
        """Upddate the G-code status bar to show active G-codes, M-codes, and current feed/spindle settings based on machine state"""
        status_bar = getattr(self.widgets, 'txt_gcodeStatusBar', None)
        if not status_bar:
            return

        # 1. Extract active G-codes and format them as strings (e.g., G0, G1, G2, etc.)
        active_gcodes = []
        for code in states.get('gcodes', []):
            if code == -1: continue
            g_prefix = f"G{code/10.0:g}"
            active_gcodes.append(g_prefix)
    
        # 2. Extract active M-codes and format them as strings (e.g., M3, M5, etc.)
        active_mcodes = []
        for m_code in states.get('mcodes', []):
            if m_code == -1: continue
            active_mcodes.append(f"M{m_code}")

        # 3. Extract current feed and spindle speed settings from the machine state and format them for display
        settings = states.get('settings', [0, 0, 0])
        f_set = settings[1]
        s_set = settings[2]
    
        # Combine all the information into a single status string to display in the G-code status bar
        g_str = " ".join(active_gcodes)
        m_str = " ".join(active_mcodes)
        fs_str = f"F{f_set:.0f} S{s_set:.0f}"

        # 4. Final combined status string that includes active G-codes, M-codes, and feed/spindle settings
        full_status = f"{g_str} | {m_str} | {fs_str}"
    
        # Only update the status bar text if it has changed to avoid unnecessary UI updates
        if status_bar.text() != full_status:
            status_bar.setText(full_status)
            
    def update_gcode_display(self, states):
        """"Update the G-code display panel to show the currently loaded G-code file, highlight the active line during execution, and calculate progress percentage based on the current line and total lines in the file."""
        current_file = states.get('current_file')
        is_idle = states.get('is_idle', True)
        motion_line = states.get('motion_line', 0)
    
        gcode_view = getattr(self.widgets, 'list_gcode_view', None)

        # 1. Check if the loaded file has changed and update the G-code view accordingly. If no file is loaded, clear the view and reset the filename label. If a new file is loaded, use the FileManager to load its contents into the G-code view. This ensures that the G-code display always reflects the currently active file in the machine controller.
        if not current_file:
            if self.last_loaded_file is not None:
                self.last_loaded_file = None
                lbl = getattr(self.widgets, 'lbl_filename', None)
                if lbl: lbl.setText("No file")
                if gcode_view: gcode_view.setModel(None)
    
        elif current_file != self.last_loaded_file:
            self.last_loaded_file = current_file
            if hasattr(self, 'file_manager'):
                self.file_manager._load_gcode_to_view(current_file)
        # 2. Highlight the active line in the G-code view during execution (when not idle) and ensure the active line is scrolled into view. When idle, disable editing in the G-code view to prevent changes while a program is loaded but not running, and re-enable editing when idle to allow users to make changes before starting execution.
        if gcode_view:
            model = gcode_view.model()
            if model and model.rowCount() > 0:
                if is_idle:
                    triggers = QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed
                else:
                    triggers = QAbstractItemView.NoEditTriggers
            
                gcode_view.setEditTriggers(triggers)
                
                if not is_idle:
                    if 0 <= motion_line < model.rowCount():
                        index = model.index(motion_line, 0)
                        gcode_view.setCurrentIndex(index)
                        gcode_view.scrollTo(index, QAbstractItemView.PositionAtCenter)

                # 3. Calculate and update the progress percentage based on the current motion line and total lines in the G-code file, and display it in the progress label. The progress is calculated as (current_line / total_lines) * 100, and is only updated when we are not idle to reflect actual execution progress. When idle, the progress is shown as 0% or 100% based on whether we are before the first line or after the last line, respectively.
                lbl_progress = getattr(self.widgets, 'lbl_progress_percent', None)
                if lbl_progress:
                    total_lines = model.rowCount()
                    current_line = motion_line + 1
                
                    if is_idle and motion_line <= 0:
                        percent = 0
                    elif is_idle and motion_line >= total_lines - 2:
                        percent = 100
                    else:
                        percent = int((current_line / total_lines) * 100)
                        percent = min(100, max(0, percent))
                
                    lbl_progress.setText(f"PROGRESS {percent}%")

    def _set_btn_state(self, btn_name, is_enabled):
        """Activate/deactivate a button and apply appropriate style based on its state"""
        btn = getattr(self.widgets, btn_name, None)
        if btn:
            btn.setEnabled(is_enabled)
            btn.setStyleSheet(
                self.style_manager.STYLE_GCODE_ACTIVE if is_enabled else self.style_manager.STYLE_GCODE_INACTIVE
            )