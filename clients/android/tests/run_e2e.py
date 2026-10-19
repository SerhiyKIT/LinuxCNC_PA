#!/usr/bin/env python3
# clients/android/tests/run_e2e.py
"""
Наскрізна перевірка мобільного додатка без Pi і без заліза:

  Bridge + TcpServer (мок linuxcnc, GLib-потік)
     <- websockify (роздає clients/android і проксує WebSocket)
        <- node e2e.mjs            (протокол через WebSocket)
        <- node e2e_browser.mjs    (headless Chrome: сам додаток, натискання кнопок)

Потрібні: python3 з PyGObject (gi), websockify, node >= 20, google-chrome.
Запуск: python3 clients/android/tests/run_e2e.py [каталог_для_скриншотів]
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
BRIDGE_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "system", "bt-cnc-bridge"))
sys.path[:0] = [BRIDGE_DIR, os.path.join(BRIDGE_DIR, "tests")]

from gi.repository import GLib  # noqa: E402

from bridge_constants import DEFAULT_CONFIG  # noqa: E402
from bt_cnc_bridge import Bridge  # noqa: E402
from cnc_backend import CncBackend  # noqa: E402
from conftest import FakeClock, make_fake_linuxcnc  # noqa: E402
from safety import Safety  # noqa: E402
from tcp_server import TcpServer  # noqa: E402

PIN = "1234"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_bridge(projects: str):
    lc = make_fake_linuxcnc()
    lc.machine.task_state = lc.STATE_ON           # «Power On» і Home, щоб працював jog
    lc.machine.homed = (1,) * 6
    cfg = dict(DEFAULT_CONFIG, PIN=PIN)
    safety = Safety(PIN, cfg["WATCHDOG_MS"], cfg["MAX_JOG_VEL"], "pause", FakeClock())
    bridge = Bridge(cfg, CncBackend(projects, lc=lc), safety, lambda t: None)
    server = TcpServer(bridge, "127.0.0.1", 0)
    GLib.timeout_add(200, lambda: (bridge.status_tick(), True)[1])
    loop = GLib.MainLoop()
    threading.Thread(target=loop.run, daemon=True).start()
    return lc, server, loop


def main() -> int:
    shots = sys.argv[1] if len(sys.argv) > 1 else ""
    projects = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"cnc-e2e-{os.getpid()}")
    os.makedirs(projects, exist_ok=True)
    lc, server, loop = start_bridge(projects)
    ws_port = free_port()
    websockify = shutil.which("websockify") or os.path.join(os.path.dirname(sys.executable), "websockify")
    proxy = subprocess.Popen([websockify, "--web", APP_DIR, str(ws_port), f"127.0.0.1:{server.port}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                html = urllib.request.urlopen(f"http://127.0.0.1:{ws_port}/index.html", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            print("websockify не відповідає")
            return 1
        assert b"CNC-Robot" in html
        print("OK HTTP: index.html роздається")

        env = dict(os.environ, E2E_URL=f"ws://127.0.0.1:{ws_port}/", E2E_PIN=PIN,
                   E2E_HTTP=f"http://127.0.0.1:{ws_port}/", E2E_SHOTS=shots)
        node = ["node", "--experimental-websocket", "--no-warnings"]
        rc = subprocess.call(node + [os.path.join(HERE, "e2e.mjs")], env=env)
        if rc == 0 and shutil.which("google-chrome"):
            rc = subprocess.call(node + [os.path.join(HERE, "e2e_browser.mjs")], env=env)
        # Перевірки на боці «верстата»
        files = os.listdir(projects)
        print("файли на «роботі»:", files)
        jogs = lc.commands("jog")
        print("jog-команди моста:", jogs)
        if rc == 0:
            assert any(c[1] == lc.JOG_STOP for c in jogs), "немає JOG_STOP після відпускання"
        return rc
    finally:
        proxy.terminate()
        loop.quit()
        server.close()
        shutil.rmtree(projects, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
