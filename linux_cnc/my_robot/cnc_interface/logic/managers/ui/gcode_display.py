# logic/managers/ui/gcode_display.py
from managers.style_manager import StyleManager
from managers.file_manager import FileManager, _LineNumScrollForwarder
from config import CYCLE_BUTTONS, FILE_BUTTONS
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtCore import QCoreApplication, QStringListModel


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

    # ------------------------------------------------------------------
    # Line-number sync helpers
    # ------------------------------------------------------------------

    def _rebuild_line_numbers(self, line_count: int) -> None:
        """
        Populate ``list_gcode_num`` with ``line_count`` sequential numbers
        and refresh the scroll synchronisation afterwards.

        This is called from :meth:`update_gcode_display` whenever the
        displayed file changes so that the sidebar always matches the code
        view without going through :class:`FileManager`.

        Args:
            line_count: Number of lines in the currently displayed file.
        """
        num_view = getattr(self.widgets, "list_gcode_num", None)
        if num_view is None:
            return

        num_model = QStringListModel()
        num_model.setStringList([str(i + 1) for i in range(line_count)])
        num_view.setModel(num_model)

        # Non-interactive: read-only, no selection, no focus
        num_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        num_view.setSelectionMode(QAbstractItemView.NoSelection)
        num_view.setFocusPolicy(num_view.NoFocus)

    # ------------------------------------------------------------------
    # Cycle / file button updates
    # ------------------------------------------------------------------

    def update_cycle_buttons(self, states):
        """Update the enabled state and styles of cycle control buttons
        (Start, Pause, Continue, Stop, Step) based on current machine
        status and file state."""
        ready      = states.get('is_ready', False) and states.get('all_homed', False)
        is_idle    = states.get('is_idle',    False)
        is_paused  = states.get('is_paused',  False)
        is_running = states.get('is_running', False)
        has_file   = states.get('has_file',   False)

        can_step     = has_file and ready and (is_idle or is_paused or is_running)
        can_continue = is_paused and not is_running
        can_pause    = is_running and ready

        conditions = {
            'btn_cycle_start':    is_idle and has_file and ready,
            'btn_cycle_pause':    can_pause,
            'btn_cycle_continue': can_continue,
            'btn_cycle_stop':     (is_running or is_paused) and ready,
            'btn_cycle_step':     can_step,
        }

        for btn_name in self.cycle_buttons:
            self._set_btn_state(btn_name, conditions.get(btn_name, False))

    def update_file_buttons(self, states):
        """Update the state and style of file management buttons based on
        machine state and file status."""
        is_idle  = states.get('is_idle', True)
        has_file = bool(self.cnc.get_last_file())
        is_ready = states.get('is_ready', False)

        can_open        = is_idle and is_ready
        can_edit_reload = is_idle and has_file and is_ready

        has_content = False
        gcode_view  = getattr(self.widgets, 'list_gcode_view', None)
        if gcode_view and gcode_view.model():
            has_content = gcode_view.model().rowCount() > 0
        can_save = is_idle and has_content and is_ready

        conditions = {
            'btn_file_open':    can_open,
            'btn_file_edit':    can_edit_reload,
            'btn_file_reload':  can_edit_reload,
            'btn_file_save_as': can_save,
        }

        for btn_name in ['btn_file_open', 'btn_file_edit',
                         'btn_file_reload', 'btn_file_save_as']:
            btn = getattr(self.widgets, btn_name, None)
            if not btn:
                continue

            is_enabled = conditions.get(btn_name, False)

            if btn.isEnabled() != is_enabled:
                btn.setEnabled(is_enabled)

            if not is_enabled:
                target_style = self.style_manager.STYLE_GCODE_INACTIVE
            elif btn_name == 'btn_file_reload' and getattr(self.cnc, 'reload_needed', False):
                target_style = self.style_manager.STYLE_GCODE_WARN
            else:
                target_style = self.style_manager.STYLE_GCODE_ACTIVE

            if btn.styleSheet() != target_style:
                btn.setStyleSheet(target_style)

    # ------------------------------------------------------------------
    # Active G-code status bar
    # ------------------------------------------------------------------

    def update_active_gcodes(self, states):
        """Update the G-code status bar to show active G-codes, M-codes,
        and current feed/spindle settings based on machine state."""
        status_bar = getattr(self.widgets, 'txt_gcodeStatusBar', None)
        if not status_bar:
            return

        active_gcodes = []
        for code in states.get('gcodes', []):
            if code == -1:
                continue
            active_gcodes.append(f"G{code / 10.0:g}")

        active_mcodes = []
        for m_code in states.get('mcodes', []):
            if m_code == -1:
                continue
            active_mcodes.append(f"M{m_code}")

        settings = states.get('settings', [0, 0, 0])
        f_set    = settings[1]
        s_set    = settings[2]

        g_str       = " ".join(active_gcodes)
        m_str       = " ".join(active_mcodes)
        fs_str      = f"F{f_set:.0f} S{s_set:.0f}"
        full_status = f"{g_str} | {m_str} | {fs_str}"

        if status_bar.text() != full_status:
            status_bar.setText(full_status)

    # ------------------------------------------------------------------
    # G-code display panel
    # ------------------------------------------------------------------

    def update_gcode_display(self, states):
        """Update the G-code display panel: load a new file when it
        changes, highlight the active line during execution, synchronise
        the line-number sidebar, and update the progress label."""
        current_file = states.get('current_file')
        is_idle      = states.get('is_idle', True)
        motion_line  = states.get('motion_line', 0)

        gcode_view = getattr(self.widgets, 'list_gcode_view', None)

        # 1. React to file changes ----------------------------------------
        if not current_file:
            if self.last_loaded_file is not None:
                self.last_loaded_file = None
                lbl = getattr(self.widgets, 'lbl_filename', None)
                if lbl:
                    lbl.setText("No file")
                if gcode_view:
                    gcode_view.setModel(None)
                # Clear the number sidebar as well
                num_view = getattr(self.widgets, 'list_gcode_num', None)
                if num_view:
                    num_view.setModel(None)

        elif current_file != self.last_loaded_file:
            self.last_loaded_file = current_file
            if hasattr(self, 'file_manager'):
                # FileManager._load_gcode_to_view already calls
                # _sync_line_numbers, so the sidebar is populated there.
                self.file_manager._load_gcode_to_view(current_file)

        # 2. Highlight active line & sync the number sidebar scroll -------
        if gcode_view:
            model = gcode_view.model()
            if model and model.rowCount() > 0:

                # Rebuild the sidebar only when the row count changed
                # (avoids the overhead on every polling cycle).
                num_view = getattr(self.widgets, 'list_gcode_num', None)
                if num_view is not None:
                    num_model = num_view.model()
                    if num_model is None or num_model.rowCount() != model.rowCount():
                        self._rebuild_line_numbers(model.rowCount())

                # Edit triggers: allow editing only when idle
                if is_idle:
                    triggers = (QAbstractItemView.DoubleClicked
                                | QAbstractItemView.EditKeyPressed
                                | QAbstractItemView.AnyKeyPressed)
                else:
                    triggers = QAbstractItemView.NoEditTriggers

                gcode_view.setEditTriggers(triggers)

                # Scroll to and highlight the executing line
                if not is_idle:
                    if 0 <= motion_line < model.rowCount():
                        index = model.index(motion_line, 0)
                        gcode_view.setCurrentIndex(index)
                        # PositionAtCenter keeps the active line visible;
                        # the num_view scrollbar follows via valueChanged.
                        gcode_view.scrollTo(index, QAbstractItemView.PositionAtCenter)

                # 3. Progress label ----------------------------------------
                lbl_progress = getattr(self.widgets, 'lbl_progress_percent', None)
                if lbl_progress:
                    total_lines  = model.rowCount()
                    current_line = motion_line + 1

                    if is_idle and motion_line <= 0:
                        percent = 0
                    elif is_idle and motion_line >= total_lines - 2:
                        percent = 100
                    else:
                        percent = int((current_line / total_lines) * 100)
                        percent = min(100, max(0, percent))

                    template     = QCoreApplication.translate("MainWindow", "PROGRESS %1%")
                    display_text = template.replace("%1", str(percent))
                    lbl_progress.setText(display_text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_btn_state(self, btn_name: str, is_enabled: bool) -> None:
        """Activate/deactivate a button and apply the appropriate style."""
        btn = getattr(self.widgets, btn_name, None)
        if btn:
            btn.setEnabled(is_enabled)
            btn.setStyleSheet(
                self.style_manager.STYLE_GCODE_ACTIVE
                if is_enabled
                else self.style_manager.STYLE_GCODE_INACTIVE
            )
