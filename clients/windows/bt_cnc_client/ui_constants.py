# clients/windows/bt_cnc_client/ui_constants.py
"""Тексти, кольори і стилі вікна клієнта."""

WINDOW_TITLE = "CNC-Robot Studio"
SETTINGS_ORG = "CNC-Robot"          # QSettings: на Windows — реєстр HKCU\Software\CNC-Robot
SETTINGS_APP = "Studio"
WINDOW_SIZE  = (1280, 860)

JOINT_NAMES = ["J0", "J1", "J2", "J3", "J4", "J5"]
AXIS_NAMES  = ["X", "Y", "Z", "A", "B", "C"]

TRANSPORT_WIFI = "Wi-Fi"
TRANSPORT_BLE  = "Bluetooth"

JOG_VEL_DEFAULT  = 10.0     # град/с (міст обріже до MAX_JOG_VEL і INI)
JOG_VEL_RANGE    = (0.5, 60.0)
JOG_LIN_DEFAULT  = 0.2      # од./с для X Y Z (міст обріже до MAX_JOG_LIN)
JOG_LIN_RANGE    = (0.01, 5.0)
JOG_STEP_DEFAULT = 1.0      # град або од.
JOG_STEP_RANGE   = (0.001, 90.0)
FO_RANGE         = (0, 150)

MODE_CONTINUOUS = "Утримання"
MODE_STEP       = "Крок"
SPACE_JOINTS    = "Joints (J0–J5)"
SPACE_WORLD     = "Світ (X Y Z A B C)"

STATE_TEXT = {
    "nocnc": "LinuxCNC не запущений",
    "estop": "E-STOP",
    "off":   "Вимкнено",
    "on":    "Увімкнено",
}
RUN_TEXT = {"idle": "очікування", "run": "виконується", "paused": "пауза"}

COLORS = {
    "estop": "#c62828",
    "off":   "#ef6c00",
    "on":    "#2e7d32",
    "nocnc": "#616161",
}

# --- Навчання ---------------------------------------------------------------
PROGRAM_FILE_FILTER = "Програми робота (*.robot.json);;Усі файли (*)"
PROGRAM_SUFFIX      = ".robot.json"
GOTO_FILE           = "_studio_goto.ngc"
SPEED_JOINT_RANGE   = (0.0, 60.0)    # 0 — типова швидкість програми
SPEED_LINEAR_RANGE  = (0.0, 5.0)
VALUE_RANGE         = (-10000.0, 10000.0)
WAIT_RANGE          = (0.0, 3600.0)

ESTOP_STYLE = """
QPushButton {
    background: #d50000; color: white; font-size: 22px; font-weight: bold;
    border: 4px solid #7f0000; border-radius: 12px; min-height: 64px;
}
QPushButton:pressed { background: #9b0000; }
QPushButton:disabled { background: #e57373; border-color: #b71c1c; }
"""
RESET_STYLE = "QPushButton { min-height: 64px; font-size: 14px; }"
JOG_BUTTON_STYLE = "QPushButton { min-width: 54px; min-height: 34px; font-size: 18px; }"
RECORD_STYLE = "QPushButton { font-weight: bold; min-height: 32px; }"
STATE_LABEL_STYLE = "QLabel {{ color: white; background: {color}; padding: 4px 12px; border-radius: 6px; font-weight: bold; }}"
