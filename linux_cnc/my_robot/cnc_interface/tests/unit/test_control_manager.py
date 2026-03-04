"""
Tests for logic/managers/control_manager.py  –  ControlManager & MachineDialogs
================================================================================

Run with:
    pytest test_control_manager.py -v

PyQt5 and config are mocked at module level so the suite runs without a
display server or a real LinuxCNC installation.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Mock PyQt5 and config before importing the module under test
# ---------------------------------------------------------------------------
_qmsgbox        = MagicMock()
_qmsgbox.Ok     = 0x00000400
_qmsgbox.Cancel = 0x00400000

_qt_widgets_mock             = MagicMock()
_qt_widgets_mock.QMessageBox = _qmsgbox

sys.modules.setdefault("PyQt5",                _qt_widgets_mock)
sys.modules.setdefault("PyQt5.QtWidgets",      _qt_widgets_mock)
sys.modules.setdefault("config",               MagicMock(STYLES={}))

from logic.managers.control_manager import (  # noqa: E402
    ControlManager,
    MachineDialogs,
    _AXIS_MODE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    cnc = MagicMock()
    cnc.speed = 100
    cnc.is_ready.return_value    = True
    cnc.can_home.return_value    = True
    cnc.is_all_homed.return_value = False
    return cnc


@pytest.fixture()
def mock_widgets() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def manager(mock_cnc, mock_widgets) -> ControlManager:
    return ControlManager(mock_cnc, mock_widgets)


# ===========================================================================
# ControlManager – initialisation
# ===========================================================================

class TestInit:
    def test_stores_cnc_reference(self, mock_cnc, mock_widgets):
        m = ControlManager(mock_cnc, mock_widgets)
        assert m.cnc is mock_cnc

    def test_stores_widgets_reference(self, mock_cnc, mock_widgets):
        m = ControlManager(mock_cnc, mock_widgets)
        assert m.widgets is mock_widgets

    def test_homing_flag_starts_false(self, manager):
        assert manager.homing_complete_shown is False

    def test_speed_cached_from_cnc(self, mock_cnc, mock_widgets):
        mock_cnc.speed = 250
        m = ControlManager(mock_cnc, mock_widgets)
        assert m.SPEED == 250

    def test_slots_prevent_arbitrary_attributes(self, manager):
        with pytest.raises(AttributeError):
            manager.unexpected = "oops"

    def test_repr_contains_class_name(self, manager):
        assert "ControlManager" in repr(manager)

    def test_repr_contains_speed(self, manager):
        assert "100" in repr(manager)


# ===========================================================================
# toggle_estop
# ===========================================================================

class TestToggleEstop:
    def test_delegates_to_cnc(self, manager, mock_cnc):
        manager.toggle_estop()
        mock_cnc.toggle_estop.assert_called_once()

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.toggle_estop.side_effect = Exception("Hardware fault")
        manager.toggle_estop()   # must not raise

    def test_exception_is_logged(self, manager, mock_cnc):
        mock_cnc.toggle_estop.side_effect = Exception("fault")
        with patch("logic.managers.control_manager.logger") as mock_log:
            manager.toggle_estop()
            mock_log.error.assert_called_once()

    def test_on_btn_estop_clicked_delegates(self, manager, mock_cnc):
        manager.on_btn_estop_clicked()
        mock_cnc.toggle_estop.assert_called_once()


# ===========================================================================
# toggle_power
# ===========================================================================

class TestTogglePower:
    def test_turns_on_when_off(self, manager, mock_cnc):
        manager.toggle_power(current_power_state=False)
        mock_cnc.set_power.assert_called_with(True)

    def test_turns_off_when_on(self, manager, mock_cnc):
        manager.toggle_power(current_power_state=True)
        mock_cnc.set_power.assert_called_with(False)

    def test_polls_before_set_power(self, manager, mock_cnc):
        """poll() must precede set_power() — safety requirement."""
        manager.toggle_power(False)
        assert mock_cnc.mock_calls == [call.poll(), call.set_power(True)]

    def test_resets_homing_flag_when_turning_off(self, manager, mock_cnc):
        manager.homing_complete_shown = True
        manager.toggle_power(current_power_state=True)
        assert manager.homing_complete_shown is False

    def test_does_not_reset_homing_flag_when_turning_on(self, manager, mock_cnc):
        manager.homing_complete_shown = True
        manager.toggle_power(current_power_state=False)
        assert manager.homing_complete_shown is True

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.poll.side_effect = Exception("CNC Connection Lost")
        manager.toggle_power(False)  # must not raise

    def test_exception_is_logged(self, manager, mock_cnc):
        mock_cnc.poll.side_effect = Exception("lost")
        with patch("logic.managers.control_manager.logger") as mock_log:
            manager.toggle_power(False)
            mock_log.error.assert_called_once()

    def test_on_btn_power_off_clicked_reads_power_on_key(self, manager, mock_cnc):
        manager.on_btn_power_off_clicked({"power_on": True})
        mock_cnc.set_power.assert_called_with(False)

    def test_on_btn_power_off_clicked_empty_dict_defaults_to_false(self, manager, mock_cnc):
        """Missing key defaults to False → new_state = True (turn on)."""
        manager.on_btn_power_off_clicked({})
        mock_cnc.set_power.assert_called_with(True)


# ===========================================================================
# execute_homing
# ===========================================================================

class TestExecuteHoming:
    def test_blocked_when_not_ready(self, manager, mock_cnc):
        mock_cnc.can_home.return_value = False
        manager.execute_homing()
        mock_cnc.home_all_sequence.assert_not_called()

    def test_starts_immediately_when_not_homed(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = False
        manager.execute_homing()
        mock_cnc.home_all_sequence.assert_called_once()

    def test_skips_dialog_when_not_homed(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = False
        with patch(
            "logic.managers.control_manager.MachineDialogs.confirm_rehome"
        ) as mock_dialog:
            manager.execute_homing()
            mock_dialog.assert_not_called()

    def test_shows_dialog_when_already_homed(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = True
        with patch(
            "logic.managers.control_manager.MachineDialogs.confirm_rehome",
            return_value=False,
        ) as mock_dialog:
            manager.execute_homing()
            mock_dialog.assert_called_once()

    def test_rehomes_on_confirmation_ok(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = True
        with patch(
            "logic.managers.control_manager.MachineDialogs.confirm_rehome",
            return_value=True,
        ):
            manager.execute_homing()
        mock_cnc.home_all_sequence.assert_called_once()

    def test_aborts_on_confirmation_cancel(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = True
        with patch(
            "logic.managers.control_manager.MachineDialogs.confirm_rehome",
            return_value=False,
        ):
            manager.execute_homing()
        mock_cnc.home_all_sequence.assert_not_called()

    def test_dialog_receives_main_window_as_parent(self, manager, mock_cnc, mock_widgets):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = True
        sentinel = object()
        mock_widgets.main_window = sentinel
        with patch(
            "logic.managers.control_manager.MachineDialogs.confirm_rehome",
            return_value=False,
        ) as mock_dialog:
            manager.execute_homing()
            mock_dialog.assert_called_once_with(sentinel)

    def test_dialog_receives_none_when_main_window_absent(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = True
        manager.widgets = MagicMock(spec=[])   # no main_window attribute
        with patch(
            "logic.managers.control_manager.MachineDialogs.confirm_rehome",
            return_value=False,
        ) as mock_dialog:
            manager.execute_homing()
            mock_dialog.assert_called_once_with(None)

    def test_on_btn_home_all_clicked_delegates(self, manager, mock_cnc):
        mock_cnc.can_home.return_value    = True
        mock_cnc.is_all_homed.return_value = False
        manager.on_btn_home_all_clicked()
        mock_cnc.home_all_sequence.assert_called_once()


# ===========================================================================
# switch_control_mode
# ===========================================================================

class TestSwitchControlMode:
    @pytest.mark.parametrize("panel_type, expected_teleop", [
        (_AXIS_MODE, True),
        ("joint",    False),
    ])
    def test_sets_teleop_correctly(self, manager, mock_cnc, panel_type, expected_teleop):
        manager.switch_control_mode(panel_type, is_ready=True, all_homed=True)
        mock_cnc.set_teleop.assert_called_once_with(expected_teleop)

    @pytest.mark.parametrize("panel_type", [_AXIS_MODE, "joint"])
    def test_updates_manual_mode(self, manager, mock_cnc, panel_type):
        manager.switch_control_mode(panel_type, is_ready=True, all_homed=True)
        assert mock_cnc.manual_mode == panel_type

    def test_no_op_when_not_ready(self, manager, mock_cnc):
        manager.switch_control_mode(_AXIS_MODE, is_ready=False, all_homed=True)
        mock_cnc.set_teleop.assert_not_called()

    def test_no_op_when_not_homed(self, manager, mock_cnc):
        manager.switch_control_mode(_AXIS_MODE, is_ready=True, all_homed=False)
        mock_cnc.set_teleop.assert_not_called()

    def test_no_op_when_neither_ready_nor_homed(self, manager, mock_cnc):
        manager.switch_control_mode(_AXIS_MODE, is_ready=False, all_homed=False)
        mock_cnc.set_teleop.assert_not_called()

    def test_on_overlay_clicked_reads_states(self, manager, mock_cnc):
        states = {"is_ready": True, "all_homed": True}
        manager.on_overlay_clicked(states, _AXIS_MODE)
        mock_cnc.set_teleop.assert_called_once_with(True)

    def test_on_overlay_clicked_empty_dict_is_no_op(self, manager, mock_cnc):
        manager.on_overlay_clicked({}, _AXIS_MODE)
        mock_cnc.set_teleop.assert_not_called()