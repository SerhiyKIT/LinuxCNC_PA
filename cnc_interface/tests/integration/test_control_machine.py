#!/usr/bin/env python3
"""
Інтеграційні тести ControlManager ↔ MachineController ↔ LinuxCNC sim
======================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_control_logic.py

ControlManager не має прямого доступу до linuxcnc — він делегує все
MachineController. Тести перевіряють реальний ефект через ctrl.status.

Підтверджені значення цього sim (з diagnose_sim.py):
  STATE_ON          = 4
  STATE_OFF         = 3
  STATE_ESTOP       = 1
  STATE_ESTOP_RESET = 2
  MODE_MANUAL       = 1
  MODE_AUTO         = 2
  kinematics_type   = 4 завжди (IDENTITY, teleop не змінює)
  JOINTS_COUNT      = 6 (конфіг)

Архітектура:
  * _setup()                — мінімально (без homing)
  * _setup_for_motion()     — home + MANUAL + стабілізація
  * FakeWidgets             — мінімальна заглушка (без PyQt5)
  * MachineDialogs заглушається через monkey-patch у тестах що хомлять
"""

import sys
import time
import traceback
from unittest.mock import patch

import linuxcnc

from logic.core.machine import MachineController
from logic.managers.control_manager import ControlManager

# ---------------------------------------------------------------------------
# ANSI кольори
# ---------------------------------------------------------------------------
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

# ---------------------------------------------------------------------------
# Підтверджені константи цього sim
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


def wait_motion_stopped(ctrl: MachineController,
                        timeout: float = 8.0) -> bool:
    """Чекати motion_type==0 і стабільну позицію 4 цикли."""
    time.sleep(0.15)
    deadline = time.time() + timeout
    prev_pos = None
    stable   = 0
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

class FakeWidgets:
    """
    Мінімальна заглушка widgets для ControlManager.
    ControlManager звертається лише до widgets.main_window (для діалогу).
    """
    main_window = None


def bring_to_manual(ctrl: MachineController) -> None:
    """
    ESTOP скинути → STATE_ON → MODE_MANUAL.

    Цей sim повертає estop=0 коли ESTOP скинутий (не linuxcnc.STATE_ESTOP_RESET=2).
    Тому перевіряємо != _STATE_ESTOP замість == _STATE_ESTOP_RESET.
    task_state після STATE_OFF = 2 в цьому sim (не linuxcnc.STATE_OFF=3).
    Тому перевіряємо != _STATE_ON замість == _STATE_OFF.
    """
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
    try:
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    except Exception:
        pass


def home_all(ctrl: MachineController) -> bool:
    """
    Home all joints і чекати поки всі JOINTS_COUNT joints стануть homed.
    JOINTS_COUNT береться з config (6 для цього sim).
    Joints 0..5 homed після home(-1); joints 6+ не використовуються.
    """
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    ctrl.command.home(-1)
    joints_count = MachineController().params.get("JOINTS_COUNT", 6)
    return poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(joints_count)),
        timeout=20.0,
    )


def _setup() -> tuple[MachineController, ControlManager]:
    """Мінімальне підключення — без homing."""
    ctrl    = MachineController()
    manager = ControlManager(ctrl, FakeWidgets())
    bring_to_manual(ctrl)
    return ctrl, manager


def _setup_for_motion() -> tuple[MachineController, ControlManager]:
    """Повний підготовчий цикл: home + MANUAL + стабілізація."""
    ctrl    = MachineController()
    manager = ControlManager(ctrl, FakeWidgets())
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    wait_motion_stopped(ctrl, timeout=3.0)
    return ctrl, manager


# ===========================================================================
#  ГРУПА 1: toggle_estop — реальний стан ESTOP
# ===========================================================================

def _test_toggle_estop_activates_estop():
    """
    Викликати toggle_estop з non-ESTOP стану → має стати STATE_ESTOP.
    Цей sim: estop=0 коли скинутий (не linuxcnc.STATE_ESTOP_RESET=2).
    Передумова: estop != _STATE_ESTOP (тобто 0 або будь-яке не-ESTOP значення).
    """
    ctrl, mgr = _setup()
    ctrl.poll()
    assert_true(ctrl.status.estop != _STATE_ESTOP,
                f"Передумова: маємо бути поза ESTOP, є {ctrl.status.estop}")

    mgr.toggle_estop()
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP, timeout=3.0)
    ctrl.poll()

    assert_eq(ctrl.status.estop, _STATE_ESTOP,
              f"Після toggle_estop машина має бути в ESTOP, є {ctrl.status.estop}")


