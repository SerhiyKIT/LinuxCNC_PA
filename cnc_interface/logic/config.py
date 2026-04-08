import os
import linuxcnc

from PyQt5.QtCore import Qt

# --- INI FILE ---
INI_PATH = os.environ.get('INI_FILE_NAME')
INI_FILE = linuxcnc.ini(INI_PATH) if INI_PATH else None

# --- DEFAULTS ---
DEFAULT_MANUAL_MODE = "axis"

# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME_QSS_PATH = os.path.join(BASE_DIR, 'styles', 'theme.qss')

# --- UTILITY FUNCTIONS ---
def get_ini_val(section, key, default, val_type=float):
    """
    Safely get values from INI file.
    """
    if not INI_FILE:
        return default
    try:
        val = INI_FILE.find(section, key)
        return val_type(val) if val is not None else default
    except Exception:
        return default
    
# --- JOINT LIMITS ---
def get_joint_limits(num_joints=6):
    """
    Dynamically creates a dictionary of min/max limits for each joint from INI.
    """
    limits = {}
    for i in range(num_joints):
        limits[i] = {
            "min": get_ini_val(f"JOINT_{i}", "MIN_LIMIT", -360.0),
            "max": get_ini_val(f"JOINT_{i}", "MAX_LIMIT", 360.0)
        }
    return limits

# --- MACHINE PARAMETERS ---
MACHINE_PARAMS = {
    "POLL_INTERVAL": 100,
    
    # Linear velocities from TRAJ
    "LINEAR_VEL":         get_ini_val("TRAJ", "DEFAULT_LINEAR_VELOCITY", 5.0),
    "MAX_LINEAR_VEL":     get_ini_val("TRAJ", "MAX_LINEAR_VELOCITY", 30.0),
    
    # Angular velocities
    "ANGULAR_VEL":        get_ini_val("DISPLAY", "DEFAULT_ANGULAR_VELOCITY", 36.0),
    "MAX_ANGULAR_VEL":    get_ini_val("AXIS_A", "MAX_VELOCITY", 30.0),
    
    # Increments for jogging
    "JOG_MODES":     ["Continuous", "1.0000", "0.1000", "0.0100", "0.0010"],
    
    # Number of joints (from [KINS])
    "JOINTS_COUNT":       int(get_ini_val("KINS", "JOINTS", 6, val_type=float)),
    
    # Kinematics parameters
    "TELEOP_ENABLE": 0,
    "JOG_CMD_FLAG":  1
}

# --- DYNAMIC LIMITS OBJECT ---
JOINT_LIMITS = get_joint_limits(MACHINE_PARAMS["JOINTS_COUNT"])

# --- CYCLE CONTROL BUTTONS ---
CYCLE_BUTTONS = [
    'btn_cycle_start',
    'btn_cycle_pause',
    'btn_cycle_continue',
    'btn_cycle_stop',
    'btn_cycle_step'
]

# --- EDITOR ---
EDITOR = {
    "AUTOSAVE_DELAY_MS": 800,
    "EDITABLE_EXTS":     (".txt", ".ini", ".xml", ".json", ".parl"),
}

# --- SLIDER CONFIGS ---
SLIDER_CONFIGS = {
    'sld_feed_override': (0, 200),
    'sld_rapid_override': (0, 100),
    'sld_spindle_override': (0, 200),
    'sld_linear_jog_speed': (1, 593000),
    'sld_angular_jog_speed': (1, 605900),
    'sld_max_velocity': (0, 600)
}

# --- MANAGER KEYS ---
MGR_CONTROL = "control"
MGR_CYCLE   = "cycle"
MGR_TOOL    = "tool"
MGR_FILE    = "file"

# --- HOTKEYS ---
HOTKEYS = {
    # System commands
    "ESTOP":         Qt.Key_F1,
    "POWER":         Qt.Key_F2,
    "HOME_ALL":      (Qt.Key_Home, Qt.ControlModifier),
    
    # File commands
    "OPEN_FILE":     Qt.Key_O,
    "SAVE_AS":       (Qt.Key_S, Qt.ControlModifier),
    "RELOAD":        (Qt.Key_R, Qt.ControlModifier),
    
    # Execution commands
    "RUN":           Qt.Key_R,
    "STEP":          Qt.Key_T,
    "PAUSE":         Qt.Key_P,
    "RESUME":        Qt.Key_S,
    "STOP":          Qt.Key_Escape,
}

