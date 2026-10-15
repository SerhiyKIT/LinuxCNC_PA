# Контекст проєкту: LinuxCNC_PA (6-осьовий робот-маніпулятор на Raspberry Pi 4B)

Ти — мій асистент-розробник цього проєкту. Нижче повний опис того, як він влаштований. Використовуй його як основу для всіх відповідей. Відповідай українською. Якщо пропонуєш зміни, вказуй конкретний файл і шлях. Пиши код у стилі наявного коду: Python 3.13, PyQt5, коментарі українською, менеджери з окремими UI-binder'ами. Не вигадуй файли чи API, яких тут немає. Якщо чогось не знаєш, попроси вивід команди або вміст файлу.

---

## 1. Залізо та ОС

- **Плата:** Raspberry Pi 4 Model B, завантаження з SD-картки.
- **ОС:** Raspberry Pi OS на базі Debian 13 "trixie", arm64. Є ядро `kernel8_rt.img` (PREEMPT_RT), але чи завантажується саме воно, не перевірено.
- **Користувач:** `cnc` (uid 1000), групи sudo і netdev. Hostname: `linuxcnc`.
- **LinuxCNC 2.9.x, пакет `linuxcnc-uspace`** (userspace realtime) та `linuxcnc-uspace-dev`.
- **Python 3.13** (системний), PyQt5 5.15.11. Додатково через pip з `--break-system-packages`: `pytest`, `uuid6`.
- **Мотори:** 6 крокових двигунів, драйвери **TB6600**. STEP/DIR керуються напряму з GPIO через `hal_pi_gpio`.
- **Мережа:** NetworkManager (`nmcli`). Регіон Wi-Fi UA задано в `cmdline.txt`. Енергозбереження Wi-Fi вимкнене (`/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf`, `wifi.powersave = 2`).
- **Дисплей:** HDMI 1920x1080. Вхід у робочий стіл (LXDE / rpd-x) автоматичний.

## 2. Віддалений доступ

- **SSH:** `openssh-server` увімкнений, `ssh cnc@<IP>`.
- **Веб-VNC:** `/etc/systemd/system/webvnc.service` запускає TigerVNC (`vncserver :1 -geometry 1920x1080`, порт 5901) і `websockify` + noVNC на порту 8080. Адреса: `http://<IP>:8080/vnc.html`. Пароль VNC зберігається в `~/.config/tigervnc/passwd`. Це **окремий** X-дисплей :1, а не той, що виводиться на HDMI.
- **Bluetooth-конфігуратор Wi-Fi (новий, написаний окремо):**
  - Вихідні файли лежать у репозиторії: `system/bt-wifi-setup/`: `bt_wifi_setup.py`, `bt-wifi-setup.service`, `install.sh`, `bt-wifi-setup.txt`, `README.md`.
  - Після запуску `install.sh` скрипт копіюється в `/usr/local/lib/bt-wifi-setup/`, а systemd-сервіс `bt-wifi-setup.service` працює від root.
  - Він піднімає BLE GATT-сервіс **Nordic UART** (UUID `6e400001-b5a3-f393-e0a9-e50e24dcca9e`; RX `…0002` для запису з телефона, TX `…0003` для notify) через BlueZ D-Bus (`python3-dbus`, `python3-gi`, GLib mainloop).
  - Пристрій видно як `CNC-Setup`.
  - Текстові команди: `pin`, `status`, `scan`, `wifi "SSID" "pass"`, `ssid`/`pass`/`open`, `saved`, `forget`, `help`. Wi-Fi налаштовується через `nmcli`.
  - Конфіг (`NAME`, `PIN`) лежить на boot-розділі: `/boot/firmware/bt-wifi-setup.txt`.
  - Захист: після 5 невірних PIN блокування на 60 с, автовихід через 15 хв неактивності.
  - Скрипт повністю незалежний від LinuxCNC.
- **Мертві залишки старої спроби:** `autohotspot.service` та `wayvnc.service` залишились увімкненими symlink'ами, але їхні unit-файли видалені. `install.sh` прибирає ці посилання. На boot-розділі лежить застарілий `wpa_supplicant.conf`, який ця ОС ігнорує.

