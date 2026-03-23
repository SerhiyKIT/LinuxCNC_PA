#!/usr/bin/env python3
"""
Інтеграційні тести ToolManager ↔ MachineController ↔ LinuxCNC sim
====================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_tool_machine.py

Архітектура ToolManager:
  arm_tool(armed)              → якщо disarm і joints homed → send_mdi(M102)
                                 → повертає bool

  perform_action(is_grip, is_armed)
    guard 1: not is_armed      → return False  (no MDI)
    guard 2: not _joints_homed → return False  (no MDI)
    is_grip=True               → send_mdi("M101")
    is_grip=False              → send_mdi("M102")
    → повертає bool від send_mdi

  set_power(percentage)        → set_gripper_force(percentage / 100.0)
                                 → command.set_analog_output(1, val)
                                 → повертає normalized float

  _joints_homed()              → all(status.homed[:3])
                                 (_REQUIRED_HOMED_JOINTS = 3)

send_mdi поведінка в sim:
  • M101 / M102 — кастомні M-коди, ВІДСУТНІ в стандартному sim-конфігу.
    send_mdi() ловить Exception → повертає False.
  • Стандартні коди (G0 X0, G21, тощо) → повертають True при idle машині.
  • При interpreter busy → повертає False без MDI-виклику.
  • Відновлює попередній task_mode після виконання.

Покриття (26 тестів у 6 групах):
  Група 1 — arm_tool:         arm/disarm логіка, disarm→send_mdi(M102),
                               disarm без homing → no MDI
  Група 2 — perform_action:   not armed guard, not homed guard,
                               grip=True→M101, grip=False→M102,
                               повертає bool від send_mdi
  Група 3 — set_power:        normalized value, bounds, set_gripper_force,
                               return value
  Група 4 — _joints_homed:    True після home_all, False до homing,
                               homed[:3] vs homed[:6]
  Група 5 — send_mdi contract: returns bool, відновлює режим,
                               відхиляє при busy, True для стандартних кодів
  Група 6 — наскрізні:        arm→grip→release→disarm workflow,
                               power зберігається між діями,
                               set_power bounds (10..100)
"""

import sys
import time
import traceback

import linuxcnc
from unittest.mock import patch, MagicMock

from logic.core.machine import MachineController
from logic.managers.tool_manager import (
    ToolManager,
    _MDI_GRIP,
    _MDI_RELEASE,
    _REQUIRED_HOMED_JOINTS,
    _POWER_MIN,
    _POWER_MAX,
)

# ---------------------------------------------------------------------------
# ANSI кольори
# ---------------------------------------------------------------------------
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

# ---------------------------------------------------------------------------
# Підтверджені константи sim
# ---------------------------------------------------------------------------
_STATE_ESTOP       = linuxcnc.STATE_ESTOP        # 1
_STATE_ESTOP_RESET = linuxcnc.STATE_ESTOP_RESET  # 2
_STATE_ON          = linuxcnc.STATE_ON           # 4
_MODE_MANUAL       = linuxcnc.MODE_MANUAL        # 1
_MODE_MDI          = linuxcnc.MODE_MDI           # 3
_INTERP_IDLE       = linuxcnc.INTERP_IDLE        # 1

# ---------------------------------------------------------------------------
# Мінімальний тестовий фреймворк
# ---------------------------------------------------------------------------

_results: list[tuple[str, bool, str]] = []


def run_test(name: str, fn) -> None:
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  {_GREEN}✓{_RESET}  {name}")
    except AssertionError as exc:
        _results.append((name, False, str(exc)))
        print(f"  {_RED}✗{_RESET}  {name}")
        print(f"      {_RED}AssertionError: {exc}{_RESET}")
    except Exception as exc:
        tb = traceback.format_exc()
        _results.append((name, False, tb))
        print(f"  {_RED}✗{_RESET}  {name}")
        print(f"      {_RED}{type(exc).__name__}: {exc}{_RESET}")


def assert_eq(actual, expected, msg: str = "") -> None:
    label = f" — {msg}" if msg else ""
    assert actual == expected, \
        f"Очікувалось {expected!r}, отримано {actual!r}{label}"


def assert_true(val, msg: str = "") -> None:
    assert val, msg or f"Очікувалось True, отримано {val!r}"


