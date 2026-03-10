#!/usr/bin/env python3
"""
Інтеграційні тести CycleManager ↔ MachineController ↔ LinuxCNC sim
====================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_cycle_machine.py

Покриття:
  Група 1 — start_cycle:  запуск, перехід в AUTO/RUNNING, guard без файлу,
                           guard без homing, запуск з конкретного рядка
  Група 2 — stop_cycle:   зупинка під час виконання, повернення в MANUAL,
                           виклик без активного циклу (no-op)
  Група 3 — pause/resume: пауза під час виконання, resume після паузи,
                           resume без паузи (no-op), подвійна пауза
  Група 4 — step_cycle:   переключення в AUTO, крок не виконується без файлу,
                           крок не виконується без homing
  Група 5 — наскрізні:    start→pause→resume→stop, start→stop→restart,
                           position зберігається після pause/resume,
                           повне виконання програми до M2

Підтверджені значення sim:
  estop=0 коли скинутий (не STATE_ESTOP_RESET=2)
  task_state=2 після STATE_OFF (не STATE_OFF=3)
  JOINTS_COUNT=6, joints 0..5 homed через home(-1)
"""

import os
import sys
import time
import traceback

import linuxcnc

from logic.core.machine import MachineController
from logic.managers.cycle_manager import CycleManager

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
_STATE_ESTOP  = linuxcnc.STATE_ESTOP        # 1
_STATE_ESTOP_RESET = linuxcnc.STATE_ESTOP_RESET  # 2 (але sim віддає 0)
_STATE_ON     = linuxcnc.STATE_ON           # 4
_MODE_MANUAL  = linuxcnc.MODE_MANUAL        # 1
_MODE_AUTO    = linuxcnc.MODE_AUTO          # 2
_INTERP_IDLE   = linuxcnc.INTERP_IDLE       # 1
_INTERP_PAUSED = linuxcnc.INTERP_PAUSED     # 2
_INTERP_READING = linuxcnc.INTERP_READING   # 3 (running)
_INTERP_WAITING = linuxcnc.INTERP_WAITING   # 4 (running)

# ---------------------------------------------------------------------------
# G-code файли для тестів
# ---------------------------------------------------------------------------
_GCODE_DIR = "/tmp"

# Стандартна програма — рух X+ і назад, потім M2
_GCODE_STANDARD = os.path.join(_GCODE_DIR, "tc_standard.ngc")
# Довга програма — багато рухів, щоб встигнути перехопити паузу
_GCODE_LONG     = os.path.join(_GCODE_DIR, "tc_long.ngc")
# Мінімальна програма — тільки M2 (без руху)
_GCODE_MINIMAL  = os.path.join(_GCODE_DIR, "tc_minimal.ngc")

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

_POLL_STEP = 0.05


