# clients/windows/bt_cnc_client/tests/test_setup_wizard.py
"""
Майстер першого підключення у вікні (offscreen) зі справжньою логікою:
Bluetooth-конфігуратор — Session з bt_wifi_setup (nmcli підмінено),
Wi-Fi — справжній TcpServer мосту з моком linuxcnc. Кнопки натискаються
як користувачем. Скриншоти — у $WIZARD_SHOTS, якщо задано.
"""
import asyncio
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
qasync = pytest.importorskip("qasync")
GLib = pytest.importorskip("gi.repository.GLib")

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.dirname(HERE)
REPO = os.path.normpath(os.path.join(CLIENT_DIR, "..", "..", ".."))
BRIDGE_DIR = os.path.join(REPO, "system", "bt-cnc-bridge")
WIFI_DIR = os.path.join(REPO, "system", "bt-wifi-setup")
sys.path[:0] = [CLIENT_DIR, BRIDGE_DIR, os.path.join(BRIDGE_DIR, "tests"), WIFI_DIR, HERE]
try:
    import bt_wifi_setup as bt_wifi  # noqa: E402
except ImportError:
    pytest.skip("bt_wifi_setup недоступний", allow_module_level=True)

from PyQt5 import QtCore  # noqa: E402

from bridge_constants import DEFAULT_CONFIG  # noqa: E402
from bt_cnc_bridge import Bridge  # noqa: E402
from cnc_backend import CncBackend  # noqa: E402
from conftest import FakeClock, make_fake_linuxcnc  # noqa: E402
from safety import Safety  # noqa: E402
from setup_wizard import SetupWizard  # noqa: E402
from tcp_server import TcpServer  # noqa: E402
from test_setup_client import FakeNmcli  # noqa: E402
from ble_transport import FoundDevice  # noqa: E402

PIN = "949335"
SHOTS = os.environ.get("WIZARD_SHOTS")


class FakeBle:
    """Замість bleak: байти йдуть прямо в Session конфігуратора."""

    def __init__(self, on_data, on_disconnect, session_factory):
        self.on_data = on_data
        self.session = session_factory(self._notify)
        self.connected = False

    def _notify(self, text):
        data = (text.rstrip("\n") + "\n").encode()
        for i in range(0, len(data), 20):
            self.on_data(data[i:i + 20])

    async def connect(self, address):
        self.connected = True

    async def write(self, data):
        for line in data.decode().splitlines():
            self.session.handle_line(line)

    async def disconnect(self):
        self.connected = False


@pytest.fixture
def env(monkeypatch, tmp_path):
    nm = FakeNmcli()
    monkeypatch.setattr(bt_wifi, "run", nm)
    monkeypatch.setattr(bt_wifi.time, "sleep", lambda s: None)
    # міст на 127.0.0.1, а «робот» повідомляє IP 192.168.1.57 — підміняємо адресу в TcpTransport
    lc = make_fake_linuxcnc()
    cfg = dict(DEFAULT_CONFIG, PIN=PIN)
    bridge = Bridge(cfg, CncBackend(str(tmp_path), lc=lc), Safety(PIN, 500, 20.0, "pause", FakeClock()),
                    lambda t: None)
    server = TcpServer(bridge, "127.0.0.1", 0)
    import tcp_transport
    real_connect = tcp_transport.TcpTransport.connect

    async def connect(self, address):
        return await real_connect(self, address.replace("192.168.1.57:8765", f"127.0.0.1:{server.port}"))
    monkeypatch.setattr(tcp_transport.TcpTransport, "connect", connect)
    yield nm, bridge
    server.close()


