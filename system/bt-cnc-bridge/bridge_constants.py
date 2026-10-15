# system/bt-cnc-bridge/bridge_constants.py
"""
Константи BLE-мосту LinuxCNC: UUID, ліміти, коди помилок, тексти.
"""

PROTOCOL_VERSION = 1

# --- BLE ---
# Власний 128-бітний UUID (не Nordic UART, щоб не плутати з bt-wifi-setup).
# Шаблон як у NUS: ...01 сервіс, ...02 RX (клієнт -> Pi), ...03 TX (Pi -> клієнт)
SERVICE_UUID = "a002da01-7653-4ff1-a840-6568658847c6"
RX_UUID      = "a002da02-7653-4ff1-a840-6568658847c6"
TX_UUID      = "a002da03-7653-4ff1-a840-6568658847c6"

DBUS_APP_PATH = "/org/cnc/bridge"

RX_BUFFER_MAX   = 512   # байт без '\n' -> ERR overflow
DEFAULT_PAYLOAD = 20    # корисне навантаження notify при MTU 23
MAX_PAYLOAD     = 180   # навіть при великому MTU не шлемо більші пакети
SEND_INTERVAL_MS = 15   # пауза між пакетами notify

# --- Конфіг ---
CONFIG_FILES = ["/boot/firmware/bt-cnc-bridge.txt", "/etc/bt-cnc-bridge.conf"]

DEFAULT_CONFIG = {
    "NAME":          "CNC-Robot",
    "PIN":           "",
    "ON_DISCONNECT": "pause",      # pause | abort
    "STATUS_HZ":     5.0,
    "MAX_JOG_VEL":   20.0,         # град/с
    "JOG_VEL":       10.0,         # град/с для інкрементального jog
    "WATCHDOG_MS":   500,
    "PROJECTS_DIR":  "/home/cnc/ProjectLinuxCNC",
}
ON_DISCONNECT_MODES = ("pause", "abort")
STATUS_HZ_RANGE     = (0.5, 20.0)

# --- Безпека ---
MAX_PIN_FAILS = 5
LOCKOUT_SEC   = 60
WATCHDOG_TICK_MS = 50

# --- LinuxCNC ---
MAX_JOINTS      = 6
RECONNECT_SEC   = 2.0
WAIT_TIMEOUT    = 3.0     # с, wait_complete для перемикання режимів/станів
FO_RANGE        = (0, 150)
RO_RANGE        = (0, 100)
PROGRAM_EXTS    = (".ngc", ".nc")
POSITION_DIGITS = 3

# --- Команди ---
# Дозволені до введення PIN
PUBLIC_CMDS = frozenset({"pin", "help", "ver"})
# Після PIN, без керування
READ_CMDS = frozenset({"status", "take", "release", "ping", "ls"})
# Будь-який авторизований клієнт може натиснути аварійну зупинку
ANYONE_CMDS = frozenset({"estop"})
# Решта команд — лише власник керування (після take)

# --- Коди помилок (ERR <код> <текст>) ---
E_UNKNOWN  = "unknown"    # невідома команда
E_ARGS     = "args"       # неправильні аргументи
E_AUTH     = "auth"       # потрібен pin / невірний pin
E_LOCKED   = "locked"     # забагато спроб pin
E_BUSY     = "busy"       # керування зайняте іншим клієнтом
E_OWNER    = "owner"      # спершу take
E_NOCNC    = "nocnc"      # LinuxCNC не запущений
E_STATE    = "state"      # не виконана передумова (on, homed, idle...)
E_PATH     = "path"       # заборонене ім'я файлу
E_NOFILE   = "nofile"     # файл не знайдено
E_CNC      = "cnc"        # LinuxCNC відхилив команду
E_TIMEOUT  = "timeout"    # LinuxCNC не відповів
E_OVERFLOW = "overflow"   # рядок довший за RX_BUFFER_MAX

HELP_TEXT = """\
ver | help | pin <PIN>
take | release | status | ping | ls
estop on|off | power on|off
home all|<J> | unhome all|<J>
jog <J> <+-крок> | jogc <J> <+|-> <швидк> | jogstop [J]
mdi <G-код> | open <файл> | run [рядок]
pause | resume | stop | step
fo <0-150> | ro <0-100>"""
