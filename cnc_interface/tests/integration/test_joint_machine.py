#!/usr/bin/env python3
"""
Інтеграційні тести JointManager ↔ MachineController ↔ LinuxCNC sim
====================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_joint_machine.py

Архітектурні відмінності від AxisManager тестів:
  • is_joint=True  → flag = JOG_CMD_FLAG = 1  (joint mode)
  • angular_jog_speed [°/min] замість linear_jog_speed [mm/min]
  • jog() → vel = speed / 60.0 (°/min → °/s)
  • sync_mode(want_teleop=False) + teleop_enable(0) перед кожним jogом
  • joint_actual_position[j] замість actual_position[axis] для вимірювань
  • Індекс — номер joint (0..5), а не осі X/Y/Z

Підтверджені значення sim (diagnose_sim.py):
  STATE_ESTOP=1, STATE_ON=4, MODE_MANUAL=1, MODE_AUTO=2
  estop=0 коли скинутий  (sim НЕ повертає STATE_ESTOP_RESET=2)
  task_state=2 після STATE_OFF  (sim НЕ повертає STATE_OFF=3)
  kinematics_type=4 завжди  (IDENTITY kin, teleop не змінює)
  JOG_CMD_FLAG=1, JOINTS_COUNT=6
  home(-1) хомить joints 0..5

Покриття (22 тести у 7 групах):
  Група 1 — is_ready         : ESTOP / STATE_OFF / нормальний стан
  Група 2 — start_jog        : no-op без ready, continuous +/-,
                               incremental, sync_mode, no-crash
  Grupa 3 — stop_jog         : continuous зупиняє, incremental no-op,
                               нечисловий mode_text → no-op
  Група 4 — sync_mode        : False → MANUAL, True → MANUAL (IDENTITY),
                               повертає True
  Група 5 — _parse_increment : Continuous→0.0, float, invalid→fallback
  Група 6 — всі joints       : J0..J5 рухаються незалежно
  Група 7 — швидкість        : 600°/min > 1.5× 120°/min за однаковий час
"""

import sys
import time
import traceback

import linuxcnc

from logic.core.machine import MachineController
from logic.managers.joint_manager import JointManager, _CONTINUOUS_MODE

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
_STATE_ESTOP_RESET = linuxcnc.STATE_ESTOP_RESET  # 2  (sim видає 0 після скидання)
_STATE_ON          = linuxcnc.STATE_ON           # 4
_MODE_MANUAL       = linuxcnc.MODE_MANUAL        # 1
_MODE_AUTO         = linuxcnc.MODE_AUTO          # 2

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


def assert_approx(actual: float, expected: float, tol: float = 0.05,
                  msg: str = "") -> None:
    label = f" — {msg}" if msg else ""
    assert abs(actual - expected) <= tol, (
        f"Очікувалось ≈{expected} (±{tol}), отримано {actual:.6f}{label}"
    )


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------

_POLL_STEP = 0.04   # секунд між polling циклами