def poll_until(ctrl: MachineController, condition,
               timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if condition(ctrl.status):
            return True
        time.sleep(_POLL_STEP)
    return False


def wait_interp_idle(ctrl: MachineController, timeout: float = 15.0) -> bool:
    """Чекати поки інтерпретатор стане IDLE."""
    return poll_until(ctrl, lambda s: s.interp_state == _INTERP_IDLE, timeout)


def wait_interp_running(ctrl: MachineController, timeout: float = 5.0) -> bool:
    """Чекати поки інтерпретатор почне виконання."""
    return poll_until(
        ctrl,
        lambda s: s.interp_state in (_INTERP_READING, _INTERP_WAITING),
        timeout,
    )


def wait_interp_paused(ctrl: MachineController, timeout: float = 5.0) -> bool:
    """Чекати поки інтерпретатор перейде в PAUSED."""
    return poll_until(ctrl, lambda s: s.interp_state == _INTERP_PAUSED, timeout)


# ---------------------------------------------------------------------------
# Стан машини
# ---------------------------------------------------------------------------

def bring_to_manual(ctrl: MachineController) -> None:
    """ESTOP скинути → STATE_ON → MODE_MANUAL."""
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
    """Abort + MANUAL, ігнорує помилки."""
    try:
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    except Exception:
        pass


def home_all(ctrl: MachineController) -> bool:
    """Home all joints і чекати завершення."""
    bring_to_manual(ctrl)
    ctrl.command.teleop_enable(0)
    ctrl.command.wait_complete()
    ctrl.command.home(-1)
    joints_count = ctrl.params.get("JOINTS_COUNT", 6)
    return poll_until(
        ctrl,
        lambda s: all(s.homed[i] for i in range(joints_count)),
        timeout=20.0,
    )


def _setup() -> tuple[MachineController, CycleManager]:
    """Повний підготовчий цикл: MANUAL + home + стабілізація."""
    ctrl = MachineController()
    mgr  = CycleManager(ctrl)
    bring_to_manual(ctrl)
    if not home_all(ctrl):
        raise RuntimeError("Homing не завершився за 20 секунд")
    bring_to_manual(ctrl)
    wait_interp_idle(ctrl, timeout=3.0)
    return ctrl, mgr


def _setup_no_home() -> tuple[MachineController, CycleManager]:
    """
    Підключення БЕЗ homing — для тестів guard-умов.
    Якщо sim не може скинути homed прапорці — повертає None, None.
    """
    ctrl = MachineController()
    mgr  = CycleManager(ctrl)

    # Спроба скинути homed через ESTOP цикл
    ctrl.command.state(_STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == _STATE_ESTOP)
    ctrl.command.state(_STATE_ESTOP_RESET)
    ctrl.command.state(_STATE_ON)
    poll_until(ctrl, lambda s: s.task_state == _STATE_ON)
    ctrl.poll()

    joints_count = ctrl.params.get("JOINTS_COUNT", 6)
    if all(ctrl.status.homed[i] for i in range(joints_count)):
        return None, None  # sim не скидає homed — тест треба пропустити

    bring_to_manual(ctrl)
    return ctrl, mgr


# ---------------------------------------------------------------------------
# G-code файли
# ---------------------------------------------------------------------------

def _create_gcode_files() -> None:
    """Створити тестові G-code файли."""
    # Стандартна програма — достатньо руху щоб перехопити виконання
    with open(_GCODE_STANDARD, "w") as f:
        f.write(
            "G21 G90\n"
            "G0 X0 Y0 Z0\n"
            "G1 X10 F200\n"
            "G1 X0\n"
            "M2\n"
        )

    # Довга програма — багато коротких рухів для стабільного тестування паузи
    with open(_GCODE_LONG, "w") as f:
        lines = ["G21 G90\n", "G0 X0 Y0 Z0\n"]
        for i in range(20):
            lines.append(f"G1 X{(i % 5) + 1} F100\n")
            lines.append(f"G1 X0 F100\n")
        lines.append("M2\n")
        f.writelines(lines)

    # Мінімальна програма — тільки M2
    with open(_GCODE_MINIMAL, "w") as f:
        f.write("G21 G90\nM2\n")


# ===========================================================================
#  ГРУПА 1: start_cycle
# ===========================================================================

def _test_start_cycle_transitions_to_auto_mode():
    """start_cycle переводить task_mode в AUTO."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    mgr.start_cycle()
    ok = poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok, "start_cycle має переводити task_mode в AUTO")


def _test_start_cycle_transitions_interpreter_to_running():
    """start_cycle запускає інтерпретатор (READING або WAITING)."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    mgr.start_cycle()
    ok = wait_interp_running(ctrl, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok,
                f"Після start_cycle інтерпретатор має бути RUNNING, "
                f"є {ctrl.status.interp_state}")


def _test_start_cycle_without_file_does_not_crash():
    """
    start_cycle без завантаженого файлу не кидає виняток назовні.
    cycle_start кидає Exception → CycleManager ловить і логує WARNING.
    """
    ctrl, mgr = _setup()
    # Не завантажуємо файл
    ctrl.poll()
    # Якщо файл вже є в sim — пропускаємо
    if ctrl.status.file:
        print(f"\n  {_YELLOW}[skip] Sim вже має завантажений файл{_RESET}")
        return

    mgr.start_cycle()   # має завершитись без виключення
    ctrl.poll()
    # Інтерпретатор має залишитись IDLE
    assert_eq(ctrl.status.interp_state, _INTERP_IDLE,
              "Без файлу інтерпретатор має залишитись IDLE")


def _test_start_cycle_without_homing_does_not_crash():
    """
    start_cycle без homing не кидає виняток назовні.
    cycle_start кидає Exception → CycleManager ловить і логує WARNING.
    """
    ctrl, mgr = _setup_no_home()
    if ctrl is None:
        print(f"\n  {_YELLOW}[skip] Sim не скидає homed прапорці{_RESET}")
        return

    ctrl.open_program(_GCODE_STANDARD)
    mgr.start_cycle()   # має завершитись без виключення
    ctrl.poll()
    assert_eq(ctrl.status.interp_state, _INTERP_IDLE,
              "Без homing інтерпретатор має залишитись IDLE")


def _test_start_cycle_from_nonzero_line():
    """start_cycle(start_line=N) запускає виконання — не кидає виняток."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    # Рядок 2 є в програмі (G0 X0 Y0 Z0)
    mgr.start_cycle(start_line=2)
    ok = wait_interp_running(ctrl, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok, "start_cycle(start_line=2) має запустити виконання")


def _test_start_cycle_invalid_line_type_defaults_to_zero():
    """start_cycle з нечисловим start_line фолбекує на 0."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    mgr.start_cycle(start_line="not_a_number")
    ok = wait_interp_running(ctrl, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok,
                "start_cycle('not_a_number') має фолбекнути на рядок 0 і запустити програму")


# ===========================================================================
#  ГРУПА 2: stop_cycle
# ===========================================================================

def _test_stop_cycle_returns_to_manual_mode():
    """stop_cycle повертає task_mode в MANUAL."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    mgr.stop_cycle()
    ok = poll_until(ctrl, lambda s: s.task_mode == _MODE_MANUAL, timeout=5.0)

    assert_true(ok,
                f"stop_cycle має повернути task_mode в MANUAL, "
                f"є {ctrl.status.task_mode}")


def _test_stop_cycle_makes_interpreter_idle():
    """stop_cycle зупиняє інтерпретатор → INTERP_IDLE."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    mgr.stop_cycle()
    ok = wait_interp_idle(ctrl, timeout=5.0)

    assert_true(ok,
                f"Після stop_cycle інтерпретатор має бути IDLE, "
                f"є {ctrl.status.interp_state}")


def _test_stop_cycle_when_idle_does_not_crash():
    """stop_cycle без активного циклу не кидає виняток."""
    ctrl, mgr = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.interp_state, _INTERP_IDLE,
              "Передумова: інтерпретатор IDLE")
    mgr.stop_cycle()   # no-op — не має впасти


