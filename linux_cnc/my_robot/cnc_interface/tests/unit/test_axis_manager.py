"""
Tests for logic/core/axis_manager.py  –  AxisManager & AxisUIBinder
====================================================================

Run with:
    pytest test_axis_manager.py -v
"""

import pytest
from unittest.mock import MagicMock, call, patch

from logic.managers.axis_manager import (
    AxisManager,
    AxisUIBinder,
    _AXES,
    _CONTINUOUS_INCREMENT,
    _CONTINUOUS_MODE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    """Stand-in for MachineController with safe defaults."""
    cnc = MagicMock()
    cnc.linear_jog_speed = 1200.0
    cnc.is_ready.return_value = True
    cnc.sync_mode.return_value = True
    return cnc


@pytest.fixture()
def manager(mock_cnc: MagicMock) -> AxisManager:
    return AxisManager(mock_cnc)


@pytest.fixture()
def mock_widgets() -> MagicMock:
    """
    Widget container with all six axis button pairs and a combo box.
    Each button exposes .pressed and .released signal mocks.
    """
    widgets = MagicMock()
    for axis in _AXES:
        for side in ("plus", "minus"):
            btn = MagicMock()
            btn.pressed  = MagicMock()
            btn.released = MagicMock()
            setattr(widgets, f"btn_{axis}_{side}", btn)
    widgets.combo_axis_mode = MagicMock()
    widgets.combo_axis_mode.currentText.return_value = _CONTINUOUS_MODE
    return widgets


@pytest.fixture()
def binder(manager: AxisManager, mock_widgets: MagicMock) -> AxisUIBinder:
    return AxisUIBinder(manager, mock_widgets)


# ===========================================================================
# AxisManager – initialisation
# ===========================================================================

class TestAxisManagerInit:
    def test_stores_cnc_reference(self, mock_cnc):
        am = AxisManager(mock_cnc)
        assert am.cnc is mock_cnc

    def test_default_axes_match_constant(self, manager):
        assert manager.axes == list(_AXES)

    def test_slots_prevent_arbitrary_attributes(self, manager):
        with pytest.raises(AttributeError):
            manager.unexpected = "oops"

    def test_repr_contains_class_name(self, manager):
        assert "AxisManager" in repr(manager)

    def test_repr_contains_axes(self, manager):
        assert "x" in repr(manager)


# ===========================================================================
# AxisManager._parse_increment
# ===========================================================================

class TestParseIncrement:
    @pytest.mark.parametrize("text, expected", [
        # Normal cases
        (_CONTINUOUS_MODE, 0.0),
        ("0.1",            0.1),
        ("1.0",            1.0),
        ("10",            10.0),
        # Invalid / defensive
        ("invalid",        0.0),
        (None,             0.0),
        # Edge cases
        ("",               0.0),
        ("   ",            0.0),   # spaces — float("   ") raises ValueError
        ("0,5",            0.0),   # comma decimal separator
        # Numeric input (already a number, not a string)
        (5,                5.0),
        (0.25,             0.25),
    ])
    def test_parse_increment_parametrized(self, manager, text, expected):
        assert manager._parse_increment(text) == expected

    def test_continuous_returns_constant(self, manager):
        """Return value must equal _CONTINUOUS_INCREMENT, not just 0.0."""
        assert manager._parse_increment(_CONTINUOUS_MODE) is _CONTINUOUS_INCREMENT or \
               manager._parse_increment(_CONTINUOUS_MODE) == _CONTINUOUS_INCREMENT

    def test_valid_float_string_exact(self, manager):
        result = manager._parse_increment("0.001")
        assert result == pytest.approx(0.001)

    def test_invalid_logs_warning(self, manager):
        with patch("logic.managers.axis_manager.logger") as mock_log:
            manager._parse_increment("bad_value")
            mock_log.warning.assert_called_once()


# ===========================================================================
# AxisManager.start_jog
# ===========================================================================

class TestStartJog:
    def test_no_op_when_not_ready(self, manager, mock_cnc):
        mock_cnc.is_ready.return_value = False
        manager.start_jog(axis_idx=0, direction=1, mode_text=_CONTINUOUS_MODE)
        mock_cnc.sync_mode.assert_not_called()
        mock_cnc.jog.assert_not_called()

    def test_continuous_mode_uses_zero_increment(self, manager, mock_cnc):
        manager.start_jog(axis_idx=1, direction=-1, mode_text=_CONTINUOUS_MODE)
        mock_cnc.jog.assert_called_once_with(1, -1, 1200.0, 0.0, is_joint=False)

    def test_incremental_mode_parses_increment(self, manager, mock_cnc):
        manager.start_jog(axis_idx=2, direction=1, mode_text="0.5")
        mock_cnc.jog.assert_called_once_with(2, 1, 1200.0, 0.5, is_joint=False)

    def test_teleop_enabled_before_jog(self, manager, mock_cnc):
        """sync_mode(want_teleop=True) must precede the jog command."""
        manager.start_jog(0, 1, _CONTINUOUS_MODE)

        calls = mock_cnc.method_calls
        idx_sync = next(
            (i for i, c in enumerate(calls) if c[0] == "sync_mode"), -1
        )
        idx_jog = next(
            (i for i, c in enumerate(calls) if c[0] == "jog"), -1
        )
        assert idx_sync != -1, "sync_mode was never called"
        assert idx_jog  != -1, "jog was never called"
        assert idx_sync < idx_jog, "sync_mode must be called before jog"

    def test_sync_mode_called_with_want_teleop_true(self, manager, mock_cnc):
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        mock_cnc.sync_mode.assert_called_once_with(want_teleop=True)

    def test_uses_linear_jog_speed_from_cnc(self, manager, mock_cnc):
        mock_cnc.linear_jog_speed = 600.0
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        args = mock_cnc.jog.call_args[0]
        assert args[2] == 600.0

    def test_jog_called_with_is_joint_false(self, manager, mock_cnc):
        manager.start_jog(0, 1, _CONTINUOUS_MODE)
        _, kwargs = mock_cnc.jog.call_args
        assert kwargs.get("is_joint") is False

    def test_exception_from_jog_is_swallowed(self, manager, mock_cnc):
        mock_cnc.jog.side_effect = Exception("Hardware failure")
        # Must not raise
        manager.start_jog(0, 1, _CONTINUOUS_MODE)

    def test_exception_is_logged_as_error(self, manager, mock_cnc):
        mock_cnc.jog.side_effect = Exception("Timeout")
        with patch("logic.managers.axis_manager.logger") as mock_log:
            manager.start_jog(0, 1, _CONTINUOUS_MODE)
            mock_log.error.assert_called_once()

    def test_invalid_increment_falls_back_to_continuous(self, manager, mock_cnc):
        manager.start_jog(0, 1, mode_text="bad_value")
        args = mock_cnc.jog.call_args[0]
        assert args[3] == 0.0   # increment falls back to continuous


# ===========================================================================
# AxisManager.stop_jog
# ===========================================================================

class TestStopJog:
    def test_stop_sent_in_continuous_mode(self, manager, mock_cnc):
        manager.stop_jog(axis_idx=0, mode_text=_CONTINUOUS_MODE)
        mock_cnc.stop_jog.assert_called_once_with(0, is_joint=False)

    def test_stop_not_sent_in_incremental_mode(self, manager, mock_cnc):
        manager.stop_jog(axis_idx=0, mode_text="0.1")
        mock_cnc.stop_jog.assert_not_called()

    def test_stop_not_sent_for_arbitrary_mode(self, manager, mock_cnc):
        manager.stop_jog(axis_idx=3, mode_text="step")
        mock_cnc.stop_jog.assert_not_called()

    def test_correct_axis_index_forwarded(self, manager, mock_cnc):
        manager.stop_jog(axis_idx=4, mode_text=_CONTINUOUS_MODE)
        mock_cnc.stop_jog.assert_called_once_with(4, is_joint=False)

    def test_is_joint_always_false(self, manager, mock_cnc):
        manager.stop_jog(0, _CONTINUOUS_MODE)
        _, kwargs = mock_cnc.stop_jog.call_args
        assert kwargs.get("is_joint") is False


# ===========================================================================
# AxisUIBinder – initialisation
# ===========================================================================

class TestAxisUIBinderInit:
    def test_stores_manager_reference(self, manager, mock_widgets):
        binder = AxisUIBinder(manager, mock_widgets)
        assert binder.manager is manager

    def test_stores_widgets_reference(self, manager, mock_widgets):
        binder = AxisUIBinder(manager, mock_widgets)
        assert binder.widgets is mock_widgets

    def test_slots_prevent_arbitrary_attributes(self, binder):
        with pytest.raises(AttributeError):
            binder.unexpected = "oops"

    def test_repr_contains_class_name(self, binder):
        assert "AxisUIBinder" in repr(binder)


# ===========================================================================
# AxisUIBinder.connect_buttons / _bind_axis_pair
# ===========================================================================

class TestConnectButtons:
    def test_all_plus_buttons_connected(self, binder, mock_widgets):
        binder.connect_buttons()
        for axis in _AXES:
            btn = getattr(mock_widgets, f"btn_{axis}_plus")
            btn.pressed.connect.assert_called_once()
            btn.released.connect.assert_called_once()

    def test_all_minus_buttons_connected(self, binder, mock_widgets):
        binder.connect_buttons()
        for axis in _AXES:
            btn = getattr(mock_widgets, f"btn_{axis}_minus")
            btn.pressed.connect.assert_called_once()
            btn.released.connect.assert_called_once()

    def test_missing_widget_is_skipped_silently(self, manager):
        """AxisUIBinder must not raise when a button is absent."""
        widgets = MagicMock(spec=[])          # no attributes at all
        binder = AxisUIBinder(manager, widgets)
        binder.connect_buttons()              # must not raise

    def test_partial_widgets_only_bind_present_buttons(self, manager):
        """Only X buttons present — others are silently skipped."""
        widgets = MagicMock(spec=["btn_x_plus", "btn_x_minus"])
        widgets.btn_x_plus  = MagicMock()
        widgets.btn_x_plus.pressed  = MagicMock()
        widgets.btn_x_plus.released = MagicMock()
        widgets.btn_x_minus = MagicMock()
        widgets.btn_x_minus.pressed  = MagicMock()
        widgets.btn_x_minus.released = MagicMock()

        binder = AxisUIBinder(manager, widgets)
        binder.connect_buttons()

        widgets.btn_x_plus.pressed.connect.assert_called_once()
        widgets.btn_x_minus.pressed.connect.assert_called_once()


# ===========================================================================
# AxisUIBinder._get_current_mode
# ===========================================================================

class TestGetCurrentMode:
    def test_returns_combo_text_when_present(self, binder, mock_widgets):
        mock_widgets.combo_axis_mode.currentText.return_value = "0.5"
        assert binder._get_current_mode() == "0.5"

    def test_returns_continuous_when_combo_absent(self, manager):
        widgets = MagicMock(spec=[])          # no combo_axis_mode
        binder = AxisUIBinder(manager, widgets)
        assert binder._get_current_mode() == _CONTINUOUS_MODE


# ===========================================================================
# AxisUIBinder._handle_press / _handle_release
# ===========================================================================

class TestHandlePressRelease:
    def test_handle_press_calls_start_jog(self, binder, mock_widgets):
        mock_widgets.combo_axis_mode.currentText.return_value = _CONTINUOUS_MODE
        binder._handle_press(axis_idx=0, direction=1)
        mock_cnc = binder.manager.cnc
        mock_cnc.jog.assert_called_once_with(0, 1, 1200.0, 0.0, is_joint=False)

    def test_handle_press_negative_direction(self, binder, mock_widgets):
        mock_widgets.combo_axis_mode.currentText.return_value = _CONTINUOUS_MODE
        binder._handle_press(axis_idx=2, direction=-1)
        args = binder.manager.cnc.jog.call_args[0]
        assert args[1] == -1

    def test_handle_release_calls_stop_jog_in_continuous(self, binder, mock_widgets):
        mock_widgets.combo_axis_mode.currentText.return_value = _CONTINUOUS_MODE
        binder._handle_release(axis_idx=1)
        binder.manager.cnc.stop_jog.assert_called_once_with(1, is_joint=False)

    def test_handle_release_no_stop_in_incremental(self, binder, mock_widgets):
        mock_widgets.combo_axis_mode.currentText.return_value = "0.1"
        binder._handle_release(axis_idx=1)
        binder.manager.cnc.stop_jog.assert_not_called()

    def test_handle_press_reads_current_mode(self, binder, mock_widgets):
        """Mode must be read at press time, not at bind time."""
        mock_widgets.combo_axis_mode.currentText.return_value = "1.0"
        binder._handle_press(0, 1)
        args = binder.manager.cnc.jog.call_args[0]
        assert args[3] == 1.0    # increment 1.0 was used