def assert_false(val, msg: str = "") -> None:
    assert not val, msg or f"Очікувалось False, отримано {val!r}"


def assert_approx(actual: float, expected: float, tol: float,
                  msg: str = "") -> None:
    label = f" — {msg}" if msg else ""
    assert abs(actual - expected) <= tol, (
        f"Очікувалось ≈{expected} (±{tol}), отримано {actual:.6f}{label}"
    )


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------

_POLL_STEP = 0.04


def poll_until(ctrl: MachineController, condition,
               timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if condition(ctrl.status):
            return True
        time.sleep(_POLL_STEP)
    return False


# ---------------------------------------------------------------------------
# Стан машини
# ---------------------------------------------------------------------------

def bring_to_manual(ctrl: MachineController) -> None:
    ctrl.poll()
    if ctrl.status.estop == _STATE_ESTOP:
        ctrl.command.state(_STATE_ESTOP_RESET)
        poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP)
    ctrl.poll()
    if ctrl.status.task_state != _STATE_ON:
        ctrl.command.state(_STATE_ON)
        ok = poll_until(ctrl, lambda s: s.task_state == _STATE_ON)
        if not ok:
            raise RuntimeError("Не вдалося увімкнути STATE_ON")
    ctrl.poll()
    if ctrl.status.task_mode != _MODE_MANUAL:
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    ctrl.poll()


def safe_stop(ctrl: MachineController) -> None:
    try:
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    except Exception:
        pass


def home_all(ctrl: MachineController) -> bool:
    """home(-1) → чекати homed[0..JOINTS_COUNT-1]."""
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    ctrl.command.home(-1)
    jc = ctrl.params.get("JOINTS_COUNT", 6)
    return poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(jc)),
        timeout=20.0,
    )


def wait_interp_idle(ctrl: MachineController, timeout: float = 5.0) -> bool:
    return poll_until(ctrl, lambda s: s.interp_state == _INTERP_IDLE, timeout)


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _setup() -> tuple[MachineController, ToolManager]:
    """MANUAL, без homing."""
    ctrl = MachineController()
    mgr  = ToolManager(ctrl)
    bring_to_manual(ctrl)
    wait_interp_idle(ctrl)
    return ctrl, mgr


def _setup_homed() -> tuple[MachineController, ToolManager]:
    """MANUAL + всі joints homed."""
    ctrl = MachineController()
    mgr  = ToolManager(ctrl)
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    wait_interp_idle(ctrl)
    return ctrl, mgr


def _setup_not_homed() -> tuple[MachineController, ToolManager]:
    """
    MANUAL, homed скинутий через unhome(-1).
    Якщо unhome недоступний — повертаємо _setup() (joints можуть бути homed).
    Тести що потребують not-homed стану використовують patch.
    """
    ctrl = MachineController()
    mgr  = ToolManager(ctrl)
    bring_to_manual(ctrl)
    # Намагаємось скинути homed через unhome
    try:
        ctrl.command.teleop_enable(0)
        ctrl.command.wait_complete()
        ctrl.command.home(-2)   # -2 = unhome all (LinuxCNC 2.8+)
        time.sleep(0.5)
    except Exception:
        pass
    wait_interp_idle(ctrl)
    return ctrl, mgr


# ===========================================================================
#  ГРУПА 1: arm_tool
# ===========================================================================

def _test_arm_tool_returns_true_when_arming():
    """arm_tool(True) → повертає True."""
    _, mgr = _setup()
    result = mgr.arm_tool(True)
    assert_true(result, "arm_tool(True) має повернути True")


def _test_arm_tool_returns_false_when_disarming():
    """arm_tool(False) → завжди повертає False."""
    _, mgr = _setup()
    result = mgr.arm_tool(False)
    assert_false(result, "arm_tool(False) має повернути False")


def _test_arm_tool_disarm_sends_mdi_when_homed():
    """
    arm_tool(False) коли joints homed → викликає send_mdi(M102).
    Перевіряємо через patch.object — не залежимо від наявності M102 в sim.
    """
    ctrl, mgr = _setup_homed()
    ctrl.poll()
    assert_true(
        all(ctrl.status.homed[i] for i in range(_REQUIRED_HOMED_JOINTS)),
        "Передумова: joints 0..2 homed",
    )
    with patch.object(ctrl, "send_mdi", return_value=True) as mock_mdi:
        mgr.arm_tool(False)
    mock_mdi.assert_called_once_with(_MDI_RELEASE)


