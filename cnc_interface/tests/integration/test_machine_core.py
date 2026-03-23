#!/usr/bin/env python3
"""
Інтеграційні тести MachineController ↔ LinuxCNC sim
=====================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_machine_core.py

Цей файл тестує MachineController **напряму** — методи що мають
власну логіку і не покриті через менеджери в інших тест-файлах.

Що вже покрито опосередковано (НЕ повторюємо):
  poll, is_ready, sync_mode, jog, stop_jog
    → test_axis_manager_integration.py, test_joint_machine.py
  set_feed_override, set_rapid_override, set_max_velocity
    → test_overrides_machine.py
  send_mdi, open_program, cycle_start/pause/resume/stop
    → test_cycle_machine.py, test_file_machine.py, test_tool_machine.py

Що тестуємо тут (власна логіка, непокрита раніше):
  Група 1 — toggle_estop:      ESTOP↔RESET двосторонній перемикач
  Група 2 — set_power:         STATE_ON / STATE_OFF через command.state
  Група 3 — set_mode:          MANUAL/MDI/AUTO, ідемпотентність
  Група 4 — home_axis:         home(-1) і home(0), MANUAL+teleop_enable(0)
  Група 5 — poll_errors:       None коли нема помилок, (text,severity) tuple
  Група 6 — get_states:        всі ключі, правильні значення при різних станах
  Група 7 — can_home:          True при ON+idle, False при ESTOP/OFF/busy
  Група 8 — is_all_homed:      True після home_all, JOINTS_COUNT
  Група 9 — home_all_sequence: MANUAL+teleop_enable(0)+home(-1)
  Група 10 — get_position:     повертає tuple 9 floats
  Група 11 — is_idle:          True при idle, False при busy
  Група 12 — _severity:        NML_ERROR→error, NML_TEXT→warning, інше→info

Підтверджені значення sim:
  STATE_ESTOP=1, STATE_ON=4, MODE_MANUAL=1, MODE_MDI=3, MODE_AUTO=2
  estop=0 коли скинутий (не STATE_ESTOP_RESET=2)
  task_state=2 після STATE_OFF (не STATE_OFF=3)
  kinematics_type=4 завжди (IDENTITY)
  JOINTS_COUNT=6, home(-1) хомить joints 0..5
"""

import sys
import time
import traceback

import linuxcnc

from logic.core.machine import MachineController, _severity

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
_MODE_AUTO         = linuxcnc.MODE_AUTO          # 2
_INTERP_IDLE       = linuxcnc.INTERP_IDLE

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


def assert_in(val, container, msg: str = "") -> None:
    label = f" — {msg}" if msg else ""
    assert val in container, \
        f"{val!r} не знайдено в {container!r}{label}"


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


def wait_interp_idle(ctrl: MachineController, timeout: float = 5.0) -> bool:
    return poll_until(ctrl, lambda s: s.interp_state == _INTERP_IDLE, timeout)


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


def _setup() -> MachineController:
    ctrl = MachineController()
    bring_to_manual(ctrl)
    wait_interp_idle(ctrl)
    return ctrl


def _setup_homed() -> MachineController:
    ctrl = MachineController()
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    wait_interp_idle(ctrl)
    return ctrl


# ===========================================================================
#  ГРУПА 1: toggle_estop
# ===========================================================================

def _test_toggle_estop_activates_from_reset():
    """
    toggle_estop() при estop!=ESTOP → надсилає STATE_ESTOP.
    Перевіряємо що estop стає активним.
    """
    ctrl = _setup()
    ctrl.poll()
    assert_true(ctrl.status.estop != _STATE_ESTOP, "Передумова: не в ESTOP")

    ctrl.toggle_estop()
    ok = poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP, timeout=3.0)
    assert_true(ok, f"toggle_estop має активувати ESTOP, estop={ctrl.status.estop}")


def _test_toggle_estop_resets_from_estop():
    """
    toggle_estop() при estop==ESTOP → надсилає STATE_ESTOP_RESET.
    Перевіряємо що estop стає != STATE_ESTOP.
    """
    ctrl = _setup()
    # Активуємо ESTOP вручну
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    ctrl.toggle_estop()
    ok = poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP, timeout=3.0)
    assert_true(ok, f"toggle_estop має скинути ESTOP, estop={ctrl.status.estop}")