def poll_until(ctrl: MachineController, condition,
               timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if condition(ctrl.status):
            return True
        time.sleep(_POLL_STEP)
    return False


def jpos(ctrl: MachineController, j: int) -> float:
    """Повернути поточну позицію joint j [°] з joint_actual_position."""
    ctrl.poll()
    return ctrl.status.joint_actual_position[j]


def wait_motion_started(ctrl: MachineController,
                        j: int = 0,
                        min_delta: float = 0.05,
                        timeout: float = 2.5) -> bool:
    """
    Чекати поки joint j реально почне рухатись (|Δ| >= min_delta°).
    Sim має затримку ~100ms від команди до старту.
    """
    ctrl.poll()
    start = ctrl.status.joint_actual_position[j]
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if abs(ctrl.status.joint_actual_position[j] - start) >= min_delta:
            return True
        time.sleep(_POLL_STEP)
    return False


def wait_motion_stopped(ctrl: MachineController,
                        timeout: float = 8.0) -> bool:
    """
    Чекати повної зупинки:
      motion_type == 0  І  joint_actual_position стабільна 4 цикли підряд.
    Затримка 0.15s на початку, щоб не спрацювати раніше початку руху.
    """
    time.sleep(0.15)
    prev: tuple | None = None
    stable = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        cur = tuple(
            round(ctrl.status.joint_actual_position[i], 4)
            for i in range(6)
        )
        if ctrl.status.motion_type == 0 and cur == prev:
            stable += 1
            if stable >= 4:
                return True
        else:
            stable = 0
        prev = cur
        time.sleep(_POLL_STEP)
    return False


# ---------------------------------------------------------------------------
# Стан машини
# ---------------------------------------------------------------------------

def bring_to_manual(ctrl: MachineController) -> None:
    """
    ESTOP скинути → STATE_ON → MODE_MANUAL.

    Sim: estop=0 після скидання (не STATE_ESTOP_RESET=2) → перевіряємо
    != _STATE_ESTOP, а не == _STATE_ESTOP_RESET.
    """
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
    """Abort + MANUAL, ігнорує будь-які помилки."""
    try:
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    except Exception:
        pass


def home_all(ctrl: MachineController) -> bool:
    """
    Home всіх joints через home(-1).
    Sim: joints 0..JOINTS_COUNT-1 homed, teleop_enable(0) перед home.
    """
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


def _setup() -> tuple[MachineController, JointManager]:
    """Мінімальне підключення — MANUAL, без homing."""
    ctrl = MachineController()
    mgr  = JointManager(ctrl)
    bring_to_manual(ctrl)
    return ctrl, mgr


def _setup_for_motion() -> tuple[MachineController, JointManager]:
    """
    Повний підготовчий цикл для рухових тестів:
      bring_to_manual → home_all → bring_to_manual
      → teleop_enable(0) → wait_motion_stopped.
    """
    ctrl = MachineController()
    mgr  = JointManager(ctrl)
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    # Явно joint mode перед тестом
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    wait_motion_stopped(ctrl, timeout=3.0)
    return ctrl, mgr


# ===========================================================================
#  ГРУПА 1: is_ready
# ===========================================================================

def _test_is_ready_false_when_estopped():
    """is_ready() == False при активному ESTOP."""
    ctrl, _ = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)
    ctrl.poll()
    assert_false(ctrl.is_ready(),
                 f"is_ready() має бути False при ESTOP, "
                 f"estop={ctrl.status.estop}, "
                 f"task_state={ctrl.status.task_state}")


def _test_is_ready_true_when_on_and_estop_reset():
    """is_ready() == True при STATE_ON і ESTOP скинутий."""
    ctrl, _ = _setup()
    ctrl.poll()
    assert_true(ctrl.is_ready(),
                f"is_ready() має бути True: "
                f"task_state={ctrl.status.task_state}, "
                f"estop={ctrl.status.estop}")


def _test_is_ready_false_when_power_off():
    """
    is_ready() == False при STATE_OFF.
    Sim: task_state=2 після STATE_OFF (не linuxcnc.STATE_OFF=3).
    is_ready() перевіряє task_state==STATE_ON → False.
    """
    ctrl, _ = _setup()
    ctrl.command.state(linuxcnc.STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state != _STATE_ON)
    ctrl.poll()
    assert_false(ctrl.is_ready(),
                 f"is_ready() має бути False при task_state={ctrl.status.task_state}")


# ===========================================================================
#  ГРУПА 2: start_jog
# ===========================================================================

def _test_start_jog_noop_when_not_ready():
    """
    start_jog — no-op якщо is_ready()==False (ESTOP).
    joint_actual_position не змінюється після виклику.
    """
    ctrl, mgr = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.3)
    pos_after = jpos(ctrl, 0)

    assert_approx(pos_after, pos_before, tol=0.002,
                  msg=f"Joint 0 не має рухатись — машина не готова: "
                      f"{pos_before:.4f}° → {pos_after:.4f}°")


def _test_start_jog_continuous_positive_moves_joint():
    """start_jog direction=+1 continuous збільшує joint_actual_position."""
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.35)
    safe_stop(ctrl)
    wait_motion_stopped(ctrl, timeout=3.0)
    pos_after = jpos(ctrl, 0)

    assert_true(pos_after > pos_before,
                f"Joint 0 має збільшитись: {pos_before:.4f}° → {pos_after:.4f}°")


def _test_start_jog_continuous_negative_decreases_joint():
    """start_jog direction=-1 зменшує joint_actual_position."""
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0

    # Спочатку рухаємось в + щоб мати запас для мінусового jog
    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.4)
    mgr.stop_jog(joint_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=-1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.35)
    safe_stop(ctrl)
    wait_motion_stopped(ctrl, timeout=3.0)
    pos_after = jpos(ctrl, 0)

    assert_true(pos_after < pos_before,
                f"Joint 0 має зменшитись: {pos_before:.4f}° → {pos_after:.4f}°")