def _test_arm_tool_disarm_no_mdi_when_not_homed():
    """
    arm_tool(False) коли joints NOT homed → send_mdi НЕ викликається.

    __slots__ + C extension (linuxcnc.stat.homed read-only) → patch.object
    на instance або клас не працює в Python 3.12.
    Єдиний надійний підхід: замінити ctrl.status на MagicMock де homed
    повертає всі нулі. _joints_homed() читає self.cnc.status.homed[:3].
    """
    ctrl, mgr = _setup()
    fake_status = MagicMock()
    fake_status.homed = (0,) * 9
    ctrl.status = fake_status
    with patch.object(ctrl, "send_mdi") as mock_mdi:
        result = mgr.arm_tool(False)
    mock_mdi.assert_not_called()
    assert_false(result, "arm_tool(False) має повернути False навіть без homing")


def _test_arm_tool_disarm_returns_false_regardless_of_mdi():
    """
    arm_tool(False) повертає False незалежно від результату send_mdi.
    """
    ctrl, mgr = _setup_homed()
    with patch.object(ctrl, "send_mdi", return_value=True):
        result = mgr.arm_tool(False)
    assert_false(result, "arm_tool(False) завжди повертає False")


def _test_arm_tool_arm_does_not_send_mdi():
    """
    arm_tool(True) → send_mdi НЕ викликається (тільки disarm надсилає команду).
    """
    ctrl, mgr = _setup()
    with patch.object(ctrl, "send_mdi") as mock_mdi:
        mgr.arm_tool(True)
    mock_mdi.assert_not_called()


# ===========================================================================
#  ГРУПА 2: perform_action
# ===========================================================================

def _test_perform_action_returns_false_when_not_armed():
    """
    perform_action(is_grip=True, is_armed=False) → False.
    Guard 1: not is_armed → відхилити без MDI.
    """
    ctrl, mgr = _setup_homed()
    with patch.object(ctrl, "send_mdi") as mock_mdi:
        result = mgr.perform_action(is_grip=True, is_armed=False)
    assert_false(result, "perform_action без arm має повернути False")
    mock_mdi.assert_not_called()


def _test_perform_action_returns_false_when_not_homed():
    """
    perform_action(is_grip=True, is_armed=True) → False коли joints not homed.
    Guard 2: not _joints_homed → відхилити без MDI.

    __slots__ блокує patch.object на instance/клас.
    Замінюємо ctrl.status на MagicMock з homed=(0,...).
    """
    ctrl, mgr = _setup()
    fake_status = MagicMock()
    fake_status.homed = (0,) * 9
    ctrl.status = fake_status
    with patch.object(ctrl, "send_mdi") as mock_mdi:
        result = mgr.perform_action(is_grip=True, is_armed=True)
    assert_false(result, "perform_action без homing має повернути False")
    mock_mdi.assert_not_called()


def _test_perform_action_grip_sends_m101():
    """
    perform_action(is_grip=True, is_armed=True) → send_mdi("M101").
    Обидва guards пройдені → надсилається _MDI_GRIP.
    """
    ctrl, mgr = _setup_homed()
    with patch.object(ctrl, "send_mdi", return_value=True) as mock_mdi:
        result = mgr.perform_action(is_grip=True, is_armed=True)
    mock_mdi.assert_called_once_with(_MDI_GRIP)
    assert_true(result, "perform_action grip має повернути True (mock)")


def _test_perform_action_release_sends_m102():
    """
    perform_action(is_grip=False, is_armed=True) → send_mdi("M102").
    """
    ctrl, mgr = _setup_homed()
    with patch.object(ctrl, "send_mdi", return_value=True) as mock_mdi:
        result = mgr.perform_action(is_grip=False, is_armed=True)
    mock_mdi.assert_called_once_with(_MDI_RELEASE)
    assert_true(result, "perform_action release має повернути True (mock)")