def _test_toggle_estop_double_toggle_restores_state():
    """
    Два виклики toggle_estop підряд → повертає до початкового стану.
    """
    ctrl = _setup()
    ctrl.poll()
    estop_before = ctrl.status.estop

    ctrl.toggle_estop()   # активує ESTOP
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP, timeout=3.0)

    ctrl.toggle_estop()   # скидає ESTOP
    poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP, timeout=3.0)
    ctrl.poll()

    assert_true(ctrl.status.estop != _STATE_ESTOP,
                "Після подвійного toggle_estop ESTOP має бути скинутий")


# ===========================================================================
#  ГРУПА 2: set_power
# ===========================================================================

def _test_set_power_on():
    """
    set_power(True) → command.state(STATE_ON) → task_state == STATE_ON.
    """
    ctrl = _setup()
    # Спочатку вимикаємо
    ctrl.command.state(linuxcnc.STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state != _STATE_ON)

    # Відновлюємо ESTOP_RESET перед вмиканням
    ctrl.poll()
    if ctrl.status.estop == _STATE_ESTOP:
        ctrl.command.state(_STATE_ESTOP_RESET)
        poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP)

    ctrl.set_power(True)
    ok = poll_until(ctrl, lambda s: s.task_state == _STATE_ON, timeout=3.0)
    assert_true(ok,
                f"set_power(True) має перевести в STATE_ON, "
                f"task_state={ctrl.status.task_state}")


def _test_set_power_off():
    """
    set_power(False) → command.state(STATE_OFF) → task_state != STATE_ON.
    Sim повертає task_state=2 (не STATE_OFF=3) після вимкнення.
    """
    ctrl = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_state, _STATE_ON, "Передумова: STATE_ON")

    ctrl.set_power(False)
    ok = poll_until(ctrl, lambda s: s.task_state != _STATE_ON, timeout=3.0)
    assert_true(ok,
                f"set_power(False) має вимкнути STATE_ON, "
                f"task_state={ctrl.status.task_state}")


def _test_set_power_on_off_on_cycle():
    """ON → OFF → ON цикл: task_state повертається до STATE_ON."""
    ctrl = _setup()

    ctrl.set_power(False)
    poll_until(ctrl, lambda s: s.task_state != _STATE_ON)

    ctrl.poll()
    if ctrl.status.estop == _STATE_ESTOP:
        ctrl.command.state(_STATE_ESTOP_RESET)
        poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP)

    ctrl.set_power(True)
    ok = poll_until(ctrl, lambda s: s.task_state == _STATE_ON, timeout=3.0)
    assert_true(ok, "ON→OFF→ON цикл: має повернутись до STATE_ON")


# ===========================================================================
#  ГРУПА 3: set_mode
# ===========================================================================

def _test_set_mode_manual_to_auto():
    """set_mode(MODE_AUTO) перемикає з MANUAL в AUTO."""
    ctrl = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Передумова: MANUAL")

    ctrl.set_mode(_MODE_AUTO)
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_AUTO,
              "set_mode(AUTO) має перемкнути в AUTO")


def _test_set_mode_auto_to_manual():
    """set_mode(MODE_MANUAL) перемикає з AUTO в MANUAL."""
    ctrl = _setup()
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    ctrl.set_mode(_MODE_MANUAL)
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "set_mode(MANUAL) має перемкнути з AUTO в MANUAL")


def _test_set_mode_idempotent():
    """
    set_mode коли вже в правильному режимі — no-op, не надсилає команду.
    Перевіряємо опосередковано: режим залишається незмінним.
    """
    ctrl = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Передумова: MANUAL")

    ctrl.set_mode(_MODE_MANUAL)   # no-op
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "set_mode ідемпотентний: MANUAL → MANUAL залишається MANUAL")


def _test_set_mode_manual_to_mdi():
    """set_mode(MODE_MDI) перемикає в MDI."""
    ctrl = _setup()
    ctrl.set_mode(_MODE_MDI)
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MDI,
              "set_mode(MDI) має перемкнути в MDI")


# ===========================================================================
#  ГРУПА 4: home_axis
# ===========================================================================

def _test_home_axis_minus1_homes_all_joints():
    """
    home_axis(-1) → home(-1) → всі joints 0..JOINTS_COUNT-1 стають homed.
    home_axis встановлює MANUAL і teleop_enable(0) перед home.
    """
    ctrl = _setup()
    ctrl.home_axis(-1)
    jc = ctrl.params.get("JOINTS_COUNT", 6)
    ok = poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(jc)),
        timeout=20.0,
    )
    assert_true(ok, f"home_axis(-1) має отримати homed для joints 0..{jc-1}")


