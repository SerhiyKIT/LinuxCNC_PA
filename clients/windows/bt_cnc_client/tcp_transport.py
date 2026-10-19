# clients/windows/bt_cnc_client/tcp_transport.py
"""
Wi-Fi-транспорт: TCP-з'єднання з мостом (system/bt-cnc-bridge/tcp_server.py).
Той самий інтерфейс, що й BleTransport: connect / write / disconnect,
вхідні байти — в on_data, обрив — on_disconnect. Без Qt.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Callable

from protocol_client import TCP_PORT

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0


def parse_address(text: str) -> tuple[str, int]:
    """`linuxcnc.local`, `192.168.1.5` або `192.168.1.5:8765` -> (host, port)."""
    text = text.strip()
    host, sep, port = text.rpartition(":")
    if sep and port.isdigit() and host:
        return host, int(port)
    return text, TCP_PORT


class TcpTransport:
    def __init__(self, on_data: Callable[[bytes], None],
                 on_disconnect: Callable[[], None]) -> None:
        self.on_data = on_data
        self.on_disconnect = on_disconnect
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    async def connect(self, address: str) -> None:
        await self.disconnect()
        host, port = parse_address(address)
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        sock = self.writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.task = asyncio.ensure_future(self._read_loop())
        logger.info("підключено до %s:%d", host, port)

    async def _read_loop(self) -> None:
        try:
            while True:
                data = await self.reader.read(4096)
                if not data:
                    break
                self.on_data(data)
        except (ConnectionError, OSError) as exc:
            logger.info("TCP: %s", exc)
        except asyncio.CancelledError:
            return                     # відключення з нашого боку
        self._lost()

    async def write(self, data: bytes) -> None:
        if not self.connected:
            raise ConnectionError("немає з'єднання")
        self.writer.write(data)
        await self.writer.drain()

    async def disconnect(self) -> None:
        task, self.task = self.task, None
        if task:
            task.cancel()
        writer, self.writer = self.writer, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    def _lost(self) -> None:
        if self.writer is not None:
            self.writer = None
            self.task = None
            self.on_disconnect()
