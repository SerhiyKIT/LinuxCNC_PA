# system/bt-cnc-bridge/tests/test_bridge.py
"""Наскрізні сценарії: байти з BLE -> Bridge -> мок linuxcnc -> відповіді."""
import json

import pytest

from bridge_constants import DEFAULT_CONFIG
from bt_cnc_bridge import Bridge, load_config
from conftest import power_on
from safety import Safety

A = "/org/bluez/hci0/dev_AA"
B = "/org/bluez/hci0/dev_BB"


@pytest.fixture
def out():
    return []


@pytest.fixture
def bridge(backend, clock, out):
    cfg = dict(DEFAULT_CONFIG, PIN="1234")
    safety = Safety(cfg["PIN"], cfg["WATCHDOG_MS"], cfg["MAX_JOG_VEL"], "pause", clock)
    return Bridge(cfg, backend, safety, out.append)


def say(bridge, out, client, line):
    out.clear()
    bridge.handle_bytes(client, (line + "\n").encode())
    return list(out)


def login_take(bridge, out, client=A):
    assert say(bridge, out, client, "pin 1234") == ["OK pin"]
    return say(bridge, out, client, "take")


def test_public_commands_before_pin(bridge, out):
    assert say(bridge, out, A, "ver") == ["OK ver 1"]
    assert say(bridge, out, A, "help")[0].startswith("OK help ")
    assert say(bridge, out, A, "status") == ["ERR auth спершу pin <PIN>"]
    assert say(bridge, out, A, "pin 9999") == ["ERR auth невірний PIN"]


def test_take_sends_status(bridge, out, lc):
    replies = login_take(bridge, out)
    assert replies[0] == "OK take"
    status = json.loads(replies[1][len("EVT S "):])
    assert status["st"] == "estop" and status["ctl"] == 1


def test_status_streams_only_on_change(bridge, out, lc):
    login_take(bridge, out)
    out.clear()
    bridge.status_tick()
    assert out == []                           # нічого не змінилось
    lc.machine.joint_actual_position = (5.0, 0, 0, 0, 0, 0)
    bridge.status_tick()
    assert len(out) == 1 and '"j":[5.0,' in out[0]


def test_errors_forwarded(bridge, out, lc):
    login_take(bridge, out)
    out.clear()
    lc.errors = [(lc.NML_ERROR, "joint 2 following error")]
    bridge.status_tick()
    assert "EVT E joint 2 following error" in out


def test_control_needs_take(bridge, out):
    say(bridge, out, A, "pin 1234")
    assert say(bridge, out, A, "power on") == ["ERR owner спершу take"]
    say(bridge, out, B, "pin 1234")
    login_take(bridge, out, A)
    assert say(bridge, out, B, "take") == ["ERR busy керування зайняте іншим клієнтом"]
    # аварійну зупинку може натиснути будь-хто з PIN
    assert say(bridge, out, B, "estop on") == ["OK estop"]


def test_nocnc_does_not_crash(bridge, out, lc):
    lc.running = False
    login_take(bridge, out)
    assert say(bridge, out, A, "power on") == ["ERR nocnc LinuxCNC не запущений"]
    out.clear()
    bridge.status_tick()                       # без винятку


def test_full_sequence(bridge, out, lc, projects):
    login_take(bridge, out)
    assert say(bridge, out, A, "estop off") == ["OK estop"]
    assert say(bridge, out, A, "power on") == ["OK power"]
    assert say(bridge, out, A, "mdi G0 X1")[0].startswith("ERR state")   # не homed
    assert say(bridge, out, A, "home all") == ["OK home"]
    lc.machine.homed = (1,) * 6               # хоумінг завершився
    # J1: MAX_VELOCITY=5 в INI, JOG_VEL=10 -> обрізано до 5
    assert say(bridge, out, A, "jog J1 +5") == ["OK jog J1 5 @5"]
    assert lc.commands("jog")[-1] == ("jog", lc.JOG_INCREMENT, True, 1, 5.0, 5.0)
    assert say(bridge, out, A, "ls") == ['OK ls ["part.ngc","Деталь 2.nc"]']
    assert say(bridge, out, A, "open ../secret.ngc")[0].startswith("ERR path")
    assert say(bridge, out, A, "open part.ngc") == ["OK open part.ngc"]
    assert say(bridge, out, A, "run") == ["OK run"]
    lc.machine.interp_state = lc.INTERP_READING
    assert say(bridge, out, A, "pause") == ["OK pause"]
    assert say(bridge, out, A, "stop") == ["OK stop"]
    assert ("abort",) in lc.calls


