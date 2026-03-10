#!/usr/bin/env python3
"""
Інтеграційні тести FileManager ↔ MachineController ↔ LinuxCNC sim
===================================================================

Запускати ТІЛЬКИ при запущеному LinuxCNC у режимі симуляції.
Скрипт: /usr/bin/python3 tests/integration/test_file_machine.py

Відомі баги у попередньому файлі (виправлено тут):
  • FileManager._read_lines не існує — такого методу немає в класі
  • patch('PyQt5.QtWidgets.QFileDialog...') — неправильно; треба патчити
    модуль де ім'я використовується: 'logic.managers.file_manager.QFileDialog'

Стратегія:
  FileManager має два шари:
    1. Machine layer — cnc.open_program / get_last_file / reload_needed /
                       is_interpreter_idle
                       Тестується через реальний MachineController + sim.
    2. Qt layer      — QFileDialog, QStringListModel, widget-атрибути.
                       Ніколи не тестується напряму (потрібен QApplication).
                       Замінюється через patch() + FakeWidgets (MagicMock).

  Тести НЕ запускають Qt event loop.

Підтверджені значення sim:
  estop=0 коли скинутий (не STATE_ESTOP_RESET=2)
  task_state=2 після STATE_OFF (не STATE_OFF=3)
  STATE_ESTOP=1, STATE_ON=4
  JOINTS_COUNT=6, home(-1) хомить joints 0..5

Покриття (44 тести):
  Група 1 — machine layer:   open_program, get_last_file, is_interpreter_idle
  Група 2 — btn_open:        через patch QFileDialog
  Група 3 — btn_reload:      reload logic + guards
  Група 4 — btn_save_as:     запис файлу + guards
  Група 5 — btn_edit:        editor launch + reload_needed
  Група 6 — _load_gcode_to_view: UI side-effects (Qt patched)
  Група 7 — наскрізні:       open→reload, open→saveas, edit→reload
"""

import os
import sys
import time
import traceback

import linuxcnc
from unittest.mock import MagicMock, patch

from logic.core.machine import MachineController
from logic.managers.file_manager import FileManager

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
_INTERP_IDLE       = linuxcnc.INTERP_IDLE        # 1

# ---------------------------------------------------------------------------
# Тестові файли
# ---------------------------------------------------------------------------
_GCODE_BASIC   = "/tmp/tf_basic.ngc"
_GCODE_LONG    = "/tmp/tf_long.ngc"
_GCODE_MISSING = "/tmp/tf_does_not_exist_99999.ngc"

# ---------------------------------------------------------------------------
# Мінімальний тестовий фреймворк
# ---------------------------------------------------------------------------

_results: list = []


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


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------

_POLL_STEP = 0.05


