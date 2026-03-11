#!/usr/bin/env python3
"""
Інтеграційні тести AxisManager  ↔  MachineController  ↔  LinuxCNC sim
=======================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_axis_logic.py

Підтверджені значення цього sim (з diagnose_sim.py):
  STATE_ON          = 4  (не 1!)
  STATE_OFF         = 3
  STATE_ESTOP       = 1  (= ESTOP активний)
  STATE_ESTOP_RESET = 2  (= ESTOP скинутий, але OFF)
  MODE_MANUAL       = 1
  MODE_AUTO         = 2
  INTERP_IDLE       = 1
  kinematics_type   = 4  завжди (IDENTITY kinematics, teleop не змінює)
  JOG_CMD_FLAG      = 1  (joint mode)

Архітектура тестів:
  * кожен тест стартує з _setup_for_motion() — home + MANUAL + стабілізація
  * is_ready тести використовують окремий _setup_minimal() без homing
  * teleop тести замінені на перевірку через рух (kinematics_type незмінний)
  * incremental тести: wait_for_motion_start() + wait_motion_stopped()
"""

import sys
import time
import traceback

import linuxcnc

from logic.core.machine import MachineController
from logic.managers.axis_manager import AxisManager, _CONTINUOUS_MODE

# ---------------------------------------------------------------------------
# ANSI кольори
# ---------------------------------------------------------------------------
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

# ---------------------------------------------------------------------------
# Підтверджені константи LinuxCNC для цього sim
# ---------------------------------------------------------------------------
_STATE_ESTOP       = linuxcnc.STATE_ESTOP        # 1
_STATE_ESTOP_RESET = linuxcnc.STATE_ESTOP_RESET  # 2
_STATE_OFF         = linuxcnc.STATE_OFF          # 3
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
    assert actual == expected, f"Очікувалось {expected!r}, отримано {actual!r}{label}"


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


def wait_motion_started(ctrl: MachineController,
                        axis_idx: int = 0,
                        min_delta: float = 0.01,
                        timeout: float = 2.0) -> bool:
    """
    Чекати поки вісь axis_idx реально почне рухатись (зміна > min_delta).
    Потрібно для incremental jog: між командою і початком руху є затримка sim.
    """
    ctrl.poll()
    start_pos = ctrl.status.actual_position[axis_idx]
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if abs(ctrl.status.actual_position[axis_idx] - start_pos) >= min_delta:
            return True
        time.sleep(_POLL_STEP)
    return False


def wait_motion_stopped(ctrl: MachineController,
                        timeout: float = 8.0) -> bool:
    """
    Чекати повної зупинки: motion_type == 0 і позиція стабільна 4 цикли.
    Чекаємо мінімум 0.15s щоб sim встиг почати рух перед перевіркою зупинки.
    """
    time.sleep(0.15)
    deadline = time.time() + timeout
    prev_pos = None
    stable = 0
    while time.time() < deadline:
        ctrl.poll()
        cur = tuple(round(x, 4) for x in ctrl.status.actual_position[:3])
        if ctrl.status.motion_type == 0 and cur == prev_pos:
            stable += 1
            if stable >= 4:
                return True
        else:
            stable = 0
        prev_pos = cur
        time.sleep(_POLL_STEP)
    return False


# ---------------------------------------------------------------------------
# Стан машини
# ---------------------------------------------------------------------------

def bring_to_manual(ctrl: MachineController) -> None:
    """ESTOP_RESET → STATE_ON → MODE_MANUAL."""
    ctrl.poll()
    if ctrl.status.estop == _STATE_ESTOP:
        ctrl.command.state(_STATE_ESTOP_RESET)
        ok = poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP)
        if not ok:
            raise RuntimeError("Не вдалося скинути ESTOP")

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
    """Зупинити рух, повернути в MANUAL, ігнорувати помилки."""
    try:
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    except Exception:
        pass


def home_all(ctrl: MachineController) -> bool:
    """Home all axes, чекати homed[0..2]. Timeout=20s."""
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    ctrl.command.home(-1)
    return poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(3)),
        timeout=20.0,
    )