# --- COLORS ---
COLORS = {
    # Accent colors
    "ACCENT": "#FE5C0D",          
    "ACCENT_HOVER": "#FF7533",    
    "ACCENT_BORDER": "#FEAE0D",   
    
    # Status colors
    "DANGER": "#FF0000",          
    "DANGER_HOVER": "#F50000",   
    "DANGER_SOFT": "#FF6161",     
    
    # Background colors
    "BG_MAIN": "#121212",        
    "BG_LIST": "#161616",         
    "BG_PANEL": "#1A1A1A",       
    "BG_WIDGET": "#2D2D2D",       
    "BG_BTN_DEFAULT": "#333333", 
    "BG_BTN_HOVER": "#5B5B5B",    
    "BG_TRANSPARENT": "transparent",
    
    # Text colors
    "TEXT_MAIN": "#FFFFFF",       
    "TEXT_INACTIVE": "#9E9E9E",   
    "TEXT_LIGHT_GRAY": "#F1F1F1", 
    "TEXT_DISABLED": "#DCDCDC",
    "TEXT_GREEN": "#00FF00",
    
    # Special colors
    "BORDER_DEFAULT": "#333333",  
    "SCROLLBAR_BG": "#333333",   
    "EDIT_MODE_ITALIC": "#FE5C0D",
    "LOGGER_BORDER": "#444444",
    "LOGGER_TEXT": "#888888"
}

