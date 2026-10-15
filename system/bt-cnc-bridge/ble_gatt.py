# system/bt-cnc-bridge/ble_gatt.py
"""
BlueZ D-Bus GATT: застосунок, сервіс з RX/TX, реклама.
За зразком system/bt-wifi-setup/bt_wifi_setup.py.

Обмеження BlueZ: notify через PropertiesChanged отримують УСІ клієнти,
підписані на TX, — адресно відповісти одному клієнту не можна.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import dbus
import dbus.exceptions
import dbus.service
from gi.repository import GLib

from bridge_constants import (
    DBUS_APP_PATH, DEFAULT_PAYLOAD, MAX_PAYLOAD, RX_UUID, SEND_INTERVAL_MS,
    SERVICE_UUID, TX_UUID,
)
from protocol import split_payload

logger = logging.getLogger(__name__)

BLUEZ          = "org.bluez"
DBUS_OM        = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP      = "org.freedesktop.DBus.Properties"
GATT_MANAGER   = "org.bluez.GattManager1"
GATT_SERVICE   = "org.bluez.GattService1"
GATT_CHRC      = "org.bluez.GattCharacteristic1"
LE_ADV_MANAGER = "org.bluez.LEAdvertisingManager1"
LE_ADV         = "org.bluez.LEAdvertisement1"
ADAPTER        = "org.bluez.Adapter1"
DEVICE         = "org.bluez.Device1"


class InvalidArgs(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class Application(dbus.service.Object):
    def __init__(self, bus, path: str = DBUS_APP_PATH) -> None:
        super().__init__(bus, path)
        self.path = path
        self.services: list[Service] = []

    @dbus.service.method(DBUS_OM, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        resp = {}
        for s in self.services:
            resp[s.get_path()] = s.get_properties()
            for c in s.chars:
                resp[c.get_path()] = c.get_properties()
        return resp


class Service(dbus.service.Object):
    def __init__(self, bus, path: str, uuid: str) -> None:
        super().__init__(bus, path)
        self.path, self.uuid = path, uuid
        self.chars: list[Characteristic] = []

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
    def __init__(self, bus, path: str, uuid: str, flags: list[str], service: Service) -> None:
        super().__init__(bus, path)
        self.path, self.uuid, self.flags, self.service = path, uuid, flags, service

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {GATT_CHRC: {
            "Service": self.service.get_path(), "UUID": self.uuid,
            "Flags": self.flags, "Value": dbus.Array([], signature="y")}}

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHRC:
            raise InvalidArgs()
        return self.get_properties()[GATT_CHRC]

    @dbus.service.signal(DBUS_PROP, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class SerialService(Service):
    """
    Сервіс із RX (write) і TX (notify).

    on_write(device_path, data) — байти від клієнта;
    on_subscribe(active) — хтось підписався на TX / усі відписались.
    """

    def __init__(self, bus, path: str,
                 on_write: Callable[[str, bytes], None],
                 on_subscribe: Callable[[bool], None]) -> None:
        super().__init__(bus, path, SERVICE_UUID)
        self.on_write = on_write
        self.on_subscribe = on_subscribe
        self.payload = DEFAULT_PAYLOAD
        self.queue: list[bytes] = []
        self.tx = TxChrc(bus, self)
        self.chars = [RxChrc(bus, self), self.tx]

    def handle_write(self, data: bytes, options) -> None:
        if "mtu" in options:
            self.payload = max(DEFAULT_PAYLOAD, min(int(options["mtu"]) - 3, MAX_PAYLOAD))
        device = str(options.get("device", "unknown"))
        self.on_write(device, data)

    def send(self, text: str) -> None:
        if not self.tx.notifying:
            return
        start = not self.queue
        self.queue.extend(split_payload(text, self.payload))
        if start:
            GLib.timeout_add(SEND_INTERVAL_MS, self._pump)

    def _pump(self) -> bool:
        if not self.queue or not self.tx.notifying:
            self.queue.clear()
            return False
        self.tx.notify(self.queue.pop(0))
        return bool(self.queue)


class RxChrc(Characteristic):
    def __init__(self, bus, service: SerialService) -> None:
        super().__init__(bus, service.path + "/rx", RX_UUID,
                         ["write", "write-without-response"], service)

    @dbus.service.method(GATT_CHRC, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        self.service.handle_write(bytes(value), options)


class TxChrc(Characteristic):
    def __init__(self, bus, service: SerialService) -> None:
        super().__init__(bus, service.path + "/tx", TX_UUID, ["notify"], service)
        self.notifying = False

    def notify(self, data: bytes) -> None:
        self.PropertiesChanged(GATT_CHRC, {"Value": dbus.Array(data, signature="y")}, [])

    @dbus.service.method(GATT_CHRC, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array([], signature="y")

    @dbus.service.method(GATT_CHRC)
    def StartNotify(self):
        self.notifying = True
        self.service.on_subscribe(True)

    @dbus.service.method(GATT_CHRC)
    def StopNotify(self):
        self.notifying = False
        self.service.on_subscribe(False)


class Advertisement(dbus.service.Object):
    """level 2: ім'я + UUID + discoverable, 1: без UUID, 0: лише ім'я."""

    def __init__(self, bus, path: str, name: str, level: int) -> None:
        super().__init__(bus, path)
        self.path, self.name, self.level = path, name, level

    def get_properties(self):
        props = {"Type": "peripheral", "LocalName": dbus.String(self.name)}
        if self.level >= 1:
            props["Discoverable"] = dbus.Boolean(True)
        if self.level >= 2:
            props["ServiceUUIDs"] = dbus.Array([SERVICE_UUID], signature="s")
        return props

    @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADV:
            raise InvalidArgs()
        return self.get_properties()

    @dbus.service.method(LE_ADV)
    def Release(self):
        logger.info("рекламу знято BlueZ")


def find_adapter(bus, timeout: float = 60) -> str | None:
    deadline = time.monotonic() + timeout
    while True:
        om = dbus.Interface(bus.get_object(BLUEZ, "/"), DBUS_OM)
        for path, ifaces in om.GetManagedObjects().items():
            if GATT_MANAGER in ifaces and LE_ADV_MANAGER in ifaces:
                return str(path)
        if time.monotonic() > deadline:
            return None
        logger.info("чекаю Bluetooth-адаптер...")
        time.sleep(3)


def register(bus, adapter_path: str, app: Application, adv_path: str, name: str,
             on_fatal: Callable[[str], None]) -> None:
    """
    Реєструє GATT-застосунок і рекламу. Alias адаптера НЕ змінюємо —
    його виставляє bt-wifi-setup; наше ім'я лише в LocalName реклами.
    """
    adapter = bus.get_object(BLUEZ, adapter_path)
    dbus.Interface(adapter, DBUS_PROP).Set(ADAPTER, "Powered", dbus.Boolean(True))
    gatt = dbus.Interface(adapter, GATT_MANAGER)
    adv_mgr = dbus.Interface(adapter, LE_ADV_MANAGER)

    def register_adv(level: int) -> None:
        adv = Advertisement(bus, adv_path, name, level)

        def on_err(e):
            adv.remove_from_connection()
            if level > 0:
                logger.warning("реклама рівня %d не пройшла (%s), спрощую", level, e)
                register_adv(level - 1)
            else:
                on_fatal(f"реклама не зареєстрована: {e}")

        adv_mgr.RegisterAdvertisement(
            adv.path, {},
            reply_handler=lambda: logger.info("реклама '%s' (рівень %d)", name, level),
            error_handler=on_err)

    gatt.RegisterApplication(
        app.path, {},
        reply_handler=lambda: logger.info("GATT-сервіс зареєстровано"),
        error_handler=lambda e: on_fatal(f"GATT не зареєстровано: {e}"))
    register_adv(2)


def watch_disconnects(bus, on_disconnect: Callable[[str], None]) -> None:
    """Викликає on_disconnect(device_path), коли пристрій BlueZ відключився."""

    def handler(interface, changed, invalidated, path=None):
        if interface == DEVICE and "Connected" in changed and not changed["Connected"]:
            on_disconnect(str(path))

    bus.add_signal_receiver(handler, dbus_interface=DBUS_PROP, signal_name="PropertiesChanged",
                            bus_name=BLUEZ, path_keyword="path")
