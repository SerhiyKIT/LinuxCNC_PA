# clients/windows/bt_cnc_client/ble_transport.py
"""
BLE-транспорт на bleak: пошук CNC-Robot, підключення, notify з TX,
запис у RX пакетами під MTU. Без Qt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from bleak import BleakClient, BleakScanner

from protocol_client import DEVICE_NAME, RX_UUID, SERVICE_UUID, TX_UUID
from setup_client import SETUP_DEVICE_NAME, SETUP_SERVICE_UUID

logger = logging.getLogger(__name__)

DEFAULT_WRITE_SIZE = 20     # ATT MTU 23 - 3
MAX_WRITE_SIZE     = 180    # як на стороні мосту
SCAN_TIMEOUT       = 5.0


@dataclass(frozen=True)
class FoundDevice:
    name: str
    address: str
    rssi: int


async def scan(timeout: float = SCAN_TIMEOUT) -> list[FoundDevice]:
    """
    Роботи поблизу, сильніші першими. Один Pi рекламує по черзі CNC-Robot
    (міст) і CNC-Setup (Wi-Fi), тому шукаємо за обома і групуємо за адресою.
    """
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    result = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        uuids = [u.lower() for u in adv.service_uuids]
        if (SERVICE_UUID in uuids or SETUP_SERVICE_UUID in uuids
                or name.startswith((DEVICE_NAME, SETUP_DEVICE_NAME))):
            result.append(FoundDevice(name or device.address, device.address, adv.rssi))
    return sorted(result, key=lambda d: -d.rssi)


class BleTransport:
    def __init__(self, on_data: Callable[[bytes], None],
                 on_disconnect: Callable[[], None],
                 rx_uuid: str = RX_UUID, tx_uuid: str = TX_UUID) -> None:
        """Типово — міст CNC-Robot; для CNC-Setup передайте UUID Nordic UART."""
        self.on_data = on_data
        self.on_disconnect = on_disconnect
        self.rx_uuid, self.tx_uuid = rx_uuid, tx_uuid
        self.client: BleakClient | None = None
        self.write_size = DEFAULT_WRITE_SIZE

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def connect(self, address: str) -> None:
        await self.disconnect()
        client = BleakClient(address, disconnected_callback=lambda _: self._lost())
        await client.connect()
        try:
            self.write_size = max(DEFAULT_WRITE_SIZE, min(client.mtu_size - 3, MAX_WRITE_SIZE))
        except Exception:
            self.write_size = DEFAULT_WRITE_SIZE
        await client.start_notify(self.tx_uuid, lambda _char, data: self.on_data(bytes(data)))
        self.client = client
        logger.info("підключено до %s, пакет %d байт", address, self.write_size)

    async def write(self, data: bytes) -> None:
        if not self.connected:
            raise ConnectionError("немає з'єднання")
        for i in range(0, len(data), self.write_size):
            # З підтвердженням: порядок і доставка важливіші за швидкість
            await self.client.write_gatt_char(self.rx_uuid, data[i:i + self.write_size], response=True)

    async def disconnect(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception as exc:
                logger.debug("disconnect: %s", exc)

    def _lost(self) -> None:
        if self.client is not None:
            self.client = None
            self.on_disconnect()