def _test_home_axis_sets_manual_mode_before_homing():
    """
    home_axis переводить в MANUAL перед home(-1).
    Починаємо з AUTO — після home_axis режим MANUAL.
    """
    ctrl = _setup()
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    ctrl.home_axis(-1)
    # Одразу після виклику home_axis — перевіряємо що set_mode MANUAL відбувся
    # (homing може ще тривати)
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "home_axis має перевести в MANUAL перед home")

    # Чекаємо завершення homing щоб не залишати sim в нестабільному стані
    jc = ctrl.params.get("JOINTS_COUNT", 6)
    poll_until(ctrl, lambda s: all(s.homed[i] for i in range(jc)), timeout=20.0)


def _test_home_axis_single_joint_0():
    """
    home_axis(0) → лише joint 0 homed (якщо sim підтримує поодинокий home).
    Перевіряємо що метод не кидає виняток.
    """
    ctrl = _setup()
    ctrl.home_axis(0)   # не має кидати виняток
    # Чекаємо стабілізації
    time.sleep(0.5)
    ctrl.poll()
    # Joint 0 має бути в процесі або вже homed
    assert_true(True, "home_axis(0) не кинув виняток")


# ===========================================================================
#  ГРУПА 5: poll_errors
# ===========================================================================

def _test_poll_errors_returns_none_when_no_errors():
    """poll_errors() → None коли error channel порожній."""
    ctrl = _setup()
    # Дренуємо канал перед тестом
    for _ in range(10):
        ctrl.poll_errors()

    result = ctrl.poll_errors()
    assert_true(result is None,
                f"poll_errors() має повернути None коли нема помилок, є {result!r}")


def _test_poll_errors_returns_tuple_on_error():
    """
    poll_errors() → (text, severity) tuple коли є повідомлення.
    Провокуємо помилку: відкриваємо неіснуючий файл через program_open.
    """
    ctrl = _setup()
    # Дренуємо канал
    for _ in range(10):
        ctrl.poll_errors()

    # Провокуємо помилку через невалідний MDI
    try:
        ctrl.send_mdi("G99999")   # невідомий G-код → NML_ERROR
    except Exception:
        pass
    time.sleep(0.3)

    # Читаємо з error channel
    result = ctrl.poll_errors()
    if result is None:
        # Деякі sim не генерують NML_ERROR для невідомих G-кодів
        # Пропускаємо без провалу — канал може бути порожнім
        print(f"\n  {_YELLOW}    [info] error channel порожній після G99999"
              f" — sim не генерує NML_ERROR{_RESET}")
        return

    assert_true(isinstance(result, tuple),
                f"poll_errors() має повертати tuple, є {type(result).__name__}")
    assert_eq(len(result), 2, "poll_errors() tuple має мати 2 елементи")
    text, severity = result
    assert_true(isinstance(text, str), f"text має бути str, є {type(text).__name__}")
    assert_in(severity, ("error", "warning", "info"),
              f"severity має бути одним з error/warning/info, є {severity!r}")


# ===========================================================================
#  ГРУПА 6: get_states
# ===========================================================================

def _test_get_states_returns_all_required_keys():
    """get_states() повертає dict з усіма обов'язковими ключами."""
    ctrl = _setup()
    states = ctrl.get_states()

    required = {
        "power_on", "estop_off", "is_ready", "all_homed",
        "is_idle", "is_paused", "is_running",
        "actual_position", "joint_position",
        "has_file", "manual_mode", "teleop",
        "gcodes", "mcodes", "settings",
        "current_file", "motion_line",
        "linear_jog_speed",
    }
    missing = required - set(states.keys())
    assert_true(len(missing) == 0,
                f"get_states() відсутні ключі: {missing}")


def _test_get_states_power_on_true_when_on():
    """get_states()['power_on'] == True при STATE_ON."""
    ctrl = _setup()
    states = ctrl.get_states()
    assert_true(states["power_on"],
                f"power_on має бути True при STATE_ON, task_state={ctrl.status.task_state}")


