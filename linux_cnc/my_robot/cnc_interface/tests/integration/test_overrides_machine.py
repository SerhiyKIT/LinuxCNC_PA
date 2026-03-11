#!/usr/bin/env python3
"""
Інтеграційні тести OverridesManager ↔ MachineController ↔ LinuxCNC sim
========================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_overrides_machine.py

Архітектура OverridesManager:
  set_feed(scale)          → cnc.set_feed_override(scale)
                             → command.feedrate(rate)
                             → status.feedrate  [читається з sim]

  set_rapid(scale)         → cnc.set_rapid_override(scale)
                             → command.rapidrate(rate)
                             → status.rapidrate  [читається з sim]

  set_spindle(scale)       → cnc.set_spindle_override(scale)
                             → command.spindleoverride(rate)
                             → status.spindlerate  [читається з sim]

  set_linear_speed(v)      → cnc.linear_jog_speed = v
                             Python-атрибут, НЕ передається в sim.
                             Перевіряємо напряму: ctrl.linear_jog_speed == v

  set_angular_speed(v)     → cnc.angular_jog_speed = v
                             Python-атрибут, НЕ передається в sim.
                             Перевіряємо напряму: ctrl.angular_jog_speed == v

  set_max_velocity(v)      → cnc.set_max_velocity(v)
                             → command.maxvel(v / 60.0)
                             → status.max_velocity  [в одиницях/с]
                             Ловить Exception і логує — не пробрасує.

Підтверджені значення sim (diagnose_sim.py):
  estop=0 коли скинутий, STATE_ESTOP=1, STATE_ON=4, MODE_MANUAL=1
  task_state=2 після STATE_OFF (не STATE_OFF=3)
  JOINTS_COUNT=6

Покриття (29 тестів у 7 групах):
  Група 1 — set_feed:          scale відображається в status.feedrate
  Група 2 — set_rapid:         scale відображається в status.rapidrate
  Група 3 — set_spindle:       scale відображається в status.spindlerate
  Група 4 — set_linear_speed:  значення зберігається в python-атрибуті
  Група 5 — set_angular_speed: значення зберігається в python-атрибуті
  Група 6 — set_max_velocity:  значення відображається в status.max_velocity,
                               виняток не пробрасується
  Група 7 — наскрізні:         _SLIDER_CONFIG scaling, незалежність overrides,
                               jog speed впливає на реальний рух
"""

import sys
import time
import traceback

import linuxcnc

