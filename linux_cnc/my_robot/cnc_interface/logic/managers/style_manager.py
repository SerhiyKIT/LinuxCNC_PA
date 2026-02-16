# logic/managers/style_manager.py
from config import STYLES

class StyleManager:
    def __init__(self):
        self._set_styles()

    def _set_styles(self):
        """Initialize all style attributes by delegating to smaller setup methods."""
        self._set_emergency_stop_styles()
        self._set_power_styles()
        self._set_homing_styles()
        self._set_jogging_styles()
        self._set_gcode_button_styles()
        self._set_panel_styles()
        self._set_dialog_and_list_styles()
        self._set_tool_and_gripper_styles()
        self._set_logger_styles()

    def _set_emergency_stop_styles(self):
        self.STYLE_ESTOP_OFF = STYLES['ESTOP_OFF']
        self.STYLE_ESTOP_ON = STYLES['ESTOP_ON']

    def _set_power_styles(self):
        self.STYLE_POWER_OFF = STYLES['POWER_OFF']
        self.STYLE_POWER_ON = STYLES['POWER_ON']

    def _set_homing_styles(self):
        self.STYLE_HOME_INACTIVE = STYLES['HOME_INACTIVE']
        self.STYLE_HOME_READY = STYLES['HOME_READY']

    def _set_jogging_styles(self):
        self.STYLE_JOG_ACTIVE = STYLES['JOG_ACTIVE']
        self.STYLE_JOG_LIMITED = STYLES['JOG_LIMITED']

    def _set_gcode_button_styles(self):
        self.STYLE_GCODE_INACTIVE = STYLES['GCODE_INACTIVE']
        self.STYLE_GCODE_ACTIVE = STYLES['GCODE_ACTIVE']
        self.STYLE_GCODE_WARN = STYLES['GCODE_WARN']

    def _set_panel_styles(self):
        self.PANEL_FRAME_INACTIVE = STYLES['PANEL_FRAME_INACTIVE']
        self.PANEL_FRAME_ACTIVE = STYLES['PANEL_FRAME_ACTIVE']
        self.PANEL_LABEL_INACTIVE = STYLES['PANEL_LABEL_INACTIVE']
        self.PANEL_LABEL_ACTIVE = STYLES['PANEL_LABEL_ACTIVE']

    def _set_dialog_and_list_styles(self):
        self.STYLE_MSGBOX = STYLES['MSGBOX']
        self.STYLE_GCODE_LIST = STYLES['GCODE_LIST']
        self.STYLE_OUTPUT_VIEW = STYLES.get('STYLE_OUTPUT_VIEW', '')

    def _set_tool_and_gripper_styles(self):
        self.STYLE_TOOL_ARMED = STYLES['TOOL_ARMED']
        self.STYLE_TOOL_DISARMED = STYLES['TOOL_DISARMED']
        self.STYLE_GRIP_ACTIVE = STYLES['GRIP_ACTIVE']
        self.STYLE_GRIP_INACTIVE = STYLES['GRIP_INACTIVE']

    def _set_logger_styles(self):
        self.STYLE_COPY_BTN = STYLES.get('COPY_BTN', '')
        self.STYLE_SEPARATOR_LINE = STYLES.get('SEPARATOR_LINE', '')
        self.STYLE_CLIPBOARD = STYLES.get('CLIPBOARD', '')
        self.STYLE_MSG_TEXT = STYLES.get('MSG_TEXT', '')
        
        