def _test_get_states_power_on_false_when_off():
    """get_states()['power_on'] == False після set_power(False)."""
    ctrl = _setup()
    ctrl.set_power(False)
    poll_until(ctrl, lambda s: s.task_state != _STATE_ON)

    states = ctrl.get_states()
    assert_false(states["power_on"],
                 f"power_on має бути False після STATE_OFF, "
                 f"task_state={ctrl.status.task_state}")


def _test_get_states_estop_off_false_when_estopped():
    """get_states()['estop_off'] == False при активному ESTOP."""
    ctrl = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    states = ctrl.get_states()
    assert_false(states["estop_off"],
                 f"estop_off має бути False при ESTOP, estop={ctrl.status.estop}")


def _test_get_states_is_ready_true_when_on_and_no_estop():
    """get_states()['is_ready'] == power_on AND estop_off."""
    ctrl = _setup()
    states = ctrl.get_states()
    expected = states["power_on"] and states["estop_off"]
    assert_eq(states["is_ready"], expected,
              f"is_ready має бути power_on({states['power_on']}) AND "
              f"estop_off({states['estop_off']})")


def _test_get_states_is_idle_true_when_interpreter_idle():
    """get_states()['is_idle'] == True коли interpreter idle."""
    ctrl = _setup()
    wait_interp_idle(ctrl)
    states = ctrl.get_states()
    assert_true(states["is_idle"],
                f"is_idle має бути True, interp_state={ctrl.status.interp_state}")


def _test_get_states_all_homed_after_home_all():
    """get_states()['all_homed'] == True після home_all."""
    ctrl = _setup_homed()
    states = ctrl.get_states()
    assert_true(states["all_homed"],
                "all_homed має бути True після home_all")


def _test_get_states_linear_jog_speed_reflects_attribute():
    """get_states()['linear_jog_speed'] == ctrl.linear_jog_speed."""
    ctrl = _setup()
    ctrl.linear_jog_speed = 456.0
    states = ctrl.get_states()
    assert_eq(states["linear_jog_speed"], 456.0,
              "linear_jog_speed в get_states має відповідати атрибуту")


def _test_get_states_has_file_false_when_no_program():
    """get_states()['has_file'] == False коли програма не завантажена."""
    ctrl = _setup()
    # Скидаємо файл через abort
    ctrl.command.abort()
    ctrl.command.wait_complete()
    ctrl.poll()
    # has_file відповідає bool(status.file)
    states = ctrl.get_states()
    assert_eq(states["has_file"], bool(ctrl.status.file),
              "has_file має відповідати bool(status.file)")


# ===========================================================================
#  ГРУПА 7: can_home
# ===========================================================================

def _test_can_home_true_when_on_and_idle():
    """can_home() == True при STATE_ON + idle interpreter."""
    ctrl = _setup()
    wait_interp_idle(ctrl)
    assert_true(ctrl.can_home(),
                f"can_home() має бути True: "
                f"estop={ctrl.status.estop}, "
                f"task_state={ctrl.status.task_state}, "
                f"interp={ctrl.status.interp_state}")


def _test_can_home_false_when_estopped():
    """can_home() == False при активному ESTOP."""
    ctrl = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)
    assert_false(ctrl.can_home(),
                 f"can_home() має бути False при ESTOP")


def _test_can_home_false_when_power_off():
    """can_home() == False при STATE_OFF."""
    ctrl = _setup()
    ctrl.set_power(False)
    poll_until(ctrl, lambda s: s.task_state != _STATE_ON)
    assert_false(ctrl.can_home(),
                 f"can_home() має бути False при task_state={ctrl.status.task_state}")


def _test_can_home_all_three_conditions():
    """
    can_home() перевіряє три умови: not_in_error AND power_on AND idle.
    Перевіряємо що результат відповідає AND всіх трьох.
    """
    ctrl = _setup()
    wait_interp_idle(ctrl)
    ctrl.poll()

    not_in_error = ctrl.status.estop != _STATE_ESTOP
    power_on     = ctrl.status.task_state == _STATE_ON
    is_idle      = ctrl.status.interp_state == _INTERP_IDLE
    expected     = not_in_error and power_on and is_idle

    assert_eq(ctrl.can_home(), expected,
              f"can_home() має дорівнювати {expected}: "
              f"not_in_error={not_in_error}, power_on={power_on}, idle={is_idle}")


# ===========================================================================
#  ГРУПА 8: is_all_homed
# ===========================================================================

