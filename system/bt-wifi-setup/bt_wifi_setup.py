#!/usr/bin/env python3
"""
Bluetooth LE конфігуратор Wi-Fi для Raspberry Pi (LinuxCNC).

Піднімає BLE-сервіс Nordic UART (NUS). З телефона підключаєтесь будь-яким
BLE-терміналом (Android: "Serial Bluetooth Terminal", iOS: "Bluefruit Connect"
або "nRF Toolbox" -> UART), вводите текстові команди — `help` покаже список.

Wi-Fi налаштовується через NetworkManager (nmcli). Працює від root.
Налаштування: /boot/firmware/bt-wifi-setup.txt (NAME, PIN).
"""

import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BLUEZ = "org.bluez"
DBUS_OM = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP = "org.freedesktop.DBus.Properties"
GATT_MANAGER = "org.bluez.GattManager1"
GATT_SERVICE = "org.bluez.GattService1"
GATT_CHRC = "org.bluez.GattCharacteristic1"
LE_ADV_MANAGER = "org.bluez.LEAdvertisingManager1"
LE_ADV = "org.bluez.LEAdvertisement1"
ADAPTER = "org.bluez.Adapter1"

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # телефон -> Pi
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Pi -> телефон

CONFIG_FILES = ["/boot/firmware/bt-wifi-setup.txt", "/etc/bt-wifi-setup.conf"]
WIFI_IFACE = "wlan0"
MAX_PIN_FAILS = 5
LOCKOUT_SEC = 60
AUTH_IDLE_SEC = 15 * 60
LINE_FLUSH_MS = 500
DRY_RUN = os.environ.get("BT_WIFI_DRY_RUN") == "1"

HELP = """Команди:
 pin 123456      - увійти (PIN з bt-wifi-setup.txt)
 status          - стан мережі, IP, адреси VNC/SSH
 scan            - знайти Wi-Fi мережі
 wifi "Назва" "Пароль" - зберегти мережу і підключитись
 ssid Назва      - вказати мережу (можна з пробілами)
 pass Пароль     - пароль і підключення до мережі з ssid
 open            - підключення до відкритої мережі з ssid
 saved           - збережені мережі
 forget Назва    - видалити збережену мережу
 help            - ця довідка"""


def log(*args):
    print(*args, flush=True)


def load_config():
    cfg = {"NAME": "CNC-Setup", "PIN": ""}
    for path in CONFIG_FILES:
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    cfg[key.strip().upper()] = val.strip().strip('"')
            log(f"config: {path}")
            break
        except FileNotFoundError:
            continue
    return cfg


# ---------------------------------------------------------------- nmcli ---

def run(cmd, timeout=40):
    if DRY_RUN and cmd[0] == "nmcli" and "con" in cmd \
            and any(a in cmd for a in ("add", "up", "delete", "modify")):
        log("DRY RUN:", " ".join(cmd[:4]), "...")
        return 0, "dry run"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "таймаут"
    except FileNotFoundError:
        return 1, f"{cmd[0]} не знайдено"


def split_terse(line):
    """Розбиває рядок `nmcli -t` по ':' з урахуванням екранування '\\:'."""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def wifi_profiles():
    """[(name, ssid)] збережених Wi-Fi профілів (крім точки доступу)."""
    rc, out = run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])
    if rc:
        return []
    result = []
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            rc2, info = run(["nmcli", "-t", "-g", "802-11-wireless.ssid,802-11-wireless.mode",
                             "con", "show", "id", f[0]])
            lines = info.splitlines() if rc2 == 0 else []
            ssid = lines[0] if lines else ""
            mode = lines[1] if len(lines) > 1 else ""
            if mode != "ap":
                result.append((f[0], ssid))
    return result


def cmd_scan():
    run(["nmcli", "dev", "wifi", "rescan", "ifname", WIFI_IFACE], timeout=20)
    time.sleep(3)
    rc, out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
                   "ifname", WIFI_IFACE])
    if rc:
        return f"Помилка сканування: {out}"
    nets = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 3 or not f[0]:
            continue
        ssid, sig, sec = f[0], int(f[1] or 0), f[2] or "open"
        if ssid not in nets or nets[ssid][0] < sig:
            nets[ssid] = (sig, sec)
    if not nets:
        return "Мереж не знайдено"
    rows = sorted(nets.items(), key=lambda x: -x[1][0])[:15]
    return "Мережі:\n" + "\n".join(f" {s:3d}% {n} [{sec}]" for n, (s, sec) in rows)