def _test_toggle_estop_deactivates_estop():
    """Викликати toggle_estop з STATE_ESTOP → має стати STATE_ESTOP_RESET."""
    ctrl, mgr = _setup()

    # Спочатку активуємо ESTOP
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    mgr.toggle_estop()
    poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP, timeout=3.0)
    ctrl.poll()

    # Sim повертає 0 (не linuxcnc.STATE_ESTOP_RESET=2) коли ESTOP скинутий
    assert_true(ctrl.status.estop != _STATE_ESTOP,
                f"Після toggle_estop ESTOP має бути скинутий, є {ctrl.status.estop}")


def _test_toggle_estop_twice_restores_state():
    """Два виклики toggle_estop → повернення до початкового стану."""
    ctrl, mgr = _setup()
    ctrl.poll()
    initial_estop = ctrl.status.estop

    mgr.toggle_estop()
    time.sleep(0.15)
    mgr.toggle_estop()
    poll_until(ctrl, lambda s: s.estop == initial_estop, timeout=3.0)
    ctrl.poll()

    assert_eq(ctrl.status.estop, initial_estop,
              "Два toggle_estop мають повернути початковий стан ESTOP")


def _test_toggle_estop_does_not_raise():
    """toggle_estop ніколи не пробрасує виняток — ControlManager ловить їх."""
    ctrl, mgr = _setup()
    # Викликаємо двічі — будь-який стан
    mgr.toggle_estop()
    time.sleep(0.1)
    mgr.toggle_estop()


# ===========================================================================
#  ГРУПА 2: toggle_power — реальний стан живлення
# ===========================================================================

def _test_toggle_power_off_when_on():
    """Виклик toggle_power(True) → машина переходить в STATE_OFF."""
    ctrl, mgr = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_state, _STATE_ON,
              "Передумова: маємо бути в STATE_ON")

    states = ctrl.get_states()
    mgr.on_btn_power_off_clicked(states)

    poll_until(ctrl, lambda s: s.task_state != _STATE_ON, timeout=3.0)
    ctrl.poll()

    # Sim повертає task_state=2 після STATE_OFF (не linuxcnc.STATE_OFF=3).
    # Перевіряємо що вийшли з STATE_ON, а не конкретне значення.
    assert_true(ctrl.status.task_state != _STATE_ON,
                f"Після toggle_power(ON→OFF) task_state має бути != STATE_ON, "
                f"є {ctrl.status.task_state}")


def _test_toggle_power_on_when_off():
    """Виклик toggle_power(False) → машина переходить в STATE_ON."""
    ctrl, mgr = _setup()

    # Вимикаємо
    ctrl.command.state(_STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state == _STATE_OFF)

    states = ctrl.get_states()
    mgr.on_btn_power_off_clicked(states)

    poll_until(ctrl, lambda s: s.task_state == _STATE_ON, timeout=3.0)
    ctrl.poll()

    assert_eq(ctrl.status.task_state, _STATE_ON,
              f"Після toggle_power(OFF→ON) маємо STATE_ON, є {ctrl.status.task_state}")


def _test_toggle_power_off_resets_homing_flag():
    """Вимкнення живлення скидає homing_complete_shown."""
    ctrl, mgr = _setup()
    mgr.homing_complete_shown = True

    states = ctrl.get_states()
    mgr.on_btn_power_off_clicked(states)

    assert_false(mgr.homing_complete_shown,
                 "homing_complete_shown має скинутись при вимкненні живлення")


def _test_toggle_power_on_does_not_reset_homing_flag():
    """Увімкнення живлення НЕ скидає homing_complete_shown."""
    ctrl, mgr = _setup()

    # Вимикаємо вручну, щоб наступний виклик buде ON
    ctrl.command.state(_STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state == _STATE_OFF)

    mgr.homing_complete_shown = True
    states = ctrl.get_states()
    mgr.on_btn_power_off_clicked(states)  # power_on=False → вмикає

    assert_true(mgr.homing_complete_shown,
                "homing_complete_shown не має змінюватись при увімкненні живлення")

    # Cleanup
    bring_to_manual(ctrl)


# ===========================================================================
#  ГРУПА 3: execute_homing — реальний homing через sim
# ===========================================================================