## 3. Розташування файлів

```
/home/cnc/
├── linuxcnc/
│   ├── configs/
│   │   ├── LinuxCNC_PA/          ← ОСНОВНИЙ ПРОЄКТ (git-репозиторій)
│   │   │   ├── system/bt-wifi-setup/ ← BLE-конфігуратор Wi-Fi (див. розділ 2)
│   │   │   └── docs/PROJECT_CONTEXT.md ← цей опис
│   │   ├── robot_tb6600/         ← старіша/експериментальна конфігурація під TB6600
│   │   └── sim.axis/             ← стандартні демо LinuxCNC
│   └── nc_files/                 ← стандартні приклади G-коду
├── LinuxCNC_PA/db/system.db      ← SQLite БД GUI (створюється програмою)
├── ProjectLinuxCNC/              ← каталог проєктів (G-код) для project manager
├── test_stepper.py, test_step.py, test_6_joints.py, sync_demo.py, sync_demo_1.py
│                                 ← ручні тестові скрипти для перевірки моторів
└── .linuxcncrc                   ← LAST_CONFIG вказує на sim.axis
```

Запуск: `linuxcnc ~/linuxcnc/configs/LinuxCNC_PA/robot.ini`.

**Git:** `git@github.com:SerhiyKIT/LinuxCNC_PA.git`, гілка `main`. Розробка йде через гілки-фічі з номерами issues (`38-tool-control`, `46-project-manager`, `34-code-editor` тощо) і PR. Останній коміт: "Merge pull request #47 from SerhiyKIT/46-project-manager".

## 4. Конфігурація LinuxCNC (`LinuxCNC_PA/`)

### `robot.ini` (основне)

- Робот збудований на прикладі **PUMA560 із switchkins** з LinuxCNC.
- `[KINS] JOINTS=6`, `KINEMATICS=genserkins`.
- `[TRAJ] COORDINATES = X Y Z A B C`, `LINEAR_UNITS = inch`, `ANGULAR_UNITS = deg`.
- `[HAL]`:
  - `HALUI = halui`
  - `HALFILE = LIB:basic_sim.tcl` генерує `robot_cmds.hal` під час запуску. Тому `robot_cmds.hal` є в `.gitignore`.
  - `HALFILE = robot_dh.hal`
  - `HALFILE = robot_hw.hal`
- `[EMCMOT] SERVO_PERIOD = 1000000` (1 мс), `BASE_PERIOD = 200000` (200 мкс). base-thread потрібен для програмної генерації кроків.
- `[RS274NGC]`:
  - `USER_M_PATH = ./mcodes`, `SUBROUTINE_PATH = ./remap_subs`, `HAL_PIN_VARS = 1`.
  - `REMAP` для M428/M429/M430 (перемикання кінематики).
  - `RS274NGC_STARTUP_CODE = G20 G10L2P0 x19.2 y5.5 z9.4 a90 b0 c90`.
  - `PARAMETER_FILE = puma560.var`.
- `[HALUI] MDI_COMMAND`: M428, M429, M430, M128, M129, M130.
- `[DISPLAY] DISPLAY = axis` у **робочій копії**. У git-версії стоїть `DISPLAY = qtvcp ./cnc_interface/main_window`, тобто власний GUI (див. розділ 5).
- Joints 0–5 типу ANGULAR. Ліміти J0 ±180, J2 від −215 до 35, решта ±360. `MAX_VELOCITY` 30, `MAX_ACCELERATION` 200. Усі `HOME_SEQUENCE = 0`.
- `TOOL_TABLE = tool.tbl`.

### `robot_dh.hal`

Параметри Денавіта–Гартенберга для `genserkins` (`A-n`, `ALPHA-n`, `D-n`), геометрія PUMA560 у дюймах:

- A-2 = 17
- D-0 = 26.45, D-1 = −5.5, D-3 = 17.05, D-5 = 2.2
- ALPHA = 0, π/2, 0, π/2, −π/2, π/2

### `robot_hw.hal` (фізичне залізо, ще не закомічений)

