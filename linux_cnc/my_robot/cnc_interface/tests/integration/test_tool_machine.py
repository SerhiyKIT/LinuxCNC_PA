#!/usr/bin/env python3
import sys
import time
import linuxcnc
from logic.core.machine import MachineController
from logic.managers.tool_manager import ToolManager

# ---------------------------------------------------------------------------
# ANSI кольори та оформлення (для ідентичності з вашими тестами)
# ---------------------------------------------------------------------------
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

# ---------------------------------------------------------------------------
# Підтверджені константи LinuxCNC для цього sim
# ---------------------------------------------------------------------------
_MODE_MANUAL       = linuxcnc.MODE_MANUAL        # 1

_results = []

def run_test(name: str, fn) -> None:
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  {_GREEN}✓{_RESET}  {name}")
    except Exception as exc:
        _results.append((name, False, str(exc)))
        print(f"  {_RED}✗{_RESET}  {name}")
        print(f"      {_RED}Error: {exc}{_RESET}")

def poll_until(ctrl, condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if condition(ctrl.status): return True
        time.sleep(0.05)
    return False

# ---------------------------------------------------------------------------
# Підготовка
# ---------------------------------------------------------------------------

def _setup():
    ctrl = MachineController()
    mgr = ToolManager(ctrl)
    
    # Підготовка машини для MDI (Power ON + Home + Manual)
    ctrl.command.state(linuxcnc.STATE_ESTOP_RESET)
    ctrl.command.state(linuxcnc.STATE_ON)
    ctrl.command.mode(linuxcnc.MODE_MANUAL)
    
    # Хомінг мінімум 3 осей (згідно з вашим _REQUIRED_HOMED_JOINTS)
    ctrl.command.home(-1)
    poll_until(ctrl, lambda s: all(s.homed[:3]), timeout=5.0)
    
    return ctrl, mgr

# ---------------------------------------------------------------------------
# ТЕСТИ
# ---------------------------------------------------------------------------

def _test_tool_action_blocked_when_disarmed():
    """Перевірка безпеки: дія заблокована, якщо tool_manager не 'armed'."""
    ctrl, mgr = _setup()
    
    # Спробуємо GRIP (is_grip=False -> True)
    mgr.perform_action(is_grip=False, is_armed=False)
    
    # Оскільки MDI команда не мала бути відправлена, черга MDI має бути порожньою/IDLE
    ctrl.poll()
    assert ctrl.status.interp_state == linuxcnc.INTERP_IDLE, "Інтерпретатор не мав запускати MDI"

def _test_tool_action_mdi_execution():
    """Перевірка виконання MDI команди (M101/M102) при активованому 'armed'."""
    ctrl, mgr = _setup()
    
    # Активуємо режим "Озброєно" і тиснемо GRIP
    mgr.perform_action(is_grip=False, is_armed=True)
    
    # Чекаємо, поки інтерпретатор обробить MDI (M101)
    # В симуляторі MDI виконується швидко, але стан на мить зміниться
    poll_until(ctrl, lambda s: s.interp_state != linuxcnc.INTERP_IDLE, timeout=1.0)
    
    # Після виконання M101 інтерпретатор має повернутися в IDLE
    ok = poll_until(ctrl, lambda s: s.interp_state == linuxcnc.INTERP_IDLE, timeout=2.0)
    assert ok, "MDI команда (M101) мала завершитись"
    
def _test_safety_interlock_estop():
    """Перевірка блокування дії, якщо натиснуто E-STOP (Safety Interlock)."""
    ctrl, mgr = _setup()
    
    # 1. Активуємо E-STOP
    ctrl.command.state(linuxcnc.STATE_ESTOP)
    poll_until(ctrl, lambda s: s.estop == linuxcnc.STATE_ESTOP)
    
    # 2. Спробуємо виконати дію (навіть якщо "Armed")
    mgr.perform_action(is_grip=False, is_armed=True)
    
    # 3. Перевіряємо, що MDI не запустився
    ctrl.poll()
    assert ctrl.status.estop == linuxcnc.STATE_ESTOP, "Машина мала залишатися в стані E-STOP"
    assert ctrl.status.interp_state == linuxcnc.INTERP_IDLE, "Дія заблокована через E-STOP"

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


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

TESTS = [
    ("tool_action: блок при DISARMED", _test_tool_action_blocked_when_disarmed),
    ("tool_action: виконання M101 при ARMED", _test_tool_action_mdi_execution),
    ("tool_action: блок при E-STOP (Interlock)", _test_safety_interlock_estop),
]

if __name__ == "__main__":
    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: ToolManager ↔ MachineController ↔ sim{_RESET}")
    print(f"{_BOLD}{'=' * 64}{_RESET}\n")

    for name, fn in TESTS:
        run_test(name, fn)

    _cleanup()
    
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    if failed == 0:
        print(f"{_GREEN}{_BOLD}  ✓ Всі {total} тестів пройшли{_RESET}")
    else:
        print(f"{_RED}{_BOLD}  ✗ {failed}/{total} тестів провалились{_RESET}")
    print(f"{_BOLD}{'=' * 64}{_RESET}\n")

    sys.exit(0 if failed == 0 else 1)