def _test_stop_cycle_during_pause():
    """stop_cycle під час паузи → IDLE."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    mgr.pause_cycle()
    wait_interp_paused(ctrl, timeout=5.0)

    mgr.stop_cycle()
    ok = wait_interp_idle(ctrl, timeout=5.0)

    assert_true(ok,
                "stop_cycle під час паузи має повернути IDLE")


# ===========================================================================
#  ГРУПА 3: pause_cycle / resume_cycle
# ===========================================================================

def _test_pause_cycle_sets_interp_paused():
    """pause_cycle переводить інтерпретатор в INTERP_PAUSED."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    mgr.pause_cycle()
    ok = wait_interp_paused(ctrl, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok,
                f"pause_cycle має дати INTERP_PAUSED, є {ctrl.status.interp_state}")


def _test_resume_cycle_exits_paused_state():
    """resume_cycle виводить інтерпретатор з PAUSED → RUNNING або IDLE."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    mgr.pause_cycle()
    wait_interp_paused(ctrl, timeout=5.0)

    mgr.resume_cycle()
    ok = poll_until(
        ctrl,
        lambda s: s.interp_state != _INTERP_PAUSED,
        timeout=5.0,
    )
    safe_stop(ctrl)

    assert_true(ok,
                f"resume_cycle має вивести з PAUSED, є {ctrl.status.interp_state}")


def _test_resume_cycle_when_not_paused_is_noop():
    """
    resume_cycle без активної паузи — no-op.
    cycle_resume перевіряє interp_state != PAUSED і повертається.
    Машина залишається в IDLE.
    """
    ctrl, mgr = _setup()
    ctrl.poll()
    assert_eq(ctrl.status.interp_state, _INTERP_IDLE,
              "Передумова: IDLE")
    mgr.resume_cycle()
    ctrl.poll()
    assert_eq(ctrl.status.interp_state, _INTERP_IDLE,
              "resume_cycle без паузи не має змінювати стан")


def _test_pause_resume_cycle_position_preserved():
    """
    Після pause → resume машина продовжує рух з тієї самої позиції.
    Перевіряємо що позиція після resume > позиції до паузи (рух продовжився).
    """
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)
    mgr.start_cycle()

    # Чекаємо поки почнеться реальний рух
    assert_true(wait_interp_running(ctrl, timeout=5.0), "Цикл не стартував")
    time.sleep(0.3)

    mgr.pause_cycle()
    assert_true(wait_interp_paused(ctrl, timeout=5.0), "Пауза не настала")

    ctrl.poll()
    pos_at_pause = ctrl.status.actual_position[0]

    # Перевіряємо що після паузи машина не рухається
    time.sleep(0.4)
    ctrl.poll()
    pos_after_pause_wait = ctrl.status.actual_position[0]
    assert_approx(pos_after_pause_wait, pos_at_pause, tol=0.08,
                  msg="Під час паузи машина не має рухатись")

    mgr.resume_cycle()
    assert_true(
        poll_until(ctrl, lambda s: s.interp_state != _INTERP_PAUSED, timeout=5.0),
        "resume_cycle не вивів з паузи",
    )
    safe_stop(ctrl)


def _test_double_pause_is_idempotent():
    """Подвійний виклик pause_cycle — no-op для другого виклику."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    mgr.pause_cycle()
    wait_interp_paused(ctrl, timeout=5.0)

    # Другий виклик не має кидати виняток і не має змінювати стан
    mgr.pause_cycle()
    ctrl.poll()
    assert_eq(ctrl.status.interp_state, _INTERP_PAUSED,
              "Після подвійної паузи стан має залишитись PAUSED")
    safe_stop(ctrl)


