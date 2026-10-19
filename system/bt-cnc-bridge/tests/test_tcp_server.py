# system/bt-cnc-bridge/tests/test_tcp_server.py
"""Справжній TCP-сервер у GLib-циклі на 127.0.0.1 (без BlueZ і заліза)."""
import socket
import time

import pytest

GLib = pytest.importorskip("gi.repository.GLib")

from bridge_constants import DEFAULT_CONFIG  # noqa: E402
from bt_cnc_bridge import Bridge  # noqa: E402
from cnc_backend import CncBackend  # noqa: E402
from safety import Safety  # noqa: E402
from tcp_server import TcpServer  # noqa: E402


def pump(seconds=0.2):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


class Peer:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.sock.setblocking(False)
        self.buf = b""

    def say(self, line, wait=0.2):
        self.sock.sendall((line + "\n").encode())
        pump(wait)
        return self.read()

    def read(self):
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                self.buf += chunk
        except BlockingIOError:
            pass
        lines, _, self.buf = self.buf.rpartition(b"\n")
        return [l.decode() for l in lines.split(b"\n") if l] if lines else []


@pytest.fixture
def server(lc, clock, projects):
    cfg = dict(DEFAULT_CONFIG, PIN="1234")
    safety = Safety("1234", cfg["WATCHDOG_MS"], cfg["MAX_JOG_VEL"], "pause", clock)
    ble = []
    bridge = Bridge(cfg, CncBackend(str(projects), lc=lc, clock=clock), safety, ble.append)
    srv = TcpServer(bridge, "127.0.0.1", 0)
    yield srv, bridge, ble
    srv.close()


def test_session_over_tcp(server, lc):
    srv, bridge, ble = server
    peer = Peer(srv.port)
    pump()
    assert peer.say("ver") == ["OK ver 1"]
    assert peer.say("take") == ["ERR auth спершу pin <PIN>"]
    assert peer.say("pin 1234") == ["OK pin"]
    replies = peer.say("take")
    assert replies[0] == "OK take" and replies[1].startswith("EVT S ")
    # Адресні відповіді не йдуть у BLE; події (EVT) — для всіх
    assert not [l for l in ble if l.startswith(("OK", "ERR"))]
    peer.sock.close()


def test_two_lines_in_one_packet_and_split_packets(server):
    srv, *_ = server
    peer = Peer(srv.port)
    pump()
    peer.sock.sendall(b"ver\nhel")
    pump()
    peer.sock.sendall(b"p\n")
    pump()
    replies = peer.read()
    assert replies[0] == "OK ver 1" and replies[1].startswith("OK help ")


def test_owner_disconnect_releases_control(server, lc):
    srv, bridge, _ = server
    lc.machine.task_state = lc.STATE_ON
    peer = Peer(srv.port)
    pump()
    peer.say("pin 1234")
    peer.say("take")
    peer.say("jogc J0 + 5")
    assert bridge.safety.owner is not None
    peer.sock.close()
    pump(0.3)
    assert bridge.safety.owner is None
    assert lc.commands("jog")[-1][1] == lc.JOG_STOP
    assert not srv.conns


def test_max_clients(server):
    srv, *_ = server
    peers = [Peer(srv.port) for _ in range(5)]
    pump(0.3)
    assert len(srv.conns) == 4
