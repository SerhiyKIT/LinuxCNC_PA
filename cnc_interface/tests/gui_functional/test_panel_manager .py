# tests/gui_functional/test_panel_manager.py
"""
Функціональні GUI-тести PanelManager
======================================
Перевіряємо що реальні Qt-віджети змінюють свій стан
(isEnabled, isVisible, text, styleSheet) у відповідь на виклики менеджера.

Групи:
  1. E-Stop button          — 4 тести
  2. Power button           — 5 тестів
  3. Status display text    — 5 тестів
  4. Home button            — 3 тести
  5. Manual control panels  — 5 тестів
  6. GCode control panel    — 3 тести
"""

import pytest
from unittest.mock import patch
from PyQt5 import QtWidgets, QtCore

from tests.gui_functional.conftest import base_states, make_cnc


# ---------------------------------------------------------------------------
# Реальні Qt-віджети для PanelManager
# ---------------------------------------------------------------------------

class PanelWidgets(QtWidgets.QWidget):
    """Мінімальний контейнер з усіма реальними Qt-віджетами для PanelManager."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Machine state buttons
        self.btn_estop     = QtWidgets.QPushButton("E-STOP", self)
        self.btn_power_off = QtWidgets.QPushButton("OFF", self)
        self.btn_home_all  = QtWidgets.QPushButton("HOME ALL", self)

        # Status display
        self.txt_status_display = QtWidgets.QLabel("", self)

        # Panels — рамки і мітки
        self.frm_joint_control  = QtWidgets.QFrame(self)
        self.lbl_joint_control  = QtWidgets.QLabel("Joint Control", self)
        self.frm_axis_control   = QtWidgets.QFrame(self)
        self.lbl_axis_control   = QtWidgets.QLabel("Axis Control", self)
        self.frm_gcode_control  = QtWidgets.QFrame(self)
        self.lbl_gcode_control  = QtWidgets.QLabel("GCode Control", self)

        # Overlays — накладки блокування
        self.joint_control_overlay  = QtWidgets.QWidget(self)
        self.axis_control_overlay   = QtWidgets.QWidget(self)
        self.gcode_control_overlay  = QtWidgets.QWidget(self)


@pytest.fixture
def panel(qtbot):
    """Fixture: реальний PanelWidgets + PanelManager.

    widgets.show() + waitExposed() обов'язкові: isVisible() у Qt повертає True
    лише якщо весь ланцюжок батьківських віджетів видимий на екрані.
    Без цього навіть QPushButton всередині контейнера isVisible() == False.
    """
    widgets = PanelWidgets()
    qtbot.addWidget(widgets)
    widgets.show()
    qtbot.waitExposed(widgets)
    cnc = make_cnc()

    with patch("managers.ui.panel_manager.QCoreApplication.translate",
               side_effect=lambda ctx, key: key):
        from managers.ui.panel_manager import PanelManager
        mgr = PanelManager(cnc, widgets)

    return mgr, widgets


# ---------------------------------------------------------------------------
# Група 1: E-Stop button
# ---------------------------------------------------------------------------

class TestEstopButton:

    def test_estop_button_exists_and_is_visible(self, panel):
        """btn_estop існує і видимий після ініціалізації."""
        _, widgets = panel
        assert widgets.btn_estop.isVisible()

    def test_estop_active_changes_stylesheet(self, panel):
        """При estop_off=False stylesheet кнопки змінюється (≠ стан 'off')."""
        mgr, widgets = panel
        mgr.update_machine_state(base_states(estop_off=True))
        style_off = widgets.btn_estop.styleSheet()

        mgr.update_machine_state(base_states(estop_off=False))
        style_on = widgets.btn_estop.styleSheet()

        assert style_on != style_off

    def test_estop_inactive_restores_stylesheet(self, panel):
        """Після скидання ESTOP stylesheet повертається до стану 'off'."""
        mgr, widgets = panel
        mgr.update_machine_state(base_states(estop_off=False))
        mgr.update_machine_state(base_states(estop_off=True))
        assert "estop_on" not in widgets.btn_estop.styleSheet()

    def test_estop_stylesheet_changes_are_idempotent(self, panel):
        """Повторний виклик з тим самим станом не змінює stylesheet."""
        mgr, widgets = panel
        mgr.update_machine_state(base_states(estop_off=False))
        style_first = widgets.btn_estop.styleSheet()
        mgr.update_machine_state(base_states(estop_off=False))
        assert widgets.btn_estop.styleSheet() == style_first


# ---------------------------------------------------------------------------
# Група 2: Power button
# ---------------------------------------------------------------------------

class TestPowerButton:

    def test_power_button_disabled_when_estop_active(self, panel):
        """btn_power_off реально вимикається при estop_off=False."""
        mgr, widgets = panel
        mgr.update_machine_state(base_states(estop_off=False))
        assert not widgets.btn_power_off.isEnabled()

    def test_power_button_enabled_when_no_estop(self, panel):
        """btn_power_off реально вмикається при estop_off=True."""
        mgr, widgets = panel
        mgr.update_machine_state(base_states(estop_off=True, power_on=True))
        assert widgets.btn_power_off.isEnabled()

    def test_power_button_text_on(self, panel):
        """btn_power_off.text() == 'ON' коли power_on=True і estop_off=True."""
        mgr, widgets = panel
        with patch("managers.ui.panel_manager.QCoreApplication.translate",
                   side_effect=lambda ctx, key: key):
            mgr.update_machine_state(base_states(power_on=True, estop_off=True))
        assert widgets.btn_power_off.text() == "ON"

    def test_power_button_text_off(self, panel):
        """btn_power_off.text() == 'OFF' коли power_on=False."""
        mgr, widgets = panel
        with patch("managers.ui.panel_manager.QCoreApplication.translate",
                   side_effect=lambda ctx, key: key):
            mgr.update_machine_state(base_states(power_on=False, estop_off=True))
        assert widgets.btn_power_off.text() == "OFF"

    def test_power_stylesheet_changes_with_state(self, panel):
        """Stylesheet кнопки живлення різний для ON і OFF стану."""
        mgr, widgets = panel
        with patch("managers.ui.panel_manager.QCoreApplication.translate",
                   side_effect=lambda ctx, key: key):
            mgr.update_machine_state(base_states(power_on=True, estop_off=True))
            style_on = widgets.btn_power_off.styleSheet()
            mgr.update_machine_state(base_states(power_on=False, estop_off=True))
            style_off = widgets.btn_power_off.styleSheet()
        assert style_on != style_off


# ---------------------------------------------------------------------------
# Група 3: Status display text
# ---------------------------------------------------------------------------

class TestStatusDisplay:

    def _update(self, mgr, states):
        with patch("managers.ui.panel_manager.QCoreApplication.translate",
                   side_effect=lambda ctx, key: key):
            mgr.update_status_display(states)

    def test_shows_emergency_stop(self, panel):
        """Реальний QLabel отримує текст 'EMERGENCY STOP' при ESTOP."""
        mgr, widgets = panel
        self._update(mgr, base_states(estop_off=False))
        assert widgets.txt_status_display.text() == "EMERGENCY STOP"

    def test_shows_power_off(self, panel):
        """QLabel отримує 'POWER OFF' при power_on=False."""
        mgr, widgets = panel
        self._update(mgr, base_states(estop_off=True, power_on=False))
        assert widgets.txt_status_display.text() == "POWER OFF"

    def test_shows_homing_required(self, panel):
        """QLabel отримує 'HOMING REQUIRED' при all_homed=False."""
        mgr, widgets = panel
        self._update(mgr, base_states(estop_off=True, power_on=True, all_homed=False))
        assert widgets.txt_status_display.text() == "HOMING REQUIRED"

    def test_shows_system_ready(self, panel):
        """QLabel отримує 'SYSTEM READY' при повній готовності."""
        mgr, widgets = panel
        self._update(mgr, base_states())
        assert widgets.txt_status_display.text() == "SYSTEM READY"

    def test_status_transitions_correctly(self, panel):
        """Послідовність: ESTOP → POWER OFF → SYSTEM READY."""
        mgr, widgets = panel
        self._update(mgr, base_states(estop_off=False))
        assert widgets.txt_status_display.text() == "EMERGENCY STOP"
        self._update(mgr, base_states(estop_off=True, power_on=False))
        assert widgets.txt_status_display.text() == "POWER OFF"
        self._update(mgr, base_states())
        assert widgets.txt_status_display.text() == "SYSTEM READY"


# ---------------------------------------------------------------------------
# Група 4: Home button
# ---------------------------------------------------------------------------

class TestHomeButton:

    def test_home_button_enabled_when_ready(self, panel):
        """btn_home_all реально вмикається при is_ready=True."""
        mgr, widgets = panel
        mgr.update_home_button_state(base_states(is_ready=True))
        assert widgets.btn_home_all.isEnabled()

    def test_home_button_disabled_when_not_ready(self, panel):
        """btn_home_all реально вимикається при is_ready=False."""
        mgr, widgets = panel
        mgr.update_home_button_state(base_states(is_ready=False))
        assert not widgets.btn_home_all.isEnabled()

    def test_home_button_stylesheet_changes(self, panel):
        """Stylesheet home button різний для ready і not-ready."""
        mgr, widgets = panel
        mgr.update_home_button_state(base_states(is_ready=True))
        style_ready = widgets.btn_home_all.styleSheet()
        mgr.update_home_button_state(base_states(is_ready=False))
        style_inactive = widgets.btn_home_all.styleSheet()
        assert style_ready != style_inactive


# ---------------------------------------------------------------------------
# Група 5: Manual control panels (overlays)
# ---------------------------------------------------------------------------

class TestManualControlPanels:

    def test_joint_overlay_hidden_when_not_homed(self, panel):
        """joint_control_overlay прихований (joint panel видимий) коли not all_homed."""
        mgr, widgets = panel
        mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=False, is_running=False)
        )
        assert not widgets.joint_control_overlay.isVisible()

    def test_axis_overlay_hidden_in_axis_mode(self, panel):
        """axis_control_overlay прихований у axis-mode після homing."""
        mgr, widgets = panel
        mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True,
                        is_running=False, manual_mode="axis")
        )
        assert not widgets.axis_control_overlay.isVisible()

    def test_joint_overlay_hidden_in_joint_mode(self, panel):
        """joint_control_overlay прихований у joint-mode після homing."""
        mgr, widgets = panel
        mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True,
                        is_running=False, manual_mode="joint")
        )
        assert not widgets.joint_control_overlay.isVisible()

    def test_both_overlays_visible_when_not_ready(self, panel):
        """Обидва overlays видимі (панелі заблоковані) при is_ready=False.

        Використовуємо not isHidden() — точно відображає setVisible(True/False)
        незалежно від того чи батьківський віджет показаний.
        """
        mgr, widgets = panel
        # Спочатку приховуємо (встановлюємо стан 'ready') щоб overlay точно
        # пройшов через setVisible(True) у наступному виклику
        mgr.update_manual_controls(base_states(is_ready=True, all_homed=True,
                                               is_running=False, manual_mode="axis"))
        mgr.update_manual_controls(
            base_states(is_ready=False, is_running=False)
        )
        assert not widgets.joint_control_overlay.isHidden()
        assert not widgets.axis_control_overlay.isHidden()

    def test_both_overlays_visible_when_running(self, panel):
        """Обидва overlays видимі при is_running=True."""
        mgr, widgets = panel
        mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True, is_running=False,
                        manual_mode="axis")
        )
        mgr.update_manual_controls(
            base_states(is_ready=True, all_homed=True, is_running=True)
        )
        assert not widgets.joint_control_overlay.isHidden()
        assert not widgets.axis_control_overlay.isHidden()


# ---------------------------------------------------------------------------
# Група 6: GCode control panel overlay
# ---------------------------------------------------------------------------

class TestGcodeControlPanel:

    def test_overlay_hidden_when_ready(self, panel):
        """gcode_control_overlay прихований при is_ready=True."""
        mgr, widgets = panel
        mgr.update_gcode_controls(base_states(is_ready=True))
        assert not widgets.gcode_control_overlay.isVisible()

    def test_overlay_visible_when_not_ready(self, panel):
        """gcode_control_overlay видимий при is_ready=False.

        Спочатку встановлюємо ready=True (щоб overlay отримав setVisible(False)),
        потім ready=False — перевіряємо через not isHidden() що setVisible(True)
        було викликано.
        """
        mgr, widgets = panel
        mgr.update_gcode_controls(base_states(is_ready=True))
        mgr.update_gcode_controls(base_states(is_ready=False))
        assert not widgets.gcode_control_overlay.isHidden()

    def test_panel_label_stylesheet_changes(self, panel):
        """lbl_gcode_control stylesheet різний для active і inactive."""
        mgr, widgets = panel
        mgr._apply_panel_style("gcode_control", True)
        style_active = widgets.lbl_gcode_control.styleSheet()
        mgr._apply_panel_style("gcode_control", False)
        style_inactive = widgets.lbl_gcode_control.styleSheet()
        assert style_active != style_inactive