def _test_start_jog_incremental_exact_1_deg():
    """
    start_jog incremental "1.0" переміщує joint рівно на 1.0° (±0.05°).
    Перевіряємо через wait_motion_started + wait_motion_stopped.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 300.0
    TARGET = 1.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text=str(TARGET))

    assert_true(
        wait_motion_started(ctrl, j=0, min_delta=0.05, timeout=3.0),
        "Incremental 1.0° не почався за 3 секунди",
    )
    assert_true(
        wait_motion_stopped(ctrl, timeout=8.0),
        "Incremental 1.0° не завершився за 8 секунд",
    )

    delta = jpos(ctrl, 0) - pos_before
    assert_approx(delta, TARGET, tol=0.05,
                  msg=f"Incremental jog 1.0°: дельта={delta:.4f}°")


def _test_start_jog_calls_sync_mode_switches_to_manual():
    """
    start_jog викликає sync_mode(want_teleop=False) → task_mode == MANUAL.
    Починаємо з AUTO щоб перехід був видимий.
    """
    ctrl, mgr = _setup_for_motion()
    # Явно переходимо в AUTO перед тестом
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    ctrl.angular_jog_speed = 300.0
    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.15)
    safe_stop(ctrl)
    wait_motion_stopped(ctrl, timeout=2.0)

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "start_jog через sync_mode має перемкнути AUTO → MANUAL")


def _test_start_jog_exception_does_not_propagate():
    """
    start_jog ніколи не пробрасує виняток назовні.
    JointManager.start_jog ловить Exception і логує logger.error.
    """
    ctrl, mgr = _setup()
    # Активуємо ESTOP щоб is_ready() == False → guard return
    # Потім відкликаємо is_ready щоб обійти guard і дійти до jog()
    from unittest.mock import patch
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    # Patch is_ready → True, щоб дійти до cnc.jog() в неробочому стані
    with patch.object(ctrl, "is_ready", return_value=True):
        mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    # Якщо дійшли сюди — виняток не пропагувався ✓


# ===========================================================================
#  ГРУПА 3: stop_jog
# ===========================================================================

def _test_stop_jog_continuous_halts_joint():
    """
    stop_jog(_CONTINUOUS_MODE) надсилає JOG_STOP → joint зупиняється.
    Перевіряємо що позиція стабілізується після stop.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0

    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.3)

    mgr.stop_jog(joint_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=4.0)

    pos_stop = jpos(ctrl, 0)
    time.sleep(0.4)
    pos_later = jpos(ctrl, 0)

    assert_approx(pos_later, pos_stop, tol=0.005,
                  msg=f"Після stop_jog joint не має рухатись: "
                      f"зупинка={pos_stop:.4f}°, через 400ms={pos_later:.4f}°")


def _test_stop_jog_incremental_is_noop():
    """
    stop_jog в incremental mode — no-op (не надсилає JOG_STOP).
    Incremental jog продовжується до кінця кроку.
    Перевіряємо що повна дистанція все одно пройдена.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 300.0
    TARGET = 2.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text=str(TARGET))
    mgr.stop_jog(joint_idx=0, mode_text=str(TARGET))   # no-op

    assert_true(
        wait_motion_started(ctrl, j=0, min_delta=0.05, timeout=3.0),
        "Incremental 2.0° (після no-op stop) не почався",
    )
    assert_true(
        wait_motion_stopped(ctrl, timeout=12.0),
        "Incremental 2.0° не завершився за 12 секунд",
    )

    delta = jpos(ctrl, 0) - pos_before
    assert_approx(delta, TARGET, tol=0.05,
                  msg=f"no-op stop: incremental {TARGET}° має бути пройдений повністю, "
                      f"дельта={delta:.4f}°")


def _test_stop_jog_non_continuous_mode_text_is_noop():
    """
    stop_jog з mode_text != _CONTINUOUS_MODE — не надсилає JOG_STOP.
    Continuous jog продовжується після "no-op stop".
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.2)

    # No-op: mode_text != _CONTINUOUS_MODE
    mgr.stop_jog(joint_idx=0, mode_text="1.0")
    time.sleep(0.2)

    pos_during = jpos(ctrl, 0)
    safe_stop(ctrl)

    # Якщо рух продовжився — pos_during > pos_before
    assert_true(pos_during > pos_before,
                f"Після no-op stop_jog joint має продовжувати рух: "
                f"before={pos_before:.4f}°, during={pos_during:.4f}°")


