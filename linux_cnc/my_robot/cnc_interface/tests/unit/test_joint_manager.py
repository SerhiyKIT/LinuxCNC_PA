"""
Tests for logic/managers/joint_manager.py  –  JointManager & JointUIBinder
===========================================================================

Run with:
    pytest test_joint_manager.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from logic.managers.joint_manager import (
    JointManager,
    JointUIBinder,
    _CONTINUOUS_INCREMENT,
    _CONTINUOUS_MODE,
    _NUM_JOINTS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    """Stand-in for MachineController with safe defaults."""
    cnc = MagicMock()
    cnc.angular_jog_speed  = 500.0
    cnc.linear_jog_speed   = 1000.0   # must never be used by JointManager
    cnc.is_ready.return_value   = True
    cnc.sync_mode.return_value  = True
    return cnc


@pytest.fixture()
def manager(mock_cnc: MagicMock) -> JointManager:
    return JointManager(mock_cnc)


@pytest.fixture()
def mock_widgets() -> MagicMock:
    """Widget container with all joint button pairs and a combo box."""
    widgets = MagicMock()
    for j in range(_NUM_JOINTS):
        for side in ("plus", "minus"):
            btn = MagicMock()
            btn.pressed  = MagicMock()
            btn.released = MagicMock()
            setattr(widgets, f"btn_j{j}_{side}", btn)
    widgets.combo_joint_mode = MagicMock()
    widgets.combo_joint_mode.currentText.return_value = _CONTINUOUS_MODE
    return widgets


@pytest.fixture()
def binder(manager: JointManager, mock_widgets: MagicMock) -> JointUIBinder:
    return JointUIBinder(manager, mock_widgets)


# ===========================================================================
# JointManager – initialisation
# ===========================================================================

class TestJointManagerInit:
    def test_stores_cnc_reference(self, mock_cnc):
        m = JointManager(mock_cnc)
        assert m.cnc is mock_cnc

    def test_num_joints_matches_constant(self, manager):
        assert manager.num_joints == _NUM_JOINTS

    def test_slots_prevent_arbitrary_attributes(self, manager):
        with pytest.raises(AttributeError):
            manager.unexpected = "oops"

    def test_repr_contains_class_name(self, manager):
        assert "JointManager" in repr(manager)

    def test_repr_contains_num_joints(self, manager):
        assert str(_NUM_JOINTS) in repr(manager)


# ===========================================================================
# JointManager._parse_increment
# ===========================================================================

class TestParseIncrement:
    @pytest.mark.parametrize("text, expected", [
        # Normal cases
        (_CONTINUOUS_MODE, 0.0),
        ("0.5",             0.5),
        ("1.0",             1.0),
        ("10",             10.0),
        # Invalid / defensive
        ("invalid_val",    0.0),
        ("",               0.0),
        (None,             0.0),
        ("0,5",            0.0),   # comma decimal separator
        ("   ",            0.0),   # whitespace only
        # Numeric input (already a number)
        (5,                5.0),
        (0.25,             0.25),
    ])
    def test_parametrized(self, manager, text, expected):
        assert manager._parse_increment(text) == expected

    def test_continuous_returns_constant(self, manager):
        """Return value must equal _CONTINUOUS_INCREMENT, not just 0.0."""
        assert manager._parse_increment(_CONTINUOUS_MODE) == _CONTINUOUS_INCREMENT

    def test_invalid_logs_warning(self, manager):
        with patch("logic.managers.joint_manager.logger") as mock_log:
            manager._parse_increment("bad_value")
            mock_log.warning.assert_called_once()

    def test_valid_float_string_exact(self, manager):
        assert manager._parse_increment("0.001") == pytest.approx(0.001)


# ===========================================================================
# JointManager.start_jog
# ===========================================================================

class TestStartJog:
    def test_no_op_when_not_ready(self, manager, mock_cnc):
        mock_cnc.is_ready.return_value = False
        manager.start_jog(joint_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
        mock_cnc.sync_mode.assert_not_called()
        mock_cnc.jog.assert_not_called()

    def test_activates_joint_mode_before_jog(self, manager, mock_cnc):
        """sync_mode(want_teleop=False) must be called before jog."""
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        mock_cnc.sync_mode.assert_called_once_with(want_teleop=False)

    def test_sync_mode_precedes_jog(self, manager, mock_cnc):
        """Order: sync_mode → jog."""
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        names = [c[0] for c in mock_cnc.method_calls]
        assert names.index("sync_mode") < names.index("jog"), \
            "sync_mode must be called before jog"

    def test_uses_angular_speed_not_linear(self, manager, mock_cnc):
        """JointManager must use angular_jog_speed, never linear_jog_speed."""
        mock_cnc.angular_jog_speed = 50.0
        mock_cnc.linear_jog_speed  = 1000.0
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        args = mock_cnc.jog.call_args[0]
        assert args[2] == 50.0
        assert args[2] != 1000.0

    def test_passes_is_joint_true(self, manager, mock_cnc):
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        _, kwargs = mock_cnc.jog.call_args
        assert kwargs.get("is_joint") is True

    def test_continuous_mode_uses_zero_increment(self, manager, mock_cnc):
        manager.start_jog(joint_idx=3, direction=1, mode_text=_CONTINUOUS_MODE)
        mock_cnc.jog.assert_called_once_with(3, 1, 500.0, 0.0, is_joint=True)

    def test_incremental_mode_parses_increment(self, manager, mock_cnc):
        manager.start_jog(joint_idx=2, direction=-1, mode_text="1.5")
        mock_cnc.jog.assert_called_once_with(2, -1, 500.0, 1.5, is_joint=True)

    def test_boundary_joint_zero(self, manager, mock_cnc):
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        mock_cnc.jog.assert_called_with(0, 1, 500.0, 0.0, is_joint=True)

    def test_boundary_joint_last(self, manager, mock_cnc):
        last = _NUM_JOINTS - 1
        manager.start_jog(last, -1, _CONTINUOUS_MODE)
        mock_cnc.jog.assert_called_with(last, -1, 500.0, 0.0, is_joint=True)

    def test_exception_from_jog_is_swallowed(self, manager, mock_cnc):
        mock_cnc.jog.side_effect = Exception("Joint Motor Timeout")
        manager.start_jog(0, 1, _CONTINUOUS_MODE)   # must not raise

    def test_exception_is_logged_as_error(self, manager, mock_cnc):
        mock_cnc.jog.side_effect = Exception("timeout")
        with patch("logic.managers.joint_manager.logger") as mock_log:
            manager.start_jog(0, 1, _CONTINUOUS_MODE)
            mock_log.error.assert_called_once()

    def test_invalid_increment_falls_back_to_continuous(self, manager, mock_cnc):
        manager.start_jog(0, 1, mode_text="bad_value")
        args = mock_cnc.jog.call_args[0]
        assert args[3] == 0.0


# ===========================================================================
# JointManager.stop_jog
# ===========================================================================

class TestStopJog:
    def test_stop_sent_in_continuous_mode(self, manager, mock_cnc):
        manager.stop_jog(joint_idx=0, mode_text=_CONTINUOUS_MODE)
        mock_cnc.stop_jog.assert_called_once_with(0, is_joint=True)

    def test_stop_not_sent_in_incremental_mode(self, manager, mock_cnc):
        manager.stop_jog(joint_idx=0, mode_text="0.5")
        mock_cnc.stop_jog.assert_not_called()

    def test_stop_not_sent_for_arbitrary_mode(self, manager, mock_cnc):
        manager.stop_jog(joint_idx=2, mode_text="step")
        mock_cnc.stop_jog.assert_not_called()

    def test_correct_joint_index_forwarded(self, manager, mock_cnc):
        manager.stop_jog(joint_idx=4, mode_text=_CONTINUOUS_MODE)
        mock_cnc.stop_jog.assert_called_once_with(4, is_joint=True)

    def test_is_joint_always_true(self, manager, mock_cnc):
        manager.stop_jog(0, _CONTINUOUS_MODE)
        _, kwargs = mock_cnc.stop_jog.call_args
        assert kwargs.get("is_joint") is True

    def test_continuous_then_incremental(self, manager, mock_cnc):
        """Two calls: first stops, second is silent."""
        manager.stop_jog(0, _CONTINUOUS_MODE)
        mock_cnc.stop_jog.assert_called_once()
        mock_cnc.stop_jog.reset_mock()
        manager.stop_jog(0, "0.1")
        mock_cnc.stop_jog.assert_not_called()


# ===========================================================================
# JointUIBinder – initialisation
# ===========================================================================

class TestJointUIBinderInit:
    def test_stores_manager_reference(self, manager, mock_widgets):
        b = JointUIBinder(manager, mock_widgets)
        assert b.manager is manager

    def test_stores_widgets_reference(self, manager, mock_widgets):
        b = JointUIBinder(manager, mock_widgets)
        assert b.widgets is mock_widgets

    def test_slots_prevent_arbitrary_attributes(self, binder):
        with pytest.raises(AttributeError):
            binder.unexpected = "oops"

    def test_repr_contains_class_name(self, binder):
        assert "JointUIBinder" in repr(binder)


# ===========================================================================
# JointUIBinder.connect_buttons / _bind_joint_pair
# ===========================================================================

class TestConnectButtons:
    def test_all_plus_buttons_connected(self, binder, mock_widgets):
        binder.connect_buttons()
        for j in range(_NUM_JOINTS):
            btn = getattr(mock_widgets, f"btn_j{j}_plus")
            btn.pressed.connect.assert_called_once()
            btn.released.connect.assert_called_once()

    def test_all_minus_buttons_connected(self, binder, mock_widgets):
        binder.connect_buttons()
        for j in range(_NUM_JOINTS):
            btn = getattr(mock_widgets, f"btn_j{j}_minus")
            btn.pressed.connect.assert_called_once()
            btn.released.connect.assert_called_once()

    def test_missing_button_skipped_silently(self, manager):
        """No buttons at all — connect_buttons must not raise."""
        widgets = MagicMock(spec=[])
        b = JointUIBinder(manager, widgets)
        b.connect_buttons()

    def test_partial_widgets_only_bind_present(self, manager):
        """Only J0 plus present — rest silently skipped."""
        widgets = MagicMock(spec=["btn_j0_plus"])
        btn = MagicMock()
        btn.pressed  = MagicMock()
        btn.released = MagicMock()
        widgets.btn_j0_plus = btn

        b = JointUIBinder(manager, widgets)
        b.connect_buttons()

        btn.pressed.connect.assert_called_once()
        btn.released.connect.assert_called_once()

    def test_lambda_captures_correct_index(self, binder, mock_widgets):
        """
        Verify the late-binding closure bug is absent: each lambda must
        capture its own ``idx`` value, not the loop variable's final value.
        """
        binder.connect_buttons()

        for j in range(_NUM_JOINTS):
            btn_plus = getattr(mock_widgets, f"btn_j{j}_plus")
            # Extract the lambda that was passed to pressed.connect
            lambda_fn = btn_plus.pressed.connect.call_args[0][0]
            # Simulate what Qt does when the button is pressed
            with patch.object(binder.manager.cnc, "jog") as mock_jog, \
                 patch.object(binder.manager.cnc, "sync_mode"):
                lambda_fn()
            # The jog must have been called with the correct joint index j
            mock_jog.assert_called_once()
            assert mock_jog.call_args[0][0] == j


# ===========================================================================
# JointUIBinder._get_current_mode
# ===========================================================================

class TestGetCurrentMode:
    def test_returns_combo_text_when_present(self, binder, mock_widgets):
        mock_widgets.combo_joint_mode.currentText.return_value = "1.0"
        assert binder._get_current_mode() == "1.0"

    def test_returns_continuous_when_combo_absent(self, manager):
        widgets = MagicMock(spec=[])
        b = JointUIBinder(manager, widgets)
        assert b._get_current_mode() == _CONTINUOUS_MODE


# ===========================================================================
# JointUIBinder._handle_press / _handle_release
# ===========================================================================

class TestHandlePressRelease:
    def test_handle_press_calls_start_jog(self, binder, mock_widgets, mock_cnc):
        mock_widgets.combo_joint_mode.currentText.return_value = _CONTINUOUS_MODE
        binder._handle_press(idx=2, direction=1)
        mock_cnc.jog.assert_called_once_with(2, 1, 500.0, 0.0, is_joint=True)

    def test_handle_press_negative_direction(self, binder, mock_widgets, mock_cnc):
        mock_widgets.combo_joint_mode.currentText.return_value = _CONTINUOUS_MODE
        binder._handle_press(idx=1, direction=-1)
        assert mock_cnc.jog.call_args[0][1] == -1

    def test_handle_release_stops_in_continuous(self, binder, mock_widgets, mock_cnc):
        mock_widgets.combo_joint_mode.currentText.return_value = _CONTINUOUS_MODE
        binder._handle_release(idx=0)
        mock_cnc.stop_jog.assert_called_once_with(0, is_joint=True)

    def test_handle_release_no_stop_in_incremental(self, binder, mock_widgets, mock_cnc):
        mock_widgets.combo_joint_mode.currentText.return_value = "0.5"
        binder._handle_release(idx=0)
        mock_cnc.stop_jog.assert_not_called()

    def test_handle_press_reads_mode_at_call_time(self, binder, mock_widgets, mock_cnc):
        """Mode must be read at press time, not at bind time."""
        mock_widgets.combo_joint_mode.currentText.return_value = "2.0"
        binder._handle_press(0, 1)
        assert mock_cnc.jog.call_args[0][3] == 2.0