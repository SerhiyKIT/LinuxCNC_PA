# logic/managers/ui_manager.py
from PyQt5 import QtWidgets, QtCore
from datetime import datetime
from config import STYLES, FILE_BUTTONS, CYCLE_BUTTONS

class UIManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        
        # State for manual panel selection (joint vs axis)
        self.manual_panel_selection = self.cnc.manual_mode
        
        # State to track if homing complete message has been shown
        self.last_joint_pos = {}
        
        # Limits and parameters from the machine controller
        self.limits = self.cnc.limits
        
        # Cycle buttons
        self.cycle_buttons = CYCLE_BUTTONS
        
        # File buttons
        self.file_buttons = FILE_BUTTONS
        
        # Preload styles for different states
        self.STYLE_ESTOP_ON = STYLES.get('ESTOP_ON', '')
        self.STYLE_ESTOP_OFF = STYLES.get('ESTOP_OFF', '')
        self.STYLE_POWER_ON = STYLES.get('POWER_ON', '')
        self.STYLE_POWER_OFF = STYLES.get('POWER_OFF', '')
        self.STYLE_HOME_READY = STYLES.get('HOME_READY', '')
        self.STYLE_HOME_INACTIVE = STYLES.get('HOME_INACTIVE', '')
        self.STYLE_PANEL_ACTIVE = STYLES.get('PANEL_ACTIVE', '')
        self.STYLE_PANEL_INACTIVE = STYLES.get('PANEL_INACTIVE', '')
        self.PANEL_LABEL_ACTIVE = STYLES.get('PANEL_LABEL_ACTIVE', '')
        self.PANEL_LABEL_INACTIVE = STYLES.get('PANEL_LABEL_INACTIVE', '')
        self.PANEL_FRAME_ACTIVE = STYLES.get('PANEL_FRAME_ACTIVE', '')
        self.PANEL_FRAME_INACTIVE = STYLES.get('PANEL_FRAME_INACTIVE', '')
        self.STYLE_GCODE_ACTIVE = STYLES.get('GCODE_ACTIVE', '')
        self.STYLE_GCODE_INACTIVE = STYLES.get('GCODE_INACTIVE', '')
        self.JOG_ACTIVE = STYLES.get('JOG_ACTIVE', '')
        self.JOG_LIMITED = STYLES.get('JOG_LIMITED', '')
        self.OUTPUT_VIEW = STYLES.get('STYLE_OUTPUT_VIEW', '')
        self.STYLE_COPY_BTN = STYLES.get('STYLE_COPY_BTN', '')
        self.SEPARATOR_LINE = STYLES.get('SEPARATOR_LINE', '')
        self.CLIPBOARD = STYLES.get('CLIPBOARD', '')
        self.MSG_TEXT = STYLES.get('MSG_TEXT', '')
        

    def update_ui(self, states):
        """Main method to update all UI elements based on the current machine status"""
        try:
            self._update_coordinates(states)
            self._update_status_display(states)
            self._update_machine_state(states)
            self._update_home_button_state(states)
            self._update_manual_controls(states)
            self._update_gcode_controls(states)
            self._update_cycle_buttons(states)
            self._update_file_buttons(states)
        except Exception as e:
            print(f"DEBUG UI Error: {e}")

    def _update_coordinates(self, states):
        """Update the coordinate displays (joint and world) based on current machine state"""
        j_pos = states.get('joint_position', [])
        actual_pos = states.get('actual_position', [])
        
        # 1. Update Joint positions
        for i in range(min(6, len(j_pos))):
            val = j_pos[i]
            label = getattr(self.widgets, f"txt_j{i}_pos", None)
            
            if label:
                prev = self.last_joint_pos.get(i, None)
                
                if prev is None or abs(val - prev) > 0.0005:
                    label.setText(f"{val:.4f}")
                    self.last_joint_pos[i] = val
        
        # Call soft limit handler to update jog button states based on joint positions and limits
        self._handle_joint_soft_limits(states)

        # 2. Update World positions
        axes = ['x', 'y', 'z', 'a', 'b', 'c']
        for i, axis in enumerate(axes):
            val = actual_pos[i] if i < len(actual_pos) else 0.0
            w = getattr(self.widgets, f'txt_{axis}_pos', None)
            
            if w:
                storage_key = f"world_{axis}"
                prev_w = self.last_joint_pos.get(storage_key, None)
                
                if prev_w is None or abs(val - prev_w) > 0.0005:
                    w.setText(f"{val:.4f}")
                    self.last_joint_pos[storage_key] = val
                
    def _update_machine_state(self, states):
        """Update the visual state of machine control buttons (E-Stop, Power) based on current status"""
        estop_active = (states['estop_off'] == False)
        power_on = (states['power_on'] == True)

        # Update E-Stop button
        btn_estop = getattr(self.widgets, 'btn_estop', None)
        if btn_estop:
            style = self.STYLE_ESTOP_ON if estop_active else self.STYLE_ESTOP_OFF
            btn_estop.setStyleSheet(style)

        # Update Power button
        btn_power = getattr(self.widgets, 'btn_power_off', None)
        if btn_power:
            btn_power.setEnabled(not estop_active)
            
            is_active = power_on and not estop_active
            style = self.STYLE_POWER_ON if is_active else self.STYLE_POWER_OFF
            
            btn_power.setStyleSheet(style)
            btn_power.setText("ON" if is_active else "OFF")
            
    def _update_status_display(self, states):
        """Update the main status display text based on machine state (E-Stop, Power, Homing)"""
        txt_display = getattr(self.widgets, 'txt_status_display', None)
        if not txt_display:
            return
        
        if states['estop_off'] == False:
            msg = "EMERGENCY STOP"
        elif not states['power_on']:
            msg = "POWER OFF"
        elif not states['all_homed']:
            msg = "HOMING REQUIRED"
        else:
            msg = "SYSTEM READY"

        txt_display.setText(msg)

    def _update_home_button_state(self, states):
        """Update the state and style of the 'Home All' button based on machine readiness"""
        btn = getattr(self.widgets, 'btn_home_all', None)
        if btn:
            btn.setEnabled(states['is_ready'])
            
            style = self.STYLE_HOME_READY if states['is_ready'] else self.STYLE_HOME_INACTIVE
            btn.setStyleSheet(style)

    def _update_manual_controls(self, states):
        """Logic to show/hide manual control panels based on machine state and homing status"""
        show_joints = False
        show_axis = False

        current_mode = states.get('manual_mode', 'axis')

        if states['is_ready'] and not states['is_running']:
            if not states['all_homed']:
                show_joints = True 
            else:
                show_joints = (current_mode == "joint")
                show_axis = (current_mode == "axis")
                
        self._apply_panel_style('joint_control', show_joints)
        if hasattr(self.widgets, 'joint_control_overlay'):
            self.widgets.joint_control_overlay.setVisible(not show_joints)

        self._apply_panel_style('axis_control', show_axis)
        if hasattr(self.widgets, 'axis_control_overlay'):
            self.widgets.axis_control_overlay.setVisible(not show_axis)
    
    def _update_gcode_controls(self, states):
        """Update G-code control panel based on machine state (Power, E-Stop)"""
        is_ready = states['is_ready'] #and states['all_homed']
        
        # 1. Style the entire G-code control panel
        self._apply_panel_style('gcode_control', is_ready)
        
        # 2. Optionally show an overlay to block interaction when not ready
        if hasattr(self.widgets, 'gcode_control_overlay'):
            self.widgets.gcode_control_overlay.setVisible(not is_ready)


    def _update_cycle_buttons(self, states):
        """Logic to enable/disable cycle control buttons based on machine state"""
        ready = states['is_ready'] and states['all_homed']
        
        conditions = {
            'btn_cycle_start':    states['is_idle'] and states['has_file'] and ready,
            'btn_cycle_pause':    states['is_running'] and ready,
            'btn_cycle_continue': states['is_paused'] and ready,
            'btn_cycle_stop':     (states['is_running'] or states['is_paused']) and ready,
            'btn_cycle_step':     states['has_file'] and ready and (states['is_idle'] or states['is_paused'])
        }

        for btn_name in self.cycle_buttons:
            self._set_btn_state(btn_name, conditions.get(btn_name, False))
            
    def _update_file_buttons(self, states):
        """Update file-related buttons (Open, Edit, Reload, Save As) based on machine state and file status"""
        is_idle = states['is_idle']
        has_file = states['has_file']
        is_ready = states['is_ready'] # Power ON + No E-Stop

        # 1. Specify conditions for each file button
        
        # Open File: can open if machine is idle and ready (power on + no E-Stop)
        can_open = is_idle and is_ready
        
        # Edit / Reload: can edit/reload if machine is idle, has a file loaded, and is ready
        can_edit_reload = is_idle and has_file and is_ready
        
        # Save As: check if there's content to save
        has_content = False
        gcode_view = getattr(self.widgets, 'list_gcode_view', None)
        if gcode_view and gcode_view.model():
            has_content = gcode_view.model().rowCount() > 0
        can_save = is_idle and has_content and is_ready

        # 2. Update buttons based on conditions
        conditions = {
            'btn_file_open':    can_open,
            'btn_file_edit':    can_edit_reload,
            'btn_file_reload':  can_edit_reload,
            'btn_file_save_as': can_save
        }

        for btn_name in self.file_buttons:
            btn = getattr(self.widgets, btn_name, None)
            if not btn:
                continue
            
            is_enabled = conditions.get(btn_name, False)
            btn.setEnabled(is_enabled)

            # Special case for Reload: if enabled but reload is needed, show warning style
            if btn_name == 'btn_file_reload' and is_enabled and getattr(self, 'reload_needed', False):
                style = self.STYLE_GCODE_WARN
            else:
                style = self.STYLE_GCODE_ACTIVE if is_enabled else self.STYLE_GCODE_INACTIVE
            
            btn.setStyleSheet(style)

    def _set_btn_state(self, btn_name, is_enabled):
        """Activate/deactivate a button and apply appropriate style based on its state"""
        btn = getattr(self.widgets, btn_name, None)
        if btn:
            btn.setEnabled(is_enabled)
            btn.setStyleSheet(
                self.STYLE_GCODE_ACTIVE if is_enabled else self.STYLE_GCODE_INACTIVE
            )
    
    def _handle_joint_soft_limits(self, states):
        """Check joint positions against soft limits and disable/enable jog buttons accordingly"""
        if not states['is_ready']:
            return

        j_pos = states['joint_position']
        
        style_active = self.JOG_ACTIVE
        style_limited = self.JOG_LIMITED

        for i in range(min(6, len(j_pos))):
            limits = self.limits.get(i)
            if not limits: continue
            
            curr_pos = j_pos[i]

            # 1. Determine if we are at or beyond limits and update button states and styles
            btn_plus = getattr(self.widgets, f"btn_j{i}_plus", None)
            btn_minus = getattr(self.widgets, f"btn_j{i}_minus", None)
            
            if btn_plus:
                at_max = curr_pos >= limits["max"]
                btn_plus.setEnabled(not at_max)
                btn_plus.setStyleSheet(style_limited if at_max else style_active)
                
            if btn_minus:
                at_min = curr_pos <= limits["min"]
                btn_minus.setEnabled(not at_min)
                btn_minus.setStyleSheet(style_limited if at_min else style_active)
    
    def _apply_panel_style(self, prefix, is_active):
        """
        Complex method to update the style of a panel group (main panel, label, frame) based on a common prefix.
        """
        # 1. Basic panel (QWidget group)
        panel = getattr(self.widgets, prefix, None)
        if panel:
            panel.setEnabled(is_active)
            panel.setStyleSheet(self.STYLE_PANEL_ACTIVE if is_active else self.STYLE_PANEL_INACTIVE)

        # 2. Title label of the panel
        lbl = getattr(self.widgets, f"lbl_{prefix}", None)
        if lbl:
            lbl.setStyleSheet(self.PANEL_LABEL_ACTIVE if is_active else self.PANEL_LABEL_INACTIVE)

        # 3. Border frame of the panel
        frm = getattr(self.widgets, f"frm_{prefix}", None)
        if frm:
            frm.setStyleSheet(self.PANEL_FRAME_ACTIVE if is_active else self.PANEL_FRAME_INACTIVE)

    def setup_output_panel(self):
        """Initial setup for the output log panel to ensure it has the correct styles and behavior for displaying log messages."""
        view = self.widgets.list_output_view
        view.setStyleSheet(self.OUTPUT_VIEW)
        view.setSpacing(0)
        view.setContentsMargins(0, 0, 0, 0)
        
        if hasattr(view, 'viewport'):
            view.viewport().setContentsMargins(0, 0, 0, 0)
            
        view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

    def log_message(self, message, level="info"):
        """Log a message to the output panel with a timestamp and appropriate styling based on the message level (info, warning, error)."""
        if not hasattr(self.widgets, 'list_output_view'):
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {"info": "#DCDCDC", "warning": "#FE5C0D", "error": "#FF0000"}
        color = colors.get(level, "#FFFFFF")
        full_log_text = f"[{timestamp}] {level.upper()}: {message}"

        # Create a custom widget for the log entry
        item = QtWidgets.QListWidgetItem(self.widgets.list_output_view)
        container = QtWidgets.QWidget()
        container.setObjectName("logContainer")
        container.setStyleSheet("#logContainer { background: transparent; border: none; }")
        
        v_layout = QtWidgets.QVBoxLayout(container)
        v_layout.setContentsMargins(5, 2, 5, 2)
        v_layout.setSpacing(0)

        h_layout = QtWidgets.QHBoxLayout()
        h_layout.setSpacing(10)

        # Styled label for the log message
        label = QtWidgets.QLabel(
            f'<span style="color: #666666;">[{timestamp}]</span> '
            f'<b style="color: {color};">{level.upper()}:</b> {message}'
        )
        label.setWordWrap(True)
        # Fix the width to prevent it from expanding indefinitely and ensure proper text wrapping within the output panel
        label.setFixedWidth(self.widgets.list_output_view.width() - 60)
        label.setStyleSheet(self.MSG_TEXT)
        
        # Copy button to copy the log message to clipboard
        btn_copy = QtWidgets.QPushButton("📋")
        btn_copy.setFixedSize(24, 24)
        btn_copy.setCursor(QtCore.Qt.PointingHandCursor)
        btn_copy.setStyleSheet(self.STYLE_COPY_BTN)
        
        btn_copy.clicked.connect(lambda: self._copy_to_clipboard(full_log_text, btn_copy))

        h_layout.addWidget(label, 1)
        h_layout.addWidget(btn_copy, 0)
        v_layout.addLayout(h_layout)

        # Separator line below each log entry for better visual separation
        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(self.SEPARATOR_LINE)
        v_layout.addWidget(line)

        self.widgets.list_output_view.addItem(item)
        self.widgets.list_output_view.setItemWidget(item, container)
        item.setSizeHint(container.sizeHint())
        self.widgets.list_output_view.scrollToBottom()

    def _copy_to_clipboard(self, text, button):
        """"Copy the provided text to the system clipboard and provide visual feedback on the copy button"""
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        
        old_text = button.text()
        button.setText("✓")
        button.setStyleSheet(self.CLIPBOARD)
        QtCore.QTimer.singleShot(1000, lambda: self._reset_copy_button(button, old_text))

    def _reset_copy_button(self, button, old_text):
        """"Reset the copy button to its original state after showing feedback"""
        button.setText(old_text)
        button.setStyleSheet(STYLES.get('STYLE_COPY_BTN', ""))