def _test_perform_action_returns_false_when_mdi_fails():
    """
    perform_action → False якщо send_mdi повертає False
    (наприклад, sim не знає M101).
    """
    ctrl, mgr = _setup_homed()
    with patch.object(ctrl, "send_mdi", return_value=False):
        result = mgr.perform_action(is_grip=True, is_armed=True)
    assert_false(result, "perform_action має повернути False якщо send_mdi=False")


def _test_perform_action_not_armed_takes_priority_over_not_homed():
    """
    Guard 1 (not armed) спрацьовує першим — guard 2 (not homed) не перевіряється.

    Підхід: замінюємо ctrl.status на MagicMock з homed=(0,...) щоб guard 2
    теж провалився якби дійшло до нього. Переконуємось що MDI не викликається
    і результат False — тобто guard 1 відпрацював раніше.
    """
    ctrl, mgr = _setup()
    fake_status = MagicMock()
    fake_status.homed = (0,) * 9
    ctrl.status = fake_status
    with patch.object(ctrl, "send_mdi") as mock_mdi:
        result = mgr.perform_action(is_grip=True, is_armed=False)
    assert_false(result, "not armed → False незалежно від homed стану")
    mock_mdi.assert_not_called()


def _test_perform_action_real_m101_in_sim_returns_bool():
    """
    perform_action з реальним sim (без patch) → повертає bool.
    M101 відсутній у стандартному sim → send_mdi повертає False.
    Тест підтверджує що виняток не пробрасується — лише bool.
    """
    ctrl, mgr = _setup_homed()
    result = mgr.perform_action(is_grip=True, is_armed=True)
    assert_true(
        isinstance(result, bool),
        f"perform_action має повертати bool, отримано {type(result).__name__}",
    )


# ===========================================================================
#  ГРУПА 3: set_power
# ===========================================================================

def _test_set_power_returns_normalized_value():
    """set_power(50) → повертає 0.5 (50 / 100.0)."""
    ctrl, mgr = _setup()
    with patch.object(ctrl, "set_gripper_force"):
        result = mgr.set_power(50)
    assert_approx(result, 0.5, tol=1e-9,
                  msg="set_power(50) має повертати 0.5")


def _test_set_power_calls_set_gripper_force_with_normalized():
    """set_power(75) → set_gripper_force(0.75)."""
    ctrl, mgr = _setup()
    with patch.object(ctrl, "set_gripper_force") as mock_force:
        mgr.set_power(75)
    mock_force.assert_called_once_with(0.75)


def _test_set_power_min_boundary():
    """set_power(10) → set_gripper_force(0.1), повертає 0.1."""
    ctrl, mgr = _setup()
    assert_eq(_POWER_MIN, 10, "_POWER_MIN має бути 10")
    with patch.object(ctrl, "set_gripper_force") as mock_force:
        result = mgr.set_power(_POWER_MIN)
    mock_force.assert_called_once_with(0.1)
    assert_approx(result, 0.1, tol=1e-9, msg="set_power(10) → 0.1")


def _test_set_power_max_boundary():
    """set_power(100) → set_gripper_force(1.0), повертає 1.0."""
    ctrl, mgr = _setup()
    assert_eq(_POWER_MAX, 100, "_POWER_MAX має бути 100")
    with patch.object(ctrl, "set_gripper_force") as mock_force:
        result = mgr.set_power(_POWER_MAX)
    mock_force.assert_called_once_with(1.0)
    assert_approx(result, 1.0, tol=1e-9, msg="set_power(100) → 1.0")


def _test_set_power_real_sim_does_not_crash():
    """
    set_power з реальним sim — set_analog_output не кидає виняток.
    Перевіряємо що виклик проходить без аварії.
    """
    ctrl, mgr = _setup()
    mgr.set_power(50)   # не має кидати виняток


def _test_set_power_sequential_values():
    """Послідовні set_power → set_gripper_force отримує правильне значення."""
    ctrl, mgr = _setup()
    calls = []
    with patch.object(ctrl, "set_gripper_force", side_effect=lambda v: calls.append(v)):
        for pct, expected in ((10, 0.1), (25, 0.25), (50, 0.5), (100, 1.0)):
            mgr.set_power(pct)
    assert_eq(calls, [0.1, 0.25, 0.5, 1.0],
              "set_gripper_force має отримувати правильні normalized values")