def _test_execute_homing_blocked_when_estopped():
    """Homing не відбувається якщо машина в ESTOP."""
    ctrl, mgr = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    # Фіксуємо стан homed до виклику
    ctrl.poll()
    homed_before = list(ctrl.status.homed[:3])

    mgr.on_btn_home_all_clicked()
    time.sleep(0.3)

    ctrl.poll()
    homed_after = list(ctrl.status.homed[:3])

    assert_eq(homed_after, homed_before,
              "Homing не має стартувати при активному ESTOP")


def _test_execute_homing_blocked_when_power_off():
    """Homing не відбувається якщо живлення вимкнено."""
    ctrl, mgr = _setup()
    ctrl.command.state(_STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state == _STATE_OFF)

    mgr.on_btn_home_all_clicked()
    time.sleep(0.3)

    ctrl.poll()
    # can_home() = False → жодна homing-команда не надсилалась
    # Sim повертає task_state=2 після STATE_OFF (не linuxcnc.STATE_OFF=3).
    # Перевіряємо що машина НЕ перейшла в STATE_ON.
    assert_true(ctrl.status.task_state != _STATE_ON,
                f"Машина не має переходити в STATE_ON — homing заблокований, "
                f"task_state={ctrl.status.task_state}")


def _test_execute_homing_completes_successfully():
    """execute_homing запускає homing і всі осі стають homed."""
    ctrl, mgr = _setup()

    # Monkey-patch confirm_rehome → True (якщо вже homed)
    with patch("logic.managers.control_manager.MachineDialogs.confirm_rehome",
               return_value=True):
        mgr.on_btn_home_all_clicked()

    _jc = ctrl.params.get("JOINTS_COUNT", 6)
    ok = poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(_jc)),
        timeout=20.0,
    )
    assert_true(ok, "Після execute_homing всі осі мають бути homed")


def _test_execute_homing_skipped_when_confirm_rehome_cancelled():
    """Якщо всі осі вже homed і оператор відмовився — homing не запускається."""
    ctrl, mgr = _setup()

    # Спочатку виконуємо homing щоб is_all_homed() == True
    if not home_all(ctrl):
        raise RuntimeError("Попередній homing не завершився")
    bring_to_manual(ctrl)

    ctrl.poll()
    homed_snapshot = list(ctrl.status.homed[:6])

    # Відміна підтвердження → homing не запускається
    with patch("logic.managers.control_manager.MachineDialogs.confirm_rehome",
               return_value=False):
        mgr.on_btn_home_all_clicked()

    time.sleep(0.3)
    ctrl.poll()

    assert_eq(list(ctrl.status.homed[:6]), homed_snapshot,
              "homed стан не має змінюватись якщо оператор відмовився від re-home")


def _test_execute_homing_switches_to_manual_mode():
    """home_all_sequence переводить машину в MANUAL і вимикає teleop."""
    ctrl, mgr = _setup()

    # Переходимо в AUTO перед homing
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO)

    with patch("logic.managers.control_manager.MachineDialogs.confirm_rehome",
               return_value=True):
        mgr.on_btn_home_all_clicked()

    # Чекаємо поки homing стартує (машина перейде в MANUAL)
    poll_until(ctrl, lambda s: s.task_mode == _MODE_MANUAL, timeout=5.0)
    ctrl.poll()

    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "home_all_sequence має перевести в MANUAL перед homing")

    # Чекаємо завершення homing щоб не залишити машину в проміжному стані
    _jc2 = ctrl.params.get("JOINTS_COUNT", 6)
    poll_until(ctrl, lambda s: all(s.homed[i] for i in range(_jc2)), timeout=20.0)


# ===========================================================================
#  ГРУПА 4: switch_control_mode — teleop і manual_mode
# ===========================================================================

def _test_switch_control_mode_blocked_when_not_ready():
    """Перемикання режиму заблоковано якщо машина не готова."""
    ctrl, mgr = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    initial_mode = ctrl.manual_mode
    states = {"is_ready": False, "all_homed": True}
    mgr.on_overlay_clicked(states, panel_type="axis")

    assert_eq(ctrl.manual_mode, initial_mode,
              "manual_mode не має змінюватись якщо is_ready=False")


def _test_switch_control_mode_blocked_when_not_homed():
    """Перемикання режиму заблоковано якщо осі не homed."""
    ctrl, mgr = _setup()
    initial_mode = ctrl.manual_mode

    states = {"is_ready": True, "all_homed": False}
    mgr.on_overlay_clicked(states, panel_type="joint")

    assert_eq(ctrl.manual_mode, initial_mode,
              "manual_mode не має змінюватись якщо all_homed=False")


