"""
Tests for logic/managers/keyboard_manager.py  –  KeyboardManager
=================================================================

Run with:
    pytest test_keyboard_manager.py -v

PyQt5 and config are mocked at module level so the suite runs without a
display server or a real LinuxCNC installation.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock PyQt5 and config BEFORE importing the module under test
# ---------------------------------------------------------------------------

_Key        = MagicMock()
_Key.Key_Escape = 0x01000000   # real Qt value

_Modifier   = MagicMock()
_Modifier.NoModifier   = 0x00000000
_Modifier.ControlModifier = 0x04000000
_Modifier.ShiftModifier   = 0x02000000

_QtCore_mock              = MagicMock()
_QtCore_mock.Qt.Key_Escape       = _Key.Key_Escape
_QtCore_mock.Qt.NoModifier       = _Modifier.NoModifier
_QtCore_mock.Qt.ControlModifier  = _Modifier.ControlModifier
_QtCore_mock.Qt.ShiftModifier    = _Modifier.ShiftModifier

# QLineEdit / QTextEdit / QPlainTextEdit — real distinct classes so
# isinstance() checks work correctly in the module under test.
class _FakeQLineEdit:       pass
class _FakeQTextEdit:       pass
class _FakeQPlainTextEdit:  pass
class _FakeOtherWidget:     pass

_QtWidgets_mock = MagicMock()
_QtWidgets_mock.QLineEdit       = _FakeQLineEdit
_QtWidgets_mock.QTextEdit       = _FakeQTextEdit
_QtWidgets_mock.QPlainTextEdit  = _FakeQPlainTextEdit

_MGR_CONTROL = "control"
_MGR_FILE    = "file"
_MGR_CYCLE   = "cycle"

_KEY_ESTOP    = 0x01000001
_KEY_POWER    = 0x01000002
_KEY_HOME     = 0x01000003
_KEY_OPEN     = 0x01000004
_KEY_SAVE_AS  = 0x01000005
_KEY_RELOAD   = 0x01000006
_KEY_RUN      = 0x01000007
_KEY_STOP     = 0x01000008
_KEY_PAUSE    = 0x01000009
_KEY_RESUME   = 0x0100000A
_KEY_STEP     = 0x0100000B
_KEY_CTRL_MOD = (_KEY_RUN, _Modifier.ControlModifier)   # example modifier hotkey

_config_mock = MagicMock()
_config_mock.MGR_CONTROL = _MGR_CONTROL
_config_mock.MGR_FILE    = _MGR_FILE
_config_mock.MGR_CYCLE   = _MGR_CYCLE
_config_mock.HOTKEYS     = {
    "ESTOP":    _KEY_ESTOP,
    "POWER":    _KEY_POWER,
    "HOME_ALL": _KEY_HOME,
    "OPEN_FILE":_KEY_OPEN,
    "SAVE_AS":  _KEY_SAVE_AS,
    "RELOAD":   _KEY_RELOAD,
    "RUN":      _KEY_RUN,
    "STOP":     _KEY_STOP,
    "PAUSE":    _KEY_PAUSE,
    "RESUME":   _KEY_RESUME,
    "STEP":     _KEY_STEP,
}

sys.modules.setdefault("PyQt5",              MagicMock())
sys.modules["PyQt5.QtCore"]    = _QtCore_mock
sys.modules["PyQt5.QtWidgets"] = _QtWidgets_mock
sys.modules["PyQt5"]           = MagicMock(QtCore=_QtCore_mock, QtWidgets=_QtWidgets_mock)
sys.modules["config"]          = _config_mock

from logic.managers.keyboard_manager import (  # noqa: E402
    KeyboardManager,
    _HOTKEY_DISPATCH,
    _INPUT_WIDGET_TYPES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(key: int, mods: int = _Modifier.NoModifier) -> MagicMock:
    """Create a minimal QKeyEvent-like mock."""
    ev = MagicMock()
    ev.key.return_value       = key
    ev.modifiers.return_value = mods
    return ev


def _make_manager_mock(*method_names: str) -> MagicMock:
    """Return a MagicMock that has named methods and a cnc attribute."""
    mgr = MagicMock()
    mgr.cnc = MagicMock()
    mgr.cnc.get_states.return_value = {"power_on": True}
    for name in method_names:
        setattr(mgr, name, MagicMock())
    return mgr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def control_mgr() -> MagicMock:
    return _make_manager_mock(
        "on_btn_estop_clicked",
        "on_btn_power_off_clicked",
        "on_btn_home_all_clicked",
    )


@pytest.fixture()
def file_mgr() -> MagicMock:
    return _make_manager_mock(
        "on_btn_file_open_clicked",
        "on_btn_file_save_as_clicked",
        "on_btn_file_reload_clicked",
    )


@pytest.fixture()
def cycle_mgr() -> MagicMock:
    return _make_manager_mock(
        "start_cycle", "stop_cycle", "pause_cycle", "resume_cycle", "step_cycle"
    )


@pytest.fixture()
def managers(control_mgr, file_mgr, cycle_mgr) -> dict:
    return {
        _MGR_CONTROL: control_mgr,
        _MGR_FILE:    file_mgr,
        _MGR_CYCLE:   cycle_mgr,
    }


@pytest.fixture()
def kb(managers) -> KeyboardManager:
    return KeyboardManager(widgets=MagicMock(), managers_map=managers)


# ===========================================================================
# Initialisation
# ===========================================================================

class TestInit:
    def test_stores_managers(self, managers):
        kb = KeyboardManager(MagicMock(), managers)
        assert kb.managers is managers

    def test_slots_prevent_arbitrary_attributes(self, kb):
        with pytest.raises(AttributeError):
            kb.unexpected = "oops"

    def test_repr_contains_class_name(self, kb):
        assert "KeyboardManager" in repr(kb)

    def test_repr_contains_manager_keys(self, kb):
        r = repr(kb)
        assert _MGR_CONTROL in r
        assert _MGR_CYCLE in r


# ===========================================================================
# processed_key_event – key-release ignored
# ===========================================================================

class TestKeyRelease:
    def test_release_event_is_ignored(self, kb, control_mgr):
        ev = _make_event(_KEY_ESTOP)
        kb.processed_key_event(ev, is_pressed=False)
        control_mgr.on_btn_estop_clicked.assert_not_called()

    def test_only_press_triggers_dispatch(self, kb, control_mgr):
        ev = _make_event(_KEY_ESTOP)
        kb.processed_key_event(ev, is_pressed=True)
        control_mgr.on_btn_estop_clicked.assert_called_once()


# ===========================================================================
# processed_key_event – focus guard
# ===========================================================================

class TestFocusGuard:
    @pytest.mark.parametrize("widget_cls", [
        _FakeQLineEdit,
        _FakeQTextEdit,
        _FakeQPlainTextEdit,
    ])
    def test_hotkeys_suppressed_while_input_focused(self, kb, control_mgr, widget_cls):
        ev = _make_event(_KEY_ESTOP)
        fake_widget = widget_cls()
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=fake_widget
        ):
            kb.processed_key_event(ev, is_pressed=True)
        control_mgr.on_btn_estop_clicked.assert_not_called()

    def test_escape_clears_focus_on_input_widget(self, kb):
        ev        = _make_event(_Key.Key_Escape)
        fake_edit = _FakeQLineEdit()
        fake_edit.clearFocus = MagicMock()
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=fake_edit
        ):
            kb.processed_key_event(ev, is_pressed=True)
        fake_edit.clearFocus.assert_called_once()

    def test_escape_does_not_clear_focus_on_non_input(self, kb):
        ev          = _make_event(_Key.Key_Escape)
        other_widget = _FakeOtherWidget()
        other_widget.clearFocus = MagicMock()
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=other_widget
        ):
            kb.processed_key_event(ev, is_pressed=True)
        other_widget.clearFocus.assert_not_called()

    def test_non_escape_on_input_does_not_clear_focus(self, kb):
        ev        = _make_event(_KEY_ESTOP)
        fake_edit = _FakeQLineEdit()
        fake_edit.clearFocus = MagicMock()
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=fake_edit
        ):
            kb.processed_key_event(ev, is_pressed=True)
        fake_edit.clearFocus.assert_not_called()

    def test_hotkeys_work_without_focus(self, kb, control_mgr):
        ev = _make_event(_KEY_ESTOP)
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=_FakeOtherWidget()
        ):
            kb.processed_key_event(ev, is_pressed=True)
        control_mgr.on_btn_estop_clicked.assert_called_once()


# ===========================================================================
# processed_key_event – dispatch to correct manager/method
# ===========================================================================

class TestDispatch:
    @pytest.mark.parametrize("key, mgr_attr, method_name", [
        (_KEY_ESTOP,   "control_mgr", "on_btn_estop_clicked"),
        (_KEY_POWER,   "control_mgr", "on_btn_power_off_clicked"),
        (_KEY_HOME,    "control_mgr", "on_btn_home_all_clicked"),
        (_KEY_OPEN,    "file_mgr",    "on_btn_file_open_clicked"),
        (_KEY_SAVE_AS, "file_mgr",    "on_btn_file_save_as_clicked"),
        (_KEY_RELOAD,  "file_mgr",    "on_btn_file_reload_clicked"),
        (_KEY_RUN,     "cycle_mgr",   "start_cycle"),
        (_KEY_STOP,    "cycle_mgr",   "stop_cycle"),
        (_KEY_PAUSE,   "cycle_mgr",   "pause_cycle"),
        (_KEY_RESUME,  "cycle_mgr",   "resume_cycle"),
        (_KEY_STEP,    "cycle_mgr",   "step_cycle"),
    ])
    def test_correct_method_called(
        self, kb, control_mgr, file_mgr, cycle_mgr,
        key, mgr_attr, method_name
    ):
        mgr = {"control_mgr": control_mgr,
               "file_mgr":    file_mgr,
               "cycle_mgr":   cycle_mgr}[mgr_attr]
        ev = _make_event(key)
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=_FakeOtherWidget()
        ):
            kb.processed_key_event(ev, is_pressed=True)
        getattr(mgr, method_name).assert_called_once()

    def test_only_first_matching_hotkey_fires(self, kb, control_mgr):
        """Two entries sharing the same key — only the first must fire."""
        # Temporarily inject a duplicate key into the dispatch table
        with patch(
            "logic.managers.keyboard_manager._HOTKEY_DISPATCH",
            (
                ("ESTOP", _MGR_CONTROL, "on_btn_estop_clicked"),
                ("ESTOP", _MGR_CONTROL, "on_btn_home_all_clicked"),
            ),
        ):
            ev = _make_event(_KEY_ESTOP)
            with patch.object(
                _QtWidgets_mock.QApplication,
                "focusWidget",
                return_value=_FakeOtherWidget(),
            ):
                kb.processed_key_event(ev, is_pressed=True)

        control_mgr.on_btn_estop_clicked.assert_called_once()
        control_mgr.on_btn_home_all_clicked.assert_not_called()

    def test_unknown_key_triggers_nothing(self, kb, control_mgr, file_mgr, cycle_mgr):
        ev = _make_event(0xDEAD)
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=_FakeOtherWidget()
        ):
            kb.processed_key_event(ev, is_pressed=True)
        for m in (control_mgr, file_mgr, cycle_mgr):
            for method in vars(m).values():
                if callable(method) and hasattr(method, "assert_not_called"):
                    method.assert_not_called()


# ===========================================================================
# _match
# ===========================================================================

class TestMatch:
    def test_plain_key_matches_without_modifier(self):
        assert KeyboardManager._match(
            0x41, _Modifier.NoModifier, 0x41
        ) is True

    def test_plain_key_fails_with_modifier(self):
        assert KeyboardManager._match(
            0x41, _Modifier.ControlModifier, 0x41
        ) is False

    def test_plain_key_fails_wrong_key(self):
        assert KeyboardManager._match(
            0x42, _Modifier.NoModifier, 0x41
        ) is False

    def test_tuple_target_matches_with_correct_modifier(self):
        assert KeyboardManager._match(
            0x41, _Modifier.ControlModifier,
            (0x41, _Modifier.ControlModifier)
        ) is True

    def test_tuple_target_fails_without_modifier(self):
        assert KeyboardManager._match(
            0x41, _Modifier.NoModifier,
            (0x41, _Modifier.ControlModifier)
        ) is False

    def test_tuple_target_fails_wrong_key(self):
        assert KeyboardManager._match(
            0x42, _Modifier.ControlModifier,
            (0x41, _Modifier.ControlModifier)
        ) is False

    def test_none_target_always_false(self):
        assert KeyboardManager._match(0x41, _Modifier.NoModifier, None) is False

    def test_tuple_modifier_partial_match(self):
        """Both Ctrl and Shift active — Ctrl-only target must still match."""
        combined = _Modifier.ControlModifier | _Modifier.ShiftModifier
        assert KeyboardManager._match(
            0x41, combined, (0x41, _Modifier.ControlModifier)
        ) is True


# ===========================================================================
# _is_input_focused
# ===========================================================================

class TestIsInputFocused:
    @pytest.mark.parametrize("widget_cls", [
        _FakeQLineEdit, _FakeQTextEdit, _FakeQPlainTextEdit,
    ])
    def test_returns_true_for_input_widgets(self, widget_cls):
        w = widget_cls()
        w.clearFocus = MagicMock()
        with patch.object(_QtWidgets_mock.QApplication, "focusWidget", return_value=w):
            assert KeyboardManager._is_input_focused(0x41) is True

    def test_returns_false_for_non_input_widget(self):
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget",
            return_value=_FakeOtherWidget()
        ):
            assert KeyboardManager._is_input_focused(0x41) is False

    def test_returns_false_when_no_focus(self):
        with patch.object(
            _QtWidgets_mock.QApplication, "focusWidget", return_value=None
        ):
            assert KeyboardManager._is_input_focused(0x41) is False

    def test_escape_clears_focus_and_returns_true(self):
        w = _FakeQLineEdit()
        w.clearFocus = MagicMock()
        with patch.object(_QtWidgets_mock.QApplication, "focusWidget", return_value=w):
            result = KeyboardManager._is_input_focused(_Key.Key_Escape)
        assert result is True
        w.clearFocus.assert_called_once()

    def test_non_escape_does_not_clear_focus(self):
        w = _FakeQLineEdit()
        w.clearFocus = MagicMock()
        with patch.object(_QtWidgets_mock.QApplication, "focusWidget", return_value=w):
            KeyboardManager._is_input_focused(0x41)
        w.clearFocus.assert_not_called()


# ===========================================================================
# _call
# ===========================================================================

class TestCall:
    def test_calls_method_with_states(self, kb, control_mgr):
        states = {"power_on": True}
        control_mgr.cnc.get_states.return_value = states
        kb._call(_MGR_CONTROL, "on_btn_estop_clicked")
        control_mgr.on_btn_estop_clicked.assert_called_once_with(states)

    def test_falls_back_to_no_args_on_type_error(self, kb, control_mgr):
        """Methods that don't accept args must be called without them."""
        control_mgr.on_btn_estop_clicked.side_effect = [TypeError("no args"), None]
        kb._call(_MGR_CONTROL, "on_btn_estop_clicked")
        assert control_mgr.on_btn_estop_clicked.call_count == 2
        # Second call must have no arguments
        _, args, kwargs = control_mgr.on_btn_estop_clicked.mock_calls[1]
        assert args == () and kwargs == {}

    def test_missing_manager_key_logs_warning(self, kb):
        with patch("logic.managers.keyboard_manager.logger") as mock_log:
            kb._call("nonexistent_mgr", "some_method")
        mock_log.warning.assert_called_once()

    def test_missing_method_name_logs_warning(self, managers):
        # MagicMock with spec= restricts hasattr to only declared attributes,
        # so hasattr(manager, "nonexistent_method") correctly returns False.
        strict_mgr = MagicMock(spec=["on_btn_estop_clicked"])
        managers[_MGR_CONTROL] = strict_mgr
        kb = KeyboardManager(widgets=MagicMock(), managers_map=managers)
        with patch("logic.managers.keyboard_manager.logger") as mock_log:
            kb._call(_MGR_CONTROL, "nonexistent_method")
        mock_log.warning.assert_called_once()

    def test_missing_manager_does_not_raise(self, kb):
        kb._call("ghost", "method")   # must not raise

    def test_states_empty_dict_when_no_cnc(self, kb, managers):
        """Manager without a cnc attribute must pass {} as states."""
        mgr = MagicMock(spec=["some_method"])   # no cnc
        mgr.some_method = MagicMock()
        managers["no_cnc_mgr"] = mgr
        kb._call("no_cnc_mgr", "some_method")
        mgr.some_method.assert_called_once_with({})

    def test_states_populated_from_cnc_get_states(self, kb, control_mgr):
        expected = {"power_on": False, "all_homed": True}
        control_mgr.cnc.get_states.return_value = expected
        kb._call(_MGR_CONTROL, "on_btn_estop_clicked")
        control_mgr.on_btn_estop_clicked.assert_called_once_with(expected)

    def test_successful_call_logged_as_debug(self, kb, control_mgr):
        with patch("logic.managers.keyboard_manager.logger") as mock_log:
            kb._call(_MGR_CONTROL, "on_btn_estop_clicked")
        mock_log.debug.assert_called_once()

    def test_fallback_call_logged_as_debug(self, kb, control_mgr):
        control_mgr.on_btn_estop_clicked.side_effect = [TypeError, None]
        with patch("logic.managers.keyboard_manager.logger") as mock_log:
            kb._call(_MGR_CONTROL, "on_btn_estop_clicked")
        mock_log.debug.assert_called_once()