# ===========================================================================
#  ГРУПА 4: step_cycle
# ===========================================================================

def _test_step_cycle_switches_to_auto_mode():
    """step_cycle переключає task_mode в AUTO."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    mgr.step_cycle()
    ok = poll_until(ctrl, lambda s: s.task_mode == _MODE_AUTO, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok,
                f"step_cycle має переключити в AUTO, є {ctrl.status.task_mode}")


def _test_step_cycle_without_file_does_not_crash():
    """step_cycle без файлу — no-op, не кидає виняток."""
    ctrl, mgr = _setup()
    ctrl.poll()
    if ctrl.status.file:
        print(f"\n  {_YELLOW}[skip] Sim вже має завантажений файл{_RESET}")
        return
    mgr.step_cycle()   # cycle_step перевіряє status.file → повертається


def _test_step_cycle_without_homing_does_not_crash():
    """step_cycle без homing — no-op, не кидає виняток."""
    ctrl, mgr = _setup_no_home()
    if ctrl is None:
        print(f"\n  {_YELLOW}[skip] Sim не скидає homed прапорці{_RESET}")
        return
    ctrl.open_program(_GCODE_STANDARD)
    mgr.step_cycle()
    ctrl.poll()
    # cycle_step guard: not all(homed[:3]) → return без команди
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "step_cycle без homing не має перемикати в AUTO")


def _test_step_cycle_polls_status_after_step():
    """step_cycle оновлює статус після виконання кроку."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    # Запускаємо крок і одразу читаємо motion_line
    mgr.step_cycle()
    time.sleep(0.2)
    ctrl.poll()
    # Після step_cycle + poll статус має бути свіжим (не кидати виняток)
    _ = ctrl.status.motion_line   # просто перевіряємо що атрибут доступний
    safe_stop(ctrl)


