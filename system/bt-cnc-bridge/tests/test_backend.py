# system/bt-cnc-bridge/tests/test_backend.py
"""Перевіряємо, що кожна команда дає правильні виклики linuxcnc.command."""
import os

import pytest

from bridge_constants import E_CNC, E_NOCNC, E_NOFILE, E_PATH, E_STATE, E_TIMEOUT, RECONNECT_SEC
from cnc_backend import CncError
from conftest import power_on


def err_code(fn, *args):
    with pytest.raises(CncError) as exc:
        fn(*args)
    return exc.value.code


# --- з'єднання ---------------------------------------------------------

def test_nocnc_and_throttled_reconnect(backend, lc, clock):
    lc.running = False
    assert err_code(backend.status) == E_NOCNC
    lc.running = True
    # спроба не частіше ніж раз на RECONNECT_SEC
    assert err_code(backend.status) == E_NOCNC
    clock.advance(RECONNECT_SEC)
    assert backend.status()["st"] == "estop"


def test_crash_while_connected(backend, lc, clock):
    backend.status()
    lc.running = False
    assert err_code(backend.status) == E_NOCNC
    assert not backend.connected
    assert backend.is_running() is False       # не кидає


def test_without_linuxcnc_module(projects):
    from cnc_backend import CncBackend
    b = CncBackend(str(projects), lc=None)
    b.lc = None
    assert err_code(b.status) == E_NOCNC


def test_joint_limits_from_ini(backend):
    backend.ensure()
    assert backend.joint_max_vel == {0: 30.0, 1: 5.0}


# --- стан --------------------------------------------------------------

def test_status_snapshot(backend, lc):
    power_on(lc)
    lc.machine.joint_actual_position = (1.23456, 0, 0, 0, 0, -90)
    lc.machine.file = "/home/cnc/ProjectLinuxCNC/part.ngc"
    lc.machine.motion_line = 7
    lc.machine.interp_state = lc.INTERP_READING
    lc.machine.feedrate = 0.5
    st = backend.status()
    assert st == {"st": "on", "mode": "manual", "homed": [1] * 6,
                  "j": [1.235, 0, 0, 0, 0, -90], "prog": "part.ngc", "line": 7,
                  "run": "run", "fo": 50, "ro": 100,
                  "w": [17.0, 5.5, 7.2, 180.0, 0.0, 0.0], "u": "in"}


def test_poll_errors_only_errors(backend, lc):
    backend.ensure()
    lc.errors = [(lc.NML_ERROR, "joint 0 following error"), (lc.NML_TEXT, "info"),
                 (lc.OPERATOR_ERROR, "oops")]
    assert backend.poll_errors() == ["joint 0 following error", "oops"]


# --- estop / power -----------------------------------------------------

def test_estop_and_power(backend, lc):
    backend.estop(False)
    assert ("state", lc.STATE_ESTOP_RESET) in lc.calls
    backend.power(True)
    assert ("state", lc.STATE_ON) in lc.calls
    backend.estop(True)
    assert lc.commands("state")[-1] == ("state", lc.STATE_ESTOP)


def test_power_on_requires_estop_reset(backend, lc):
    assert err_code(backend.power, True) == E_STATE
    assert lc.commands("state") == []


# --- home / jog -------------------------------------------------------

def test_home_requires_on(backend, lc):
    assert err_code(backend.home, -1) == E_STATE
    assert lc.commands("home") == []


def test_home_all_switches_to_joint_mode(backend, lc):
    power_on(lc, homed=False)
    lc.machine.task_mode = lc.MODE_MDI
    backend.home(-1)
    names = [c[0] for c in lc.calls]
    assert names.index("mode") < names.index("teleop_enable") < names.index("home")
    assert ("mode", lc.MODE_MANUAL) in lc.calls
    assert ("teleop_enable", 0) in lc.calls
    assert lc.commands("home") == [("home", -1)]


def test_home_rejected_while_program_runs(backend, lc):
    power_on(lc)
    lc.machine.interp_state = lc.INTERP_READING
    assert err_code(backend.home, 0) == E_STATE


def test_unhome_all(backend, lc):
    power_on(lc)
    backend.unhome(-1)
    assert lc.commands("unhome") == [("unhome", -1)]


def test_jog_increment_direction_from_speed_sign(backend, lc):
    power_on(lc, homed=False)                  # jog joints дозволений без home
    backend.jog_increment(2, -5.0, 10.0)
    assert lc.commands("jog") == [("jog", lc.JOG_INCREMENT, True, 2, -10.0, 5.0)]


def test_jog_continuous_and_stop(backend, lc):
    power_on(lc)
    backend.jog_continuous(1, -1, 4.0)
    backend.jog_stop([1, 3])
    assert lc.commands("jog") == [
        ("jog", lc.JOG_CONTINUOUS, True, 1, -4.0),
        ("jog", lc.JOG_STOP, True, 1),
        ("jog", lc.JOG_STOP, True, 3),
    ]


def test_jog_requires_on(backend, lc):
    assert err_code(backend.jog_continuous, 0, 1, 5.0) == E_STATE
    assert lc.commands("jog") == []


def test_jog_stop_without_connection_is_silent(backend, lc):
    backend.jog_stop([0])                      # ще не підключені
    assert lc.calls == []


# --- MDI / програми -----------------------------------------------------

def test_mdi_requires_homed(backend, lc):
    power_on(lc, homed=False)
    assert err_code(backend.mdi, "G0 X1") == E_STATE
    assert lc.commands("mdi") == []