def _setup_for_motion() -> tuple[MachineController, AxisManager]:
    """
    Повний підготовчий цикл для рухових тестів:
    bring_to_manual → home_all → bring_to_manual → wait_motion_stopped.
    Кидає RuntimeError якщо homing не вдався.
    """
    ctrl = MachineController()
    mgr  = AxisManager(ctrl)
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    wait_motion_stopped(ctrl, timeout=3.0)
    return ctrl, mgr


def _setup_minimal() -> tuple[MachineController, AxisManager]:
    """Мінімальне підключення без homing — для is_ready тестів."""
    ctrl = MachineController()
    mgr  = AxisManager(ctrl)
    return ctrl, mgr


# ===========================================================================
#  ГРУПА 1: is_ready
# ===========================================================================

def _test_is_ready_false_when_estopped():
    ctrl, _ = _setup_minimal()
    bring_to_manual(ctrl)  # стартуємо з чистого стану
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)
    ctrl.poll()
    assert_false(ctrl.is_ready(),
                 f"is_ready() має бути False при estop={ctrl.status.estop}")


def _test_is_ready_true_when_on_and_reset():
    ctrl, _ = _setup_minimal()
    bring_to_manual(ctrl)
    ctrl.poll()
    assert_true(ctrl.is_ready(),
                f"is_ready() має бути True: task_state={ctrl.status.task_state}, "
                f"estop={ctrl.status.estop}")


def _test_is_ready_false_when_power_off():
    ctrl, _ = _setup_minimal()
    bring_to_manual(ctrl)
    ctrl.command.state(_STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state == _STATE_OFF)
    ctrl.poll()
    assert_false(ctrl.is_ready(),
                 f"is_ready() має бути False при task_state={ctrl.status.task_state}")


# ===========================================================================
#  ГРУПА 2: start_jog
# ===========================================================================

def _test_start_jog_no_movement_when_not_ready():
    ctrl, mgr = _setup_minimal()
    bring_to_manual(ctrl)
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.25)

    ctrl.poll()
    pos_after = ctrl.status.actual_position[0]
    assert_approx(pos_after, pos_before, tol=0.002,
                  msg="Позиція не має змінитись — машина не готова (ESTOP)")


def _test_start_jog_continuous_changes_position():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 600.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.35)

    ctrl.poll()
    pos_mid = ctrl.status.actual_position[0]
    safe_stop(ctrl)
    wait_motion_stopped(ctrl, timeout=2.0)
    ctrl.poll()
    pos_after = ctrl.status.actual_position[0]

    assert_true(
        pos_after > pos_before,
        f"X-позиція має збільшитись: {pos_before:.4f} → {pos_after:.4f} "
        f"(під час руху: {pos_mid:.4f})"
    )


def _test_start_jog_negative_direction_decreases_position():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 600.0

    # Рух в + щоб мати місце для -
    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.4)
    mgr.stop_jog(axis_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=2.0)

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=-1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.35)
    safe_stop(ctrl)
    wait_motion_stopped(ctrl, timeout=2.0)

    ctrl.poll()
    pos_after = ctrl.status.actual_position[0]

    assert_true(
        pos_after < pos_before,
        f"X-позиція має зменшитись: {pos_before:.4f} → {pos_after:.4f}"
    )


def _test_start_jog_incremental_moves_exact_distance():
    ctrl, mgr = _setup_for_motion()
    TARGET = 1.0
    ctrl.linear_jog_speed = 300.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text=str(TARGET))

    # Чекаємо початку руху (sim має затримку ~100ms до старту)
    assert_true(
        wait_motion_started(ctrl, axis_idx=0, min_delta=0.05, timeout=3.0),
        "Incremental jog не почався за 3 секунди"
    )
    # Чекаємо зупинки після кроку
    assert_true(
        wait_motion_stopped(ctrl, timeout=8.0),
        "Incremental jog не завершився за 8 секунд"
    )

    ctrl.poll()
    pos_after = ctrl.status.actual_position[0]
    delta = pos_after - pos_before

    assert_approx(delta, TARGET, tol=0.05,
                  msg=f"Incremental jog має перемістити {TARGET}mm, отримано {delta:.4f}")


