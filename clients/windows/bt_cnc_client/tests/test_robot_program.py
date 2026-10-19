# clients/windows/bt_cnc_client/tests/test_robot_program.py
"""Модель програми навчання і генерація G-коду."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot_program import Program, ProgramError, Step, to_gcode  # noqa: E402

J1 = [0, 10, -20, 0, 45, 90]
J2 = [5.5, 0, 0, 0, 0, 0]
P1 = [17, 5.5, 7.2, 180, 0, 0]


def body(gcode: str) -> list[str]:
    """Рядки без шапки (коментарі на початку) — для порівняння."""
    return [l for l in gcode.splitlines() if not l.startswith("(")]


def test_mixed_program_switches_kinematics_only_when_needed():
    prog = Program(name="demo", steps=[
        Step("movej", joints=J1, speed=20),
        Step("movej", joints=J2),
        Step("wait", seconds=1.5),
        Step("movel", pose=P1),
        Step("dout", output=2, state=True),
        Step("movep", pose=P1),
        Step("dout", output=2, state=False),
        Step("movej", joints=J1),
    ])
    assert body(to_gcode(prog)) == [
        "G20 G90 G94",
        "M428 (кінематика genserkins)",
        "M129 (ліміти осей = ліміти joints)",
        "M429 (кінематика identity: X..C = J0..J5)",
        "G53 G1 X0 Y10 Z-20 A0 B45 C90 F1200",
        "G53 G1 X5.5 Y0 Z0 A0 B0 C0 F600",           # типова 10 град/с
        "G4 P1.5",
        "M128 (ліміти осей з INI)",
        "M428 (кінематика genserkins)",
        "G53 G1 X17 Y5.5 Z7.2 A180 B0 C0 F12",       # 0.2 од./с
        "M64 P2",
        "G53 G0 X17 Y5.5 Z7.2 A180 B0 C0",
        "M65 P2",
        "M129 (ліміти осей = ліміти joints)",
        "M429 (кінематика identity: X..C = J0..J5)",
        "G53 G1 X0 Y10 Z-20 A0 B45 C90 F600",
        "M128 (ліміти осей з INI)",                   # завжди закінчуємо у світі
        "M428 (кінематика genserkins)",
        "M2",
    ]


def test_mm_units_and_labels_and_comments():
    prog = Program(name="(bad) name", units="mm", steps=[
        Step("comment", text="Підхід (повільно)"),
        Step("movel", pose=P1, text="P1"),
    ])
    g = to_gcode(prog)
    assert "G21 G90 G94" in g
    assert "(CNC-Robot Studio:  bad  name)" in g.splitlines()[0]
    assert "(Підхід  повільно)" in g
    assert "(2: P1)" in g
    assert g.endswith("M2\n")


def test_selected_steps_only_for_goto():
    prog = Program(steps=[Step("movel", pose=P1), Step("movej", joints=J1)])
    g = to_gcode(prog, [prog.steps[1]])
    assert "X17" not in g and "M429" in g


@pytest.mark.parametrize("step, msg", [
    (Step("movej", joints=[1, 2, 3]), "6 значень"),
    (Step("movel", pose=[0, 0, 0, 0, 0, float("nan")]), "некоректне"),
    (Step("wait", seconds=-1), "від'ємною"),
    (Step("dout", output=64), "0..63"),
    (Step("teleport"), "невідомий"),
])
def test_invalid_steps(step, msg):
    with pytest.raises(ProgramError) as exc:
        to_gcode(Program(steps=[Step("wait", seconds=0), step]))
    assert msg in str(exc.value)


def test_program_without_actions():
    with pytest.raises(ProgramError):
        to_gcode(Program(steps=[Step("comment", text="x")]))


def test_json_roundtrip_and_format_check():
    prog = Program(name="Деталь 1", joint_speed=15, steps=[Step("movej", joints=J1, text="P1"),
                                                           Step("wait", seconds=2)])
    again = Program.from_json(prog.to_json())
    assert again == prog
    with pytest.raises(ProgramError):
        Program.from_json('{"format": "other"}')
    with pytest.raises(ProgramError):
        Program.from_json('{"format": "cnc-robot-program", "version": 99}')


def test_file_name_is_safe():
    assert Program(name="Деталь 1/../x").file_name() == "Деталь_1_x.ngc"
    assert Program(name="..").file_name() == "program.ngc"
    assert Program(name="a" * 100).file_name() == "a" * 60 + ".ngc"


def test_summary():
    assert Step("movej", joints=J2).summary().startswith("J0 5.50°")
    assert "in" in Step("movel", pose=P1).summary("in")
    assert Step("dout", output=3, state=False).summary() == "вихід 3 = 0"