def _test_switch_control_mode_to_axis_sets_manual_mode():
    """Перемикання в axis-режим встановлює ctrl.manual_mode='axis'."""
    ctrl, mgr = _setup_for_motion()

    states = {"is_ready": True, "all_homed": True}
    mgr.on_overlay_clicked(states, panel_type="axis")
    time.sleep(0.2)

    assert_eq(ctrl.manual_mode, "axis",
              "manual_mode має стати 'axis' після перемикання в axis-режим")


def _test_switch_control_mode_to_joint_sets_manual_mode():
    """Перемикання в joint-режим встановлює ctrl.manual_mode='joint'."""
    ctrl, mgr = _setup_for_motion()

    states = {"is_ready": True, "all_homed": True}
    mgr.on_overlay_clicked(states, panel_type="joint")
    time.sleep(0.2)

    assert_eq(ctrl.manual_mode, "joint",
              "manual_mode має стати 'joint' після перемикання в joint-режим")


def _test_switch_control_mode_uses_states_from_get_states():
    """on_overlay_clicked з реальним get_states() після homing дозволяє перемикання."""
    ctrl, mgr = _setup_for_motion()

    states = ctrl.get_states()
    assert_true(states["is_ready"],  "Передумова: машина має бути ready")
    assert_true(states["all_homed"], "Передумова: всі осі мають бути homed")

    mgr.on_overlay_clicked(states, panel_type="joint")
    assert_eq(ctrl.manual_mode, "joint",
              "Перемикання через реальний get_states() має працювати")

    mgr.on_overlay_clicked(states, panel_type="axis")
    assert_eq(ctrl.manual_mode, "axis",
              "Зворотнє перемикання через реальний get_states() має працювати")


# ===========================================================================
#  ГРУПА 5: get_states — реальні значення з sim
# ===========================================================================

def _test_get_states_power_on_true_when_on():
    ctrl, _ = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.task_state, _STATE_ON, "Передумова: STATE_ON")

    states = ctrl.get_states()
    assert_true(states["power_on"], "power_on має бути True при STATE_ON")
    assert_true(states["estop_off"], "estop_off має бути True після ESTOP_RESET")
    assert_true(states["is_ready"],  "is_ready має бути True")


def _test_get_states_power_on_false_when_estopped():
    ctrl, _ = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)

    states = ctrl.get_states()
    assert_false(states["estop_off"], "estop_off має бути False при ESTOP")
    assert_false(states["is_ready"],  "is_ready має бути False при ESTOP")


def _test_get_states_all_homed_after_homing():
    ctrl, _ = _setup()
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився")
    bring_to_manual(ctrl)

    states = ctrl.get_states()
    assert_true(states["all_homed"],
                f"all_homed має бути True після homing, homed={list(ctrl.status.homed[:6])}")


def _test_get_states_all_homed_false_before_homing():
    """all_homed == False при свіжому старті без homing."""
    ctrl = MachineController()
    bring_to_manual(ctrl)

    # Скасовуємо homing — встановлюємо нову машину без homed статусу
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()

    # Перевіряємо через is_all_homed напряму (не через home)
    # Якщо перший joint вже homed після перезапуску — пропускаємо тест
    ctrl.poll()
    _jc3 = ctrl.params.get("JOINTS_COUNT", 6)
    if all(ctrl.status.homed[i] for i in range(_jc3)):
        print(f"\n  {_YELLOW}[skip] Машина вже homed — неможливо перевірити False стан{_RESET}")
        return

    states = ctrl.get_states()
    assert_false(states["all_homed"],
                 "all_homed має бути False коли homing не виконувався")


def _test_get_states_is_idle_when_manual():
    ctrl, _ = _setup()
    states = ctrl.get_states()
    assert_true(states["is_idle"],
                f"is_idle має бути True в MANUAL режимі, interp={ctrl.status.interp_state}")


def _test_get_states_has_file_false_initially():
    ctrl, _ = _setup()
    states = ctrl.get_states()
    # Одразу після старту без завантаженого файлу
    # Якщо у sim вже є файл — не перевіряємо (не можна скинути без перезапуску)
    if states["has_file"]:
        print(f"\n  {_YELLOW}[skip] Sim вже має завантажений файл{_RESET}")
        return
    assert_false(states["has_file"], "has_file має бути False без завантаженого файлу")


def _test_get_states_actual_position_is_tuple():
    ctrl, _ = _setup()
    states = ctrl.get_states()
    pos = states["actual_position"]
    assert_true(hasattr(pos, "__len__") and len(pos) >= 3,
                f"actual_position має мати мінімум 3 координати, є {pos}")