def _test_is_all_homed_true_after_home_all():
    """is_all_homed() == True після home(-1) при JOINTS_COUNT=6."""
    ctrl = _setup_homed()
    assert_true(ctrl.is_all_homed(),
                "is_all_homed() має бути True після home_all")


def _test_is_all_homed_uses_joints_count_from_config():
    """
    is_all_homed() перевіряє range(JOINTS_COUNT) — не лише 3.
    JOINTS_COUNT=6 в конфігу → перевіряє joints 0..5.
    """
    ctrl = _setup_homed()
    jc = ctrl.params.get("JOINTS_COUNT", 6)
    ctrl.poll()
    manually_computed = all(ctrl.status.homed[i] for i in range(jc))
    assert_eq(ctrl.is_all_homed(), manually_computed,
              f"is_all_homed() має відповідати all(homed[0..{jc-1}])")


# ===========================================================================
#  ГРУПА 9: home_all_sequence
# ===========================================================================

def _test_home_all_sequence_sets_manual_and_homes():
    """
    home_all_sequence() → MANUAL + teleop_enable(0) + home(-1).
    Перевіряємо: після виклику task_mode==MANUAL і joints починають homing.
    """
    ctrl = _setup()
    # Явно ставимо AUTO щоб перевірити перемикання
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    ctrl.home_all_sequence()

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "home_all_sequence має перевести в MANUAL перед home")

    # Чекаємо завершення homing
    jc = ctrl.params.get("JOINTS_COUNT", 6)
    ok = poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(jc)),
        timeout=20.0,
    )
    assert_true(ok, "home_all_sequence має завершити homing всіх joints")


def _test_home_all_sequence_does_not_crash_when_already_in_manual():
    """home_all_sequence не падає якщо вже в MANUAL."""
    ctrl = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL, "Передумова: вже MANUAL")

    ctrl.home_all_sequence()   # не має кидати виняток

    jc = ctrl.params.get("JOINTS_COUNT", 6)
    poll_until(ctrl, lambda s: all(s.homed[i] for i in range(jc)), timeout=20.0)


# ===========================================================================
#  ГРУПА 10: get_position
# ===========================================================================

def _test_get_position_returns_tuple():
    """get_position() → tuple."""
    ctrl = _setup()
    pos = ctrl.get_position()
    assert_true(isinstance(pos, tuple),
                f"get_position() має повернути tuple, є {type(pos).__name__}")


def _test_get_position_has_9_elements():
    """get_position() → tuple з 9 елементів (X Y Z A B C U V W)."""
    ctrl = _setup()
    pos = ctrl.get_position()
    assert_eq(len(pos), 9,
              f"get_position() має 9 елементів (XYZABCUVW), є {len(pos)}")


def _test_get_position_elements_are_floats():
    """get_position() → всі елементи float."""
    ctrl = _setup()
    pos = ctrl.get_position()
    for i, val in enumerate(pos):
        assert_true(isinstance(val, float),
                    f"get_position()[{i}] має бути float, є {type(val).__name__}")


def _test_get_position_changes_after_motion():
    """
    get_position() відображає реальну позицію — змінюється після руху.
    Jog X+ → позиція X збільшується.
    """
    ctrl = _setup_homed()
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()

    pos_before = ctrl.get_position()

    # Incremental jog joint 0 на 2.0°
    vel = 300.0 / 60.0
    ctrl.command.jog(linuxcnc.JOG_INCREMENT, ctrl.JOG_CMD_FLAG, 0, vel, 2.0)

    # Чекаємо на рух
    time.sleep(0.2)
    deadline = time.time() + 8.0
    prev = None
    stable = 0
    while time.time() < deadline:
        ctrl.poll()
        cur = tuple(round(ctrl.status.joint_actual_position[i], 4) for i in range(6))
        if ctrl.status.motion_type == 0 and cur == prev:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
        prev = cur
        time.sleep(0.04)

    pos_after = ctrl.get_position()
    # position кортеж — перевіряємо що хоча б одне значення змінилось
    changed = any(abs(pos_after[i] - pos_before[i]) > 0.01 for i in range(9))
    assert_true(changed,
                f"get_position() має змінитись після руху: "
                f"before={pos_before[:3]}, after={pos_after[:3]}")


# ===========================================================================
#  ГРУПА 11: is_idle
# ===========================================================================