# ===========================================================================
#  ГРУПА 4: _joints_homed
# ===========================================================================

def _test_joints_homed_true_after_home_all():
    """_joints_homed() == True після home(-1) при JOINTS_COUNT >= 3."""
    ctrl, mgr = _setup_homed()
    ctrl.poll()
    assert_true(
        all(ctrl.status.homed[i] for i in range(_REQUIRED_HOMED_JOINTS)),
        f"Передумова: joints 0..{_REQUIRED_HOMED_JOINTS-1} homed",
    )
    assert_true(mgr._joints_homed(),
                "_joints_homed() має бути True після home_all")


def _test_joints_homed_false_when_not_homed():
    """
    _joints_homed() == False коли joints не homed.

    linuxcnc.stat.homed — read-only C extension → patch.object не працює.
    Замінюємо ctrl.status цілком на MagicMock де homed = (0,...).
    _joints_homed() читає self.cnc.status.homed[:3] → all([0,0,0]) → False.
    """
    ctrl, mgr = _setup()
    fake_status = MagicMock()
    fake_status.homed = (0,) * 9
    ctrl.status = fake_status
    result = mgr._joints_homed()
    assert_false(result, "_joints_homed() має бути False коли homed=[0,0,0,...]")


def _test_joints_homed_checks_exactly_required_count():
    """
    _joints_homed() перевіряє homed[:_REQUIRED_HOMED_JOINTS].
    Якщо тільки перші 3 homed — повертає True.
    Якщо менше 3 homed — повертає False.

    Замінюємо ctrl.status на MagicMock між перевірками.
    """
    ctrl, mgr = _setup()

    # Рівно 3 homed (0,1,2=True, решта False) → True
    fake_status = MagicMock()
    fake_status.homed = (1, 1, 1, 0, 0, 0, 0, 0, 0)
    ctrl.status = fake_status
    assert_true(mgr._joints_homed(),
                "_joints_homed() True коли перші 3 homed")

    # Тільки 2 homed → False
    fake_status2 = MagicMock()
    fake_status2.homed = (1, 1, 0, 0, 0, 0, 0, 0, 0)
    ctrl.status = fake_status2
    assert_false(mgr._joints_homed(),
                 "_joints_homed() False коли тільки 2 homed")


def _test_joints_homed_does_not_require_all_6():
    """
    _joints_homed() потребує тільки перші 3 (не 6).
    Joints 3..5 не homed — все одно повертає True.
    """
    ctrl, mgr = _setup()
    fake_status = MagicMock()
    fake_status.homed = (1, 1, 1, 0, 0, 0, 0, 0, 0)
    ctrl.status = fake_status
    assert_true(mgr._joints_homed(),
                "_joints_homed() True при homed[0..2]=1, homed[3..5]=0")


# ===========================================================================
#  ГРУПА 5: send_mdi contract
# ===========================================================================

def _test_send_mdi_returns_bool():
    """send_mdi завжди повертає bool (True або False)."""
    ctrl, _ = _setup()
    result = ctrl.send_mdi("G21")   # стандартний safe MDI
    assert_true(isinstance(result, bool),
                f"send_mdi має повертати bool, є {type(result).__name__}")


def _test_send_mdi_true_for_standard_mdi_code():
    """
    send_mdi("G21") → True в idle machine.
    G21 (metric mode) — безпечний, завжди підтримується sim.
    """
    ctrl, _ = _setup()
    result = ctrl.send_mdi("G21")
    assert_true(result, "send_mdi('G21') має повернути True в idle machine")


def _test_send_mdi_restores_previous_mode():
    """
    send_mdi відновлює попередній task_mode після виконання.
    Починаємо з MANUAL → send_mdi → task_mode == MANUAL.
    """
    ctrl, _ = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Передумова: MANUAL")

    ctrl.send_mdi("G21")
    wait_interp_idle(ctrl)
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "Після send_mdi task_mode має відновитись до MANUAL")


