"""
Tests for logic/managers/overrides_manager.py
  OverridesManager · OverridesUIBinder
==============================================

Run with:
    pytest test_overrides_manager.py -v

PyQt5.QtCore is mocked at module level so the suite runs without a display
server.  The mock is force-installed (not setdefault) and the production
module is flushed from sys.modules so it always re-imports against our mock,
regardless of test-suite execution order.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Mock PyQt5.QtCore BEFORE importing the module under test
# ---------------------------------------------------------------------------

_qt_core_mock = MagicMock()
# QCoreApplication.translate returns its second argument unchanged so labels
# can be asserted directly without involving the Qt translation machinery.
_qt_core_mock.QCoreApplication.translate.side_effect = lambda ctx, text: text

sys.modules["PyQt5"]           = MagicMock()
sys.modules["PyQt5.QtCore"]    = _qt_core_mock

for _mod_name in list(sys.modules):
    if "overrides_manager" in _mod_name and "test_" not in _mod_name:
        del sys.modules[_mod_name]

from logic.managers.overrides_manager import (  # noqa: E402
    OverridesManager,
    OverridesUIBinder,
    _SLIDER_CONFIG,
    _PRECISION_HIGH,
    _PRECISION_DEG,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    cnc = MagicMock()
    cnc.linear_jog_speed  = 0.0
    cnc.angular_jog_speed = 0.0
    return cnc


@pytest.fixture()
def manager(mock_cnc: MagicMock) -> OverridesManager:
    return OverridesManager(mock_cnc)


@pytest.fixture()
def mock_widgets() -> MagicMock:
    """Widget container with all sliders and labels pre-configured."""
    widgets = MagicMock()
    for sld_name, lbl_name, *_ in _SLIDER_CONFIG:
        slider = MagicMock()
        slider.value.return_value = 100
        slider.valueChanged = MagicMock()
        setattr(widgets, sld_name, slider)

        label = MagicMock()
        setattr(widgets, lbl_name, label)
    return widgets


@pytest.fixture()
def binder(manager: OverridesManager, mock_widgets: MagicMock) -> OverridesUIBinder:
    b = OverridesUIBinder(manager, mock_widgets)
    b.setup_overrides()
    return b


# ===========================================================================
# OverridesManager – initialisation
# ===========================================================================

class TestOverridesManagerInit:
    def test_stores_cnc_reference(self, mock_cnc):
        m = OverridesManager(mock_cnc)
        assert m.cnc is mock_cnc

    def test_slots_prevent_arbitrary_attributes(self, manager):
        with pytest.raises(AttributeError):
            manager.unexpected = "oops"

    def test_repr_contains_class_name(self, manager):
        assert "OverridesManager" in repr(manager)


# ===========================================================================
# OverridesManager – override forwarding
# ===========================================================================

class TestSetFeed:
    def test_forwards_to_cnc(self, manager, mock_cnc):
        manager.set_feed(1.25)
        mock_cnc.set_feed_override.assert_called_once_with(1.25)

    def test_zero_scale(self, manager, mock_cnc):
        manager.set_feed(0.0)
        mock_cnc.set_feed_override.assert_called_once_with(0.0)

    def test_exact_value_forwarded(self, manager, mock_cnc):
        manager.set_feed(1.5)
        args = mock_cnc.set_feed_override.call_args[0]
        assert args[0] == pytest.approx(1.5)


class TestSetRapid:
    def test_forwards_to_cnc(self, manager, mock_cnc):
        manager.set_rapid(0.5)
        mock_cnc.set_rapid_override.assert_called_once_with(0.5)

    def test_full_rate(self, manager, mock_cnc):
        manager.set_rapid(1.0)
        mock_cnc.set_rapid_override.assert_called_once_with(1.0)


class TestSetSpindle:
    def test_forwards_to_cnc(self, manager, mock_cnc):
        manager.set_spindle(1.0)
        mock_cnc.set_spindle_override.assert_called_once_with(1.0)

    def test_below_one(self, manager, mock_cnc):
        manager.set_spindle(0.75)
        mock_cnc.set_spindle_override.assert_called_once_with(0.75)


# ===========================================================================
# OverridesManager – jog speeds
# ===========================================================================

class TestSetLinearSpeed:
    def test_sets_attribute_on_cnc(self, manager, mock_cnc):
        manager.set_linear_speed(1500.0)
        assert mock_cnc.linear_jog_speed == 1500.0

    def test_zero_value(self, manager, mock_cnc):
        manager.set_linear_speed(0.0)
        assert mock_cnc.linear_jog_speed == 0.0

    def test_overwrites_previous_value(self, manager, mock_cnc):
        manager.set_linear_speed(100.0)
        manager.set_linear_speed(200.0)
        assert mock_cnc.linear_jog_speed == 200.0


class TestSetAngularSpeed:
    def test_sets_attribute_on_cnc(self, manager, mock_cnc):
        manager.set_angular_speed(45.5)
        assert mock_cnc.angular_jog_speed == 45.5

    def test_zero_value(self, manager, mock_cnc):
        manager.set_angular_speed(0.0)
        assert mock_cnc.angular_jog_speed == 0.0


# ===========================================================================
# OverridesManager – set_max_velocity
# ===========================================================================

class TestSetMaxVelocity:
    def test_forwards_to_cnc(self, manager, mock_cnc):
        manager.set_max_velocity(600.0)
        mock_cnc.set_max_velocity.assert_called_once_with(600.0)

    def test_zero_value(self, manager, mock_cnc):
        manager.set_max_velocity(0.0)
        mock_cnc.set_max_velocity.assert_called_once_with(0.0)

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.set_max_velocity.side_effect = Exception("Value out of range")
        manager.set_max_velocity(999999.0)   # must not raise

    def test_exception_is_logged_as_error(self, manager, mock_cnc, caplog):
        import logging
        mock_cnc.set_max_velocity.side_effect = Exception("out of range")
        with caplog.at_level(logging.ERROR):
            manager.set_max_velocity(999999.0)
        assert any("Max Velocity Update" in r.message for r in caplog.records)

    def test_cnc_not_called_after_exception(self, manager, mock_cnc):
        """After an exception the method must not attempt a second call."""
        mock_cnc.set_max_velocity.side_effect = Exception("fail")
        manager.set_max_velocity(1.0)
        assert mock_cnc.set_max_velocity.call_count == 1


# ===========================================================================
# OverridesUIBinder – initialisation
# ===========================================================================

class TestOverridesUIBinderInit:
    def test_stores_manager_reference(self, manager, mock_widgets):
        b = OverridesUIBinder(manager, mock_widgets)
        assert b.manager is manager

    def test_stores_widgets_reference(self, manager, mock_widgets):
        b = OverridesUIBinder(manager, mock_widgets)
        assert b.widgets is mock_widgets

    def test_configs_empty_before_setup(self, manager, mock_widgets):
        b = OverridesUIBinder(manager, mock_widgets)
        assert b._configs == {}

    def test_slots_prevent_arbitrary_attributes(self, binder):
        with pytest.raises(AttributeError):
            binder.unexpected = "oops"

    def test_repr_contains_class_name(self, binder):
        assert "OverridesUIBinder" in repr(binder)


# ===========================================================================
# OverridesUIBinder – setup_overrides
# ===========================================================================

class TestSetupOverrides:
    def test_configs_populated_after_setup(self, binder):
        assert len(binder._configs) == len(_SLIDER_CONFIG)

    def test_all_sliders_connected(self, binder, mock_widgets):
        for sld_name, *_ in _SLIDER_CONFIG:
            slider = getattr(mock_widgets, sld_name)
            slider.valueChanged.connect.assert_called_once()

    def test_initial_handle_change_called_per_slider(self, manager, mock_widgets):
        """Each slider must trigger one initial _handle_change on setup."""
        with patch.object(OverridesUIBinder, "_handle_change") as mock_hc:
            b = OverridesUIBinder(manager, mock_widgets)
            b.setup_overrides()
        assert mock_hc.call_count == len(_SLIDER_CONFIG)

    def test_missing_slider_skipped_silently(self, manager):
        """No sliders at all — setup_overrides must not raise."""
        b = OverridesUIBinder(manager, MagicMock(spec=[]))
        b.setup_overrides()

    def test_lambda_captures_correct_slider_name(self, manager, mock_widgets):
        """Verify each lambda passes its own slider name, not the last one."""
        b = OverridesUIBinder(manager, mock_widgets)
        b.setup_overrides()
        for sld_name, *_ in _SLIDER_CONFIG:
            slider = getattr(mock_widgets, sld_name)
            lambda_fn = slider.valueChanged.connect.call_args[0][0]
            with patch.object(OverridesUIBinder, "_handle_change") as mock_hc:
                lambda_fn(42)
            mock_hc.assert_called_once_with(sld_name, 42)

    def test_setup_idempotent_on_second_call(self, binder, mock_widgets):
        """Calling setup_overrides twice must reconnect cleanly."""
        binder.setup_overrides()
        assert len(binder._configs) == len(_SLIDER_CONFIG)


# ===========================================================================
# OverridesUIBinder – _handle_change
# ===========================================================================

class TestHandleChange:
    def test_scales_raw_value_by_divisor(self, binder, mock_cnc):
        """Feed slider: raw=150, divisor=100 → set_feed(1.5)."""
        binder._handle_change("sld_feed_override", 150)
        mock_cnc.set_feed_override.assert_called_with(pytest.approx(1.5))

    def test_linear_speed_divisor_1000(self, binder, mock_cnc):
        """Linear speed: raw=1234, divisor=1000 → set_linear_speed(1.234)."""
        binder._handle_change("sld_linear_jog_speed", 1234)
        assert mock_cnc.linear_jog_speed == pytest.approx(1.234)

    def test_max_velocity_divisor_1(self, binder, mock_cnc):
        """Max velocity: divisor=1 → value passes through unchanged."""
        binder._handle_change("sld_max_velocity", 500)
        mock_cnc.set_max_velocity.assert_called_with(pytest.approx(500.0))

    def test_dispatch_called_with_correct_method(self, binder):
        with patch.object(OverridesUIBinder, "_dispatch") as mock_d:
            binder._handle_change("sld_rapid_override", 50)
        mock_d.assert_called_once_with("set_rapid", pytest.approx(0.5))

    def test_update_label_called(self, binder):
        with patch.object(OverridesUIBinder, "_update_label") as mock_ul:
            binder._handle_change("sld_feed_override", 75)
        mock_ul.assert_called_once()

    def test_zero_raw_value(self, binder, mock_cnc):
        binder._handle_change("sld_feed_override", 0)
        mock_cnc.set_feed_override.assert_called_with(pytest.approx(0.0))


# ===========================================================================
# OverridesUIBinder – _dispatch
# ===========================================================================

class TestDispatch:
    def test_calls_manager_method_by_name(self, manager, mock_widgets, mock_cnc):
        # Use a fresh binder without setup_overrides to avoid prior calls
        b = OverridesUIBinder(manager, mock_widgets)
        b._configs = {
            sld: (lbl, div, m, u)
            for sld, lbl, div, m, u in _SLIDER_CONFIG
        }
        b._dispatch("set_feed", 1.25)
        mock_cnc.set_feed_override.assert_called_once_with(1.25)

    def test_dispatches_all_manager_methods(self, binder, mock_cnc):
        calls = [
            ("set_feed",         "set_feed_override",   0.5),
            ("set_rapid",        "set_rapid_override",  0.75),
            ("set_spindle",      "set_spindle_override",1.0),
            ("set_max_velocity", "set_max_velocity",    200.0),
        ]
        for method_name, cnc_attr, value in calls:
            binder._dispatch(method_name, value)
            getattr(mock_cnc, cnc_attr).assert_called_with(value)

    def test_dispatches_linear_speed(self, binder, mock_cnc):
        binder._dispatch("set_linear_speed", 750.0)
        assert mock_cnc.linear_jog_speed == 750.0

    def test_dispatches_angular_speed(self, binder, mock_cnc):
        binder._dispatch("set_angular_speed", 30.0)
        assert mock_cnc.angular_jog_speed == 30.0


# ===========================================================================
# OverridesUIBinder – _format_value
# ===========================================================================

class TestFormatValue:
    @pytest.mark.parametrize("raw, actual, divisor, unit_tpl, expected", [
        # divisor == 1000 → 3 decimal places
        (1234, 1.234,  1000.0, "%1 in/min",  "1.234"),
        (600,  0.6,    1000.0, "%1 in/min",  "0.600"),
        # "deg" in unit → 2 decimal places
        (150,  1.5,    100.0,  "%1 deg/min", "1.50"),
        (100,  1.0,    100.0,  "%1 deg/min", "1.00"),
        # plain integer (raw value)
        (75,   0.75,   100.0,  "%1 %",       "75"),
        (100,  1.0,    100.0,  "%1 %",       "100"),
        (500,  500.0,  1.0,    "%1 in/min",  "500"),
        (0,    0.0,    100.0,  "%1 %",       "0"),
    ])
    def test_parametrized(self, raw, actual, divisor, unit_tpl, expected):
        result = OverridesUIBinder._format_value(raw, actual, divisor, unit_tpl)
        assert result == expected

    def test_high_precision_takes_priority_over_deg(self):
        """divisor=1000 wins even if unit also contains 'deg'."""
        result = OverridesUIBinder._format_value(1500, 1.5, 1000.0, "%1 deg/min")
        assert result == "1.500"


# ===========================================================================
# OverridesUIBinder – _update_label
# ===========================================================================

class TestUpdateLabel:
    def test_sets_text_on_label(self, binder, mock_widgets):
        mock_widgets.val_feed_override.setText.reset_mock()
        binder._update_label("val_feed_override", 75, 0.75, 100.0, "%1 %")
        mock_widgets.val_feed_override.setText.assert_called_once_with("75 %")

    def test_missing_label_skipped_silently(self, binder):
        """No label present — must not raise."""
        binder._update_label("nonexistent_label", 75, 0.75, 100.0, "%1 %")

    def test_linear_speed_label_has_three_decimals(self, binder, mock_widgets):
        mock_widgets.val_linear_jog_speed.setText.reset_mock()
        binder._update_label("val_linear_jog_speed", 1500, 1.5, 1000.0, "%1 in/min")
        mock_widgets.val_linear_jog_speed.setText.assert_called_once_with("1.500 in/min")

    def test_angular_speed_label_has_two_decimals(self, binder, mock_widgets):
        mock_widgets.val_angular_jog_speed.setText.reset_mock()
        binder._update_label("val_angular_jog_speed", 150, 1.5, 100.0, "%1 deg/min")
        mock_widgets.val_angular_jog_speed.setText.assert_called_once_with("1.50 deg/min")

    def test_translate_called_with_unit_template(self, binder, mock_widgets):
        _qt_core_mock.QCoreApplication.translate.reset_mock()
        binder._update_label("val_feed_override", 100, 1.0, 100.0, "%1 %")
        _qt_core_mock.QCoreApplication.translate.assert_called_with("MainWindow", "%1 %")


# ===========================================================================
# OverridesUIBinder – refresh_all_labels
# ===========================================================================

class TestRefreshAllLabels:
    def test_reads_current_slider_value(self, binder, mock_widgets):
        for sld_name, *_ in _SLIDER_CONFIG:
            getattr(mock_widgets, sld_name).value.return_value = 50

        with patch.object(OverridesUIBinder, "_handle_change") as mock_hc:
            binder.refresh_all_labels()

        assert mock_hc.call_count == len(_SLIDER_CONFIG)
        for c in mock_hc.call_args_list:
            assert c[0][1] == 50   # args = (name, raw_value), raw_value at index 1

    def test_missing_slider_skipped(self, manager):
        b = OverridesUIBinder(manager, MagicMock(spec=[]))
        b.setup_overrides()
        b.refresh_all_labels()   # must not raise

    def test_calls_handle_change_for_each_config(self, binder):
        with patch.object(OverridesUIBinder, "_handle_change") as mock_hc:
            binder.refresh_all_labels()
        assert mock_hc.call_count == len(_SLIDER_CONFIG)