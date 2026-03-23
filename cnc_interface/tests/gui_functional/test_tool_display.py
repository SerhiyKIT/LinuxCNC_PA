# tests/gui_functional/test_tool_display.py
"""
Функціональні GUI-тести ToolDisplayManager
===========================================
Реальні Qt-віджети: QPushButton (checkable arm), QPushButton (action), QSlider.
cnc — MagicMock.

Групи:
  1. Arm button enable/disable     — 4 тести
  2. Action button enable/disable  — 4 тести
  3. Power slider enable/disable   — 3 тести
  4. Auto-disarm on E-Stop         — 3 тести
"""

import pytest
from unittest.mock import MagicMock
from PyQt5 import QtWidgets, QtCore

from tests.gui_functional.conftest import base_states, make_cnc


# ---------------------------------------------------------------------------
# Реальні Qt-віджети
# ---------------------------------------------------------------------------

class ToolWidgets(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.btn_tool_arm    = QtWidgets.QPushButton("ARM TOOL", self)
        self.btn_tool_arm.setCheckable(True)
        self.btn_tool_action = QtWidgets.QPushButton("GRIP", self)
        self.sld_tool_power  = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.sld_tool_power.setRange(0, 100)
        self.sld_tool_power.setValue(50)


@pytest.fixture
def tool(qtbot):
    widgets = ToolWidgets()
    qtbot.addWidget(widgets)
    cnc = make_cnc()
    from managers.ui.tool_display import ToolDisplayManager
    mgr = ToolDisplayManager(cnc, widgets)
    # on_btn_tool_arm_clicked — зовнішній хендлер, підключається з main_logic
    mgr.on_btn_tool_arm_clicked = MagicMock()
    return mgr, widgets


# ---------------------------------------------------------------------------
# Група 1: Arm button enable/disable
# ---------------------------------------------------------------------------

class TestArmButtonState:

    def test_arm_enabled_when_powered_and_no_estop(self, tool):
        """btn_tool_arm реально enabled при power_on=True, estop_off=True."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(power_on=True, estop_off=True))
        assert widgets.btn_tool_arm.isEnabled()

    def test_arm_disabled_when_estop_active(self, tool):
        """btn_tool_arm реально disabled при estop_off=False."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(estop_off=False, power_on=True))
        assert not widgets.btn_tool_arm.isEnabled()

    def test_arm_disabled_when_power_off(self, tool):
        """btn_tool_arm реально disabled при power_on=False."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(power_on=False, estop_off=True))
        assert not widgets.btn_tool_arm.isEnabled()

    def test_arm_enabled_state_transitions(self, tool):
        """Послідовність: disabled (ESTOP) → enabled (no ESTOP)."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(estop_off=False, power_on=True))
        assert not widgets.btn_tool_arm.isEnabled()
        mgr.update_tool_ui_state(base_states(estop_off=True, power_on=True))
        assert widgets.btn_tool_arm.isEnabled()


# ---------------------------------------------------------------------------
# Група 2: Action button enable/disable
# ---------------------------------------------------------------------------

class TestActionButtonState:

    def test_action_enabled_when_tool_ready_and_not_running(self, tool):
        """btn_tool_action реально enabled при tool_ready і not is_running."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(is_running=False))
        assert widgets.btn_tool_action.isEnabled()

    def test_action_disabled_when_running(self, tool):
        """btn_tool_action реально disabled під час виконання програми."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(is_running=True))
        assert not widgets.btn_tool_action.isEnabled()

    def test_action_disabled_when_not_homed(self, tool):
        """btn_tool_action реально disabled якщо all_homed=False."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(
            base_states(all_homed=False, is_running=False)
        )
        assert not widgets.btn_tool_action.isEnabled()

    def test_action_disabled_on_estop(self, tool):
        """btn_tool_action реально disabled при ESTOP."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(
            base_states(estop_off=False, power_on=True,
                        all_homed=True, is_running=False)
        )
        assert not widgets.btn_tool_action.isEnabled()


# ---------------------------------------------------------------------------
# Група 3: Power slider enable/disable
# ---------------------------------------------------------------------------

class TestPowerSliderState:

    def test_slider_enabled_when_tool_ready(self, tool):
        """sld_tool_power реально enabled при tool_ready і not running."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(is_running=False))
        assert widgets.sld_tool_power.isEnabled()

    def test_slider_disabled_when_not_homed(self, tool):
        """sld_tool_power реально disabled якщо not all_homed."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(all_homed=False, is_running=False))
        assert not widgets.sld_tool_power.isEnabled()

    def test_slider_disabled_when_running(self, tool):
        """sld_tool_power реально disabled під час виконання."""
        mgr, widgets = tool
        mgr.update_tool_ui_state(base_states(is_running=True))
        assert not widgets.sld_tool_power.isEnabled()


# ---------------------------------------------------------------------------
# Група 4: Auto-disarm on E-Stop
# ---------------------------------------------------------------------------

class TestAutoDisarmOnEstop:

    def test_arm_button_unchecked_on_estop(self, tool, qtbot):
        """btn_tool_arm.isChecked() стає False при активації ESTOP."""
        mgr, widgets = tool
        # Симулюємо armed стан: кнопка checked
        widgets.btn_tool_arm.setChecked(True)
        assert widgets.btn_tool_arm.isChecked()

        mgr.update_tool_ui_state(base_states(estop_off=False, power_on=True))

        assert not widgets.btn_tool_arm.isChecked()

    def test_arm_handler_called_on_auto_disarm(self, tool):
        """on_btn_tool_arm_clicked() викликається при auto-disarm."""
        mgr, widgets = tool
        widgets.btn_tool_arm.setChecked(True)

        mgr.update_tool_ui_state(base_states(estop_off=False, power_on=True))

        mgr.on_btn_tool_arm_clicked.assert_called_once()

    def test_no_disarm_when_already_unchecked(self, tool):
        """on_btn_tool_arm_clicked НЕ викликається якщо кнопка не checked."""
        mgr, widgets = tool
        widgets.btn_tool_arm.setChecked(False)

        mgr.update_tool_ui_state(base_states(estop_off=False, power_on=True))

        mgr.on_btn_tool_arm_clicked.assert_not_called()