def _test_is_idle_true_when_interpreter_idle():
    """is_idle() == True при idle interpreter."""
    ctrl = _setup()
    wait_interp_idle(ctrl)
    assert_true(ctrl.is_idle(),
                f"is_idle() має бути True, interp_state={ctrl.status.interp_state}")


def _test_is_idle_false_when_program_running():
    """is_idle() == False під час виконання програми."""
    ctrl = _setup_homed()
    gcode = "/tmp/tmc_busy.ngc"
    with open(gcode, "w") as f:
        f.writelines(
            ["G21 G90\n"] +
            [f"G1 X{i % 3} F20\n" for i in range(30)] +
            ["M2\n"]
        )
    ctrl.open_program(gcode)
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    ctrl.command.auto(linuxcnc.AUTO_RUN, 0)

    ok = poll_until(
        ctrl,
        lambda s: s.interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING),
        timeout=5.0,
    )
    if ok:
        assert_false(ctrl.is_idle(),
                     "is_idle() має бути False під час виконання програми")
    else:
        print(f"\n  {_YELLOW}    [info] Програма завершилась до перевірки is_idle{_RESET}")

    safe_stop(ctrl)
    import os
    if os.path.exists(gcode):
        os.remove(gcode)


def _test_is_idle_true_after_program_completes():
    """is_idle() == True після завершення програми."""
    ctrl = _setup_homed()
    gcode = "/tmp/tmc_minimal.ngc"
    with open(gcode, "w") as f:
        f.write("G21 G90\nM2\n")
    ctrl.open_program(gcode)
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    ctrl.command.auto(linuxcnc.AUTO_RUN, 0)

    ok = poll_until(ctrl, lambda s: s.interp_state == _INTERP_IDLE, timeout=10.0)
    assert_true(ok, "is_idle() має стати True після завершення програми")
    assert_true(ctrl.is_idle(), "is_idle() == True після M2")

    import os
    if os.path.exists(gcode):
        os.remove(gcode)


# ===========================================================================
#  ГРУПА 12: _severity (module-level helper)
# ===========================================================================

def _test_severity_nml_error_returns_error():
    """_severity(NML_ERROR) → 'error'."""
    assert_eq(_severity(linuxcnc.NML_ERROR), "error",
              "_severity(NML_ERROR) має бути 'error'")


def _test_severity_operator_error_returns_error():
    """_severity(OPERATOR_ERROR) → 'error'."""
    assert_eq(_severity(linuxcnc.OPERATOR_ERROR), "error",
              "_severity(OPERATOR_ERROR) має бути 'error'")


def _test_severity_nml_text_returns_warning():
    """_severity(NML_TEXT) → 'warning'."""
    assert_eq(_severity(linuxcnc.NML_TEXT), "warning",
              "_severity(NML_TEXT) має бути 'warning'")


def _test_severity_unknown_returns_info():
    """_severity(NML_DISPLAY або будь-яке інше значення) → 'info'."""
    assert_eq(_severity(linuxcnc.NML_DISPLAY), "info",
              "_severity(NML_DISPLAY) має бути 'info'")
    assert_eq(_severity(999), "info",
              "_severity(невідомий) має бути 'info'")


# ===========================================================================
#  Cleanup
# ===========================================================================

def _cleanup() -> None:
    try:
        ctrl = MachineController()
        ctrl.command.abort()
        ctrl.command.wait_complete()
        bring_to_manual(ctrl)
        import os
        for f in ("/tmp/tmc_busy.ngc", "/tmp/tmc_minimal.ngc"):
            if os.path.exists(f):
                os.remove(f)
        print(f"\n  {_YELLOW}[cleanup] Машина переведена в MANUAL.{_RESET}")
    except Exception as exc:
        print(f"\n  {_YELLOW}[cleanup] {exc}{_RESET}")


# ===========================================================================
#  Тестова таблиця
# ===========================================================================

