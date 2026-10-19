# clients/windows/bt_cnc_client/tests/test_setup_client.py
"""
Майстер першого налаштування проти справжньої логіки Wi-Fi-конфігуратора
(system/bt-wifi-setup/bt_wifi_setup.py: клас Session), з підміненим nmcli
і з нарізкою відповідей на 20-байтні BLE-пакети.
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.dirname(HERE)
WIFI_DIR = os.path.normpath(os.path.join(CLIENT_DIR, "..", "..", "..", "system", "bt-wifi-setup"))
sys.path.insert(0, CLIENT_DIR)

from setup_client import (  # noqa: E402
    SetupClient, SetupError, WifiNetwork, parse_networks, parse_status,
)

if os.path.isdir(WIFI_DIR):
    sys.path.insert(0, WIFI_DIR)
try:
    import bt_wifi_setup as bt_wifi  # noqa: E402
except ImportError:                    # немає dbus/gi (наприклад, Windows)
    bt_wifi = None

STATUS_TEXT = """Ім'я: linuxcnc
wlan0: connected (Office WiFi)
IP wlan0: 192.168.1.57
VNC: http://192.168.1.57:8080/vnc.html
SSH: ssh cnc@192.168.1.57"""


def test_parse_networks_and_status():
    nets = parse_networks("Мережі:\n  69% Office \"5G\" [WPA2]\n   8% Кафе [open]\n bad line\n")
    assert nets == [WifiNetwork('Office "5G"', 69, "WPA2"), WifiNetwork("Кафе", 8, "open")]
    assert nets[0].secured and not nets[1].secured
    st = parse_status(STATUS_TEXT)
    assert st.hostname == "linuxcnc" and st.ip == "192.168.1.57"
    assert st.wifi_state == "connected" and st.wifi_network == "Office WiFi"
    assert parse_status("IP-адреси немає").ip == ""


class FakeNmcli:
    """Мінімальна імітація nmcli для bt_wifi_setup.run()."""

    def __init__(self):
        self.connected = None
        self.calls = []

    def __call__(self, cmd, timeout=40):
        self.calls.append(cmd)
        args = cmd[1:]
        if args[:3] == ["dev", "wifi", "rescan"]:
            return 0, ""
        if "list" in args and "wifi" in args:
            return 0, "Office \\\"5G\\\":69:WPA2\nКафе:30:\nOffice \\\"5G\\\":40:WPA2\n"
        if args[:3] == ["-t", "-f", "NAME,TYPE"]:
            return 0, ""
        if "add" in args:
            psk = args[args.index("wifi-sec.psk") + 1] if "wifi-sec.psk" in args else None
            self.pending = (args[args.index("ssid") + 1], psk)
            return 0, ""
        if "up" in args:
            ssid, psk = self.pending
            if psk not in (None, "correct-horse"):
                return 4, "Error: Secrets were required, but not provided."
            self.connected = ssid
            return 0, ""
        if "dev" in args and "status" in args:
            line = f"wlan0:wifi:connected:{self.connected}" if self.connected else "wlan0:wifi:disconnected:"
            return 0, line
        if cmd[0] == "ip":
            return (0, "3: wlan0    inet 192.168.1.57/24 brd 192.168.1.255 scope global wlan0")\
                if self.connected else (0, "")
        return 0, ""


@pytest.fixture
def robot(monkeypatch):
    if bt_wifi is None:
        pytest.skip("bt_wifi_setup недоступний (dbus/gi)")
    nm = FakeNmcli()
    monkeypatch.setattr(bt_wifi, "run", nm)
    monkeypatch.setattr(bt_wifi.time, "sleep", lambda s: None)
    return nm


def make_pair(nm):
    """SetupClient <-> справжня Session конфігуратора, BLE-пакети по 20 байт."""
    from gi.repository import GLib   # Session.background віддає результат через GLib.idle_add
    holder = {}

    def session_send(text):
        data = (text.rstrip("\n") + "\n").encode()
        for i in range(0, len(data), 20):
            holder["client"].feed(data[i:i + 20])

    session = bt_wifi.Session({"PIN": "949335", "NAME": "CNC-Setup"}, session_send)

    async def write(data: bytes):
        for line in data.decode().splitlines():
            session.handle_line(line)

    client = SetupClient(write)
    holder["client"] = client

    async def pump():
        ctx = GLib.MainContext.default()
        while True:
            while ctx.iteration(False):
                pass
            await asyncio.sleep(0.01)
    return client, session, pump


def test_full_first_setup(robot):
    async def scenario():
        client, session, pump = make_pair(robot)
        task = asyncio.ensure_future(pump())
        try:
            with pytest.raises(SetupError, match="Потрібен PIN"):
                await client.status()
            with pytest.raises(SetupError, match="Невірний PIN"):
                await client.login("000000")
            await client.login("949335")
            st = await client.status()
            assert st.ip == "" and st.wifi_state == "disconnected"
            nets = await client.scan()
            assert [n.ssid for n in nets] == ['Office "5G"', "Кафе"]   # дублікати злиті, сильніша першою
            bad = await client.connect_wifi('Office "5G"', "wrong-pass")
            assert not bad.connected and "пароль" in bad.message
            ok = await client.connect_wifi('Office "5G"', "correct-horse")
            assert ok.connected and ok.status.ip == "192.168.1.57"
            # назва з лапками дійшла до nmcli без змін
            assert any(c[:3] == ["nmcli", "con", "add"] and 'Office "5G"' in c for c in robot.calls)
        finally:
            task.cancel()
    asyncio.run(scenario())


def test_open_network_and_short_password(robot):
    async def scenario():
        client, session, pump = make_pair(robot)
        task = asyncio.ensure_future(pump())
        try:
            await client.login("949335")
            short = await client.connect_wifi("Office", "123")
            assert not short.connected and "8 до 63" in short.message
            ok = await client.connect_wifi("Кафе", None)
            assert ok.connected
            add = next(c for c in robot.calls if c[:3] == ["nmcli", "con", "add"] and "Кафе" in c)
            assert "wifi-sec.psk" not in add
        finally:
            task.cancel()
    asyncio.run(scenario())


def test_timeout_when_robot_silent():
    async def scenario():
        async def write(data):
            pass
        client = SetupClient(write)
        import setup_client
        old = setup_client.REPLY_TIMEOUT
        try:
            with pytest.raises(SetupError, match="не відповів"):
                await client._exchange("status", lambda r: False, timeout=0.2)
        finally:
            setup_client.REPLY_TIMEOUT = old
    asyncio.run(scenario())