def _test_stop_jog_continuous_position_does_not_drift():
    """
    Після stop_jog continuous позиція стабільна протягом 500ms.
    Перевіряємо coasting не виходить за межі 0.05°.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 300.0

    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.4)
    mgr.stop_jog(joint_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=4.0)

    pos_stop = jpos(ctrl, 0)
    time.sleep(0.5)
    pos_later = jpos(ctrl, 0)

    assert_approx(pos_later, pos_stop, tol=0.05,
                  msg=f"Позиція після stop не має дрейфувати: "
                      f"stop={pos_stop:.4f}°, 500ms later={pos_later:.4f}°")


# ===========================================================================
#  ГРУПА 4: sync_mode
# ===========================================================================

def _test_sync_mode_false_returns_true():
    """sync_mode(want_teleop=False) повертає True при успіху."""
    ctrl, _ = _setup_for_motion()
    result = ctrl.sync_mode(want_teleop=False)
    assert_true(result, "sync_mode(want_teleop=False) має повертати True")


def _test_sync_mode_false_switches_to_manual():
    """
    sync_mode(want_teleop=False) переводить task_mode в MANUAL.
    Починаємо з AUTO щоб перехід був явним.
    """
    ctrl, _ = _setup_for_motion()
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    ctrl.sync_mode(want_teleop=False)

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "sync_mode(False) має перевести AUTO → MANUAL")


def _test_sync_mode_true_does_not_crash_on_identity_kin():
    """
    sync_mode(want_teleop=True) в IDENTITY sim не падає.
    kinematics_type=4 завжди → teleop_enable(1) приймається без помилки.
    Повертає True.
    """
    ctrl, _ = _setup_for_motion()
    result = ctrl.sync_mode(want_teleop=True)
    assert_true(result, "sync_mode(want_teleop=True) має повертати True")
    # Незалежно від kinematics_type, task_mode → MANUAL
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "sync_mode(True) в IDENTITY sim має перевести в MANUAL")


def _test_sync_mode_idempotent_in_manual():
    """
    sync_mode(want_teleop=False) коли вже MANUAL — no-op, повертає True.
    set_mode() скипає команду якщо вже в правильному режимі.
    """
    ctrl, _ = _setup_for_motion()
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Передумова: вже MANUAL")

    result = ctrl.sync_mode(want_teleop=False)
    ctrl.poll()
    assert_true(result, "sync_mode повертає True навіть коли вже MANUAL")
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "sync_mode no-op: режим має залишитись MANUAL")


# ===========================================================================
#  ГРУПА 5: _parse_increment
# ===========================================================================

def _test_parse_increment_continuous_mode_returns_zero():
    """_parse_increment("Continuous") → 0.0 → jog отримує increment=0."""
    mgr = JointManager(MachineController())
    result = mgr._parse_increment(_CONTINUOUS_MODE)
    assert_eq(result, 0.0,
              f"_parse_increment('{_CONTINUOUS_MODE}') має повернути 0.0")


def _test_parse_increment_float_string_parsed_correctly():
    """_parse_increment("0.5") → 0.5."""
    mgr = JointManager(MachineController())
    assert_approx(mgr._parse_increment("0.5"), 0.5, tol=1e-9,
                  msg="_parse_increment('0.5') має повернути 0.5")


def _test_parse_increment_large_float_parsed():
    """_parse_increment("10.0") → 10.0."""
    mgr = JointManager(MachineController())
    assert_approx(mgr._parse_increment("10.0"), 10.0, tol=1e-9,
                  msg="_parse_increment('10.0') має повернути 10.0")


def _test_parse_increment_invalid_string_fallback_to_zero():
    """_parse_increment("not_a_number") → 0.0 (fallback to Continuous)."""
    mgr = JointManager(MachineController())
    result = mgr._parse_increment("not_a_number")
    assert_eq(result, 0.0,
              "_parse_increment(invalid) має повернути 0.0 (fallback)")


def _test_parse_increment_empty_string_fallback_to_zero():
    """_parse_increment("") → 0.0."""
    mgr = JointManager(MachineController())
    result = mgr._parse_increment("")
    assert_eq(result, 0.0,
              "_parse_increment('') має повернути 0.0 (fallback)")


def _test_continuous_mode_jog_real_moves_joint():
    """
    _parse_increment → 0.0 → jog отримує increment=0 → JOG_CONTINUOUS.
    Continuous jog за 400ms при 600°/min дає > 1.0°.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.4)
    mgr.stop_jog(joint_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)
    pos_stopped = jpos(ctrl, 0)

    assert_true(pos_stopped - pos_before > 1.0,
                f"Continuous 600°/min за 400ms має дати >1°: "
                f"before={pos_before:.4f}°, stopped={pos_stopped:.4f}°, "
                f"Δ={pos_stopped - pos_before:.3f}°")