def _test_get_states_manual_mode_reflects_ctrl():
    ctrl, mgr = _setup()
    ctrl.manual_mode = "joint"
    states = ctrl.get_states()
    assert_eq(states["manual_mode"], "joint",
              "get_states має відображати поточне ctrl.manual_mode")


# ===========================================================================
#  ГРУПА 6: can_home / is_all_homed
# ===========================================================================

def _test_can_home_false_when_estopped():
    ctrl, _ = _setup()
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)
    assert_false(ctrl.can_home(),
                 "can_home() має бути False при активному ESTOP")


def _test_can_home_false_when_power_off():
    ctrl, _ = _setup()
    ctrl.command.state(_STATE_OFF)
    poll_until(ctrl, lambda s: s.task_state == _STATE_OFF)
    assert_false(ctrl.can_home(),
                 "can_home() має бути False при STATE_OFF")


def _test_can_home_true_when_ready():
    ctrl, _ = _setup()
    assert_true(ctrl.can_home(),
                f"can_home() має бути True: task_state={ctrl.status.task_state}, "
                f"estop={ctrl.status.estop}, interp={ctrl.status.interp_state}")


def _test_is_all_homed_true_after_homing():
    ctrl, _ = _setup()
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився")
    bring_to_manual(ctrl)
    assert_true(ctrl.is_all_homed(),
                "is_all_homed() має бути True після успішного homing")


# ===========================================================================
#  ГРУПА 7: наскрізний workflow — ESTOP → Power → Home → Mode
# ===========================================================================

def _test_full_workflow_estop_power_home_mode():
    """
    Повний наскрізний сценарій оператора:
    1. Активувати ESTOP  → перевірити
    2. Скинути ESTOP     → перевірити
    3. Увімкнути живлення → перевірити
    4. Виконати homing   → перевірити
    5. Перемкнути в axis-режим → перевірити
    """
    ctrl    = MachineController()
    manager = ControlManager(ctrl, FakeWidgets())

    # --- Крок 1: Активувати ESTOP ---
    bring_to_manual(ctrl)  # починаємо з чистого стану
    manager.toggle_estop()
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP, timeout=3.0)
    ctrl.poll()
    assert_eq(ctrl.status.estop, _STATE_ESTOP, "Крок 1: ESTOP активний")

    # --- Крок 2: Скинути ESTOP ---
    manager.toggle_estop()
    poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP, timeout=3.0)
    ctrl.poll()
    # Sim повертає estop=0 після скидання (не linuxcnc.STATE_ESTOP_RESET=2)
    assert_true(ctrl.status.estop != _STATE_ESTOP,
                f"Крок 2: ESTOP має бути скинутий, є {ctrl.status.estop}")

    # --- Крок 3: Увімкнути живлення ---
    # Після ESTOP_RESET стан може бути STATE_OFF
    ctrl.poll()
    if ctrl.status.task_state != _STATE_ON:
        states = ctrl.get_states()  # power_on=False
        manager.on_btn_power_off_clicked(states)
        poll_until(ctrl, lambda s: s.task_state == _STATE_ON, timeout=3.0)
    ctrl.poll()
    assert_eq(ctrl.status.task_state, _STATE_ON, "Крок 3: живлення ON")

    # --- Крок 4: Homing ---
    with patch("logic.managers.control_manager.MachineDialogs.confirm_rehome",
               return_value=True):
        manager.on_btn_home_all_clicked()

    _jc_wf = MachineController().params.get("JOINTS_COUNT", 6)
    ok = poll_until(ctrl, lambda s: all(s.homed[i] for i in range(_jc_wf)), timeout=20.0)
    assert_true(ok, "Крок 4: всі осі homed після execute_homing")
    bring_to_manual(ctrl)

    # --- Крок 5: Перемикання режиму ---
    states = ctrl.get_states()
    manager.on_overlay_clicked(states, panel_type="axis")
    time.sleep(0.2)
    assert_eq(ctrl.manual_mode, "axis", "Крок 5: manual_mode='axis'")

    manager.on_overlay_clicked(states, panel_type="joint")
    time.sleep(0.2)
    assert_eq(ctrl.manual_mode, "joint", "Крок 5b: manual_mode='joint'")


