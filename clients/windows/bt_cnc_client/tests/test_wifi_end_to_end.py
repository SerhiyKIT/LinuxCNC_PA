# clients/windows/bt_cnc_client/tests/test_wifi_end_to_end.py
"""
Наскрізно по Wi-Fi: TcpTransport + CncClient (asyncio) <-> TcpServer + Bridge
мосту (GLib) з моком linuxcnc, в одному процесі на 127.0.0.1.
Потрібен gi (PyGObject) — на Windows тест пропускається.
"""
import asyncio
import os
import sys

import pytest

GLib = pytest.importorskip("gi.repository.GLib")

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.dirname(HERE)
BRIDGE_DIR = os.path.normpath(os.path.join(CLIENT_DIR, "..", "..", "..", "system", "bt-cnc-bridge"))
if not os.path.isdir(BRIDGE_DIR):
    pytest.skip("system/bt-cnc-bridge не знайдено", allow_module_level=True)
sys.path.insert(0, CLIENT_DIR)
sys.path.insert(0, os.path.join(BRIDGE_DIR, "tests"))
sys.path.insert(0, BRIDGE_DIR)

from bridge_constants import DEFAULT_CONFIG  # noqa: E402
from bt_cnc_bridge import Bridge  # noqa: E402
from cnc_backend import CncBackend  # noqa: E402
from conftest import FakeClock, make_fake_linuxcnc  # noqa: E402
from protocol_client import CncClient, CommandError, JogHold  # noqa: E402
from robot_program import Program, Step, to_gcode  # noqa: E402
from safety import Safety  # noqa: E402
from tcp_server import TcpServer  # noqa: E402
from tcp_transport import TcpTransport, parse_address  # noqa: E402


async def glib_pump():
    ctx = GLib.MainContext.default()
    while True:
        while ctx.iteration(False):
            pass
        await asyncio.sleep(0.002)


def make_robot(tmp_path):
    lc = make_fake_linuxcnc()
    clock = FakeClock()
    cfg = dict(DEFAULT_CONFIG, PIN="1234")
    safety = Safety("1234", cfg["WATCHDOG_MS"], cfg["MAX_JOG_VEL"], "pause", clock)
    bridge = Bridge(cfg, CncBackend(str(tmp_path), lc=lc, clock=clock), safety, lambda t: None)
    server = TcpServer(bridge, "127.0.0.1", 0)
    return lc, clock, bridge, server


def test_parse_address():
    assert parse_address("linuxcnc.local") == ("linuxcnc.local", 8765)
    assert parse_address(" 192.168.1.5:9000 ") == ("192.168.1.5", 9000)


def test_teach_upload_and_run_over_wifi(tmp_path):
    async def scenario():
        lc, clock, bridge, server = make_robot(tmp_path)
        pump = asyncio.ensure_future(glib_pump())
        lost = []
        statuses = []
        client = None
        transport = TcpTransport(on_data=lambda d: client.feed(d), on_disconnect=lambda: lost.append(1))
        client = CncClient(transport.write, on_status=statuses.append)
        try:
            await transport.connect(f"127.0.0.1:{server.port}")
            assert await client.version() == 1
            await client.login("1234")
            await client.take()
            await client.estop(False)
            await client.power(True)
            lc.machine.homed = (1,) * 6

            # «Навчання»: записуємо поточні положення зі статусу
            await client.request_status()
            await asyncio.sleep(0.05)
            st = statuses[-1]
            assert st.w == [17.0, 5.5, 7.2, 180.0, 0.0, 0.0] and st.u == "in"
            prog = Program(name="Навчання 1", steps=[
                Step("movej", joints=list(st.j), text="P1"),
                Step("movel", pose=list(st.w), text="P2"),
                Step("wait", seconds=0.5),
            ])
            gcode = to_gcode(prog)
            progress = []
            result = await client.upload_program(prog.file_name(), gcode,
                                                 lambda i, n: progress.append((i, n)))
            assert result.startswith("Навчання_1.ngc ")
            assert (tmp_path / "Навчання_1.ngc").read_text(encoding="utf-8") == gcode
            assert progress[-1][0] == progress[-1][1]

            await client.open_program(prog.file_name())
            await client.run()
            assert ("auto", lc.AUTO_RUN, 0) in lc.calls

            # Jog у світі з утриманням: зупинка після відпускання
            lc.machine.interp_state = lc.INTERP_IDLE
            jog = JogHold(client, interval=0.05)
            await jog.start("Z", 1, 0.3)
            await asyncio.sleep(0.15)
            await jog.stop()
            jogs = lc.commands("jog")
            assert jogs[0] == ("jog", lc.JOG_CONTINUOUS, False, 2, 0.3)
            assert jogs[-1] == ("jog", lc.JOG_STOP, False, 2)

            with pytest.raises(CommandError) as exc:
                await client.command("file begin ../evil.ngc")
            assert exc.value.code == "path"
        finally:
            await transport.disconnect()
            await asyncio.sleep(0.05)
            pump.cancel()
            server.close()
        assert lost == []                         # відключення з нашого боку — не «обрив»
        assert bridge.safety.owner is None        # міст звільнив керування
    asyncio.run(scenario())


def test_server_side_drop_is_reported(tmp_path):
    async def scenario():
        lc, clock, bridge, server = make_robot(tmp_path)
        pump = asyncio.ensure_future(glib_pump())
        lost = asyncio.Event()
        client = None
        transport = TcpTransport(on_data=lambda d: client.feed(d), on_disconnect=lost.set)
        client = CncClient(transport.write)
        try:
            await transport.connect(f"127.0.0.1:{server.port}")
            await client.version()
            server.close()                        # Pi зник (перезавантаження, Wi-Fi)
            await asyncio.wait_for(lost.wait(), 2)
            assert not transport.connected
        finally:
            pump.cancel()
    asyncio.run(scenario())