def test_jogc_watchdog(bridge, out, lc, clock):
    power_on(lc)
    login_take(bridge, out)
    # 50 > MAX_JOG_VEL=20 і > 30 з INI -> 20
    assert say(bridge, out, A, "jogc J0 + 50") == ["OK jogc J0 +20"]
    assert lc.commands("jog")[-1] == ("jog", lc.JOG_CONTINUOUS, True, 0, 20.0)
    for _ in range(5):
        clock.advance(0.2)
        say(bridge, out, A, "ping")
        bridge.watchdog_tick()
    assert lc.commands("jog")[-1][1] == lc.JOG_CONTINUOUS     # ще їде
    clock.advance(0.6)
    out.clear()
    bridge.watchdog_tick()
    assert lc.commands("jog")[-1] == ("jog", lc.JOG_STOP, True, 0)
    assert out == ["EVT E watchdog J0"]


def test_ping_from_non_owner_does_not_feed_watchdog(bridge, out, lc, clock):
    power_on(lc)
    login_take(bridge, out, A)
    say(bridge, out, B, "pin 1234")
    say(bridge, out, A, "jogc J0 + 5")
    clock.advance(0.4)
    assert say(bridge, out, B, "ping") == ["OK ping"]
    clock.advance(0.2)
    bridge.watchdog_tick()
    assert lc.commands("jog")[-1] == ("jog", lc.JOG_STOP, True, 0)


def test_owner_disconnect_during_jog_and_program(bridge, out, lc):
    power_on(lc)
    login_take(bridge, out)
    say(bridge, out, A, "jogc J3 - 5")
    lc.machine.interp_state = lc.INTERP_READING   # програма виконується
    out.clear()
    bridge.client_disconnected(A)
    stops = [c for c in lc.commands("jog") if c[1] == lc.JOG_STOP]
    assert {c[3] for c in stops} == set(range(6))
    assert lc.commands("auto")[-1] == ("auto", lc.AUTO_PAUSE)
    assert bridge.safety.owner is None
    assert out[-1].startswith("EVT E власник відключився")


def test_all_unsubscribed_counts_as_disconnect(bridge, out, lc):
    power_on(lc)
    login_take(bridge, out)
    bridge.subscribers_changed(False)
    assert bridge.safety.owner is None and not bridge.streaming


def test_overflow_line(bridge, out):
    replies = say(bridge, out, A, "x" * 600)
    assert replies[0].startswith("ERR overflow")
    assert say(bridge, out, A, "ver") == ["OK ver 1"]


def test_load_config_inline_comments_and_validation(tmp_path):
    p = tmp_path / "bt-cnc-bridge.txt"
    p.write_text(
        "# коментар\nNAME=CNC-Robot\nPIN=0000\n"
        "ON_DISCONNECT=abort      # pause | abort\n"
        "STATUS_HZ=500\nMAX_JOG_VEL=abc\nWATCHDOG_MS=-5\n", encoding="utf-8")
    cfg = load_config([str(p)])
    assert cfg["PIN"] == "0000" and cfg["ON_DISCONNECT"] == "abort"
    assert cfg["STATUS_HZ"] == 20.0
    assert cfg["MAX_JOG_VEL"] == DEFAULT_CONFIG["MAX_JOG_VEL"]
    assert cfg["WATCHDOG_MS"] == DEFAULT_CONFIG["WATCHDOG_MS"]