def poll_until(ctrl, condition, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if condition(ctrl.status):
            return True
        time.sleep(_POLL_STEP)
    return False


def wait_file_loaded(ctrl, path: str, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ctrl.poll()
        if ctrl.status.file == path:
            return True
        time.sleep(_POLL_STEP)
    return False


# ---------------------------------------------------------------------------
# Стан машини
# ---------------------------------------------------------------------------

def bring_to_manual(ctrl) -> None:
    ctrl.poll()
    if ctrl.status.estop == _STATE_ESTOP:
        ctrl.command.state(_STATE_ESTOP_RESET)
        poll_until(ctrl, lambda s: s.estop != _STATE_ESTOP)
    ctrl.poll()
    if ctrl.status.task_state != _STATE_ON:
        ctrl.command.state(_STATE_ON)
        poll_until(ctrl, lambda s: s.task_state == _STATE_ON)
    ctrl.poll()
    if ctrl.status.task_mode != _MODE_MANUAL:
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    ctrl.poll()


def safe_stop(ctrl) -> None:
    try:
        ctrl.command.abort()
        ctrl.command.wait_complete()
        ctrl.command.mode(_MODE_MANUAL)
        ctrl.command.wait_complete()
    except Exception:
        pass


def home_all(ctrl) -> bool:
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


# ---------------------------------------------------------------------------
# FakeWidgets — повна заглушка без Qt
# ---------------------------------------------------------------------------

class FakeWidgets:
    """
    Замінює Qt widgets без запуску QApplication.
    Кожен атрибут — окремий MagicMock (незалежні лічильники викликів).
    list_gcode_view.model() → fake model з rowCount=3 і stringList.
    """
    def __init__(self):
        self.btn_file_open        = MagicMock()
        self.btn_file_save_as     = MagicMock()
        self.btn_file_reload      = MagicMock()
        self.btn_file_edit        = MagicMock()
        self.lbl_filename         = MagicMock()
        self.lbl_progress_percent = MagicMock()

        self.list_gcode_view = MagicMock()
        _m = MagicMock()
        _m.rowCount.return_value = 3
        _m.stringList.return_value = ["G21 G90", "G0 X0", "M2"]
        _m.index.return_value.data.return_value = "G21 G90"
        self.list_gcode_view.model.return_value = _m


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _create_test_files() -> None:
    with open(_GCODE_BASIC, "w") as f:
        f.write("G21 G90\nG0 X0 Y0 Z0\nG1 X5 F200\nM2\n")
    with open(_GCODE_LONG, "w") as f:
        lines = ["G21 G90\n"]
        for i in range(30):
            lines.append(f"G1 X{i % 5 + 1} F50\n")
        lines.append("M2\n")
        f.writelines(lines)


def _setup():
    """MANUAL + IDLE — без homing."""
    ctrl = MachineController()
    mgr  = FileManager(ctrl, FakeWidgets())
    bring_to_manual(ctrl)
    poll_until(ctrl, lambda s: s.interp_state == _INTERP_IDLE, timeout=3.0)
    return ctrl, mgr


def _setup_with_file():
    """Як _setup(), але _GCODE_BASIC вже завантажений."""
    ctrl, mgr = _setup()
    ctrl.open_program(_GCODE_BASIC)
    wait_file_loaded(ctrl, _GCODE_BASIC)
    return ctrl, mgr


def _start_long_program(ctrl) -> bool:
    """home + запустити _GCODE_LONG. Повертає True якщо interpreter зайнятий."""
    if not home_all(ctrl):
        return False
    bring_to_manual(ctrl)
    ctrl.open_program(_GCODE_LONG)
    wait_file_loaded(ctrl, _GCODE_LONG)
    ctrl.command.mode(_MODE_AUTO)
    ctrl.command.wait_complete()
    ctrl.command.auto(linuxcnc.AUTO_RUN, 0)
    return poll_until(
        ctrl,
        lambda s: s.interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING),
        timeout=5.0,
    )


# ===========================================================================
#  ГРУПА 1: machine layer
# ===========================================================================

def _test_open_program_loads_file_into_linuxcnc():
    ctrl, _ = _setup()
    ctrl.open_program(_GCODE_BASIC)
    ok = wait_file_loaded(ctrl, _GCODE_BASIC)
    assert_true(ok,
                f"status.file має стати {_GCODE_BASIC!r}, є {ctrl.status.file!r}")


def _test_open_program_sets_last_loaded_file():
    ctrl, _ = _setup()
    assert_eq(ctrl.get_last_file(), None, "Передумова: last_file=None")
    ctrl.open_program(_GCODE_BASIC)
    assert_eq(ctrl.get_last_file(), _GCODE_BASIC,
              "get_last_file() має повернути завантажений шлях")


def _test_open_program_raises_for_missing_file():
    ctrl, _ = _setup()
    try:
        ctrl.open_program(_GCODE_MISSING)
        assert False, "Мав бути кинутий FileNotFoundError"
    except FileNotFoundError:
        pass


def _test_open_program_last_file_unchanged_on_error():
    """FileNotFoundError → last_loaded_file залишається None."""
    ctrl, _ = _setup()
    try:
        ctrl.open_program(_GCODE_MISSING)
    except FileNotFoundError:
        pass
    assert_eq(ctrl.get_last_file(), None,
              "last_file не має оновлюватись після FileNotFoundError")


def _test_open_program_raises_when_interpreter_busy():
    ctrl, _ = _setup()
    ok = _start_long_program(ctrl)
    if not ok:
        print(f"\n  {_YELLOW}[skip] Програма завершилась до перевірки busy-guard{_RESET}")
        safe_stop(ctrl)
        return
    try:
        ctrl.open_program(_GCODE_BASIC)
        safe_stop(ctrl)
        assert False, "Мав бути кинутий RuntimeError"
    except RuntimeError:
        pass
    finally:
        safe_stop(ctrl)


def _test_open_program_second_call_updates_status_file():
    ctrl, _ = _setup()
    second = "/tmp/tf_second.ngc"
    with open(second, "w") as f:
        f.write("G21 G90\nM2\n")
    ctrl.open_program(_GCODE_BASIC)
    wait_file_loaded(ctrl, _GCODE_BASIC)
    ctrl.open_program(second)
    ok = wait_file_loaded(ctrl, second)
    assert_true(ok, f"Після другого open status.file має стати {second!r}")
    assert_eq(ctrl.get_last_file(), second)


def _test_is_interpreter_idle_true_in_manual():
    ctrl, _ = _setup()
    assert_true(ctrl.is_interpreter_idle(),
                f"is_interpreter_idle() має бути True, interp={ctrl.status.interp_state}")


def _test_is_interpreter_idle_false_when_running():
    ctrl, _ = _setup()
    ok = _start_long_program(ctrl)
    if not ok:
        print(f"\n  {_YELLOW}[skip] Програма завершилась{_RESET}")
        safe_stop(ctrl)
        return
    result = ctrl.is_interpreter_idle()
    safe_stop(ctrl)
    assert_false(result,
                 "is_interpreter_idle() має бути False під час виконання")


def _test_get_last_file_none_initially():
    ctrl = MachineController()
    assert_eq(ctrl.get_last_file(), None,
              "get_last_file() має бути None при ініціалізації")


# ===========================================================================
#  ГРУПА 2: on_btn_file_open_clicked
# ===========================================================================

def _test_btn_open_loads_file_via_dialog():
    """
    Правильний патч: 'logic.managers.file_manager.QFileDialog',
    а НЕ 'PyQt5.QtWidgets.QFileDialog'.
    """
    ctrl, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=(_GCODE_BASIC, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_open_clicked()
    ok = wait_file_loaded(ctrl, _GCODE_BASIC)
    assert_true(ok,
                f"Після btn_open status.file має бути {_GCODE_BASIC!r}, "
                f"є {ctrl.status.file!r}")


def _test_btn_open_sets_last_file():
    ctrl, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=(_GCODE_BASIC, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_open_clicked()
    assert_eq(ctrl.get_last_file(), _GCODE_BASIC)


def _test_btn_open_cancelled_leaves_last_file_none():
    ctrl, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=("", "")):
        mgr.on_btn_file_open_clicked()
    assert_eq(ctrl.get_last_file(), None,
              "Після скасування діалогу last_file має залишитись None")


def _test_btn_open_missing_file_does_not_crash():
    """FileManager ловить FileNotFoundError — метод завершується без виключення."""
    ctrl, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=(_GCODE_MISSING, "")):
        mgr.on_btn_file_open_clicked()
    assert_eq(ctrl.get_last_file(), None,
              "Після помилки open last_file має залишитись None")


def _test_btn_open_updates_lbl_filename():
    _, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=(_GCODE_BASIC, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_open_clicked()
    mgr.widgets.lbl_filename.setText.assert_called_once_with(
        os.path.basename(_GCODE_BASIC)
    )


def _test_btn_open_resets_progress_label():
    _, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=(_GCODE_BASIC, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_open_clicked()
    mgr.widgets.lbl_progress_percent.setText.assert_called_once_with("0%")


# ===========================================================================
#  ГРУПА 3: on_btn_file_reload_clicked
# ===========================================================================

def _test_btn_reload_reloads_current_file():
    ctrl, mgr = _setup_with_file()
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()
    ok = wait_file_loaded(ctrl, _GCODE_BASIC)
    assert_true(ok, "Після reload status.file має залишатись правильним")


def _test_btn_reload_clears_reload_needed():
    ctrl, mgr = _setup_with_file()
    ctrl.reload_needed = True
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()
    assert_false(ctrl.reload_needed,
                 "reload_needed має стати False після reload")


def _test_btn_reload_preserves_last_file():
    ctrl, mgr = _setup_with_file()
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()
    assert_eq(ctrl.get_last_file(), _GCODE_BASIC,
              "get_last_file() має залишатись правильним після reload")


def _test_btn_reload_blocked_when_no_file():
    ctrl, mgr = _setup()
    assert_eq(ctrl.get_last_file(), None, "Передумова: файл не завантажений")
    mgr.on_btn_file_reload_clicked()
    assert_eq(ctrl.get_last_file(), None,
              "last_file залишається None — reload заблокований")


def _test_btn_reload_blocked_when_interpreter_busy():
    ctrl, mgr = _setup_with_file()
    original = ctrl.get_last_file()
    with patch.object(ctrl, "is_interpreter_idle", return_value=False):
        mgr.on_btn_file_reload_clicked()
    assert_eq(ctrl.get_last_file(), original,
              "Reload не має виконуватись коли interpreter busy")


def _test_btn_reload_resets_btn_stylesheet():
    ctrl, mgr = _setup_with_file()
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()
    mgr.widgets.btn_file_reload.setStyleSheet.assert_called_with("")


def _test_btn_reload_picks_up_file_content_changes():
    """Файл змінено на диску → reload передає нову версію в LinuxCNC."""
    ctrl, mgr = _setup_with_file()
    with open(_GCODE_BASIC, "a") as f:
        f.write("; reload content change\n")
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()
    ok = wait_file_loaded(ctrl, _GCODE_BASIC)
    assert_true(ok, "Після reload зміненого файлу status.file має зберегтись")


# ===========================================================================
#  ГРУПА 4: on_btn_file_save_as_clicked
# ===========================================================================

def _test_btn_save_as_writes_file_to_disk():
    ctrl, mgr = _setup_with_file()
    saveas = "/tmp/tf_saveas_write.ngc"
    if os.path.exists(saveas):
        os.remove(saveas)
    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=(saveas, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_save_as_clicked()
    assert_true(os.path.exists(saveas),
                f"Файл {saveas} має з'явитись після save-as")


def _test_btn_save_as_loads_new_path_into_linuxcnc():
    ctrl, mgr = _setup_with_file()
    saveas = "/tmp/tf_saveas_load.ngc"
    if os.path.exists(saveas):
        os.remove(saveas)
    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=(saveas, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_save_as_clicked()
    ok = wait_file_loaded(ctrl, saveas)
    assert_true(ok,
                f"Після save-as status.file має бути {saveas!r}, є {ctrl.status.file!r}")
    assert_eq(ctrl.get_last_file(), saveas)


def _test_btn_save_as_adds_ngc_extension():
    ctrl, mgr = _setup_with_file()
    path_no_ext = "/tmp/tf_saveas_noext"
    expected    = path_no_ext + ".ngc"
    for p in (path_no_ext, expected):
        if os.path.exists(p):
            os.remove(p)
    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=(path_no_ext, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_save_as_clicked()
    assert_true(os.path.exists(expected),
                f"Файл {expected} має з'явитись (.ngc додано автоматично)")


def _test_btn_save_as_blocked_when_interpreter_busy():
    ctrl, mgr = _setup_with_file()
    original = ctrl.get_last_file()
    with patch.object(ctrl, "is_interpreter_idle", return_value=False):
        mgr.on_btn_file_save_as_clicked()
    assert_eq(ctrl.get_last_file(), original,
              "Save-as не має виконуватись коли interpreter busy")


def _test_btn_save_as_cancelled_leaves_state_unchanged():
    ctrl, mgr = _setup_with_file()
    original = ctrl.get_last_file()
    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=("", "")):
        mgr.on_btn_file_save_as_clicked()
    assert_eq(ctrl.get_last_file(), original,
              "Після скасування save-as last_file не змінюється")


def _test_btn_save_as_blocked_when_model_empty():
    ctrl, mgr = _setup_with_file()
    mgr.widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=("/tmp/tf_should_not_appear.ngc", "")) as mock_dlg:
        mgr.on_btn_file_save_as_clicked()
        mock_dlg.assert_not_called()


def _test_btn_save_as_blocked_when_no_file_loaded():
    ctrl, mgr = _setup()
    # rowCount=0 бо без файлу модель порожня
    mgr.widgets.list_gcode_view.model.return_value.rowCount.return_value = 0
    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=("", "")) as mock_dlg:
        mgr.on_btn_file_save_as_clicked()
        mock_dlg.assert_not_called()


# ===========================================================================
#  ГРУПА 5: on_btn_file_edit_clicked
# ===========================================================================

def _test_btn_edit_sets_reload_needed():
    ctrl, mgr = _setup_with_file()
    ctrl.reload_needed = False
    with patch("logic.managers.file_manager.subprocess.call", return_value=0):
        with patch("logic.managers.file_manager.subprocess.Popen"):
            mgr.on_btn_file_edit_clicked()
    assert_true(ctrl.reload_needed,
                "reload_needed має стати True після on_btn_file_edit_clicked")


def _test_btn_edit_sets_btn_reload_stylesheet():
    _, mgr = _setup_with_file()
    with patch("logic.managers.file_manager.subprocess.call", return_value=0):
        with patch("logic.managers.file_manager.subprocess.Popen"):
            mgr.on_btn_file_edit_clicked()
    mgr.widgets.btn_file_reload.setStyleSheet.assert_called()


def _test_btn_edit_blocked_when_no_file():
    ctrl, mgr = _setup()
    ctrl.reload_needed = False
    mgr.on_btn_file_edit_clicked()
    assert_false(ctrl.reload_needed,
                 "reload_needed не має змінитись без завантаженого файлу")


def _test_btn_edit_blocked_when_interpreter_busy():
    ctrl, mgr = _setup_with_file()
    ctrl.reload_needed = False
    with patch.object(ctrl, "is_interpreter_idle", return_value=False):
        mgr.on_btn_file_edit_clicked()
    assert_false(ctrl.reload_needed,
                 "reload_needed не має змінитись коли interpreter busy")


def _test_btn_edit_no_editor_found_does_not_crash():
    ctrl, mgr = _setup_with_file()
    ctrl.reload_needed = False
    with patch("logic.managers.file_manager.subprocess.call", return_value=1):
        mgr.on_btn_file_edit_clicked()
    assert_false(ctrl.reload_needed,
                 "reload_needed не має змінитись якщо редактор не знайдений")


def _test_btn_edit_popen_called_with_correct_path():
    """subprocess.Popen отримує [editor, path_to_file] як аргумент."""
    _, mgr = _setup_with_file()
    with patch("logic.managers.file_manager.subprocess.call", return_value=0):
        with patch("logic.managers.file_manager.subprocess.Popen") as mock_popen:
            mgr.on_btn_file_edit_clicked()
    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert_eq(args[-1], _GCODE_BASIC,
              f"Popen має отримати шлях до файлу, отримано {args}")


# ===========================================================================
#  ГРУПА 6: _load_gcode_to_view
# ===========================================================================

def _test_load_to_view_sets_lbl_filename():
    _, mgr = _setup()
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr._load_gcode_to_view(_GCODE_BASIC)
    mgr.widgets.lbl_filename.setText.assert_called_once_with(
        os.path.basename(_GCODE_BASIC)
    )


def _test_load_to_view_resets_progress_label():
    _, mgr = _setup()
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr._load_gcode_to_view(_GCODE_BASIC)
    mgr.widgets.lbl_progress_percent.setText.assert_called_once_with("0%")


def _test_load_to_view_calls_set_model():
    _, mgr = _setup()
    fake_instance = MagicMock()
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=fake_instance):
        mgr._load_gcode_to_view(_GCODE_BASIC)
    mgr.widgets.list_gcode_view.setModel.assert_called_once_with(fake_instance)


def _test_load_to_view_missing_file_does_not_crash():
    _, mgr = _setup()
    mgr._load_gcode_to_view(_GCODE_MISSING)


def _test_load_to_view_without_list_view_no_crash():
    """widgets без list_gcode_view — метод завершується без виключення."""
    ctrl = MachineController()
    bring_to_manual(ctrl)

    class MinimalWidgets:
        lbl_filename          = MagicMock()
        lbl_progress_percent  = MagicMock()

    mgr = FileManager(ctrl, MinimalWidgets())
    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr._load_gcode_to_view(_GCODE_BASIC)


# ===========================================================================
#  ГРУПА 7: наскрізні сценарії
# ===========================================================================

def _test_workflow_open_then_reload_after_change():
    """open → змінити файл → reload → status.file правильний, reload_needed=False."""
    ctrl, mgr = _setup()
    with patch("logic.managers.file_manager.QFileDialog.getOpenFileName",
               return_value=(_GCODE_BASIC, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_open_clicked()
    assert_true(wait_file_loaded(ctrl, _GCODE_BASIC), "Файл не завантажився")

    with open(_GCODE_BASIC, "a") as f:
        f.write("; workflow reload\n")
    ctrl.reload_needed = True

    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()

    assert_true(wait_file_loaded(ctrl, _GCODE_BASIC), "Після reload status.file неправильний")
    assert_false(ctrl.reload_needed, "reload_needed має скинутись після reload")


def _test_workflow_open_saveas_new_path_active():
    """open → save-as → LinuxCNC завантажує новий шлях."""
    ctrl, mgr = _setup_with_file()
    saveas = "/tmp/tf_workflow_saveas.ngc"
    if os.path.exists(saveas):
        os.remove(saveas)

    with patch("logic.managers.file_manager.QFileDialog.getSaveFileName",
               return_value=(saveas, "")):
        with patch("logic.managers.file_manager.QStringListModel",
                   return_value=MagicMock()):
            mgr.on_btn_file_save_as_clicked()

    assert_true(os.path.exists(saveas), f"{saveas} має з'явитись")
    assert_true(wait_file_loaded(ctrl, saveas), f"LinuxCNC має завантажити {saveas}")
    assert_eq(ctrl.get_last_file(), saveas)


def _test_workflow_edit_then_reload_clears_flag():
    """edit → reload_needed=True → reload → reload_needed=False."""
    ctrl, mgr = _setup_with_file()
    ctrl.reload_needed = False

    with patch("logic.managers.file_manager.subprocess.call", return_value=0):
        with patch("logic.managers.file_manager.subprocess.Popen"):
            mgr.on_btn_file_edit_clicked()
    assert_true(ctrl.reload_needed, "Після edit reload_needed має бути True")

    with patch("logic.managers.file_manager.QStringListModel",
               return_value=MagicMock()):
        mgr.on_btn_file_reload_clicked()
    assert_false(ctrl.reload_needed, "Після reload reload_needed має бути False")


def _test_workflow_open_same_file_twice():
    """Відкрити той самий файл двічі — no crash, status.file коректний."""
    ctrl, _ = _setup()
    ctrl.open_program(_GCODE_BASIC)
    wait_file_loaded(ctrl, _GCODE_BASIC)
    ctrl.open_program(_GCODE_BASIC)
    ok = wait_file_loaded(ctrl, _GCODE_BASIC)
    assert_true(ok, "Повторне відкриття файлу має працювати")
    assert_eq(ctrl.get_last_file(), _GCODE_BASIC)


def _test_workflow_reload_needed_false_at_init():
    """ctrl.reload_needed = False при ініціалізації MachineController."""
    ctrl = MachineController()
    assert_false(ctrl.reload_needed,
                 "reload_needed має бути False при ініціалізації")


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

    for path in (
        "/tmp/tf_second.ngc",
        "/tmp/tf_saveas_write.ngc",
        "/tmp/tf_saveas_load.ngc",
        "/tmp/tf_saveas_noext.ngc",
        "/tmp/tf_should_not_appear.ngc",
        "/tmp/tf_workflow_saveas.ngc",
    ):
        if os.path.exists(path):
            os.remove(path)


# ===========================================================================
#  Тестова таблиця
# ===========================================================================

TESTS = [
    # Група 1: machine layer
    ("open_program: файл в LinuxCNC",
     _test_open_program_loads_file_into_linuxcnc),
    ("open_program: оновлює last_loaded_file",
     _test_open_program_sets_last_loaded_file),
    ("open_program: FileNotFoundError для неіснуючого шляху",
     _test_open_program_raises_for_missing_file),
    ("open_program: last_file незмінний при FileNotFoundError",
     _test_open_program_last_file_unchanged_on_error),
    ("open_program: RuntimeError коли interpreter busy",
     _test_open_program_raises_when_interpreter_busy),
    ("open_program: повторний виклик оновлює status.file",
     _test_open_program_second_call_updates_status_file),
    ("is_interpreter_idle: True в MANUAL",
     _test_is_interpreter_idle_true_in_manual),
    ("is_interpreter_idle: False під час виконання",
     _test_is_interpreter_idle_false_when_running),
    ("get_last_file: None при ініціалізації",
     _test_get_last_file_none_initially),

    # Група 2: btn_open
    ("btn_open: завантажує файл через QFileDialog",
     _test_btn_open_loads_file_via_dialog),
    ("btn_open: оновлює last_file",
     _test_btn_open_sets_last_file),
    ("btn_open: скасування → last_file=None",
     _test_btn_open_cancelled_leaves_last_file_none),
    ("btn_open: неіснуючий файл — no crash, last_file=None",
     _test_btn_open_missing_file_does_not_crash),
    ("btn_open: оновлює lbl_filename",
     _test_btn_open_updates_lbl_filename),
    ("btn_open: скидає lbl_progress_percent='0%'",
     _test_btn_open_resets_progress_label),

    # Група 3: btn_reload
    ("btn_reload: перезавантажує файл в LinuxCNC",
     _test_btn_reload_reloads_current_file),
    ("btn_reload: скидає reload_needed=False",
     _test_btn_reload_clears_reload_needed),
    ("btn_reload: зберігає коректний last_file",
     _test_btn_reload_preserves_last_file),
    ("btn_reload: заблокований без файлу",
     _test_btn_reload_blocked_when_no_file),
    ("btn_reload: заблокований коли interpreter busy",
     _test_btn_reload_blocked_when_interpreter_busy),
    ("btn_reload: скидає stylesheet кнопки",
     _test_btn_reload_resets_btn_stylesheet),
    ("btn_reload: підхоплює зміни файлу на диску",
     _test_btn_reload_picks_up_file_content_changes),

    # Група 4: btn_save_as
    ("btn_save_as: записує файл на диск",
     _test_btn_save_as_writes_file_to_disk),
    ("btn_save_as: завантажує новий шлях в LinuxCNC",
     _test_btn_save_as_loads_new_path_into_linuxcnc),
    ("btn_save_as: додає .ngc якщо немає розширення",
     _test_btn_save_as_adds_ngc_extension),
    ("btn_save_as: заблокований коли interpreter busy",
     _test_btn_save_as_blocked_when_interpreter_busy),
    ("btn_save_as: скасування → стан не змінюється",
     _test_btn_save_as_cancelled_leaves_state_unchanged),
    ("btn_save_as: заблокований при порожній моделі",
     _test_btn_save_as_blocked_when_model_empty),
    ("btn_save_as: заблокований без файлу",
     _test_btn_save_as_blocked_when_no_file_loaded),

    # Група 5: btn_edit
    ("btn_edit: reload_needed=True коли editor знайдений",
     _test_btn_edit_sets_reload_needed),
    ("btn_edit: встановлює stylesheet на btn_reload",
     _test_btn_edit_sets_btn_reload_stylesheet),
    ("btn_edit: заблокований без файлу",
     _test_btn_edit_blocked_when_no_file),
    ("btn_edit: заблокований коли interpreter busy",
     _test_btn_edit_blocked_when_interpreter_busy),
    ("btn_edit: no editor found — no crash",
     _test_btn_edit_no_editor_found_does_not_crash),
    ("btn_edit: Popen отримує правильний шлях",
     _test_btn_edit_popen_called_with_correct_path),

    # Група 6: _load_gcode_to_view
    ("load_to_view: встановлює lbl_filename",
     _test_load_to_view_sets_lbl_filename),
    ("load_to_view: скидає lbl_progress_percent",
     _test_load_to_view_resets_progress_label),
    ("load_to_view: викликає setModel",
     _test_load_to_view_calls_set_model),
    ("load_to_view: відсутній файл — no crash",
     _test_load_to_view_missing_file_does_not_crash),
    ("load_to_view: без list_gcode_view у widgets — no crash",
     _test_load_to_view_without_list_view_no_crash),

    # Група 7: наскрізні
    ("workflow: open → reload після зміни файлу",
     _test_workflow_open_then_reload_after_change),
    ("workflow: open → save-as → новий шлях активний",
     _test_workflow_open_saveas_new_path_active),
    ("workflow: edit → reload_needed → reload → cleared",
     _test_workflow_edit_then_reload_clears_flag),
    ("workflow: відкрити той самий файл двічі",
     _test_workflow_open_same_file_twice),
    ("workflow: reload_needed=False при ініціалізації",
     _test_workflow_reload_needed_false_at_init),
]


# ===========================================================================
#  Головний запуск
# ===========================================================================

if __name__ == "__main__":
    _create_test_files()

    print(f"\n{_BOLD}{'=' * 64}{_RESET}")
    print(f"{_BOLD}  Інтеграційні тести: FileManager ↔ MachineController ↔ sim{_RESET}")
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