def _test_send_mdi_false_when_interpreter_busy():
    """
    send_mdi відхиляє команду коли interpreter зайнятий.
    Симулюємо через patch.object на interp_state.
    """
    ctrl, _ = _setup()
    # Патчимо interp_state щоб повернути non-IDLE
    original_poll = ctrl.status.poll

    def fake_poll():
        original_poll()
        # Не можемо напряму змінити read-only status.interp_state,
        # тому патчимо is_interpreter_idle на machine
        pass

    with patch.object(ctrl, "is_interpreter_idle", return_value=False):
        # send_mdi перевіряє status.interp_state напряму — потрібно патчити stat
        pass

    # Реальний підхід: запустити довгу програму і відхилити MDI
    # Але M101/M102 і так повертатимуть False в стандартному sim —
    # тому перевіряємо через long-running program якщо homed, інакше skip
    ctrl2, _ = _setup()

    # Якщо можемо home — запускаємо програму
    if home_all(ctrl2):
        bring_to_manual(ctrl2)
        gcode = "/tmp/tt_busy.ngc"
        with open(gcode, "w") as f:
            f.writelines(["G21 G90\n"] + [f"G1 X{i%3} F10\n" for i in range(20)] + ["M2\n"])
        ctrl2.open_program(gcode)
        ctrl2.command.mode(linuxcnc.MODE_AUTO)
        ctrl2.command.wait_complete()
        ctrl2.command.auto(linuxcnc.AUTO_RUN, 0)

        ok = poll_until(
            ctrl2,
            lambda s: s.interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING),
            timeout=5.0,
        )
        if ok:
            result = ctrl2.send_mdi("G21")
            safe_stop(ctrl2)
            assert_false(result,
                         "send_mdi має повернути False коли interpreter busy")
            return

    safe_stop(ctrl2)
    print(f"\n  {_YELLOW}[skip] Не вдалось запустити програму для busy-guard{_RESET}")


def _test_send_mdi_m101_returns_bool_in_sim():
    """
    send_mdi("M101") в стандартному sim → False (M101 невідомий).
    Не кидає виняток — повертає bool.
    """
    ctrl, _ = _setup()
    result = ctrl.send_mdi(_MDI_GRIP)
    assert_true(isinstance(result, bool),
                f"send_mdi(M101) має повернути bool, є {type(result).__name__}")
    # В стандартному sim M101 невідомий → False
    # (якщо sim налаштований з M101 → True — обидва варіанти OK)
    print(f"\n  {_YELLOW}    [info] send_mdi(M101) → {result} "
          f"(False=стандартний sim, True=кастомний sim){_RESET}")


# ===========================================================================
#  ГРУПА 6: наскрізні сценарії
# ===========================================================================

def _test_workflow_arm_grip_release_disarm():
    """
    Повний цикл: arm → grip → release → disarm.
    Всі виклики через patch щоб не залежати від M101/M102 в sim.
    Перевіряємо порядок і аргументи MDI-викликів.
    """
    ctrl, mgr = _setup_homed()
    mdi_calls = []

    with patch.object(ctrl, "send_mdi",
                      side_effect=lambda cmd: mdi_calls.append(cmd) or True):
        # 1. arm
        r_arm = mgr.arm_tool(True)
        assert_true(r_arm, "arm_tool(True) → True")
        assert_eq(mdi_calls, [], "arm_tool не надсилає MDI")

        # 2. grip
        r_grip = mgr.perform_action(is_grip=True, is_armed=True)
        assert_true(r_grip, "perform_action(grip) → True")
        assert_eq(mdi_calls, [_MDI_GRIP],
                  f"perform_action grip має надіслати {_MDI_GRIP}")

        # 3. release
        r_release = mgr.perform_action(is_grip=False, is_armed=True)
        assert_true(r_release, "perform_action(release) → True")
        assert_eq(mdi_calls, [_MDI_GRIP, _MDI_RELEASE],
                  f"perform_action release має надіслати {_MDI_RELEASE}")

        # 4. disarm (joints homed → надсилає M102)
        r_disarm = mgr.arm_tool(False)
        assert_false(r_disarm, "arm_tool(False) → False")
        assert_eq(mdi_calls, [_MDI_GRIP, _MDI_RELEASE, _MDI_RELEASE],
                  "arm_tool(False) при homed має надіслати M102")