- `loadrt hal_pi_gpio dir=66112536 exclude=0` (бітова маска виходів). Піни мають вигляд `hal_pi_gpio.pin-NN-out`, де NN — **фізичний номер піна на роз'ємі**.
- `loadrt stepgen step_type=0,0,0,0,0,0`.
- Порядок функцій: `hal_pi_gpio.read` → `stepgen.make-pulses` → `hal_pi_gpio.write` у base-thread; `stepgen.capture-position` та `stepgen.update-freq` у servo-thread.
- `steplen`/`stepspace`: 90000 нс для J0–J2, 50000 нс для J3–J5.
- `position-scale = 42.666667` кроків на градус для всіх осей.
- Підключено `J{n}:pos-cmd => stepgen.n.position-cmd`.
- Розводка STEP/DIR по фізичних пінах:

  | Joint | STEP | DIR |
  |---|---|---|
  | J0 | 11 | 13 |
  | J1 | 15 | 16 |
  | J2 | 18 | 22 |
  | J3 | 29 | 31 |
  | J4 | не підключено | не підключено |
  | J5 | не підключено | не підключено |

### `robot_cmds.hal` (генерується `basic_sim.tcl`)

- Симульований контур: pid + mux2 + ddt + `sim_home_switch` на кожен joint.
- `joint.N.motor-pos-fb` бере значення з симуляції (mux), а не з stepgen. Фактично система працює **без зворотного зв'язку** від stepgen.
- Також: `hal_manualtoolchange`, `sim_spindle`, петля estop (`iocontrol.0.user-enable-out → emc-enable-in`).

### Інші файли конфігурації

- **`mcodes/`**:
  - `M128`, `M129`, `M130` — Tcl-скрипти, які перемикають тип кінематики (0 = genserkins, 1 = identity, 2 = user) через `M68 E3` та підміняють ліміти осей лімітами joints.
  - `M101` — тестовий Python-скрипт із shebang на чужий venv `/home/oleksii/...`, на Pi він не працює.
- **`remap_subs/428remap.ngc`, `429remap.ngc`, `430remap.ngc`** — ті самі перемикання через `motion.analog-out-03 → motion.switchkins-type`.
- **`hal_components/play_button`** — userspace HAL-компонент на Python. Піни `in`, `line_done`, `play`, `play_step`. Реалізує кнопку "утримуй, щоб виконувати" і покроковий режим.

## 5. Власний GUI: `cnc_interface/` (QtVCP)

Запускається як `DISPLAY = qtvcp ./cnc_interface/main_window`. Розмір близько 9 тис. рядків Python.

- **`main_window.ui`** — Qt Designer UI. `resources.qrc` / `resources_rc.py` — ресурси (іконки в `icons/`).
- **`main_window_handler.py`** — точка входу QtVCP. Вона додає `logic/` у `sys.path`, а `get_handlers()` повертає `HandlerClass`.
- **`logic/main_logic.py` → `HandlerClass`:**
  - У `__init__` (ДО `loadUi`) створюються об'єкти, які не потребують віджетів.
  - У `initialized__` (ПІСЛЯ `loadUi`) підключаються кнопки, редактор, таймери, binder'и.
- **`logic/config.py`:** `INI_FILE` через `linuxcnc.ini(INI_FILE_NAME)`, `MACHINE_PARAMS`, `JOINT_LIMITS`, `CYCLE_BUTTONS`, `SLIDER_CONFIGS`, `HOTKEYS`, `COLORS`, `STYLES`, `MESSAGES`, константи менеджерів (`MGR_CONTROL`, `MGR_CYCLE`, `MGR_TOOL`, `MGR_FILE`).
- **`logic/core/`:**
  - `machine.py` → `MachineController`, обгортка над `linuxcnc.stat` / `command` / `error_channel`. Методи: poll, estop, power, mode, home, teleop, jog, overrides, open_program, cycle start/pause/resume/stop/step, `send_mdi`, `set_gripper_force`, `get_states` тощо.
  - `logger.py` → `LoggerController`.
