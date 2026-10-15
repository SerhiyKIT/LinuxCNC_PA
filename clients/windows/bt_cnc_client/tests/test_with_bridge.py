# clients/windows/bt_cnc_client/tests/test_with_bridge.py
"""
Наскрізна перевірка: CncClient <-> справжній Bridge з system/bt-cnc-bridge
і мок linuxcnc. BLE замінено прямою передачею байтів з нарізкою по 20 байт.
Пропускається, якщо міст не лежить поруч у репозиторії.
"""
import asyncio
import os
import sys

import pytest

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
from protocol import split_payload  # noqa: E402
from protocol_client import CncClient, CommandError  # noqa: E402
from safety import Safety  # noqa: E402

DEVICE = "/org/bluez/hci0/dev_PC"


def make_pair(tmp_path):
    (tmp_path / "part.ngc").write_text("M2\n")
    lc = make_fake_linuxcnc()
    clock = FakeClock()
    cfg = dict(DEFAULT_CONFIG, PIN="1234", PROJECTS_DIR=str(tmp_path))
    safety = Safety("1234", cfg["WATCHDOG_MS"], cfg["MAX_JOG_VEL"], "pause", clock)
    backend = CncBackend(str(tmp_path), lc=lc, clock=clock)
    statuses = []
    holder = {}

    def bridge_send(text):
        for chunk in split_payload(text, 20):          # як notify при MTU 23
            holder["client"].feed(chunk)

    bridge = Bridge(cfg, backend, safety, bridge_send)

    async def client_write(data: bytes):
        for i in range(0, len(data), 20):
            bridge.handle_bytes(DEVICE, data[i:i + 20])

    client = CncClient(client_write, on_status=statuses.append)
    holder["client"] = client
    return client, bridge, lc, clock, statuses


def test_session_against_real_bridge(tmp_path):
    async def scenario():
        client, bridge, lc, clock, statuses = make_pair(tmp_path)
        assert await client.version() == 1
        with pytest.raises(CommandError) as exc:
            await client.take()
        assert exc.value.code == "auth"
        await client.login("1234")
        await client.take()
        assert statuses[-1].ctl == 1 and statuses[-1].st == "estop"
        await client.estop(False)
        await client.power(True)
        await client.home_all()
        lc.machine.homed = (1,) * 6
        assert await client.jog_step(1, 5) == "J1 5 @5"        # обрізано INI J1=5
        assert await client.jog_continuous(0, -1, 50) == "J0 -20"
        await client.ping()
        await client.jog_stop(0)
        assert await client.list_programs() == ["part.ngc"]
        await client.open_program("part.ngc")
        await client.run()
        lc.machine.interp_state = lc.INTERP_READING
        await client.pause()
        await client.stop()
        await client.feed_override(80)
        with pytest.raises(CommandError) as exc:
            await client.command("fo 151")
        assert exc.value.code == "args"
        bridge.status_tick()
        assert statuses[-1].prog == "part.ngc"
        assert ("auto", lc.AUTO_PAUSE) in lc.calls and ("abort",) in lc.calls
    asyncio.run(scenario())


def test_long_reply_reassembled_from_small_packets(tmp_path):
    async def scenario():
        client, *_ = make_pair(tmp_path)
        text = await client.command("help")
        assert text.startswith("ver | help") and "fo <0-150>" in text
    asyncio.run(scenario())