def test_mdi(backend, lc):
    power_on(lc)
    backend.mdi("G0 X1")
    assert ("mode", lc.MODE_MDI) in lc.calls
    assert lc.commands("mdi") == [("mdi", "G0 X1")]


def test_list_programs(backend):
    assert backend.list_programs() == ["part.ngc", "Деталь 2.nc"]


def test_open_program(backend, lc, projects):
    backend.open_program("part.ngc")
    assert ("mode", lc.MODE_AUTO) in lc.calls
    assert lc.commands("program_open") == [("program_open", str(projects / "part.ngc"))]


def test_open_rejects_traversal_and_missing(backend, lc, projects):
    assert err_code(backend.open_program, "../secret.ngc") == E_PATH
    assert err_code(backend.open_program, "missing.ngc") == E_NOFILE
    os.symlink(projects.parent / "secret.ngc", projects / "link.ngc")
    assert err_code(backend.open_program, "link.ngc") == E_PATH
    assert lc.commands("program_open") == []


def test_run_requires_file_and_homed(backend, lc):
    power_on(lc)
    assert err_code(backend.run, 0) == E_STATE
    lc.machine.file = "/x/part.ngc"
    lc.machine.homed = (1, 1, 1, 1, 1, 0)
    assert err_code(backend.run, 0) == E_STATE
    assert lc.commands("auto") == []


def test_run_pause_resume_stop_step(backend, lc):
    power_on(lc)
    lc.machine.file = "/x/part.ngc"
    backend.run(12)
    assert ("mode", lc.MODE_AUTO) in lc.calls
    assert lc.commands("auto")[-1] == ("auto", lc.AUTO_RUN, 12)

    assert err_code(backend.resume) == E_STATE   # ще не на паузі
    lc.machine.interp_state = lc.INTERP_READING
    backend.pause()
    assert lc.commands("auto")[-1] == ("auto", lc.AUTO_PAUSE)

    assert err_code(backend.step) == E_STATE     # під час виконання — спершу pause
    lc.machine.interp_state = lc.INTERP_PAUSED
    backend.step()
    assert lc.commands("auto")[-1] == ("auto", lc.AUTO_STEP)
    backend.resume()
    assert lc.commands("auto")[-1] == ("auto", lc.AUTO_RESUME)

    backend.stop()
    assert ("abort",) in lc.calls


def test_pause_when_idle(backend, lc):
    power_on(lc)
    assert err_code(backend.pause) == E_STATE


def test_overrides(backend, lc):
    backend.feed_override(150)
    backend.rapid_override(25)
    assert lc.commands("feedrate", "rapidrate") == [("feedrate", 1.5), ("rapidrate", 0.25)]


# --- wait_complete -----------------------------------------------------

def test_wait_timeout_and_error(backend, lc):
    lc.wait_rc = -1
    assert err_code(backend.estop, True) == E_TIMEOUT
    lc.wait_rc = lc.RCS_ERROR
    assert err_code(backend.estop, True) == E_CNC


# --- світові осі -----------------------------------------------------------

def test_world_jog_requires_homed(backend, lc):
    power_on(lc, homed=False)
    assert err_code(backend.jog_world_increment, "X", 0.5, 0.2) == E_STATE
    assert lc.commands("jog") == []


def test_world_jog_uses_teleop_and_axis_index(backend, lc):
    power_on(lc)
    backend.jog_world_increment("Z", -0.5, 0.2)
    backend.jog_world_continuous("C", 1, 3.0)
    assert ("teleop_enable", 1) in lc.calls
    assert lc.commands("jog") == [
        ("jog", lc.JOG_INCREMENT, False, 2, -0.2, 0.5),
        ("jog", lc.JOG_CONTINUOUS, False, 5, 3.0),
    ]
    assert backend.axis_max_vel == {"X": 30.0, "C": 4.0}


def test_jog_stop_mixed_and_all(backend, lc):
    power_on(lc)
    backend.ensure()
    backend.jog_stop([1, "B"])
    assert lc.commands("jog") == [("jog", lc.JOG_STOP, True, 1), ("jog", lc.JOG_STOP, False, 4)]
    lc.calls.clear()
    lc.machine.motion_mode = lc.TRAJ_MODE_TELEOP
    backend.jog_stop_all()
    assert [c[3] for c in lc.commands("jog")] == [0, 1, 2, 3, 4, 5]
    assert all(c[2] is False for c in lc.commands("jog"))


# --- запис програм ------------------------------------------------------

def test_write_and_delete_program(backend, lc, projects):
    backend.write_program("teach.ngc", "G0 X1\nM2\n")
    assert (projects / "teach.ngc").read_text() == "G0 X1\nM2\n"
    assert not list(projects.glob(".*.tmp"))
    backend.write_program("teach.ngc", "M2\n")          # перезапис
    assert (projects / "teach.ngc").read_text() == "M2\n"
    backend.delete_program("teach.ngc")
    assert not (projects / "teach.ngc").exists()


def test_write_program_rejects_bad_names_and_size(backend, projects):
    assert err_code(backend.write_program, "../x.ngc", "M2") == E_PATH
    assert err_code(backend.write_program, "big.ngc", "x" * 1_000_001) == "size"
    os.symlink(projects.parent / "secret.ngc", projects / "link.ngc")
    assert err_code(backend.write_program, "link.ngc", "M2") == E_PATH


def test_cannot_overwrite_running_program(backend, lc, projects):
    backend.ensure()
    lc.machine.file = str(projects / "part.ngc")
    lc.machine.interp_state = lc.INTERP_READING
    assert err_code(backend.write_program, "part.ngc", "M2\n") == E_STATE
    assert err_code(backend.delete_program, "part.ngc") == E_STATE