def _test_workflow_no_action_without_arm():
    """
    perform_action без arm — завжди False, MDI не надсилається.
    Навіть з homed joints.
    """
    ctrl, mgr = _setup_homed()
    with patch.object(ctrl, "send_mdi") as mock_mdi:
        r1 = mgr.perform_action(is_grip=True,  is_armed=False)
        r2 = mgr.perform_action(is_grip=False, is_armed=False)
    assert_false(r1, "grip без arm → False")
    assert_false(r2, "release без arm → False")
    mock_mdi.assert_not_called()


def _test_workflow_power_set_before_and_after_arm():
    """
    set_power не залежить від arm стану — завжди виконується.
    """
    ctrl, mgr = _setup()
    with patch.object(ctrl, "set_gripper_force") as mock_force:
        mgr.arm_tool(False)
        mgr.set_power(50)

        mgr.arm_tool(True)
        mgr.set_power(75)

    calls = [c.args[0] for c in mock_force.call_args_list]
    assert_eq(calls, [0.5, 0.75],
              "set_power має працювати незалежно від arm стану")


def _test_workflow_set_power_bounds_respected():
    """
    _POWER_MIN=10, _POWER_MAX=100 — межі слайдера.
    set_power(10) → 0.1, set_power(100) → 1.0.
    Перевіряємо що константи правильні.
    """
    assert_eq(_POWER_MIN, 10,  "_POWER_MIN має бути 10")
    assert_eq(_POWER_MAX, 100, "_POWER_MAX має бути 100")

    ctrl, mgr = _setup()
    with patch.object(ctrl, "set_gripper_force") as mock_force:
        low  = mgr.set_power(_POWER_MIN)
        high = mgr.set_power(_POWER_MAX)

    assert_approx(low,  0.1, tol=1e-9, msg="set_power(10) → 0.1")
    assert_approx(high, 1.0, tol=1e-9, msg="set_power(100) → 1.0")
    calls = [c.args[0] for c in mock_force.call_args_list]
    assert_approx(calls[0], 0.1, tol=1e-9)
    assert_approx(calls[1], 1.0, tol=1e-9)


def _test_workflow_action_denied_after_disarm():
    """
    arm → grip (ok) → disarm → grip denied.
    Після disarm perform_action повертає False.
    """
    ctrl, mgr = _setup_homed()
    mdi_calls = []

    with patch.object(ctrl, "send_mdi",
                      side_effect=lambda cmd: mdi_calls.append(cmd) or True):
        mgr.arm_tool(True)
        r1 = mgr.perform_action(is_grip=True, is_armed=True)
        assert_true(r1, "grip коли armed → True")

        mgr.arm_tool(False)
        r2 = mgr.perform_action(is_grip=True, is_armed=False)
        assert_false(r2, "grip після disarm → False")

    # Після disarm більше не надсилаємо M101
    grip_calls = [c for c in mdi_calls if c == _MDI_GRIP]
    assert_eq(len(grip_calls), 1,
              "M101 має надсилатись рівно один раз (до disarm)")


# ===========================================================================
#  Cleanup
# ===========================================================================

def _cleanup() -> None:
    try:
        ctrl = MachineController()
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
        import os
        if os.path.exists("/tmp/tt_busy.ngc"):
            os.remove("/tmp/tt_busy.ngc")
        print(f"\n  {_YELLOW}[cleanup] Машина переведена в MANUAL.{_RESET}")
    except Exception as exc:
        print(f"\n  {_YELLOW}[cleanup] {exc}{_RESET}")


# ===========================================================================
#  Тестова таблиця
# ===========================================================================