def _test_start_jog_sync_mode_switches_to_manual():
    """
    sync_mode має перемикати в MODE_MANUAL перед jogом.
    Тест через реальну поведінку: починаємо з AUTO, після start_jog → MANUAL.
    (Замінює kinematics_type тест — в цьому sim kinematics_type=4 завжди)
    """
    ctrl, mgr = _setup_for_motion()

    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_AUTO, "Передумова: маємо бути в AUTO")

    ctrl.linear_jog_speed = 300.0
    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.15)
    safe_stop(ctrl)
    wait_motion_stopped(ctrl, timeout=2.0)

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "start_jog (sync_mode) має перемкнути з AUTO в MANUAL")


def _test_start_jog_exception_does_not_propagate():
    ctrl, mgr = _setup_minimal()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)
    # Жодного винятку не має вийти назовні
    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)


# ===========================================================================
#  ГРУПА 3: stop_jog
# ===========================================================================

def _test_stop_jog_continuous_halts_motion():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 600.0

    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.3)

    mgr.stop_jog(axis_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)

    ctrl.poll()
    pos_stop = ctrl.status.actual_position[0]
    time.sleep(0.35)
    ctrl.poll()
    pos_later = ctrl.status.actual_position[0]

    assert_approx(pos_later, pos_stop, tol=0.005,
                  msg=f"Після stop_jog позиція не має змінюватись: "
                      f"{pos_stop:.4f} vs {pos_later:.4f}")


