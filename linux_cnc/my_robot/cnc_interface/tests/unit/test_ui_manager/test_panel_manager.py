# tests/gui/test_panel_manager.py
"""
Unit-тести PanelManager
=========================
Групи:
  1. update_machine_state    — 7 тестів
  2. update_status_display   — 6 тестів
  3. update_home_button_state — 2 тести
  4. update_manual_controls  — 5 тестів
  5. update_gcode_controls + _apply_panel_style — 6 тестів
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.unit.test_ui_manager.conftest import base_states


@pytest.fixture
def panel_mgr(mock_cnc, mock_widgets):
    with patch("managers.ui.panel_manager.StyleManager") as MockStyle:
        sm = MockStyle.return_value
        sm.STYLE_ESTOP_ON       = "estop_on"
        sm.STYLE_ESTOP_OFF      = "estop_off"
        sm.STYLE_POWER_ON       = "power_on"
        sm.STYLE_POWER_OFF      = "power_off"
        sm.STYLE_HOME_READY     = "home_ready"
        sm.STYLE_HOME_INACTIVE  = "home_inactive"
        sm.PANEL_LABEL_ACTIVE   = "label_active"
        sm.PANEL_LABEL_INACTIVE = "label_inactive"
        sm.PANEL_FRAME_ACTIVE   = "frame_active"
        sm.PANEL_FRAME_INACTIVE = "frame_inactive"
        from managers.ui.panel_manager import PanelManager
        yield PanelManager(mock_cnc, mock_widgets)


# ---------------------------------------------------------------------------
# Група 1: update_machine_state
# ---------------------------------------------------------------------------

class TestUpdateMachineState:

    def test_estop_on_style_when_active(self, panel_mgr, mock_widgets):
        """btn_estop отримує ESTOP_ON стиль при estop_off=False."""
        panel_mgr.update_machine_state(base_states(estop_off=False))
        mock_widgets.btn_estop.setStyleSheet.assert_called_with("estop_on")

    def test_estop_off_style_when_inactive(self, panel_mgr, mock_widgets):
        """btn_estop отримує ESTOP_OFF стиль при estop_off=True."""
        panel_mgr.update_machine_state(base_states(estop_off=True))
        mock_widgets.btn_estop.setStyleSheet.assert_called_with("estop_off")

    def test_power_disabled_when_estop_active(self, panel_mgr, mock_widgets):
        """btn_power_off вимкнений при активному ESTOP."""
        panel_mgr.update_machine_state(base_states(estop_off=False))
        mock_widgets.btn_power_off.setEnabled.assert_called_with(False)

    def test_power_enabled_when_no_estop(self, panel_mgr, mock_widgets):
        """btn_power_off увімкнений коли немає ESTOP."""
        panel_mgr.update_machine_state(base_states(estop_off=True))
        mock_widgets.btn_power_off.setEnabled.assert_called_with(True)

    def test_power_on_style_when_powered(self, panel_mgr, mock_widgets):
        """btn_power_off отримує POWER_ON стиль при power_on=True і estop_off=True."""
        panel_mgr.update_machine_state(base_states(power_on=True, estop_off=True))
        mock_widgets.btn_power_off.setStyleSheet.assert_called_with("power_on")

    def test_power_off_style_when_not_powered(self, panel_mgr, mock_widgets):
        """btn_power_off отримує POWER_OFF стиль при power_on=False."""
        panel_mgr.update_machine_state(base_states(power_on=False))
        mock_widgets.btn_power_off.setStyleSheet.assert_called_with("power_off")

    def test_no_crash_when_buttons_absent(self, panel_mgr):
        """update_machine_state не падає коли кнопки відсутні (spec=[])."""
        panel_mgr.widgets = MagicMock(spec=[])
        panel_mgr.update_machine_state(base_states())


# ---------------------------------------------------------------------------
# Група 2: update_status_display
# ---------------------------------------------------------------------------

class TestUpdateStatusDisplay:

    def _call(self, panel_mgr, states):
        with patch("managers.ui.panel_manager.QCoreApplication.translate",
                   side_effect=lambda ctx, key: key):
            panel_mgr.update_status_display(states)

    def test_shows_emergency_stop(self, panel_mgr, mock_widgets):
        """EMERGENCY STOP при estop_off=False."""
        self._call(panel_mgr, base_states(estop_off=False))
        mock_widgets.txt_status_display.setText.assert_called_with("EMERGENCY STOP")

    def test_shows_power_off(self, panel_mgr, mock_widgets):
        """POWER OFF при estop_off=True, power_on=False."""
        self._call(panel_mgr, base_states(estop_off=True, power_on=False))
        mock_widgets.txt_status_display.setText.assert_called_with("POWER OFF")

    def test_shows_homing_required(self, panel_mgr, mock_widgets):
        """HOMING REQUIRED при power_on=True і all_homed=False."""
        self._call(panel_mgr, base_states(estop_off=True, power_on=True, all_homed=False))
        mock_widgets.txt_status_display.setText.assert_called_with("HOMING REQUIRED")

    def test_shows_system_ready(self, panel_mgr, mock_widgets):
        """SYSTEM READY при всіх умовах виконані."""
        self._call(panel_mgr, base_states())
        mock_widgets.txt_status_display.setText.assert_called_with("SYSTEM READY")

    def test_estop_has_priority_over_power_off(self, panel_mgr, mock_widgets):
        """ESTOP має пріоритет над POWER OFF."""
        self._call(panel_mgr, base_states(estop_off=False, power_on=False))
        mock_widgets.txt_status_display.setText.assert_called_with("EMERGENCY STOP")

    def test_no_crash_when_display_absent(self, panel_mgr, mock_widgets):
        """update_status_display не падає без txt_status_display."""
        mock_widgets.txt_status_display = None
        self._call(panel_mgr, base_states())


# ---------------------------------------------------------------------------
# Група 3: update_home_button_state
# ---------------------------------------------------------------------------

class TestUpdateHomeButtonState:

    def test_enabled_and_ready_style_when_ready(self, panel_mgr, mock_widgets):
        """btn_home_all увімкнений та HOME_READY стиль при is_ready=True."""
        panel_mgr.update_home_button_state(base_states(is_ready=True))
        mock_widgets.btn_home_all.setEnabled.assert_called_with(True)
        mock_widgets.btn_home_all.setStyleSheet.assert_called_with("home_ready")

    def test_disabled_and_inactive_style_when_not_ready(self, panel_mgr, mock_widgets):
        """btn_home_all вимкнений та HOME_INACTIVE стиль при is_ready=False."""
        panel_mgr.update_home_button_state(base_states(is_ready=False))
        mock_widgets.btn_home_all.setEnabled.assert_called_with(False)
        mock_widgets.btn_home_all.setStyleSheet.assert_called_with("home_inactive")


# ---------------------------------------------------------------------------
# Група 4: update_manual_controls
# ---------------------------------------------------------------------------

class TestUpdateManualControls:

    def test_shows_joints_when_not_homed(self, panel_mgr, mock_widgets):
        """joint_control_overlay прихований (panel visible) коли not all_homed."""
        panel_mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=False, is_running=False)
        )
        mock_widgets.joint_control_overlay.setVisible.assert_called_with(False)
        mock_widgets.axis_control_overlay.setVisible.assert_called_with(True)

    def test_shows_axis_when_homed_and_axis_mode(self, panel_mgr, mock_widgets):
        """axis_control_overlay прихований при all_homed=True, manual_mode='axis'."""
        panel_mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True,
                        is_running=False, manual_mode="axis")
        )
        mock_widgets.axis_control_overlay.setVisible.assert_called_with(False)
        mock_widgets.joint_control_overlay.setVisible.assert_called_with(True)

    def test_shows_joint_when_homed_and_joint_mode(self, panel_mgr, mock_widgets):
        """joint_control_overlay прихований при manual_mode='joint'."""
        panel_mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True,
                        is_running=False, manual_mode="joint")
        )
        mock_widgets.joint_control_overlay.setVisible.assert_called_with(False)
        mock_widgets.axis_control_overlay.setVisible.assert_called_with(True)

    def test_hides_both_when_not_ready(self, panel_mgr, mock_widgets):
        """Обидва overlays видимі (панелі приховані) коли is_ready=False."""
        panel_mgr.update_manual_controls(
            base_states(is_ready=False, all_homed=True, is_running=False)
        )
        mock_widgets.joint_control_overlay.setVisible.assert_called_with(True)
        mock_widgets.axis_control_overlay.setVisible.assert_called_with(True)

    def test_hides_both_when_running(self, panel_mgr, mock_widgets):
        """Обидва overlays видимі під час виконання програми."""
        panel_mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True, is_running=True)
        )
        mock_widgets.joint_control_overlay.setVisible.assert_called_with(True)
        mock_widgets.axis_control_overlay.setVisible.assert_called_with(True)


# ---------------------------------------------------------------------------
# Група 5: update_gcode_controls + _apply_panel_style
# ---------------------------------------------------------------------------

class TestUpdateGcodeControls:

    def test_overlay_hidden_when_ready(self, panel_mgr, mock_widgets):
        """gcode_control_overlay прихований при is_ready=True."""
        panel_mgr.update_gcode_controls(base_states(is_ready=True))
        mock_widgets.gcode_control_overlay.setVisible.assert_called_with(False)

    def test_overlay_visible_when_not_ready(self, panel_mgr, mock_widgets):
        """gcode_control_overlay видимий при is_ready=False."""
        panel_mgr.update_gcode_controls(base_states(is_ready=False))
        mock_widgets.gcode_control_overlay.setVisible.assert_called_with(True)

    def test_apply_panel_style_label_active(self, panel_mgr, mock_widgets):
        """_apply_panel_style(True) → PANEL_LABEL_ACTIVE на lbl_."""
        panel_mgr._apply_panel_style("gcode_control", True)
        mock_widgets.lbl_gcode_control.setStyleSheet.assert_called_with("label_active")

    def test_apply_panel_style_label_inactive(self, panel_mgr, mock_widgets):
        """_apply_panel_style(False) → PANEL_LABEL_INACTIVE на lbl_."""
        panel_mgr._apply_panel_style("gcode_control", False)
        mock_widgets.lbl_gcode_control.setStyleSheet.assert_called_with("label_inactive")

    def test_apply_panel_style_frame_active(self, panel_mgr, mock_widgets):
        """_apply_panel_style(True) → PANEL_FRAME_ACTIVE на frm_."""
        panel_mgr._apply_panel_style("gcode_control", True)
        mock_widgets.frm_gcode_control.setStyleSheet.assert_called_with("frame_active")

    def test_apply_panel_style_frame_inactive(self, panel_mgr, mock_widgets):
        """_apply_panel_style(False) → PANEL_FRAME_INACTIVE на frm_."""
        panel_mgr._apply_panel_style("gcode_control", False)
        mock_widgets.frm_gcode_control.setStyleSheet.assert_called_with("frame_inactive")
