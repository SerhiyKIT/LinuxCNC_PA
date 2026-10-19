# clients/windows/bt_cnc_client/robot_program.py
"""
Програма робота, записана навчанням (teach-in), і генерація G-коду.

Без Qt: модель кроків, збереження в JSON, перетворення в .ngc для LinuxCNC.

Типи кроків:
  movej — рух по joints до записаних кутів (J0..J5, градуси);
  movel — лінійний рух у світових координатах X Y Z A B C;
  movep — швидкий рух (G0) у світових координатах;
  wait  — пауза, секунди;
  dout  — цифровий вихід motion.digital-out-NN (M64/M65);
  comment — коментар у програмі.

Як це працює в LinuxCNC (robot.ini, genserkins + switchkins):
  * світові рухи — кінематика genserkins (M428);
  * рухи по joints — identity-кінематика (M429), де X..C = J0..J5.
    Перед нею M129 ставить ліміти осей рівними лімітам joints,
    після — M128 повертає ліміти осей;
  * координати через G53 (машинні), щоб не діяли зміщення G54
    з RS274NGC_STARTUP_CODE.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

FORMAT_ID = "cnc-robot-program"
FORMAT_VERSION = 1
AXES = "XYZABC"
JOINTS = 6

KINDS = ("movej", "movel", "movep", "wait", "dout", "comment")
KIND_TITLES = {
    "movej":   "Рух по joints",
    "movel":   "Лінійний рух",
    "movep":   "Швидкий рух",
    "wait":    "Пауза",
    "dout":    "Вихід",
    "comment": "Коментар",
}

DEFAULT_JOINT_SPEED = 10.0     # град/с
DEFAULT_LINEAR_SPEED = 0.2     # од./с (дюйми за INI робота)
MAX_DOUT = 63

# Режими кінематики в згенерованому коді
_WORLD, _JOINT = "world", "joint"


class ProgramError(ValueError):
    """Програму не можна перетворити в G-код."""


@dataclass
class Step:
    kind: str
    joints: list[float] = field(default_factory=list)   # movej, градуси
    pose: list[float] = field(default_factory=list)     # movel/movep, X Y Z A B C
    speed: float = 0.0             # movej: град/с, movel: од./с (0 — типова програми)
    seconds: float = 0.0           # wait
    output: int = 0                # dout
    state: bool = True             # dout: увімкнути/вимкнути
    text: str = ""                 # comment або назва точки

    def summary(self, units: str = "in") -> str:
        """Короткий опис для таблиці кроків."""
        if self.kind == "movej":
            return "  ".join(f"J{i} {v:.2f}°" for i, v in enumerate(self.joints))
        if self.kind in ("movel", "movep"):
            lin = "  ".join(f"{a} {v:.3f}" for a, v in zip(AXES[:3], self.pose[:3]))
            ang = "  ".join(f"{a} {v:.1f}°" for a, v in zip(AXES[3:], self.pose[3:]))
            return f"{lin} {units}   {ang}"
        if self.kind == "wait":
            return f"{self.seconds:g} с"
        if self.kind == "dout":
            return f"вихід {self.output} = {'1' if self.state else '0'}"
        return self.text


@dataclass
class Program:
    name: str = "program"
    units: str = "in"
    joint_speed: float = DEFAULT_JOINT_SPEED
    linear_speed: float = DEFAULT_LINEAR_SPEED
    steps: list[Step] = field(default_factory=list)

    # --- JSON ---------------------------------------------------------------

    def to_json(self) -> str:
        data = {"format": FORMAT_ID, "version": FORMAT_VERSION, **asdict(self)}
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Program":
        data = json.loads(text)
        if data.get("format") != FORMAT_ID:
            raise ProgramError("це не файл програми CNC-Robot")
        if data.get("version", 0) > FORMAT_VERSION:
            raise ProgramError("файл створено новішою версією програми")
        known = Step.__dataclass_fields__
        steps = [Step(**{k: v for k, v in s.items() if k in known}) for s in data.get("steps", [])]
        return cls(name=data.get("name", "program"), units=data.get("units", "in"),
                   joint_speed=float(data.get("joint_speed", DEFAULT_JOINT_SPEED)),
                   linear_speed=float(data.get("linear_speed", DEFAULT_LINEAR_SPEED)),
                   steps=steps)

    # --- назва файлу на роботі ---------------------------------------------

    def file_name(self) -> str:
        """Ім'я .ngc для PROJECTS_DIR: лише безпечні символи."""
        base = re.sub(r"[^\w\-]+", "_", self.name.strip(), flags=re.UNICODE).strip("_.")
        return (base or "program")[:60] + ".ngc"