def _test_stop_jog_incremental_mode_does_not_abort():
    """
    stop_jog з incremental mode_text — no-op.
    Рух має дійти до кінця кроку.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 300.0
    TARGET = 2.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text=str(TARGET))

    # Одразу no-op stop
    mgr.stop_jog(axis_idx=0, mode_text=str(TARGET))

    # Чекаємо початку реального руху
    assert_true(
        wait_motion_started(ctrl, axis_idx=0, min_delta=0.05, timeout=3.0),
        "Incremental jog (no-op stop) не почався за 3 секунди"
    )
    # Чекаємо зупинки після повного кроку
    assert_true(
        wait_motion_stopped(ctrl, timeout=10.0),
        "Incremental jog не завершився за 10 секунд"
    )

    ctrl.poll()
    pos_after = ctrl.status.actual_position[0]
    delta = pos_after - pos_before

    assert_approx(delta, TARGET, tol=0.05,
                  msg=f"Крок {TARGET}mm має бути пройдений повністю, дельта={delta:.4f}")


# ===========================================================================
#  ГРУПА 4: sync_mode напряму
# ===========================================================================

def _test_sync_mode_switches_to_manual_from_auto():
    ctrl, _ = _setup_for_motion()

    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    result = ctrl.sync_mode(want_teleop=True)
    assert_true(result, "sync_mode має повернути True")

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "sync_mode має перевести в MANUAL з AUTO")


def _test_sync_mode_returns_true_when_already_manual():
    ctrl, _ = _setup_for_motion()
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Передумова: вже в MANUAL")

    result = ctrl.sync_mode(want_teleop=True)
    assert_true(result, "sync_mode має повернути True навіть якщо вже в MANUAL")

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Режим має залишитись MANUAL")


def _test_sync_mode_teleop_does_not_crash():
    """
    В цьому sim kinematics_type=4 завжди (IDENTITY).
    teleop_enable не змінює kinematics_type — але sync_mode не має падати.
    Перевіряємо тільки що метод повертає True і машина в MANUAL.
    """
    ctrl, _ = _setup_for_motion()

    result_on  = ctrl.sync_mode(want_teleop=True)
    result_off = ctrl.sync_mode(want_teleop=False)

    assert_true(result_on,  "sync_mode(want_teleop=True) має повернути True")
    assert_true(result_off, "sync_mode(want_teleop=False) має повернути True")

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "Після sync_mode машина має залишитись в MANUAL")


# ===========================================================================
#  ГРУПА 5: parse_increment
# ===========================================================================

def _test_continuous_mode_jogs_until_stopped():
    """
    _CONTINUOUS_MODE → рух не зупиняється сам, потрібен stop_jog.
    Перевіряємо 2 факти:
      1. За 450ms при 600mm/min машина рухається >1mm від старту до зупинки.
      2. Після wait_motion_stopped позиція стабільна (coasting вже завершено).
    Порівнюємо pos_stopped з pos_later — не з pos_during, бо pos_during читається
    під час активного руху і не враховує coasting після команди stop.
    """
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 600.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
    time.sleep(0.45)

    ctrl.poll()
    pos_during = ctrl.status.actual_position[0]  # під час руху (для діагностики)

    mgr.stop_jog(axis_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=3.0)  # чекаємо повного coasting

    ctrl.poll()
    pos_stopped = ctrl.status.actual_position[0]
    time.sleep(0.4)
    ctrl.poll()
    pos_later = ctrl.status.actual_position[0]

    # Факт 1: рух відбувся (>1mm від старту до повної зупинки)
    assert_true(
        pos_stopped - pos_before > 1.0,
        f"Continuous jog має дати >1mm: before={pos_before:.4f}, "
        f"stopped={pos_stopped:.4f}, Δ={pos_stopped - pos_before:.3f}mm "
        f"(під час: {pos_during:.4f})"
    )
    # Факт 2: після зупинки позиція стабільна
    assert_approx(
        pos_later, pos_stopped, tol=0.005,
        msg=f"Після wait_motion_stopped позиція не має змінюватись: "
            f"{pos_stopped:.4f} → {pos_later:.4f}"
    )


def _test_increment_05mm_accurate():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 300.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text="0.5")

    assert_true(wait_motion_started(ctrl, axis_idx=0, min_delta=0.05, timeout=3.0),
                "Incremental 0.5mm не почався")
    assert_true(wait_motion_stopped(ctrl, timeout=8.0),
                "Incremental 0.5mm не завершився")

    ctrl.poll()
    delta = ctrl.status.actual_position[0] - pos_before
    assert_approx(delta, 0.5, tol=0.05,
                  msg=f"Incremental 0.5mm: дельта={delta:.4f}")


def _test_increment_10mm_accurate():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 300.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text="1.0")

    assert_true(wait_motion_started(ctrl, axis_idx=0, min_delta=0.05, timeout=3.0),
                "Incremental 1.0mm не почався")
    assert_true(wait_motion_stopped(ctrl, timeout=8.0),
                "Incremental 1.0mm не завершився")

    ctrl.poll()
    delta = ctrl.status.actual_position[0] - pos_before
    assert_approx(delta, 1.0, tol=0.05,
                  msg=f"Incremental 1.0mm: дельта={delta:.4f}")


def _test_invalid_increment_fallback_to_continuous():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 600.0

    ctrl.poll()
    pos_before = ctrl.status.actual_position[0]

    mgr.start_jog(axis_idx=0, direction=1, mode_text="invalid_value")
    time.sleep(0.35)
    mgr.stop_jog(axis_idx=0, mode_text=_CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=2.0)

    ctrl.poll()
    pos_after = ctrl.status.actual_position[0]

    assert_true(
        pos_after > pos_before,
        f"invalid mode_text має фолбекнути на continuous і рухатись: "
        f"{pos_before:.4f} → {pos_after:.4f}"
    )


# ===========================================================================
#  ГРУПА 6: всі осі X, Y, Z
# ===========================================================================

def _test_each_xyz_axis_can_jog():
    ctrl, mgr = _setup_for_motion()
    ctrl.linear_jog_speed = 600.0

    for axis_idx, axis_name in [(0, "X"), (1, "Y"), (2, "Z")]:
        safe_stop(ctrl)
        bring_to_manual(ctrl)
        wait_motion_stopped(ctrl, timeout=3.0)

        ctrl.poll()
        pos_before = ctrl.status.actual_position[axis_idx]

        mgr.start_jog(axis_idx=axis_idx, direction=1, mode_text=_CONTINUOUS_MODE)
        time.sleep(0.35)
        mgr.stop_jog(axis_idx=axis_idx, mode_text=_CONTINUOUS_MODE)
        wait_motion_stopped(ctrl, timeout=3.0)

        ctrl.poll()
        pos_after = ctrl.status.actual_position[axis_idx]

        assert_true(
            pos_after > pos_before,
            f"Вісь {axis_name}[{axis_idx}] не рухається: "
            f"{pos_before:.4f} → {pos_after:.4f}"
        )


# ===========================================================================
#  ГРУПА 7: швидкість
# ===========================================================================

def _test_higher_speed_produces_larger_displacement():
    ctrl, mgr = _setup_for_motion()
    DURATION = 0.35

    # Повільний прогін
    ctrl.linear_jog_speed = 120.0
    ctrl.poll()
    p0 = ctrl.status.actual_position[0]
    mgr.start_jog(0, 1, _CONTINUOUS_MODE)
    time.sleep(DURATION)
    mgr.stop_jog(0, _CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=2.0)
    ctrl.poll()
    delta_slow = ctrl.status.actual_position[0] - p0

    # Повертаємось назад
    mgr.start_jog(0, -1, _CONTINUOUS_MODE)
    time.sleep(DURATION + 0.15)
    mgr.stop_jog(0, _CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=2.0)

    # Швидкий прогін
    ctrl.linear_jog_speed = 600.0
    ctrl.poll()
    p1 = ctrl.status.actual_position[0]
    mgr.start_jog(0, 1, _CONTINUOUS_MODE)
    time.sleep(DURATION)
    mgr.stop_jog(0, _CONTINUOUS_MODE)
    wait_motion_stopped(ctrl, timeout=2.0)
    ctrl.poll()
    delta_fast = ctrl.status.actual_position[0] - p1

    safe_stop(ctrl)

    assert_true(
        delta_fast > delta_slow * 1.5,
        f"600mm/min має давати >1.5× ніж 120mm/min: "
        f"slow={delta_slow:.3f}, fast={delta_fast:.3f}"
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
    ("is_ready: False при ESTOP",
     _test_is_ready_false_when_estopped),
    ("is_ready: True при STATE_ON + ESTOP_RESET",
     _test_is_ready_true_when_on_and_reset),
    ("is_ready: False при STATE_OFF",
     _test_is_ready_false_when_power_off),

    # Група 2: start_jog
    ("start_jog: no-op при not ready (ESTOP)",
     _test_start_jog_no_movement_when_not_ready),
    ("start_jog: continuous рухає позицію +X",
     _test_start_jog_continuous_changes_position),
    ("start_jog: negative direction рухає -X",
     _test_start_jog_negative_direction_decreases_position),
    ("start_jog: incremental — точна відстань 1.0mm",
     _test_start_jog_incremental_moves_exact_distance),
    ("start_jog: sync_mode перемикає AUTO → MANUAL",
     _test_start_jog_sync_mode_switches_to_manual),
    ("start_jog: виняток не пропагується назовні",
     _test_start_jog_exception_does_not_propagate),

    # Група 3: stop_jog
    ("stop_jog: continuous зупиняє рух",
     _test_stop_jog_continuous_halts_motion),
    ("stop_jog: incremental mode → no-op, крок доходить",
     _test_stop_jog_incremental_mode_does_not_abort),

    # Група 4: sync_mode
    ("sync_mode: AUTO → MANUAL",
     _test_sync_mode_switches_to_manual_from_auto),
    ("sync_mode: True якщо вже MANUAL",
     _test_sync_mode_returns_true_when_already_manual),
    ("sync_mode: teleop calls не падають (IDENTITY kin)",
     _test_sync_mode_teleop_does_not_crash),

    # Група 5: parse_increment
    ("parse_increment: Continuous → рух до stop_jog",
     _test_continuous_mode_jogs_until_stopped),
    ("parse_increment: 0.5mm — точна відстань",
     _test_increment_05mm_accurate),
    ("parse_increment: 1.0mm — точна відстань",
     _test_increment_10mm_accurate),
    ("parse_increment: invalid → fallback continuous",
     _test_invalid_increment_fallback_to_continuous),

    # Група 6: осі
    ("axes: X, Y, Z рухаються незалежно",
     _test_each_xyz_axis_can_jog),

    # Група 7: швидкість
    ("speed: 600mm/min дає >1.5× ніж 120mm/min",
     _test_higher_speed_produces_larger_displacement),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: AxisManager ↔ MachineController ↔ sim{_RESET}")
    print(f"{_BOLD}{'=' * 64}{_RESET}\n")

    try:
        _probe = linuxcnc.stat()
        _probe.poll()
    except Exception as exc:
        print(f"{_RED}❌ LinuxCNC недоступний: {exc}{_RESET}")
        print("   Запустіть симуляцію і повторіть.")
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