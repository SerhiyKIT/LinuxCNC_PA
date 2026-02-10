import os
import linuxcnc

try:
    from PyQt5.QtCore import Qt
except ImportError:
    from PyQt6.QtCore import Qt

# --- INI FILE ---
INI_PATH = os.environ.get('INI_FILE_NAME')
INI_FILE = linuxcnc.ini(INI_PATH) if INI_PATH else None

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
    
    # Linear velocities from [DISPLAY] or [AXIS_X]
    "LINEAR_VEL":         get_ini_val("DISPLAY", "DEFAULT_LINEAR_VELOCITY", 5.0),
    "MAX_LINEAR_VEL":     get_ini_val("AXIS_X", "MAX_VELOCITY", 30.0),
    
    # Angular velocities
    "ANGULAR_VEL":        get_ini_val("DISPLAY", "DEFAULT_ANGULAR_VELOCITY", 36.0),
    "MAX_ANGULAR_VEL":    get_ini_val("AXIS_A", "MAX_VELOCITY", 30.0),
    
    # Increments for jogging
    "JOG_INCREMENTS":     ["Continuous", "1.0000", "0.1000", "0.0100", "0.0010", "0.0001"],
    
    # Number of joints (from [KINS])
    "JOINTS_COUNT":       int(get_ini_val("KINS", "JOINTS", 6, val_type=float)),
}

# --- DYNAMIC LIMITS OBJECT ---
JOINT_LIMITS = get_joint_limits(MACHINE_PARAMS["JOINTS_COUNT"])

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

# --- AXIS MAPPING ---
AXIS_MAPPING = {
    0: "X", 1: "Y", 2: "Z", 3: "A", 4: "B", 5: "C"
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
    
    # Text colors
    "TEXT_MAIN": "#FFFFFF",       
    "TEXT_INACTIVE": "#9E9E9E",   
    "TEXT_LIGHT_GRAY": "#F1F1F1", 
    
    # Special colors
    "BORDER_DEFAULT": "#333333",  
    "SCROLLBAR_BG": "#333333",   
    "EDIT_MODE_ITALIC": "#FE5C0D" 
}

# --- MESSAGES ---
MESSAGES = {
    "CONFIRM_HOME": "Confirm Homing",
    "HOME_WARNING": "This will reset current coordinates and may cause unexpected motion.",
    "FILE_ERR": "Error opening file",
}