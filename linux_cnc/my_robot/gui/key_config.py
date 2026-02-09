from PyQt5.QtCore import Qt

HOTKEYS = {
    # СИСТЕМНІ
    "ESTOP":         Qt.Key_F1,
    "POWER":         Qt.Key_F2,
    "HOME_ALL":      (Qt.Key_Home, Qt.ControlModifier), # Ctrl + Home
    
    # ФАЙЛИ
    "OPEN_FILE":     Qt.Key_O,
    "SAVE_AS":       (Qt.Key_S, Qt.ControlModifier),    # Ctrl + S
    "RELOAD":        (Qt.Key_R, Qt.ControlModifier),    # Ctrl + R
    
    # ВИКОНАННЯ ПРОГРАМИ
    "RUN":           Qt.Key_R,
    "STEP":          Qt.Key_T,
    "PAUSE":         Qt.Key_P,
    "RESUME":        Qt.Key_S,
    "STOP":          Qt.Key_Escape,
}