- **`logic/managers/`:**
  - `control_manager`, `cycle_manager` (+ `CycleUIBinder`), `joint_manager` (+ `JointUIBinder`), `axis_manager` (+ `AxisUIBinder`), `overrides_manager` (+ binder), `gripper_manager` (+ binder), `keyboard_manager`, `style_manager`, `ui_manager`, `project_logger`.
  - `auth/` — користувачі, ролі (operator / engineer / admin), майстер першого запуску, підвищення ролі, тайм-аут неактивності. Модулі: `auth_db`, `auth_manager`, `auth_session`, `auth_dialogs`, `auth_constants`.
  - `tool/` — таблиця інструментів у SQLite: `tool_store`, `tool_panel`, `tool_dialogs`, `tool_models`.
  - `project/` — менеджер проєктів G-коду та FileWatcher: `project_manager`, `project_watcher`, `project_dialogs`.
  - `ui/` — `gcode_display`, `motion_display`, `logger_display`, `panel_manager`, `gripper_display`, `ui_mapping` (тексти, підказки, плейсхолдери).
  - `ui/editor/` — власний редактор G-коду: підсвітка, автодоповнення, сніпети, пошук, таблиця символів, діалог руху.
- **`logic/i18n/lang_ua.ts` / `.qm`** — український переклад через QTranslator.
- **БД `~/LinuxCNC_PA/db/system.db`** (SQLite) має таблиці `users`, `tools`, `projects`, `system_log`.
- **Тести (pytest):** `tests/unit/` (менеджери, `test_ui_manager/`), `tests/integration/` (потребує запущеного LinuxCNC), `tests/gui_functional/`. Скрипти запуску: `run_units_tests.sh`, `run_integration_tests.sh`, `run_gui_functional_tests.sh`. Конфіг: `conftest.py`, `pytest.ini`.

## 6. Поточний стан і відомі проблеми

Робоча копія на Pi **відрізняється від git**. Зараз тестують фізичні мотори через стандартний AXIS. Незакомічені зміни:

- `robot.ini` змінено, `robot_hw.hal` новий.
- У `robot.ini` прибрано `HALCMD = loadusr ./hal_components/play_button`.
- Прибрано `HALCMD = net :kinstype-select <= motion.analog-out-03 => motion.switchkins-type`. **Наслідок:** M428–M430 / M128–M130 впадуть з помилкою "Wrong motion.switchkins-type", бо мережу не створено.
- `DISPLAY` замінено з qtvcp на axis.
- Прибрано `PYVCP`, `INTRO_GRAPHIC`, `MAX_FEED_OVERRIDE` і Qt scale-змінні.

Відомі проблеми:

1. **J4 та J5 не мають stepgen-проводки** до GPIO у `robot_hw.hal`.
2. **`stepgen.N.enable` ніде не підключений** (типово false). Його варто з'єднати з `joint.N.amp-enable-out`. Інакше stepgen може не генерувати імпульси.
3. **Зворотний зв'язок береться із симуляції `basic_sim`,** а не з `stepgen.N.position-fb`. Для справжньої машини краще написати власні HAL-файли без `basic_sim.tcl`.
4. **Одиниці змішані:** `LINEAR_UNITS = inch` (спадок PUMA-демо), DH-параметри теж у дюймах.
5. **Тайминги та RT:** `steplen` 90 мкс при `BASE_PERIOD` 200 мкс. Треба перевірити latency (`latency-test`) і чи завантажене RT-ядро.
6. **Кривий тест:** `mcodes/M101` має неправильний shebang. Файл `tests/gui_functional/test_panel_manager .py` має пробіл у назві.

## 7. Як мені допомагати

- Перед змінами HAL/INI враховуй, що файли можуть генеруватись (`robot_cmds.hal`), і що порядок `addf` важливий.
- Для GUI дотримуйся поділу:
  - **Manager:** логіка без віджетів, працює через `MachineController`.
  - **UIBinder:** прив'язка до віджетів у `initialized__`.
  - **Константи** та тексти зберігаються в `config.py`, `*_constants.py` і `ui_mapping.py`.
- Пропонуй команди для перевірки на Pi: `halcmd show pin`, `halrun`, `journalctl`, `pytest`. Я виконаю їх і поверну результат.
