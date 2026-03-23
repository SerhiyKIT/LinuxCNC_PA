# tests/gui/test_tool_display.py
"""
Unit-тести ToolDisplayManager
================================
Групи:
  1. update_tool_ui_state — 9 тестів
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.unit.test_ui_manager.conftest import base_states


@pytest.fixture
def tool_mgr(mock_cnc, mock_widgets):
    with patch("managers.ui.tool_display.StyleManager"):
        from managers.ui.tool_display import ToolDisplayManager
        mgr = ToolDisplayManager(mock_cnc, mock_widgets)
        # on_btn_tool_arm_clicked відсутній в ToolDisplayManager —
        # підключається ззовні через main_logic. Додаємо mock для тестів.
        mgr.on_btn_tool_arm_clicked = MagicMock()
        yield mgr


# ---------------------------------------------------------------------------
# Група 1: update_tool_ui_state
# ---------------------------------------------------------------------------

class TestUpdateToolUiState:

    def test_action_enabled_when_tool_ready(self, tool_mgr, mock_widgets):
        """btn_tool_action увімкнений при tool_ready і not is_running."""
        tool_mgr.update_tool_ui_state(base_states(is_running=False))
        mock_widgets.btn_tool_action.setEnabled.assert_called_with(True)

    def test_action_disabled_when_running(self, tool_mgr, mock_widgets):
        """btn_tool_action вимкнений під час виконання програми."""
        tool_mgr.update_tool_ui_state(base_states(is_running=True))
        mock_widgets.btn_tool_action.setEnabled.assert_called_with(False)

    def test_action_disabled_when_estop(self, tool_mgr, mock_widgets):
        """btn_tool_action вимкнений при ESTOP (tool_ready=False)."""
        tool_mgr.update_tool_ui_state(
            base_states(estop_off=False, power_on=True,
                        all_homed=True, is_running=False)
        )
        mock_widgets.btn_tool_action.setEnabled.assert_called_with(False)

    def test_slider_enabled_when_tool_ready(self, tool_mgr, mock_widgets):
        """sld_tool_power увімкнений при tool_ready і not running."""
        tool_mgr.update_tool_ui_state(base_states(is_running=False))
        mock_widgets.sld_tool_power.setEnabled.assert_called_with(True)

    def test_slider_disabled_when_not_homed(self, tool_mgr, mock_widgets):
        """sld_tool_power вимкнений якщо not all_homed."""
        tool_mgr.update_tool_ui_state(
            base_states(all_homed=False, is_running=False)
        )
        mock_widgets.sld_tool_power.setEnabled.assert_called_with(False)

    def test_arm_enabled_when_powered_no_estop(self, tool_mgr, mock_widgets):
        """btn_tool_arm увімкнений при power_on=True і estop_off=True."""
        tool_mgr.update_tool_ui_state(base_states())
        mock_widgets.btn_tool_arm.setEnabled.assert_called_with(True)

    def test_arm_disabled_when_estop(self, tool_mgr, mock_widgets):
        """btn_tool_arm вимкнений при estop_off=False."""
        tool_mgr.update_tool_ui_state(
            base_states(estop_off=False, power_on=True)
        )
        mock_widgets.btn_tool_arm.setEnabled.assert_called_with(False)

    def test_auto_disarm_when_estop_activated(self, tool_mgr, mock_widgets):
        """isChecked=True при ESTOP → setChecked(False) + on_btn_tool_arm_clicked."""
        mock_widgets.btn_tool_arm.isChecked.return_value = True
        tool_mgr.update_tool_ui_state(
            base_states(estop_off=False, power_on=True)
        )
        mock_widgets.btn_tool_arm.setChecked.assert_called_with(False)
        tool_mgr.on_btn_tool_arm_clicked.assert_called_once()

    def test_no_disarm_when_estop_not_active(self, tool_mgr, mock_widgets):
        """setChecked НЕ викликається якщо ESTOP не активний."""
        mock_widgets.btn_tool_arm.isChecked.return_value = True
        tool_mgr.update_tool_ui_state(base_states(estop_off=True))
        mock_widgets.btn_tool_arm.setChecked.assert_not_called()