def shot(widget, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        widget.grab().save(os.path.join(SHOTS, f"{name}.png"))


async def until(cond, what, timeout=10.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError(f"не дочекались: {what}")
        await asyncio.sleep(0.02)


async def glib_pump():
    # Qt на Linux сам обслуговує головний контекст GLib (QEventDispatcherGlib),
    # тож окремо його крутити не можна — це рекурсія. Лишаємо порожню задачу.
    await asyncio.Event().wait()


def run_qt(coro_fn):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # У Studio завжди є головне вікно; тут майстер — єдине вікно, і його
    # закриття інакше завершило б застосунок разом із циклом подій
    app.setQuitOnLastWindowClosed(False)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        return loop.run_until_complete(coro_fn())


def test_wizard_first_setup(env):
    nm, bridge = env

    async def scenario():
        pump = asyncio.ensure_future(glib_pump())
        session_factory = lambda send: bt_wifi.Session({"PIN": PIN, "NAME": "CNC-Setup"}, send)  # noqa: E731

        async def fake_scan():
            await asyncio.sleep(0.05)
            return [FoundDevice("CNC-Robot", "E4:5F:01:2B:F9:63", -45),
                    FoundDevice("CNC-Setup", "E4:5F:01:2B:F9:63", -46)]

        results = []
        wizard = SetupWizard(scan=fake_scan,
                             make_ble=lambda d, l: FakeBle(d, l, session_factory))
        wizard.completed.connect(lambda h, p, r: results.append((h, p, r)))
        wizard.show()
        try:
            # 1. Пошук: один робот (дві реклами одного Pi злиті)
            assert not wizard.next_btn.isEnabled()
            wizard.find_btn.click()
            await until(lambda: wizard.robot_list.count() == 1 and not wizard.busy, "робот у списку")
            shot(wizard, "1-find")
            wizard.next_btn.click()
            await until(lambda: wizard.stack.currentIndex() == 1 and not wizard.busy, "крок PIN")

            # 2. PIN: спершу помилковий
            wizard.pin_edit.setText("000000")
            wizard.next_btn.click()
            await until(lambda: "Невірний PIN" in wizard.message.text(), "повідомлення про PIN")
            shot(wizard, "2-pin-wrong")
            wizard.pin_edit.setText(PIN)
            await until(lambda: not wizard.busy, "кінець перевірки PIN")
            wizard.next_btn.click()
            await until(lambda: wizard.stack.currentIndex() == 2 and wizard.wifi_list.count() == 2
                        and not wizard.busy, "список Wi-Fi")
            assert not wizard.keep_btn.isVisible()                 # робот ще не в мережі

            # 3. Wi-Fi: короткий пароль не пускає далі, неправильний — зрозуміла помилка
            wizard.wifi_list.setCurrentRow(0)
            wizard.password_edit.setText("short")
            assert not wizard.next_btn.isEnabled()
            wizard.password_edit.setText("wrong-pass")
            shot(wizard, "3-wifi")
            wizard.next_btn.click()
            await until(lambda: "неправильний пароль" in wizard.message.text() and not wizard.busy,
                        "помилка пароля")
            wizard.password_edit.setText("correct-horse")
            await until(lambda: wizard.next_btn.isEnabled(), "кнопка активна")
            wizard.next_btn.click()
            await until(lambda: wizard.stack.currentIndex() == 3, "крок «Готово»")
            assert "192.168.1.57" in wizard.done_label.text()
            assert wizard.control_pin.text() == PIN
            shot(wizard, "4-done")

            # 4. Перевірка зв'язку з мостом по Wi-Fi і завершення
            wizard.next_btn.click()
            await until(lambda: results, "completed")
            assert results == [("192.168.1.57:8765", PIN, True)]
            assert not wizard.isVisible()
        finally:
            pump.cancel()

    run_qt(scenario)


def test_wizard_keep_existing_network_and_wrong_control_pin(env):
    nm, bridge = env
    nm.connected = "Office"                                   # робот уже в мережі

    async def scenario():
        pump = asyncio.ensure_future(glib_pump())
        session_factory = lambda send: bt_wifi.Session({"PIN": PIN, "NAME": "CNC-Setup"}, send)  # noqa: E731

        async def fake_scan():
            return [FoundDevice("CNC-Setup", "AA:BB", -70)]

        results = []
        wizard = SetupWizard(scan=fake_scan, make_ble=lambda d, l: FakeBle(d, l, session_factory))
        wizard.completed.connect(lambda h, p, r: results.append((h, p, r)))
        wizard.show()
        try:
            wizard.find_btn.click()
            await until(lambda: wizard.robot_list.count() == 1 and not wizard.busy, "робот")
            wizard.next_btn.click()
            await until(lambda: wizard.stack.currentIndex() == 1 and not wizard.busy, "крок PIN")
            wizard.pin_edit.setText(PIN)
            wizard.next_btn.click()
            await until(lambda: wizard.stack.currentIndex() == 2 and not wizard.busy, "Wi-Fi")
            assert wizard.keep_btn.isVisible() and "Office" in wizard.current_label.text()
            wizard.keep_btn.click()
            await until(lambda: wizard.stack.currentIndex() == 3, "Готово")
            wizard.control_pin.setText("111111")
            wizard.remember.setChecked(False)
            wizard.next_btn.click()
            await until(lambda: "PIN керування не підійшов" in wizard.message.text() and not wizard.busy,
                        "помилка PIN керування")
            wizard.control_pin.setText(PIN)
            await until(lambda: wizard.next_btn.isEnabled(), "кнопка активна")
            wizard.next_btn.click()
            await until(lambda: results, "completed")
            assert results == [("192.168.1.57:8765", PIN, False)]
        finally:
            pump.cancel()

    run_qt(scenario)