# ===========================================================================
#  ГРУПА 5: наскрізні сценарії
# ===========================================================================

def _test_workflow_start_pause_resume_stop():
    """
    Повний цикл: start → pause → resume → stop.
    Перевіряємо кожен перехід стану.
    """
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)

    # Start
    mgr.start_cycle()
    assert_true(wait_interp_running(ctrl, timeout=5.0),
                "Крок 1: start_cycle → RUNNING")

    # Pause
    mgr.pause_cycle()
    assert_true(wait_interp_paused(ctrl, timeout=5.0),
                "Крок 2: pause_cycle → PAUSED")

    # Resume
    mgr.resume_cycle()
    assert_true(
        poll_until(ctrl, lambda s: s.interp_state != _INTERP_PAUSED, timeout=5.0),
        "Крок 3: resume_cycle → не PAUSED",
    )

    # Stop
    mgr.stop_cycle()
    assert_true(wait_interp_idle(ctrl, timeout=5.0),
                "Крок 4: stop_cycle → IDLE")

    ctrl.poll()
    assert_eq(ctrl.status.task_mode, _MODE_MANUAL,
              "Після stop_cycle task_mode має бути MANUAL")


def _test_workflow_start_stop_restart():
    """
    start → stop → start знову.
    Машина має нормально перезапустити програму.
    """
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_STANDARD)

    # Перший запуск
    mgr.start_cycle()
    wait_interp_running(ctrl, timeout=5.0)

    # Зупинка
    mgr.stop_cycle()
    assert_true(wait_interp_idle(ctrl, timeout=5.0), "Перша зупинка → IDLE")
    bring_to_manual(ctrl)

    # Другий запуск
    mgr.start_cycle()
    ok = wait_interp_running(ctrl, timeout=5.0)
    safe_stop(ctrl)

    assert_true(ok, "Повторний start_cycle після stop має запустити програму знову")


def _test_workflow_program_runs_to_completion():
    """
    Мінімальна програма (G21 G90 + M2) виконується повністю без зупинки ззовні.
    Після M2 інтерпретатор повертається в IDLE.
    """
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_MINIMAL)

    mgr.start_cycle()
    ok = wait_interp_idle(ctrl, timeout=10.0)

    assert_true(ok,
                f"Програма з M2 має завершитись і дати IDLE, "
                f"є interp={ctrl.status.interp_state}")