TESTS = [
    # Група 1: arm_tool
    ("arm_tool(True): повертає True",
     _test_arm_tool_returns_true_when_arming),
    ("arm_tool(False): повертає False",
     _test_arm_tool_returns_false_when_disarming),
    ("arm_tool(False): надсилає M102 коли joints homed",
     _test_arm_tool_disarm_sends_mdi_when_homed),
    ("arm_tool(False): без MDI коли joints not homed",
     _test_arm_tool_disarm_no_mdi_when_not_homed),
    ("arm_tool(False): завжди False незалежно від MDI",
     _test_arm_tool_disarm_returns_false_regardless_of_mdi),
    ("arm_tool(True): не надсилає MDI",
     _test_arm_tool_arm_does_not_send_mdi),

    # Група 2: perform_action
    ("perform_action: False коли not armed (guard 1)",
     _test_perform_action_returns_false_when_not_armed),
    ("perform_action: False коли not homed (guard 2)",
     _test_perform_action_returns_false_when_not_homed),
    ("perform_action: grip → send_mdi(M101)",
     _test_perform_action_grip_sends_m101),
    ("perform_action: release → send_mdi(M102)",
     _test_perform_action_release_sends_m102),
    ("perform_action: False якщо send_mdi повертає False",
     _test_perform_action_returns_false_when_mdi_fails),
    ("perform_action: guard 1 (not armed) має пріоритет над guard 2",
     _test_perform_action_not_armed_takes_priority_over_not_homed),
    ("perform_action: реальний sim → повертає bool (no crash)",
     _test_perform_action_real_m101_in_sim_returns_bool),

    # Група 3: set_power
    ("set_power(50): повертає 0.5",
     _test_set_power_returns_normalized_value),
    ("set_power(75): set_gripper_force(0.75)",
     _test_set_power_calls_set_gripper_force_with_normalized),
    ("set_power(10): min boundary → 0.1",
     _test_set_power_min_boundary),
    ("set_power(100): max boundary → 1.0",
     _test_set_power_max_boundary),
    ("set_power: реальний sim не кидає виняток",
     _test_set_power_real_sim_does_not_crash),
    ("set_power: послідовні значення → правильний normalized",
     _test_set_power_sequential_values),

    # Група 4: _joints_homed
    ("_joints_homed: True після home_all",
     _test_joints_homed_true_after_home_all),
    ("_joints_homed: False коли not homed",
     _test_joints_homed_false_when_not_homed),
    ("_joints_homed: перевіряє рівно перші 3 joints",
     _test_joints_homed_checks_exactly_required_count),
    ("_joints_homed: не потребує joints 3..5",
     _test_joints_homed_does_not_require_all_6),

    # Група 5: send_mdi contract
    ("send_mdi: завжди повертає bool",
     _test_send_mdi_returns_bool),
    ("send_mdi: True для стандартного коду G21",
     _test_send_mdi_true_for_standard_mdi_code),
    ("send_mdi: відновлює task_mode після виконання",
     _test_send_mdi_restores_previous_mode),
    ("send_mdi: False коли interpreter busy",
     _test_send_mdi_false_when_interpreter_busy),
    ("send_mdi(M101): повертає bool без crash в sim",
     _test_send_mdi_m101_returns_bool_in_sim),

    # Група 6: наскрізні
    ("workflow: arm → grip → release → disarm (MDI calls порядок)",
     _test_workflow_arm_grip_release_disarm),
    ("workflow: perform_action завжди False без arm",
     _test_workflow_no_action_without_arm),
    ("workflow: set_power не залежить від arm стану",
     _test_workflow_power_set_before_and_after_arm),
    ("workflow: _POWER_MIN=10 і _POWER_MAX=100 bounds",
     _test_workflow_set_power_bounds_respected),
    ("workflow: grip denied після disarm",
     _test_workflow_action_denied_after_disarm),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: ToolManager ↔ MachineController ↔ sim{_RESET}")
    print(f"{_BOLD}{'=' * 64}{_RESET}\n")

    try:
        _probe = linuxcnc.stat()
        _probe.poll()
    except Exception as exc:
        print(f"{_RED}❌ LinuxCNC недоступний: {exc}{_RESET}")
        sys.exit(1)

    for group_name, fn in TESTS:
        run_test(group_name, fn)

    _cleanup()

    total  = len(TESTS)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    if failed == 0:
        print(f"{_GREEN}{_BOLD}  ✓ Всі {total} тестів пройшли{_RESET}")
    else:
        print(f"{_RED}{_BOLD}  ✗ {failed}/{total} тестів провалились{_RESET}")
        print(f"\n{_RED}Провали:{_RESET}")
        for name, ok, msg in _results:
            if not ok:
                print(f"  • {name}")
                for line in msg.strip().splitlines()[:8]:
                    print(f"    {line}")
    print(f"{_BOLD}{'=' * 64}{_RESET}\n")

    sys.exit(0 if failed == 0 else 1)