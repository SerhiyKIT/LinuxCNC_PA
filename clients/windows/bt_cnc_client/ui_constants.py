# clients/windows/bt_cnc_client/ui_constants.py
"""Тексти, кольори і стилі вікна клієнта."""

WINDOW_TITLE = "CNC-Robot — Bluetooth"
WINDOW_SIZE  = (1100, 760)

JOINT_NAMES = ["J0", "J1", "J2", "J3", "J4", "J5"]

JOG_VEL_DEFAULT  = 10.0     # град/с (міст обріже до MAX_JOG_VEL і INI)
JOG_VEL_RANGE    = (0.5, 60.0)
JOG_STEP_DEFAULT = 1.0      # град
JOG_STEP_RANGE   = (0.01, 90.0)
FO_RANGE         = (0, 150)

MODE_CONTINUOUS = "Утримання (jogc)"
MODE_STEP       = "Крок (jog)"

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
    "homed": "#2e7d32",
    "unhomed": "#9e9e9e",
}

ESTOP_STYLE = """
QPushButton {
    background: #d50000; color: white; font-size: 22px; font-weight: bold;
    border: 4px solid #7f0000; border-radius: 12px; min-height: 70px;
}
QPushButton:pressed { background: #9b0000; }
QPushButton:disabled { background: #e57373; border-color: #b71c1c; }
"""
RESET_STYLE = "QPushButton { min-height: 70px; font-size: 14px; }"
JOG_BUTTON_STYLE = "QPushButton { min-width: 54px; min-height: 34px; font-size: 18px; }"
STATE_LABEL_STYLE = "QLabel {{ color: white; background: {color}; padding: 6px 12px; border-radius: 6px; font-weight: bold; }}"
