# system/bt-cnc-bridge/tests/conftest.py
"""
Спільні фікстури: мок модуля linuxcnc і керований годинник.
BlueZ і справжній linuxcnc для тестів не потрібні.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_fake_linuxcnc():
    """Модуль з тими ж іменами, що й linuxcnc; команди пишуться в lc.calls."""
    lc = types.SimpleNamespace(
        STATE_ESTOP=1, STATE_ESTOP_RESET=2, STATE_OFF=3, STATE_ON=4,
        MODE_MANUAL=1, MODE_AUTO=2, MODE_MDI=3,
        INTERP_IDLE=1, INTERP_READING=2, INTERP_PAUSED=3, INTERP_WAITING=4,
        JOG_STOP=0, JOG_CONTINUOUS=1, JOG_INCREMENT=2,
        AUTO_RUN=0, AUTO_PAUSE=1, AUTO_RESUME=2, AUTO_STEP=3,
        RCS_DONE=1, RCS_EXEC=2, RCS_ERROR=3,
        TRAJ_MODE_COORD=1, TRAJ_MODE_FREE=2, TRAJ_MODE_TELEOP=3,
        NML_ERROR=1, NML_TEXT=2, NML_DISPLAY=3,
        OPERATOR_ERROR=11, OPERATOR_TEXT=12, OPERATOR_DISPLAY=13,
    )

    class error(Exception):
        pass

    lc.error = error
    lc.calls = []
    lc.running = True                  # чи запущений LinuxCNC
    lc.wait_rc = lc.RCS_DONE           # що повертає wait_complete
    lc.errors = []                     # черга error_channel
    lc.ini_values = {("JOINT_0", "MAX_VELOCITY"): "30", ("JOINT_1", "MAX_VELOCITY"): "5",
                     ("AXIS_X", "MAX_VELOCITY"): "30", ("AXIS_C", "MAX_VELOCITY"): "4"}

    machine = types.SimpleNamespace(
        task_state=lc.STATE_ESTOP, task_mode=lc.MODE_MANUAL, interp_state=lc.INTERP_IDLE,
        homed=(0,) * 6, joint_actual_position=(0.0,) * 6, joints=6, file="",
        actual_position=(17.0, 5.5, 7.2, 180.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        linear_units=1 / 25.4, motion_mode=lc.TRAJ_MODE_FREE,
        motion_line=0, feedrate=1.0, rapidrate=1.0, paused=False,
        ini_filename="/home/cnc/robot.ini",
    )
    lc.machine = machine

    class stat:
        def poll(self):
            if not lc.running:
                raise error("emcStatusBuffer invalid")
            self.__dict__.update(vars(machine))

    class command:
        def __getattr__(self, name):
            def call(*args):
                if not lc.running:
                    raise error("NML not available")
                lc.calls.append((name, *args))
                # Мінімальна "фізика", щоб передумови працювали
                if name == "mode":
                    machine.task_mode = args[0]
                elif name == "teleop_enable":
                    machine.motion_mode = lc.TRAJ_MODE_TELEOP if args[0] else lc.TRAJ_MODE_FREE
                elif name == "state":
                    machine.task_state = {lc.STATE_ESTOP_RESET: lc.STATE_OFF}.get(args[0], args[0])
                elif name == "program_open":
                    machine.file = args[0]
                elif name == "wait_complete":
                    return lc.wait_rc
            return call

    class error_channel:
        def poll(self):
            return lc.errors.pop(0) if lc.errors else None

    class ini:
        def __init__(self, path):
            pass

        def find(self, section, key):
            return lc.ini_values.get((section, key))

    lc.stat, lc.command, lc.error_channel, lc.ini = stat, command, error_channel, ini

    def commands(*names):
        """Виклики без wait_complete/teleop — для коротких перевірок."""
        return [c for c in lc.calls if not names or c[0] in names]

    lc.commands = commands
    return lc


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def lc():
    return make_fake_linuxcnc()


@pytest.fixture
def projects(tmp_path):
    d = tmp_path / "projects"
    d.mkdir()
    (d / "part.ngc").write_text("G0 X0\nM2\n")
    (d / "Деталь 2.nc").write_text("M2\n")
    (d / "notes.txt").write_text("x")
    (d / ".hidden.ngc").write_text("M2\n")
    (tmp_path / "secret.ngc").write_text("M2\n")
    return d


@pytest.fixture
def backend(lc, clock, projects):
    from cnc_backend import CncBackend
    return CncBackend(str(projects), lc=lc, clock=clock)


def power_on(lc, homed=True):
    """Привести мок у стан On (і homed) без команд."""
    lc.machine.task_state = lc.STATE_ON
    lc.machine.homed = (1,) * 6 if homed else (0,) * 6