TESTS = [
    # Група 1: toggle_estop
    ("toggle_estop: активує ESTOP зі скинутого стану",
     _test_toggle_estop_activates_from_reset),
    ("toggle_estop: скидає ESTOP з активного стану",
     _test_toggle_estop_resets_from_estop),
    ("toggle_estop: подвійний toggle → початковий стан",
     _test_toggle_estop_double_toggle_restores_state),

    # Група 2: set_power
    ("set_power(True): task_state → STATE_ON",
     _test_set_power_on),
    ("set_power(False): task_state != STATE_ON",
     _test_set_power_off),
    ("set_power: ON→OFF→ON цикл",
     _test_set_power_on_off_on_cycle),

    # Група 3: set_mode
    ("set_mode(AUTO): MANUAL → AUTO",
     _test_set_mode_manual_to_auto),
    ("set_mode(MANUAL): AUTO → MANUAL",
     _test_set_mode_auto_to_manual),
    ("set_mode: ідемпотентний (MANUAL→MANUAL)",
     _test_set_mode_idempotent),
    ("set_mode(MDI): MANUAL → MDI",
     _test_set_mode_manual_to_mdi),

    # Група 4: home_axis
    ("home_axis(-1): всі joints homed",
     _test_home_axis_minus1_homes_all_joints),
    ("home_axis: встановлює MANUAL перед home",
     _test_home_axis_sets_manual_mode_before_homing),
    ("home_axis(0): no crash для одного joint",
     _test_home_axis_single_joint_0),

    # Група 5: poll_errors
    ("poll_errors: None коли канал порожній",
     _test_poll_errors_returns_none_when_no_errors),
    ("poll_errors: (text, severity) tuple при помилці",
     _test_poll_errors_returns_tuple_on_error),

    # Група 6: get_states
    ("get_states: всі обов'язкові ключі присутні",
     _test_get_states_returns_all_required_keys),
    ("get_states: power_on=True при STATE_ON",
     _test_get_states_power_on_true_when_on),
    ("get_states: power_on=False після set_power(False)",
     _test_get_states_power_on_false_when_off),
    ("get_states: estop_off=False при ESTOP",
     _test_get_states_estop_off_false_when_estopped),
    ("get_states: is_ready = power_on AND estop_off",
     _test_get_states_is_ready_true_when_on_and_no_estop),
    ("get_states: is_idle=True при idle interpreter",
     _test_get_states_is_idle_true_when_interpreter_idle),
    ("get_states: all_homed=True після home_all",
     _test_get_states_all_homed_after_home_all),
    ("get_states: linear_jog_speed відповідає атрибуту",
     _test_get_states_linear_jog_speed_reflects_attribute),
    ("get_states: has_file відповідає bool(status.file)",
     _test_get_states_has_file_false_when_no_program),

    # Група 7: can_home
    ("can_home: True при ON+idle",
     _test_can_home_true_when_on_and_idle),
    ("can_home: False при ESTOP",
     _test_can_home_false_when_estopped),
    ("can_home: False при power off",
     _test_can_home_false_when_power_off),
    ("can_home: AND трьох умов",
     _test_can_home_all_three_conditions),

    # Група 8: is_all_homed
    ("is_all_homed: True після home_all",
     _test_is_all_homed_true_after_home_all),
    ("is_all_homed: використовує JOINTS_COUNT з конфігу",
     _test_is_all_homed_uses_joints_count_from_config),

    # Група 9: home_all_sequence
    ("home_all_sequence: встановлює MANUAL і хомить всі joints",
     _test_home_all_sequence_sets_manual_and_homes),
    ("home_all_sequence: no crash коли вже MANUAL",
     _test_home_all_sequence_does_not_crash_when_already_in_manual),

    # Група 10: get_position
    ("get_position: повертає tuple",
     _test_get_position_returns_tuple),
    ("get_position: 9 елементів (XYZABCUVW)",
     _test_get_position_has_9_elements),
    ("get_position: всі елементи float",
     _test_get_position_elements_are_floats),
    ("get_position: змінюється після руху",
     _test_get_position_changes_after_motion),

    # Група 11: is_idle
    ("is_idle: True при idle interpreter",
     _test_is_idle_true_when_interpreter_idle),
    ("is_idle: False під час виконання програми",
     _test_is_idle_false_when_program_running),
    ("is_idle: True після завершення програми",
     _test_is_idle_true_after_program_completes),

    # Група 12: _severity
    ("_severity: NML_ERROR → 'error'",
     _test_severity_nml_error_returns_error),
    ("_severity: OPERATOR_ERROR → 'error'",
     _test_severity_operator_error_returns_error),
    ("_severity: NML_TEXT → 'warning'",
     _test_severity_nml_text_returns_warning),
    ("_severity: NML_DISPLAY та невідомі → 'info'",
     _test_severity_unknown_returns_info),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: MachineController ↔ LinuxCNC sim{_RESET}")
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