STYLES = {
    # --- Emergency Stop ---
    'ESTOP_OFF': f"QPushButton {{ background-color: {COLORS['DANGER']}; color: {COLORS['TEXT_MAIN']}; padding: 10px; border-radius: 10px; border: none; font-weight: bold; }} QPushButton:hover {{ background-color: {COLORS['DANGER_HOVER']}; }}",
    'ESTOP_ON': f"QPushButton {{ background-color: {COLORS['DANGER_SOFT']}; color: {COLORS['TEXT_MAIN']}; padding: 10px; border-radius: 10px; border: none; font-weight: bold; }} QPushButton:hover {{ background-color: {COLORS['DANGER']}; }}",
    
    # --- Machine Power ---
    'POWER_OFF': f"QToolButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_INACTIVE']}; padding: 10px; border-radius: 10px; border: none; }} QToolButton:hover {{ background-color: {COLORS['BG_BTN_HOVER']}; color: {COLORS['TEXT_LIGHT_GRAY']}; }}",
    'POWER_ON': f"QToolButton {{ background-color: {COLORS['ACCENT']}; color: {COLORS['TEXT_MAIN']}; padding: 10px; border-radius: 10px; border: none; }} QToolButton:hover {{ background-color: {COLORS['ACCENT_HOVER']}; color: {COLORS['TEXT_LIGHT_GRAY']}; }}",
    
    # --- Homing ---
    'HOME_INACTIVE': f"QToolButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_INACTIVE']}; padding: 10px; border-radius: 10px; border: 3px solid {COLORS['BORDER_DEFAULT']}; }}",
    'HOME_READY': f"QToolButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_INACTIVE']}; padding: 10px; border-radius: 10px; border: 3px solid {COLORS['ACCENT']}; }} QToolButton:hover {{ background-color: {COLORS['BG_BTN_HOVER']}; color: {COLORS['TEXT_LIGHT_GRAY']}; }}",
    
    # --- Jogging ---
    'JOG_ACTIVE': f"""
        QPushButton {{ background-color: {COLORS['ACCENT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }}
        QPushButton:hover {{ background-color: {COLORS['ACCENT_HOVER']}; border: 2px solid {COLORS['ACCENT_BORDER']}; }}
    """,
    'JOG_LIMITED': f"""
        QPushButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }}
    """,

    # --- G-code Control Buttons ---
    'GCODE_INACTIVE': f"QPushButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }}",
    'GCODE_ACTIVE': f"QPushButton {{ background-color: {COLORS['ACCENT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }} QPushButton:hover {{ background-color: {COLORS['ACCENT_HOVER']}; }}",
    'GCODE_WARN': f"QPushButton {{ background-color: {COLORS['DANGER']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }} QPushButton:hover {{ background-color: {COLORS['DANGER_HOVER']}; }}",
    
    # --- Panel Frames & Labels ---
    'PANEL_FRAME_INACTIVE': f"border-radius: 10px; border: 3px solid {COLORS['BORDER_DEFAULT']};",
    'PANEL_FRAME_ACTIVE': f"border-radius: 10px; border: 3px solid {COLORS['ACCENT']};",
    'PANEL_LABEL_INACTIVE': f"border: none; color: {COLORS['TEXT_INACTIVE']};",
    'PANEL_LABEL_ACTIVE': f"border: none; color: {COLORS['ACCENT']};",
    
    # --- System Dialogs ---
    'MSGBOX': f"""
        QMessageBox {{ background-color: {COLORS['BG_WIDGET']}; border: none; border-radius: 10px; }} 
        QMessageBox QLabel {{ color: {COLORS['TEXT_MAIN']}; font-size: 13px; padding: 5px; }} 
        QPushButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_MAIN']}; min-width: 80px; padding: 6px; border-radius: 5px; border: 1px solid #555555; }}
        QPushButton:hover {{ background-color: {COLORS['ACCENT']}; border: 1px solid white; }}
    """,
    
    # --- G-code List View ---
    'GCODE_LIST': f"""
        QListView {{ color: {COLORS['TEXT_MAIN']}; outline: none; background-color: {COLORS['BG_LIST']}; border: none; padding: 0px; }}
        QListView::item {{ padding: 4px; }}
        QListView::item:selected {{ background-color: {COLORS['ACCENT']}; color: white; border-radius: 3px; }}
        QListView::item:hover {{ background-color: {COLORS['BG_BTN_DEFAULT']}; }}
        QScrollBar:vertical {{ background: {COLORS['SCROLLBAR_BG']}; width: 12px; margin: 0px; border-radius: 6px; }}
        QScrollBar::handle:vertical {{ background: {COLORS['ACCENT']}; min-height: 15px; border-radius: 6px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        QScrollBar:horizontal {{ background: {COLORS['SCROLLBAR_BG']}; height: 12px; border-radius: 6px; }}
        QScrollBar::handle:horizontal {{ background: {COLORS['ACCENT']}; min-height: 20px; border-radius: 6px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0px; }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
        QListView QLineEdit {{ background-color: {COLORS['BG_WIDGET']}; color: {COLORS['EDIT_MODE_ITALIC']}; border: 1px solid {COLORS['ACCENT']}; border-radius: 2px; font-style: italic; }}
    """,
    
    # --- Line Number Gutter ---
    'LINE_NUMBER_AREA': f"""
        QListView {{
            background-color: {COLORS['BG_BTN_DEFAULT']};
            border: none;
            border-radius: 0px;
            padding: 0px;
            color: {COLORS['TEXT_INACTIVE']};
        }}
        QListView::item {{ padding: 4px; }}
       QListView::item:selected {{ background-color: {COLORS['ACCENT']}; color: white; border-radius: 3px; }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            width: 0px;
            height: 0px;
            background: transparent;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal,
        QScrollBar::add-line, QScrollBar::sub-line,
        QScrollBar::add-page, QScrollBar::sub-page {{
            width: 0px;
            height: 0px;
            background: none;
        }}
        QListView QLineEdit {{ background-color: {COLORS['BG_WIDGET']}; color: {COLORS['EDIT_MODE_ITALIC']}; border: 1px solid {COLORS['ACCENT']}; border-radius: 2px; font-style: italic; }}
    """,

    # --- Output/Log Panel ---
    'OUTPUT_VIEW': f" QListWidget {{ background-color: {COLORS['BG_MAIN']}; border: 1px solid {COLORS['BG_WIDGET']}; border-radius: 5px; outline: none; padding: 0px; }} QListWidget::item {{ background-color: transparent; padding: 0px; margin: 0px; border: none; }} QListWidget::item:selected {{ background-color: {COLORS['BG_PANEL']}; }}",
    
    # --- Tool / Gripper Control ---
    'TOOL_ARMED': f"QPushButton {{ background-color: {COLORS['ACCENT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }} QPushButton:hover {{ background-color: {COLORS['ACCENT_HOVER']}; }}",
    'TOOL_DISARMED': f"QPushButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }}",
    'GRIP_ACTIVE': f"QPushButton {{ background-color: {COLORS['ACCENT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }} QPushButton:hover {{ background-color: {COLORS['ACCENT_HOVER']}; }}",
    'GRIP_INACTIVE': f"QPushButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_MAIN']}; padding: 5px; border-radius: 10px; border: none; }}",

    # --- Copy Button for Output Panel ---
    'COPY_BTN': f"""
    QPushButton {{ background-color: {COLORS['BG_WIDGET']}; color: {COLORS['TEXT_INACTIVE']}; border: 1px solid {COLORS['LOGGER_BORDER']}; border-radius: 4px; }} 
    QPushButton:hover {{ background-color: {COLORS['BG_BTN_HOVER']}; color: {COLORS['ACCENT']}; }} """,
    
    # --- Separator Line ---
    'SEPARATOR_LINE': f""" 
    QFrame {{ background-color: {COLORS['BG_BTN_DEFAULT']}; max-height: 1px; border: none; margin: 5px 0px; }} """, 
    
    # --- clipboard ---
    'CLIPBOARD': f"QPushButton {{ background-color: {COLORS['BG_BTN_DEFAULT']}; color: {COLORS['TEXT_GREEN']}; border-radius: 4px; }}",
    
    # --- Message Text ---
    'MSG_TEXT': f"QLabel {{ color: {COLORS['TEXT_DISABLED']}; font-size: 12px; border: none; background: {COLORS['BG_TRANSPARENT']}; }}",

    # --- Log Container
    'LOG_CONTAINER': f"#logContainer {{ background: {COLORS['BG_TRANSPARENT']}; border: none;}}",
}

# --- MESSAGES ---
MESSAGES = {
    "CONFIRM_HOME": "Confirm Homing",
    "HOME_WARNING": "This will reset current coordinates and may cause unexpected motion.",
    "FILE_ERR": "Error opening file",
}