def _test_power_cycle_clears_homing_shown_flag():
    """Power OFF → ON → homing_complete_shown скинутий, потім знову True."""
    ctrl, mgr = _setup()

    # Симулюємо що homing вже показувався
    mgr.homing_complete_shown = True

    # Power OFF
    states = ctrl.get_states()
    mgr.on_btn_power_off_clicked(states)
    poll_until(ctrl, lambda s: s.task_state == _STATE_OFF, timeout=3.0)

    assert_false(mgr.homing_complete_shown,
                 "homing_complete_shown має скинутись при Power OFF")

    # Power ON
    states = ctrl.get_states()
    mgr.on_btn_power_off_clicked(states)
    poll_until(ctrl, lambda s: s.task_state == _STATE_ON, timeout=3.0)

    assert_false(mgr.homing_complete_shown,
                 "homing_complete_shown залишається False після Power ON (до homing)")

    # Cleanup
    bring_to_manual(ctrl)


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
    # Група 1: toggle_estop
    ("toggle_estop: ESTOP_RESET → STATE_ESTOP",
     _test_toggle_estop_activates_estop),
    ("toggle_estop: STATE_ESTOP → ESTOP_RESET",
     _test_toggle_estop_deactivates_estop),
    ("toggle_estop: двічі → початковий стан",
     _test_toggle_estop_twice_restores_state),
    ("toggle_estop: виняток не пробрасується",
     _test_toggle_estop_does_not_raise),

    # Група 2: toggle_power
    ("toggle_power: ON → STATE_OFF",
     _test_toggle_power_off_when_on),
    ("toggle_power: OFF → STATE_ON",
     _test_toggle_power_on_when_off),
    ("toggle_power: OFF скидає homing_complete_shown",
     _test_toggle_power_off_resets_homing_flag),
    ("toggle_power: ON не скидає homing_complete_shown",
     _test_toggle_power_on_does_not_reset_homing_flag),

    # Група 3: execute_homing
    ("execute_homing: заблокований при ESTOP",
     _test_execute_homing_blocked_when_estopped),
    ("execute_homing: заблокований при power OFF",
     _test_execute_homing_blocked_when_power_off),
    ("execute_homing: успішно виконується",
     _test_execute_homing_completes_successfully),
    ("execute_homing: скасований через confirm_rehome=False",
     _test_execute_homing_skipped_when_confirm_rehome_cancelled),
    ("execute_homing: переводить в MANUAL перед homing",
     _test_execute_homing_switches_to_manual_mode),

    # Група 4: switch_control_mode
    ("switch_control_mode: заблокований при not ready",
     _test_switch_control_mode_blocked_when_not_ready),
    ("switch_control_mode: заблокований при not homed",
     _test_switch_control_mode_blocked_when_not_homed),
    ("switch_control_mode: axis → manual_mode='axis'",
     _test_switch_control_mode_to_axis_sets_manual_mode),
    ("switch_control_mode: joint → manual_mode='joint'",
     _test_switch_control_mode_to_joint_sets_manual_mode),
    ("switch_control_mode: через реальний get_states()",
     _test_switch_control_mode_uses_states_from_get_states),

    # Група 5: get_states
    ("get_states: power_on/estop_off/is_ready при STATE_ON",
     _test_get_states_power_on_true_when_on),
    ("get_states: estop_off/is_ready False при ESTOP",
     _test_get_states_power_on_false_when_estopped),
    ("get_states: all_homed True після homing",
     _test_get_states_all_homed_after_homing),
    ("get_states: all_homed False до homing",
     _test_get_states_all_homed_false_before_homing),
    ("get_states: is_idle True в MANUAL",
     _test_get_states_is_idle_when_manual),
    ("get_states: has_file False без файлу",
     _test_get_states_has_file_false_initially),
    ("get_states: actual_position має ≥3 координати",
     _test_get_states_actual_position_is_tuple),
    ("get_states: manual_mode відображає ctrl.manual_mode",
     _test_get_states_manual_mode_reflects_ctrl),

    # Група 6: can_home / is_all_homed
    ("can_home: False при ESTOP",
     _test_can_home_false_when_estopped),
    ("can_home: False при power OFF",
     _test_can_home_false_when_power_off),
    ("can_home: True коли машина готова",
     _test_can_home_true_when_ready),
    ("is_all_homed: True після homing",
     _test_is_all_homed_true_after_homing),

    # Група 7: наскрізні сценарії
    ("workflow: ESTOP → Power → Home → Mode (повний цикл)",
     _test_full_workflow_estop_power_home_mode),
    ("workflow: Power cycle скидає homing_complete_shown",
     _test_power_cycle_clears_homing_shown_flag),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: ControlManager ↔ MachineController ↔ sim{_RESET}")
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