# system/bt-cnc-bridge/tcp_server.py
"""
Доступ до мосту по Wi-Fi (TCP). Протокол той самий, що й по BLE:
рядки UTF-8 з '\\n', PIN, власник керування.

Працює в тому ж GLib-циклі, що й BLE, тому Bridge не потребує потоків.
Обрив Wi-Fi виявляється через TCP keepalive (~11 с); безперервний jog
однаково зупиняє watchdog мосту за WATCHDOG_MS.
"""
from __future__ import annotations

import logging
import socket

from gi.repository import GLib

from bridge_constants import (
    TCP_KEEPALIVE, TCP_MAX_CLIENTS, TCP_RECV_BYTES, TCP_SEND_TIMEOUT,
)

logger = logging.getLogger(__name__)


def _set_keepalive(conn: socket.socket) -> None:
    idle, interval, count = TCP_KEEPALIVE
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for opt, value in (("TCP_KEEPIDLE", idle), ("TCP_KEEPINTVL", interval), ("TCP_KEEPCNT", count)):
        if hasattr(socket, opt):
            conn.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), value)


class TcpServer:
    def __init__(self, bridge, host: str, port: int) -> None:
        self.bridge = bridge
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(TCP_MAX_CLIENTS)
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.conns: dict[str, tuple[socket.socket, int]] = {}
        self.watch = GLib.io_add_watch(self.sock.fileno(), GLib.PRIORITY_DEFAULT,
                                       GLib.IO_IN, self._accept)
        logger.info("TCP: слухаю %s:%d", host, self.port)

    def _accept(self, _fd, _cond) -> bool:
        try:
            conn, addr = self.sock.accept()
        except BlockingIOError:
            return True
        client = f"tcp:{addr[0]}:{addr[1]}"
        if len(self.conns) >= TCP_MAX_CLIENTS:
            logger.warning("TCP: відхилено %s — забагато клієнтів", client)
            conn.close()
            return True
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        _set_keepalive(conn)
        # recv викликається лише коли є дані; таймаут обмежує sendall
        conn.settimeout(TCP_SEND_TIMEOUT)
        watch = GLib.io_add_watch(conn.fileno(), GLib.PRIORITY_DEFAULT,
                                  GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                                  self._on_readable, client)
        self.conns[client] = (conn, watch)
        self.bridge.register_client(client, lambda text, c=client: self._send(c, text))
        logger.info("TCP: підключився %s", client)
        return True

    def _on_readable(self, _fd, cond, client: str) -> bool:
        entry = self.conns.get(client)
        if entry is None:
            return False
        conn = entry[0]
        data = b""
        if cond & GLib.IO_IN:
            try:
                data = conn.recv(TCP_RECV_BYTES)
            except OSError:
                data = b""
        if not data:
            self._close(client)
            return False
        self.bridge.handle_bytes(client, data)
        return client in self.conns

    def _send(self, client: str, text: str) -> None:
        entry = self.conns.get(client)
        if entry is None:
            return
        try:
            entry[0].sendall((text.rstrip("\n") + "\n").encode("utf-8"))
        except OSError as exc:
            logger.warning("TCP: %s не приймає дані (%s)", client, exc)
            # Закриваємо пізніше, щоб не змінювати стан посеред обробки команди
            GLib.idle_add(self._close_idle, client)

    def _close_idle(self, client: str) -> bool:
        self._close(client)
        return False

    def _close(self, client: str) -> None:
        entry = self.conns.pop(client, None)
        if entry is None:
            return
        conn, watch = entry
        source = GLib.MainContext.default().find_source_by_id(watch)
        if source is not None and not source.is_destroyed():
            GLib.source_remove(watch)
        try:
            conn.close()
        except OSError:
            pass
        logger.info("TCP: відключився %s", client)
        self.bridge.client_disconnected(client)

    def close(self) -> None:
        for client in list(self.conns):
            self._close(client)
        GLib.source_remove(self.watch)
        self.sock.close()