# ---------------------------------------------------------------------------
# Генерація G-коду
# ---------------------------------------------------------------------------

def _num(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _coords(values: list[float]) -> str:
    return " ".join(f"{a}{_num(v)}" for a, v in zip(AXES, values))


def _comment(text: str) -> str:
    # У G-коді коментар — у дужках; дужки й керівні символи прибираємо
    clean = re.sub(r"[()\r\n;]", " ", text).strip()
    return f"({clean})" if clean else ""


def _check_values(step: Step, values: list[float], what: str, index: int) -> None:
    if len(values) != JOINTS:
        raise ProgramError(f"крок {index}: потрібно 6 значень {what}")
    for v in values:
        if not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
            raise ProgramError(f"крок {index}: некоректне значення {what}")


def _switch(lines: list[str], current: str, wanted: str) -> str:
    if current == wanted:
        return current
    if wanted == _JOINT:
        lines += ["M129 (ліміти осей = ліміти joints)", "M429 (кінематика identity: X..C = J0..J5)"]
    else:
        lines += ["M128 (ліміти осей з INI)", "M428 (кінематика genserkins)"]
    return wanted


def step_gcode(step: Step, program: Program, index: int, lines: list[str], mode: str) -> str:
    """Додає G-код кроку в lines, повертає режим кінематики після нього."""
    if step.kind == "movej":
        _check_values(step, step.joints, "joints", index)
        mode = _switch(lines, mode, _JOINT)
        speed = step.speed or program.joint_speed
        lines.append(f"G53 G1 {_coords(step.joints)} F{_num(speed * 60)}")
    elif step.kind in ("movel", "movep"):
        _check_values(step, step.pose, "координат", index)
        mode = _switch(lines, mode, _WORLD)
        if step.kind == "movep":
            lines.append(f"G53 G0 {_coords(step.pose)}")
        else:
            speed = step.speed or program.linear_speed
            lines.append(f"G53 G1 {_coords(step.pose)} F{_num(speed * 60)}")
    elif step.kind == "wait":
        if step.seconds < 0:
            raise ProgramError(f"крок {index}: пауза не може бути від'ємною")
        lines.append(f"G4 P{_num(step.seconds)}")
    elif step.kind == "dout":
        if not 0 <= step.output <= MAX_DOUT:
            raise ProgramError(f"крок {index}: вихід має бути 0..{MAX_DOUT}")
        lines.append(f"{'M64' if step.state else 'M65'} P{step.output}")
    elif step.kind == "comment":
        text = _comment(step.text)
        if text:
            lines.append(text)
    else:
        raise ProgramError(f"крок {index}: невідомий тип '{step.kind}'")
    return mode


def to_gcode(program: Program, steps: list[Step] | None = None) -> str:
    """
    G-код усієї програми (або лише вказаних кроків — для «Перейти до точки»).
    Завжди починає і закінчує у світовій кінематиці.
    """
    steps = program.steps if steps is None else steps
    if not any(s.kind in ("movej", "movel", "movep", "wait", "dout") for s in steps):
        raise ProgramError("у програмі немає жодного кроку з дією")
    lines = [
        _comment(f"CNC-Robot Studio: {program.name}"),
        "(Згенеровано автоматично; редагуйте програму в Studio)",
        ("G21" if program.units == "mm" else "G20") + " G90 G94",
        "M428 (кінематика genserkins)",
    ]
    mode = _WORLD
    for index, step in enumerate(steps, 1):
        label = _comment(f"{index}: {step.text}") if step.text and step.kind != "comment" else ""
        if label:
            lines.append(label)
        mode = step_gcode(step, program, index, lines, mode)
    _switch(lines, mode, _WORLD)
    lines.append("M2")
    return "\n".join(line for line in lines if line) + "\n"