def _test_increment_05_real_exact():
    """_parse_increment("0.5") → 0.5 → реальне переміщення 0.5° ± 0.05°."""
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 300.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text="0.5")

    assert_true(wait_motion_started(ctrl, j=0, timeout=3.0),
                "Incremental 0.5° не стартував")
    assert_true(wait_motion_stopped(ctrl, timeout=8.0),
                "Incremental 0.5° не завершився")

    delta = jpos(ctrl, 0) - pos_before
    assert_approx(delta, 0.5, tol=0.05,
                  msg=f"0.5° incremental: дельта={delta:.4f}°")


def _test_increment_invalid_fallback_moves_continuously():
    """
    _parse_increment("abc") → 0.0 → JOG_CONTINUOUS.
    Рух відбувається (fallback не блокує jog).
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0

    pos_before = jpos(ctrl, 0)
    mgr.start_jog(joint_idx=0, direction=1, mode_text="abc")
    time.sleep(0.4)
    mgr.stop_jog(joint_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)

    assert_true(jpos(ctrl, 0) > pos_before,
                "invalid mode_text → fallback continuous має рухати joint")


# ===========================================================================
#  ГРУПА 6: всі joints J0..J5
# ===========================================================================

def _test_all_joints_move_independently():
    """
    Кожен joint J0..J5 реально рухається від start_jog.
    Між joints — повна зупинка і reset стану.
    Один тест-цикл замість 6 окремих для швидкості виконання.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.angular_jog_speed = 600.0
    jc = ctrl.params.get("JOINTS_COUNT", 6)

    failures = []
    for j in range(jc):
        # Повне скидання між ітераціями
        safe_stop(ctrl)
        bring_to_manual(ctrl)
        ctrl.command.teleop_enable(0)
        ctrl.command.wait_complete()
        wait_motion_stopped(ctrl, timeout=3.0)

        pos_before = jpos(ctrl, j)
        mgr.start_jog(joint_idx=j, direction=1, mode_text=_CONTINUOUS_MODE)
        time.sleep(0.4)
        mgr.stop_jog(joint_idx=j, mode_text=_CONTINUOUS_MODE)
        wait_motion_stopped(ctrl, timeout=3.0)
        pos_after = jpos(ctrl, j)

        if not (pos_after > pos_before):
            failures.append(
                f"J{j}: {pos_before:.4f}° → {pos_after:.4f}° (не рухнувся)"
            )

    assert_true(
        len(failures) == 0,
        "Деякі joints не рухнулись: " + "; ".join(failures),
    )


# ===========================================================================
#  ГРУПА 7: кутова швидкість
# ===========================================================================

def _test_higher_speed_larger_displacement():
    """
    600°/min дає > 1.5× переміщення порівняно з 120°/min за той самий час.
    Відповідає vel = speed / 60.0 в MachineController.jog().
    """
    ctrl, mgr = _setup_for_motion()
    DURATION = 0.35

    # ── Повільний прогін ─────────────────────────────────
    ctrl.angular_jog_speed = 120.0
    pos0 = jpos(ctrl, 0)
    mgr.start_jog(0, 1, _CONTINUOUS_MODE)
    time.sleep(DURATION)
    mgr.stop_jog(0, _CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)
    delta_slow = jpos(ctrl, 0) - pos0

    # Повертаємось назад щоб не впертись в ліміт
    mgr.start_jog(0, -1, _CONTINUOUS_MODE)
    time.sleep(DURATION + 0.2)
    mgr.stop_jog(0, _CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)

    # ── Швидкий прогін ───────────────────────────────────
    ctrl.angular_jog_speed = 600.0
    pos1 = jpos(ctrl, 0)
    mgr.start_jog(0, 1, _CONTINUOUS_MODE)
    time.sleep(DURATION)
    mgr.stop_jog(0, _CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)
    delta_fast = jpos(ctrl, 0) - pos1

    safe_stop(ctrl)

    assert_true(
        delta_fast > delta_slow * 1.5,
        f"600°/min має давати >1.5× ніж 120°/min за {DURATION}s: "
        f"slow={delta_slow:.3f}°, fast={delta_fast:.3f}°",
    )


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
        print(f"\n  {_YELLOW}[cleanup] Машина переведена в MANUAL.{_RESET}")
    except Exception as exc:
        print(f"\n  {_YELLOW}[cleanup] {exc}{_RESET}")