def cmd_status():
    lines = [f"Ім'я: {socket.gethostname()}"]
    rc, out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"])
    for line in out.splitlines() if rc == 0 else []:
        f = split_terse(line)
        if len(f) >= 4 and f[1] in ("wifi", "ethernet"):
            lines.append(f"{f[0]}: {f[2]}" + (f" ({f[3]})" if f[3] else ""))
    rc, out = run(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    ips = re.findall(r"^\d+:\s+((?:wl|eth|en|usb)\S*)\s+inet\s+([\d.]+)", out, re.M) if rc == 0 else []
    for dev, ip in ips:
        lines.append(f"IP {dev}: {ip}")
    if ips:
        ip = ips[0][1]
        lines.append(f"VNC: http://{ip}:8080/vnc.html")
        lines.append(f"SSH: ssh cnc@{ip}")
    else:
        lines.append("IP-адреси немає")
    return "\n".join(lines)


def cmd_saved():
    profiles = wifi_profiles()
    if not profiles:
        return "Збережених мереж немає"
    return "Збережені:\n" + "\n".join(
        f" {name}" + (f" (SSID {ssid})" if ssid and ssid != name else "") for name, ssid in profiles)


def cmd_forget(name):
    targets = [n for n, s in wifi_profiles() if name in (n, s)]
    if not targets:
        return f"Мережу '{name}' не знайдено"
    for n in targets:
        run(["nmcli", "con", "delete", "id", n])
    return "Видалено: " + ", ".join(targets)


def validate(ssid, password):
    if not ssid or len(ssid.encode()) > 32:
        return "Невірна назва мережі (1-32 байти)"
    if password is not None and not (8 <= len(password) <= 63
                                     or re.fullmatch(r"[0-9a-fA-F]{64}", password)):
        return "Пароль WPA має бути 8-63 символи"
    return None


def cmd_connect(ssid, password):
    # Профіль з такою ж назвою може мати старий пароль — перестворюємо
    for name, _ in wifi_profiles():
        if name == ssid:
            run(["nmcli", "con", "delete", "id", name])
    add = ["nmcli", "con", "add", "type", "wifi", "ifname", WIFI_IFACE,
           "con-name", ssid, "ssid", ssid,
           "connection.autoconnect", "yes", "connection.autoconnect-priority", "10"]
    if password is not None:
        add += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    rc, out = run(add)
    if rc:
        return f"Не вдалося зберегти: {out}"
    rc, out = run(["nmcli", "--wait", "30", "con", "up", "id", ssid], timeout=45)
    if rc:
        return (f"Мережу '{ssid}' збережено, але підключитись зараз не вдалося.\n"
                f"Pi підключиться автоматично, коли мережа буде доступна.\n{out[-200:]}")
    time.sleep(2)
    return f"Підключено до '{ssid}'\n" + cmd_status()


# ---------------------------------------------------------- command shell --

class Session:
    """Стан розмови з телефоном: авторизація, введений SSID, черга відповідей."""

    def __init__(self, cfg, send):
        self.cfg = cfg
        self.send = send
        self.busy = False
        self.reset()
        self.fails = 0
        self.locked_until = 0

    def reset(self):
        self.authed = not self.cfg.get("PIN")
        self.last_active = time.monotonic()
        self.pending_ssid = None

    def handle_line(self, line):
        line = line.strip()
        if not line:
            return
        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        log(f"cmd: {cmd}")  # аргументи не логуємо — там може бути пароль

        now = time.monotonic()
        if self.authed and self.cfg.get("PIN") and now - self.last_active > AUTH_IDLE_SEC:
            self.authed = False
        self.last_active = now

        if cmd in ("help", "?", "h"):
            return self.send(HELP)
        if cmd in ("pin", "auth", "login"):
            return self.do_pin(arg)
        if not self.authed:
            return self.send("Спершу введіть: pin <PIN>")
        if self.busy:
            return self.send("Зачекайте, попередня команда ще виконується...")

        if cmd == "status":
            self.background(cmd_status)
        elif cmd == "scan":
            self.send("Сканую...")
            self.background(cmd_scan)
        elif cmd in ("saved", "list"):
            self.background(cmd_saved)
        elif cmd == "forget":
            if not arg:
                return self.send("Використання: forget Назва")
            self.background(cmd_forget, arg)
        elif cmd == "ssid":
            if not arg:
                return self.send("Використання: ssid Назва мережі")
            self.pending_ssid = arg
            self.send(f"Мережа: '{arg}'. Тепер: pass Пароль (або open)")
        elif cmd in ("pass", "password"):
            if not self.pending_ssid:
                return self.send("Спершу: ssid Назва")
            self.connect(self.pending_ssid, arg)
        elif cmd == "open":
            if not self.pending_ssid:
                return self.send("Спершу: ssid Назва")
            self.connect(self.pending_ssid, None)
        elif cmd == "wifi":
            try:
                parts = shlex.split(arg)
            except ValueError:
                return self.send("Помилка лапок. Спробуйте ssid/pass")
            if len(parts) not in (1, 2):
                return self.send('Використання: wifi "Назва" "Пароль"')
            self.connect(parts[0], parts[1] if len(parts) == 2 else None)
        else:
            self.send(f"Невідома команда '{cmd}'. Наберіть help")

    def do_pin(self, arg):
        now = time.monotonic()
        if not self.cfg.get("PIN"):
            self.authed = True
            return self.send("PIN не налаштовано, доступ відкритий")
        if now < self.locked_until:
            return self.send(f"Забагато спроб. Зачекайте {int(self.locked_until - now)} с")
        if arg == self.cfg["PIN"]:
            self.authed, self.fails = True, 0
            return self.send("OK. Наберіть help, status або scan")
        self.fails += 1
        if self.fails >= MAX_PIN_FAILS:
            self.fails, self.locked_until = 0, now + LOCKOUT_SEC
        self.send("Невірний PIN")

    def connect(self, ssid, password):
        self.pending_ssid = None
        error = validate(ssid, password)
        if error:
            return self.send(error)
        self.send(f"Підключаюсь до '{ssid}'...")
        self.background(cmd_connect, ssid, password)

    def background(self, fn, *args):
        self.busy = True

        def worker():
            try:
                result = fn(*args)
            except Exception as e:  # не даємо сервісу впасти через одну команду
                result = f"Помилка: {e}"
            GLib.idle_add(self.finish, result)

        threading.Thread(target=worker, daemon=True).start()

    def finish(self, result):
        self.busy = False
        self.send(result)
        return False


# ------------------------------------------------------------ BlueZ GATT ---

class InvalidArgs(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class Application(dbus.service.Object):
    PATH = "/org/cnc/btwifi"

    def __init__(self, bus):
        super().__init__(bus, self.PATH)
        self.services = []

    @dbus.service.method(DBUS_OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        resp = {}
        for s in self.services:
            resp[s.get_path()] = s.get_properties()
            for c in s.chars:
                resp[c.get_path()] = c.get_properties()
        return resp


class Service(dbus.service.Object):
    def __init__(self, bus, path, uuid):
        super().__init__(bus, path)
        self.path, self.uuid, self.chars = path, uuid, []

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {GATT_SERVICE: {
            "UUID": self.uuid, "Primary": True,
            "Characteristics": dbus.Array([c.get_path() for c in self.chars], signature="o")}}

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE:
            raise InvalidArgs()
        return self.get_properties()[GATT_SERVICE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, path, uuid, flags, service):
        super().__init__(bus, path)
        self.path, self.uuid, self.flags, self.service = path, uuid, flags, service
        self.value = []

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {GATT_CHRC: {
            "Service": self.service.get_path(), "UUID": self.uuid,
            "Flags": self.flags, "Value": dbus.Array(self.value, signature="y")}}

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHRC:
            raise InvalidArgs()
        return self.get_properties()[GATT_CHRC]

    @dbus.service.signal(DBUS_PROP, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class UartService(Service):
    """Nordic UART: RX приймає рядки команд, TX надсилає відповіді (notify)."""

    def __init__(self, bus, cfg):
        super().__init__(bus, Application.PATH + "/service0", NUS_SERVICE)
        self.tx = TxChrc(bus, self)
        self.rx = RxChrc(bus, self)
        self.chars = [self.rx, self.tx]
        self.session = Session(cfg, self.send)
        self.mtu = 23
        self.buf = b""
        self.flush_timer = None
        self.out_queue = []

    # --- вхід
    def on_write(self, data, options):
        if "mtu" in options:
            self.mtu = int(options["mtu"])
        self.buf += data
        while True:
            m = re.search(rb"[\r\n]", self.buf)
            if not m:
                break
            line, self.buf = self.buf[:m.start()], self.buf[m.end():]
            self.dispatch(line)
        # Деякі програми не додають кінець рядка — обробляємо після паузи
        if self.flush_timer:
            GLib.source_remove(self.flush_timer)
            self.flush_timer = None
        if self.buf:
            self.flush_timer = GLib.timeout_add(LINE_FLUSH_MS, self.flush_buf)

    def flush_buf(self):
        self.flush_timer = None
        line, self.buf = self.buf, b""
        self.dispatch(line)
        return False

    def dispatch(self, raw):
        self.session.handle_line(raw.decode("utf-8", errors="replace"))

    # --- вихід
    def send(self, text):
        data = (text.rstrip("\n") + "\n").encode("utf-8")
        size = max(20, min(self.mtu - 3, 180))
        start = len(self.out_queue) == 0
        while data:
            cut = min(size, len(data))
            # не розрізаємо UTF-8 символ між пакетами
            while cut < len(data) and (data[cut] & 0xC0) == 0x80:
                cut -= 1
            self.out_queue.append(data[:cut])
            data = data[cut:]
        if start:
            GLib.timeout_add(15, self.pump)

    def pump(self):
        if not self.out_queue:
            return False
        chunk = self.out_queue.pop(0)
        if self.tx.notifying:
            self.tx.notify(chunk)
        return bool(self.out_queue)

    def on_disconnect(self):
        self.out_queue.clear()
        self.buf = b""
        self.session.reset()


class RxChrc(Characteristic):
    def __init__(self, bus, service):
        super().__init__(bus, service.path + "/rx", NUS_RX,
                         ["write", "write-without-response"], service)

    @dbus.service.method(GATT_CHRC, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        self.service.on_write(bytes(value), options)


class TxChrc(Characteristic):
    def __init__(self, bus, service):
        super().__init__(bus, service.path + "/tx", NUS_TX, ["notify"], service)
        self.notifying = False

    def notify(self, data):
        self.PropertiesChanged(GATT_CHRC, {"Value": dbus.Array(data, signature="y")}, [])

    @dbus.service.method(GATT_CHRC, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array([], signature="y")

    @dbus.service.method(GATT_CHRC)
    def StartNotify(self):
        log("client connected")
        self.notifying = True
        self.service.session.reset()
        self.service.send("CNC Wi-Fi setup. " + (
            "Введіть: pin <PIN>" if not self.service.session.authed else "Наберіть help"))

    @dbus.service.method(GATT_CHRC)
    def StopNotify(self):
        log("client disconnected")
        self.notifying = False
        self.service.on_disconnect()


class Advertisement(dbus.service.Object):
    PATH = "/org/cnc/btwifi/adv0"

    def __init__(self, bus, name, level):
        super().__init__(bus, self.PATH)
        self.name, self.level = name, level

    def get_properties(self):
        # level 2: назва + UUID + discoverable, 1: без UUID, 0: лише назва
        props = {"Type": "peripheral", "LocalName": dbus.String(self.name)}
        if self.level >= 1:
            props["Discoverable"] = dbus.Boolean(True)
        if self.level >= 2:
            props["ServiceUUIDs"] = dbus.Array([NUS_SERVICE], signature="s")
        return props

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADV:
            raise InvalidArgs()
        return self.get_properties()

    @dbus.service.method(LE_ADV)
    def Release(self):
        log("advertisement released")


def find_adapter(bus, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        om = dbus.Interface(bus.get_object(BLUEZ, "/"), DBUS_OM)
        for path, ifaces in om.GetManagedObjects().items():
            if GATT_MANAGER in ifaces and LE_ADV_MANAGER in ifaces:
                return path
        if time.monotonic() > deadline:
            return None
        log("waiting for Bluetooth adapter...")
        time.sleep(3)


def main():
    cfg = load_config()
    if not cfg.get("PIN"):
        log("WARNING: PIN not set — anyone nearby can change Wi-Fi")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter_path = find_adapter(bus)
    if not adapter_path:
        log("Bluetooth adapter not found")
        sys.exit(1)
    log(f"adapter: {adapter_path}")

    adapter_props = dbus.Interface(bus.get_object(BLUEZ, adapter_path), DBUS_PROP)
    adapter_props.Set(ADAPTER, "Powered", dbus.Boolean(True))
    adapter_props.Set(ADAPTER, "Alias", dbus.String(cfg["NAME"]))

    app = Application(bus)
    app.services.append(UartService(bus, cfg))

    adapter_obj = bus.get_object(BLUEZ, adapter_path)
    gatt = dbus.Interface(adapter_obj, GATT_MANAGER)
    adv_mgr = dbus.Interface(adapter_obj, LE_ADV_MANAGER)
    loop = GLib.MainLoop()

    def fatal(msg):
        log(msg)
        loop.quit()
        sys.exit(1)

    def register_adv(level):
        adv = Advertisement(bus, cfg["NAME"], level)

        def on_err(e):
            adv.remove_from_connection()
            if level > 0:
                # 128-бітний UUID + довга назва можуть не влізти в 31 байт
                log(f"advertisement level {level} failed ({e}), retrying simpler")
                register_adv(level - 1)
            else:
                fatal(f"advertisement failed: {e}")

        adv_mgr.RegisterAdvertisement(adv.PATH, {},
                                      reply_handler=lambda: log(f"advertising as '{cfg['NAME']}'"),
                                      error_handler=on_err)

    gatt.RegisterApplication(app.PATH, {},
                             reply_handler=lambda: log("GATT service registered"),
                             error_handler=lambda e: fatal(f"GATT register failed: {e}"))
    register_adv(2)
    loop.run()


if __name__ == "__main__":
    main()