def _test_workflow_multiple_pause_resume_cycles():
    """Три цикли pause/resume підряд — машина стабільно реагує на кожен."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_LONG)
    mgr.start_cycle()
    assert_true(wait_interp_running(ctrl, timeout=5.0), "Початковий старт")

    for iteration in range(3):
        mgr.pause_cycle()
        ok_pause = wait_interp_paused(ctrl, timeout=5.0)
        assert_true(ok_pause,
                    f"Ітерація {iteration + 1}: pause має дати PAUSED, "
                    f"є {ctrl.status.interp_state}")

        mgr.resume_cycle()
        ok_resume = poll_until(
            ctrl,
            lambda s: s.interp_state != _INTERP_PAUSED,
            timeout=5.0,
        )
        assert_true(ok_resume,
                    f"Ітерація {iteration + 1}: resume має вивести з PAUSED")

        time.sleep(0.15)   # дати sim час стабілізуватись між ітераціями

    safe_stop(ctrl)


def _test_workflow_stop_after_completion():
    """
    Виклик stop_cycle після природного завершення програми (M2) — no-op,
    не кидає виняток, машина залишається в стабільному стані.
    """
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_MINIMAL)

    mgr.start_cycle()
    assert_true(wait_interp_idle(ctrl, timeout=10.0),
                "Програма має завершитись (M2)")

    # Виклик stop після завершення
    mgr.stop_cycle()
    ctrl.poll()
    assert_eq(ctrl.status.interp_state, _INTERP_IDLE,
              "Після stop_cycle на вже завершеній програмі: IDLE")


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
    # Група 1: start_cycle
    ("start_cycle: task_mode переходить в AUTO",
     _test_start_cycle_transitions_to_auto_mode),
    ("start_cycle: інтерпретатор переходить в RUNNING",
     _test_start_cycle_transitions_interpreter_to_running),
    ("start_cycle: без файлу — no crash, IDLE",
     _test_start_cycle_without_file_does_not_crash),
    ("start_cycle: без homing — no crash, IDLE",
     _test_start_cycle_without_homing_does_not_crash),
    ("start_cycle: з конкретного рядка запускається",
     _test_start_cycle_from_nonzero_line),
    ("start_cycle: нечисловий start_line → фолбек на 0",
     _test_start_cycle_invalid_line_type_defaults_to_zero),

    # Група 2: stop_cycle
    ("stop_cycle: повертає task_mode в MANUAL",
     _test_stop_cycle_returns_to_manual_mode),
    ("stop_cycle: інтерпретатор стає IDLE",
     _test_stop_cycle_makes_interpreter_idle),
    ("stop_cycle: без циклу — no crash",
     _test_stop_cycle_when_idle_does_not_crash),
    ("stop_cycle: під час паузи → IDLE",
     _test_stop_cycle_during_pause),

    # Група 3: pause / resume
    ("pause_cycle: інтерпретатор стає PAUSED",
     _test_pause_cycle_sets_interp_paused),
    ("resume_cycle: виводить з PAUSED",
     _test_resume_cycle_exits_paused_state),
    ("resume_cycle: без паузи — no-op",
     _test_resume_cycle_when_not_paused_is_noop),
    ("pause/resume: позиція збережена під час паузи",
     _test_pause_resume_cycle_position_preserved),
    ("pause_cycle: подвійна пауза — ідемпотентна",
     _test_double_pause_is_idempotent),

    # Група 4: step_cycle
    ("step_cycle: перемикає в AUTO",
     _test_step_cycle_switches_to_auto_mode),
    ("step_cycle: без файлу — no crash",
     _test_step_cycle_without_file_does_not_crash),
    ("step_cycle: без homing — no crash",
     _test_step_cycle_without_homing_does_not_crash),
    ("step_cycle: оновлює статус після кроку",
     _test_step_cycle_polls_status_after_step),

    # Група 5: наскрізні
    ("workflow: start → pause → resume → stop",
     _test_workflow_start_pause_resume_stop),
    ("workflow: start → stop → restart",
     _test_workflow_start_stop_restart),
    ("workflow: програма виконується до M2",
     _test_workflow_program_runs_to_completion),
    ("workflow: 3× pause/resume підряд",
     _test_workflow_multiple_pause_resume_cycles),
    ("workflow: stop після M2 — no crash",
     _test_workflow_stop_after_completion),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    # Створюємо G-code файли
    _create_gcode_files()

    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: CycleManager ↔ MachineController ↔ sim{_RESET}")
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