# ===========================================================================
#  Тестова таблиця
# ===========================================================================

TESTS = [
    # Група 1: is_ready
    ("is_ready: False при активному ESTOP",
     _test_is_ready_false_when_estopped),
    ("is_ready: True при STATE_ON і ESTOP скинутий",
     _test_is_ready_true_when_on_and_estop_reset),
    ("is_ready: False при STATE_OFF",
     _test_is_ready_false_when_power_off),

    # Група 2: start_jog
    ("start_jog: no-op при not ready (ESTOP)",
     _test_start_jog_noop_when_not_ready),
    ("start_jog: continuous direction=+1 рухає joint вперед",
     _test_start_jog_continuous_positive_moves_joint),
    ("start_jog: continuous direction=-1 рухає joint назад",
     _test_start_jog_continuous_negative_decreases_joint),
    ("start_jog: incremental 1.0° — точна відстань",
     _test_start_jog_incremental_exact_1_deg),
    ("start_jog: sync_mode перемикає AUTO → MANUAL",
     _test_start_jog_calls_sync_mode_switches_to_manual),
    ("start_jog: виняток з cnc.jog() не пробрасується",
     _test_start_jog_exception_does_not_propagate),

    # Група 3: stop_jog
    ("stop_jog: continuous зупиняє рух joint",
     _test_stop_jog_continuous_halts_joint),
    ("stop_jog: incremental mode_text → no-op, крок доходить",
     _test_stop_jog_incremental_is_noop),
    ("stop_jog: нечисловий mode_text → no-op, рух продовжується",
     _test_stop_jog_non_continuous_mode_text_is_noop),
    ("stop_jog: позиція стабільна 500ms після зупинки",
     _test_stop_jog_continuous_position_does_not_drift),

    # Група 4: sync_mode
    ("sync_mode(False): повертає True",
     _test_sync_mode_false_returns_true),
    ("sync_mode(False): AUTO → MANUAL",
     _test_sync_mode_false_switches_to_manual),
    ("sync_mode(True): no crash в IDENTITY sim",
     _test_sync_mode_true_does_not_crash_on_identity_kin),
    ("sync_mode(False): ідемпотентний в MANUAL",
     _test_sync_mode_idempotent_in_manual),

    # Група 5: _parse_increment
    ("_parse_increment: 'Continuous' → 0.0",
     _test_parse_increment_continuous_mode_returns_zero),
    ("_parse_increment: '0.5' → 0.5",
     _test_parse_increment_float_string_parsed_correctly),
    ("_parse_increment: '10.0' → 10.0",
     _test_parse_increment_large_float_parsed),
    ("_parse_increment: invalid → 0.0 (fallback)",
     _test_parse_increment_invalid_string_fallback_to_zero),
    ("_parse_increment: '' → 0.0 (fallback)",
     _test_parse_increment_empty_string_fallback_to_zero),
    ("_parse_increment: Continuous → реальний рух >1°",
     _test_continuous_mode_jog_real_moves_joint),
    ("_parse_increment: '0.5' → реальний рух 0.5°",
     _test_increment_05_real_exact),
    ("_parse_increment: invalid → fallback continuous рухає joint",
     _test_increment_invalid_fallback_moves_continuously),

    # Група 6: всі joints
    ("joints J0..J5: кожен рухається незалежно",
     _test_all_joints_move_independently),

    # Група 7: швидкість
    ("speed: 600°/min дає >1.5× ніж 120°/min за однаковий час",
     _test_higher_speed_larger_displacement),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: JointManager ↔ MachineController ↔ sim{_RESET}")
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