from logic.core.machine import MachineController
from logic.managers.overrides_manager import (
    OverridesManager,
    _SLIDER_CONFIG,
    _PRECISION_HIGH,
    _PRECISION_DEG,
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
               timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if condition(ctrl.status):
            return True
        time.sleep(_POLL_STEP)
    return False


def wait_feedrate(ctrl: MachineController, expected: float,
                  tol: float = 0.005, timeout: float = 2.0) -> bool:
    """Чекати поки status.feedrate стане ≈ expected."""
    return poll_until(
        ctrl,
        lambda s: abs(s.feedrate - expected) <= tol,
        timeout,
    )


def wait_rapidrate(ctrl: MachineController, expected: float,
                   tol: float = 0.005, timeout: float = 2.0) -> bool:
    return poll_until(
        ctrl,
        lambda s: abs(s.rapidrate - expected) <= tol,
        timeout,
    )


def wait_spindlerate(ctrl: MachineController, expected: float,
                     tol: float = 0.005, timeout: float = 2.0) -> bool:
    """
    Чекати поки spindle override ≈ expected.
    LinuxCNC 2.8+: stat.spindle[0]['override'] замість stat.spindlerate
    (stat.spindlerate не існує в цьому sim).
    """
    return poll_until(
        ctrl,
        lambda s: abs(s.spindle[0]["override"] - expected) <= tol,
        timeout,
    )


def wait_max_velocity(ctrl: MachineController, expected_per_sec: float,
                      tol: float = 0.005, timeout: float = 2.0) -> bool:
    """
    Чекати поки status.max_velocity ≈ expected_per_sec.
    set_max_velocity(v) → maxvel(v/60.0) → status.max_velocity в одиницях/с.
    """
    return poll_until(
        ctrl,
        lambda s: abs(s.max_velocity - expected_per_sec) <= tol,
        timeout,
    )


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


def wait_motion_stopped(ctrl: MachineController, timeout: float = 6.0) -> bool:
    time.sleep(0.15)
    prev = None
    stable = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        cur = tuple(round(ctrl.status.joint_actual_position[i], 4) for i in range(6))
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
# Setup helpers
# ---------------------------------------------------------------------------

def _setup() -> tuple[MachineController, OverridesManager]:
    """MANUAL — без homing (overrides не потребують руху)."""
    ctrl = MachineController()
    mgr  = OverridesManager(ctrl)
    bring_to_manual(ctrl)
    return ctrl, mgr


def _setup_for_motion() -> tuple[MachineController, OverridesManager]:
    """home + MANUAL — для тестів що перевіряють вплив швидкості на рух."""
    ctrl = MachineController()
    mgr  = OverridesManager(ctrl)
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    wait_motion_stopped(ctrl, timeout=3.0)
    return ctrl, mgr


# ===========================================================================
#  ГРУПА 1: set_feed — status.feedrate
# ===========================================================================

def _test_set_feed_100_percent():
    """set_feed(1.0) → status.feedrate ≈ 1.0 (100%)."""
    ctrl, mgr = _setup()
    mgr.set_feed(1.0)
    ok = wait_feedrate(ctrl, 1.0)
    ctrl.poll()
    assert_true(ok,
                f"set_feed(1.0): status.feedrate має бути ≈1.0, є {ctrl.status.feedrate:.4f}")


def _test_set_feed_50_percent():
    """set_feed(0.5) → status.feedrate ≈ 0.5 (50%)."""
    ctrl, mgr = _setup()
    mgr.set_feed(0.5)
    ok = wait_feedrate(ctrl, 0.5)
    ctrl.poll()
    assert_true(ok,
                f"set_feed(0.5): status.feedrate має бути ≈0.5, є {ctrl.status.feedrate:.4f}")


def _test_set_feed_200_percent():
    """set_feed(2.0) → status.feedrate ≈ 2.0 (200%)."""
    ctrl, mgr = _setup()
    mgr.set_feed(2.0)
    ok = wait_feedrate(ctrl, 2.0)
    ctrl.poll()
    assert_true(ok,
                f"set_feed(2.0): status.feedrate має бути ≈2.0, є {ctrl.status.feedrate:.4f}")


def _test_set_feed_zero():
    """set_feed(0.0) → status.feedrate ≈ 0.0 (feed hold via override)."""
    ctrl, mgr = _setup()
    mgr.set_feed(0.0)
    ok = wait_feedrate(ctrl, 0.0)
    ctrl.poll()
    assert_true(ok,
                f"set_feed(0.0): status.feedrate має бути ≈0.0, є {ctrl.status.feedrate:.4f}")


def _test_set_feed_changes_take_effect_sequentially():
    """Послідовні виклики set_feed → кожен оновлює status.feedrate."""
    ctrl, mgr = _setup()
    for rate in (0.25, 0.75, 1.5, 1.0):
        mgr.set_feed(rate)
        ok = wait_feedrate(ctrl, rate)
        ctrl.poll()
        assert_true(ok,
                    f"set_feed({rate}): feedrate має бути ≈{rate}, є {ctrl.status.feedrate:.4f}")


# ===========================================================================
#  ГРУПА 2: set_rapid — status.rapidrate
# ===========================================================================

def _test_set_rapid_100_percent():
    """set_rapid(1.0) → status.rapidrate ≈ 1.0."""
    ctrl, mgr = _setup()
    mgr.set_rapid(1.0)
    ok = wait_rapidrate(ctrl, 1.0)
    ctrl.poll()
    assert_true(ok,
                f"set_rapid(1.0): rapidrate має бути ≈1.0, є {ctrl.status.rapidrate:.4f}")


def _test_set_rapid_50_percent():
    """set_rapid(0.5) → status.rapidrate ≈ 0.5."""
    ctrl, mgr = _setup()
    mgr.set_rapid(0.5)
    ok = wait_rapidrate(ctrl, 0.5)
    ctrl.poll()
    assert_true(ok,
                f"set_rapid(0.5): rapidrate має бути ≈0.5, є {ctrl.status.rapidrate:.4f}")


def _test_set_rapid_minimum():
    """set_rapid(0.0) → status.rapidrate ≈ 0.0."""
    ctrl, mgr = _setup()
    mgr.set_rapid(0.0)
    ok = wait_rapidrate(ctrl, 0.0)
    ctrl.poll()
    assert_true(ok,
                f"set_rapid(0.0): rapidrate має бути ≈0.0, є {ctrl.status.rapidrate:.4f}")


def _test_set_rapid_independent_from_feed():
    """
    set_rapid не впливає на feedrate і навпаки.
    Перевіряємо незалежність двох каналів.
    """
    ctrl, mgr = _setup()
    mgr.set_feed(0.75)
    wait_feedrate(ctrl, 0.75)

    mgr.set_rapid(0.5)
    ok = wait_rapidrate(ctrl, 0.5)
    ctrl.poll()
    assert_true(ok, f"rapidrate має бути ≈0.5, є {ctrl.status.rapidrate:.4f}")
    assert_approx(ctrl.status.feedrate, 0.75, tol=0.01,
                  msg=f"set_rapid не має змінювати feedrate: є {ctrl.status.feedrate:.4f}")


# ===========================================================================
#  ГРУПА 3: set_spindle — status.spindlerate
# ===========================================================================

def _test_set_spindle_100_percent():
    """set_spindle(1.0) → status.spindlerate ≈ 1.0."""
    ctrl, mgr = _setup()
    mgr.set_spindle(1.0)
    ok = wait_spindlerate(ctrl, 1.0)
    ctrl.poll()
    assert_true(ok,
                f"set_spindle(1.0): spindle[0]['override'] має бути ≈1.0, є {ctrl.status.spindle[0]['override']:.4f}")


def _test_set_spindle_50_percent():
    """set_spindle(0.5) → status.spindlerate ≈ 0.5."""
    ctrl, mgr = _setup()
    mgr.set_spindle(0.5)
    ok = wait_spindlerate(ctrl, 0.5)
    ctrl.poll()
    assert_true(ok,
                f"set_spindle(0.5): spindle[0]['override'] має бути ≈0.5, є {ctrl.status.spindle[0]['override']:.4f}")


def _test_set_spindle_independent_from_feed_and_rapid():
    """set_spindle не впливає на feedrate і rapidrate."""
    ctrl, mgr = _setup()
    mgr.set_feed(0.8)
    mgr.set_rapid(0.6)
    wait_feedrate(ctrl, 0.8)
    wait_rapidrate(ctrl, 0.6)

    mgr.set_spindle(0.5)
    ok = wait_spindlerate(ctrl, 0.5)
    ctrl.poll()
    assert_true(ok, f"spindle[0]['override'] має бути ≈0.5, є {ctrl.status.spindle[0]['override']:.4f}")

    assert_approx(ctrl.status.feedrate, 0.8, tol=0.01,
                  msg=f"set_spindle не має змінювати feedrate: {ctrl.status.feedrate:.4f}")
    assert_approx(ctrl.status.rapidrate, 0.6, tol=0.01,
                  msg=f"set_spindle не має змінювати rapidrate: {ctrl.status.rapidrate:.4f}")


# ===========================================================================
#  ГРУПА 4: set_linear_speed — python-атрибут
# ===========================================================================

def _test_set_linear_speed_sets_attribute():
    """set_linear_speed(500.0) → ctrl.linear_jog_speed == 500.0."""
    ctrl, mgr = _setup()
    mgr.set_linear_speed(500.0)
    assert_eq(ctrl.linear_jog_speed, 500.0,
              "linear_jog_speed має бути 500.0")


def _test_set_linear_speed_default_value():
    """MachineController ініціалізується з linear_jog_speed=300.0."""
    ctrl = MachineController()
    assert_eq(ctrl.linear_jog_speed, 300.0,
              "Початкове linear_jog_speed має бути 300.0")


def _test_set_linear_speed_does_not_affect_sim_status():
    """
    set_linear_speed — python-атрибут, не надсилає команду в sim.
    status.max_velocity НЕ змінюється після set_linear_speed.
    """
    ctrl, mgr = _setup()
    ctrl.poll()
    max_vel_before = ctrl.status.max_velocity

    mgr.set_linear_speed(999.0)

    ctrl.poll()
    assert_approx(ctrl.status.max_velocity, max_vel_before, tol=0.01,
                  msg="set_linear_speed не має змінювати status.max_velocity")


def _test_set_linear_speed_sequential_updates():
    """Послідовні виклики set_linear_speed → атрибут оновлюється щоразу."""
    ctrl, mgr = _setup()
    for v in (100.0, 300.0, 600.0, 50.0):
        mgr.set_linear_speed(v)
        assert_eq(ctrl.linear_jog_speed, v,
                  f"linear_jog_speed має бути {v}")


# ===========================================================================
#  ГРУПА 5: set_angular_speed — python-атрибут
# ===========================================================================

def _test_set_angular_speed_sets_attribute():
    """set_angular_speed(90.0) → ctrl.angular_jog_speed == 90.0."""
    ctrl, mgr = _setup()
    mgr.set_angular_speed(90.0)
    assert_eq(ctrl.angular_jog_speed, 90.0,
              "angular_jog_speed має бути 90.0")


def _test_set_angular_speed_default_value():
    """MachineController ініціалізується з angular_jog_speed=30.0."""
    ctrl = MachineController()
    assert_eq(ctrl.angular_jog_speed, 30.0,
              "Початкове angular_jog_speed має бути 30.0")


def _test_set_angular_speed_independent_from_linear():
    """set_angular_speed не впливає на linear_jog_speed і навпаки."""
    ctrl, mgr = _setup()
    mgr.set_linear_speed(400.0)
    mgr.set_angular_speed(60.0)
    assert_eq(ctrl.linear_jog_speed, 400.0,
              "linear_jog_speed не має змінитись після set_angular_speed")
    assert_eq(ctrl.angular_jog_speed, 60.0,
              "angular_jog_speed не має змінитись після set_linear_speed")


def _test_set_angular_speed_sequential_updates():
    """Послідовні виклики set_angular_speed → атрибут оновлюється."""
    ctrl, mgr = _setup()
    for v in (15.0, 30.0, 90.0, 180.0, 30.0):
        mgr.set_angular_speed(v)
        assert_eq(ctrl.angular_jog_speed, v,
                  f"angular_jog_speed має бути {v}")


# ===========================================================================
#  ГРУПА 6: set_max_velocity — status.max_velocity
# ===========================================================================

def _test_set_max_velocity_reflects_in_status():
    """
    set_max_velocity(60.0) → command.maxvel(1.0) → status.max_velocity ≈ 1.0.
    Конвертація: maxvel(v / 60.0) → status.max_velocity в одиницях/с.
    """
    ctrl, mgr = _setup()
    INPUT_MM_PER_MIN = 60.0
    EXPECTED_PER_SEC = INPUT_MM_PER_MIN / 60.0   # = 1.0

    mgr.set_max_velocity(INPUT_MM_PER_MIN)
    ok = wait_max_velocity(ctrl, EXPECTED_PER_SEC, tol=0.005)
    ctrl.poll()
    assert_true(ok,
                f"set_max_velocity({INPUT_MM_PER_MIN}): "
                f"status.max_velocity має бути ≈{EXPECTED_PER_SEC:.3f} u/s, "
                f"є {ctrl.status.max_velocity:.6f}")


def _test_set_max_velocity_scaling_correct():
    """
    set_max_velocity(v) → maxvel(v/60) → status.max_velocity = v/60.
    Перевіряємо три різних значення: 30, 120, 300 mm/min.
    """
    ctrl, mgr = _setup()
    for v_min in (30.0, 120.0, 300.0):
        expected = v_min / 60.0
        mgr.set_max_velocity(v_min)
        ok = wait_max_velocity(ctrl, expected, tol=0.005)
        ctrl.poll()
        assert_true(ok,
                    f"set_max_velocity({v_min}): "
                    f"expected {expected:.4f} u/s, "
                    f"є {ctrl.status.max_velocity:.6f}")


def _test_set_max_velocity_exception_does_not_propagate():
    """
    set_max_velocity ловить Exception і не пробрасує.
    Тестуємо через patch.object → підміняємо cnc.set_max_velocity щоб кидав.
    """
    from unittest.mock import patch
    ctrl, mgr = _setup()

    with patch.object(ctrl, "set_max_velocity", side_effect=RuntimeError("sim error")):
        mgr.set_max_velocity(100.0)   # OverridesManager.set_max_velocity ловить


def _test_set_max_velocity_does_not_affect_feed_or_rapid():
    """set_max_velocity не впливає на feedrate і rapidrate."""
    ctrl, mgr = _setup()
    mgr.set_feed(0.75)
    wait_feedrate(ctrl, 0.75)
    mgr.set_rapid(0.5)
    wait_rapidrate(ctrl, 0.5)

    mgr.set_max_velocity(120.0)
    wait_max_velocity(ctrl, 2.0, tol=0.01)
    ctrl.poll()

    assert_approx(ctrl.status.feedrate, 0.75, tol=0.01,
                  msg=f"set_max_velocity не має змінювати feedrate: {ctrl.status.feedrate:.4f}")
    assert_approx(ctrl.status.rapidrate, 0.5, tol=0.01,
                  msg=f"set_max_velocity не має змінювати rapidrate: {ctrl.status.rapidrate:.4f}")


# ===========================================================================
#  ГРУПА 7: наскрізні сценарії
# ===========================================================================

def _test_slider_config_feed_scaling():
    """
    _SLIDER_CONFIG: sld_feed_override divisor=100.0.
    raw=50 → scale=0.5 → set_feed(0.5) → feedrate≈0.5.
    Відтворюємо логіку OverridesUIBinder._handle_change.
    """
    ctrl, mgr = _setup()
    # Знаходимо feed entry в _SLIDER_CONFIG
    feed_cfg = next(
        (e for e in _SLIDER_CONFIG if e[0] == "sld_feed_override"), None
    )
    assert_true(feed_cfg is not None, "sld_feed_override відсутній в _SLIDER_CONFIG")

    _, _, divisor, method_name, _ = feed_cfg
    raw = 50
    scale = raw / divisor   # 50 / 100.0 = 0.5
    getattr(mgr, method_name)(scale)   # mgr.set_feed(0.5)

    ok = wait_feedrate(ctrl, 0.5)
    assert_true(ok, f"_SLIDER_CONFIG feed scaling: feedrate має бути ≈0.5")


def _test_slider_config_linear_speed_scaling():
    """
    _SLIDER_CONFIG: sld_linear_jog_speed divisor=1000.0.
    raw=500 → value=0.5 → set_linear_speed(0.5) → linear_jog_speed==0.5.
    """
    ctrl, mgr = _setup()
    cfg = next(
        (e for e in _SLIDER_CONFIG if e[0] == "sld_linear_jog_speed"), None
    )
    assert_true(cfg is not None, "sld_linear_jog_speed відсутній в _SLIDER_CONFIG")

    _, _, divisor, method_name, _ = cfg
    assert_eq(divisor, _PRECISION_HIGH,
              "sld_linear_jog_speed divisor має бути _PRECISION_HIGH (1000.0)")

    raw = 500
    value = raw / divisor   # 500 / 1000.0 = 0.5
    getattr(mgr, method_name)(value)

    assert_eq(ctrl.linear_jog_speed, 0.5,
              f"_SLIDER_CONFIG linear_speed scaling: linear_jog_speed має бути 0.5")


def _test_slider_config_angular_speed_scaling():
    """
    _SLIDER_CONFIG: sld_angular_jog_speed divisor=100.0, unit contains 'deg'.
    raw=45 → value=0.45 → set_angular_speed(0.45) → angular_jog_speed==0.45.
    """
    ctrl, mgr = _setup()
    cfg = next(
        (e for e in _SLIDER_CONFIG if e[0] == "sld_angular_jog_speed"), None
    )
    assert_true(cfg is not None, "sld_angular_jog_speed відсутній в _SLIDER_CONFIG")

    _, _, divisor, method_name, unit_tpl = cfg
    assert_true(_PRECISION_DEG in unit_tpl,
                f"sld_angular_jog_speed unit_tpl має містити '{_PRECISION_DEG}': {unit_tpl!r}")

    raw = 45
    value = raw / divisor
    getattr(mgr, method_name)(value)

    assert_eq(ctrl.angular_jog_speed, value,
              f"_SLIDER_CONFIG angular_speed scaling: angular_jog_speed має бути {value}")


def _test_all_overrides_independent():
    """
    Встановити всі overrides → перевірити що кожен не впливає на інші.
    Симулює одночасне встановлення всіх слайдерів.
    """
    ctrl, mgr = _setup()

    mgr.set_feed(0.75)
    mgr.set_rapid(0.5)
    mgr.set_spindle(1.25)
    mgr.set_linear_speed(400.0)
    mgr.set_angular_speed(60.0)
    mgr.set_max_velocity(120.0)

    wait_feedrate(ctrl, 0.75)
    wait_rapidrate(ctrl, 0.5)
    wait_spindlerate(ctrl, 1.25)
    wait_max_velocity(ctrl, 2.0, tol=0.01)

    ctrl.poll()
    assert_approx(ctrl.status.feedrate,   0.75, tol=0.01,  msg="feedrate")
    assert_approx(ctrl.status.rapidrate,  0.5,  tol=0.01,  msg="rapidrate")
    assert_approx(ctrl.status.spindle[0]["override"], 1.25, tol=0.01, msg="spindle override")
    assert_eq(ctrl.linear_jog_speed,  400.0, "linear_jog_speed")
    assert_eq(ctrl.angular_jog_speed,  60.0, "angular_jog_speed")
    assert_approx(ctrl.status.max_velocity, 2.0, tol=0.01, msg="max_velocity")


def _test_linear_jog_speed_affects_real_jog_displacement():
    """
    Вища linear_jog_speed → більше переміщення за однаковий час.
    Використовує AxisManager для реального jogu X+.
    linear_jog_speed — python-атрибут, AxisManager читає його напряму з ctrl.
    """
    from logic.managers.axis_manager import AxisManager, _CONTINUOUS_MODE as AXIS_CONT
    ctrl, mgr = _setup_for_motion()
    DURATION = 0.35

    def _jog_and_measure(speed: float) -> float:
        ctrl.angular_jog_speed = 300.0  # фіксуємо щоб не впливало
        mgr.set_linear_speed(speed)

        ctrl.poll()
        pos_before = ctrl.status.actual_position[0]

        ax_mgr = AxisManager(ctrl)
        ax_mgr.start_jog(axis_idx=0, direction=1, mode_text=AXIS_CONT)
        time.sleep(DURATION)
        safe_stop(ctrl)
        wait_motion_stopped(ctrl, timeout=3.0)

        ctrl.poll()
        return ctrl.status.actual_position[0] - pos_before

    delta_slow = _jog_and_measure(60.0)
    # Повертаємось назад
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    wait_motion_stopped(ctrl, timeout=3.0)

    delta_fast = _jog_and_measure(600.0)
    safe_stop(ctrl)

    assert_true(delta_fast > delta_slow * 1.5,
                f"linear_jog_speed=600 має давати >1.5× ніж 60: "
                f"slow={delta_slow:.3f}, fast={delta_fast:.3f}")


def _test_angular_jog_speed_affects_real_jog_displacement():
    """
    Вища angular_jog_speed → більше переміщення joint за однаковий час.
    angular_jog_speed — python-атрибут, JointManager читає з ctrl.
    """
    from logic.managers.joint_manager import JointManager, _CONTINUOUS_MODE as JNT_CONT
    ctrl, mgr = _setup_for_motion()
    DURATION = 0.35

    def _jog_and_measure(speed: float) -> float:
        mgr.set_angular_speed(speed)

        ctrl.poll()
        pos_before = ctrl.status.joint_actual_position[0]

        jnt_mgr = JointManager(ctrl)
        jnt_mgr.start_jog(joint_idx=0, direction=1, mode_text=JNT_CONT)
        time.sleep(DURATION)
        safe_stop(ctrl)
        wait_motion_stopped(ctrl, timeout=3.0)

        ctrl.poll()
        return ctrl.status.joint_actual_position[0] - pos_before

    delta_slow = _jog_and_measure(30.0)
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    wait_motion_stopped(ctrl, timeout=3.0)

    delta_fast = _jog_and_measure(300.0)
    safe_stop(ctrl)

    assert_true(delta_fast > delta_slow * 1.5,
                f"angular_jog_speed=300 має давати >1.5× ніж 30: "
                f"slow={delta_slow:.3f}°, fast={delta_fast:.3f}°")


def _test_reset_to_defaults_after_override_changes():
    """
    Скинути overrides до дефолтних значень і перевірити.
    feedrate=1.0, rapidrate=1.0, spindle=1.0, linear=300, angular=30.
    """
    ctrl, mgr = _setup()

    # Спочатку встановлюємо нестандартні значення
    mgr.set_feed(0.5)
    mgr.set_rapid(0.25)
    mgr.set_spindle(0.75)
    mgr.set_linear_speed(100.0)
    mgr.set_angular_speed(15.0)

    wait_feedrate(ctrl, 0.5)
    wait_rapidrate(ctrl, 0.25)

    # Скидаємо до дефолтів
    mgr.set_feed(1.0)
    mgr.set_rapid(1.0)
    mgr.set_spindle(1.0)
    mgr.set_linear_speed(300.0)
    mgr.set_angular_speed(30.0)

    wait_feedrate(ctrl, 1.0)
    wait_rapidrate(ctrl, 1.0)
    wait_spindlerate(ctrl, 1.0)
    ctrl.poll()

    assert_approx(ctrl.status.feedrate,   1.0, tol=0.01, msg="feedrate reset")
    assert_approx(ctrl.status.rapidrate,  1.0, tol=0.01, msg="rapidrate reset")
    assert_approx(ctrl.status.spindle[0]["override"], 1.0, tol=0.01, msg="spindle override reset")
    assert_eq(ctrl.linear_jog_speed,  300.0, "linear_jog_speed reset")
    assert_eq(ctrl.angular_jog_speed,  30.0, "angular_jog_speed reset")


# ===========================================================================
#  Cleanup
# ===========================================================================

def _cleanup() -> None:
    """Скидаємо overrides до безпечних значень і переводимо в MANUAL."""
    try:
        ctrl = MachineController()
        mgr  = OverridesManager(ctrl)
        mgr.set_feed(1.0)
        mgr.set_rapid(1.0)
        mgr.set_spindle(1.0)
        mgr.set_linear_speed(300.0)
        mgr.set_angular_speed(30.0)
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
        print(f"\n  {_YELLOW}[cleanup] Overrides скинуто, машина в MANUAL.{_RESET}")
    except Exception as exc:
        print(f"\n  {_YELLOW}[cleanup] {exc}{_RESET}")


# ===========================================================================
#  Тестова таблиця
# ===========================================================================

TESTS = [
    # Група 1: set_feed
    ("set_feed: 100% → status.feedrate ≈ 1.0",
     _test_set_feed_100_percent),
    ("set_feed: 50% → status.feedrate ≈ 0.5",
     _test_set_feed_50_percent),
    ("set_feed: 200% → status.feedrate ≈ 2.0",
     _test_set_feed_200_percent),
    ("set_feed: 0% → status.feedrate ≈ 0.0",
     _test_set_feed_zero),
    ("set_feed: послідовні зміни 0.25→0.75→1.5→1.0",
     _test_set_feed_changes_take_effect_sequentially),

    # Група 2: set_rapid
    ("set_rapid: 100% → status.rapidrate ≈ 1.0",
     _test_set_rapid_100_percent),
    ("set_rapid: 50% → status.rapidrate ≈ 0.5",
     _test_set_rapid_50_percent),
    ("set_rapid: 0% → status.rapidrate ≈ 0.0",
     _test_set_rapid_minimum),
    ("set_rapid: незалежний від feedrate",
     _test_set_rapid_independent_from_feed),

    # Група 3: set_spindle
    ("set_spindle: 100% → status.spindlerate ≈ 1.0",
     _test_set_spindle_100_percent),
    ("set_spindle: 50% → status.spindlerate ≈ 0.5",
     _test_set_spindle_50_percent),
    ("set_spindle: незалежний від feed і rapid",
     _test_set_spindle_independent_from_feed_and_rapid),

    # Група 4: set_linear_speed
    ("set_linear_speed: 500.0 → ctrl.linear_jog_speed == 500.0",
     _test_set_linear_speed_sets_attribute),
    ("set_linear_speed: дефолт при ініціалізації == 300.0",
     _test_set_linear_speed_default_value),
    ("set_linear_speed: не змінює status.max_velocity",
     _test_set_linear_speed_does_not_affect_sim_status),
    ("set_linear_speed: послідовні зміни 100→300→600→50",
     _test_set_linear_speed_sequential_updates),

    # Група 5: set_angular_speed
    ("set_angular_speed: 90.0 → ctrl.angular_jog_speed == 90.0",
     _test_set_angular_speed_sets_attribute),
    ("set_angular_speed: дефолт при ініціалізації == 30.0",
     _test_set_angular_speed_default_value),
    ("set_angular_speed: незалежний від linear_jog_speed",
     _test_set_angular_speed_independent_from_linear),
    ("set_angular_speed: послідовні зміни 15→30→90→180→30",
     _test_set_angular_speed_sequential_updates),

    # Група 6: set_max_velocity
    ("set_max_velocity: 60 mm/min → status.max_velocity ≈ 1.0 u/s",
     _test_set_max_velocity_reflects_in_status),
    ("set_max_velocity: scaling v/60 для 30,120,300 mm/min",
     _test_set_max_velocity_scaling_correct),
    ("set_max_velocity: Exception не пробрасується",
     _test_set_max_velocity_exception_does_not_propagate),
    ("set_max_velocity: не впливає на feed і rapid",
     _test_set_max_velocity_does_not_affect_feed_or_rapid),

    # Група 7: наскрізні
    ("workflow: _SLIDER_CONFIG feed scaling raw=50 → feedrate≈0.5",
     _test_slider_config_feed_scaling),
    ("workflow: _SLIDER_CONFIG linear_speed raw=500 → linear_jog_speed=0.5",
     _test_slider_config_linear_speed_scaling),
    ("workflow: _SLIDER_CONFIG angular_speed divisor і 'deg' в unit_tpl",
     _test_slider_config_angular_speed_scaling),
    ("workflow: всі overrides встановлені незалежно",
     _test_all_overrides_independent),
    ("workflow: linear_jog_speed впливає на реальне переміщення осі",
     _test_linear_jog_speed_affects_real_jog_displacement),
    ("workflow: angular_jog_speed впливає на реальне переміщення joint",
     _test_angular_jog_speed_affects_real_jog_displacement),
    ("workflow: reset до дефолтних значень",
     _test_reset_to_defaults_after_override_changes),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: OverridesManager ↔ MachineController ↔ sim{_RESET}")
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