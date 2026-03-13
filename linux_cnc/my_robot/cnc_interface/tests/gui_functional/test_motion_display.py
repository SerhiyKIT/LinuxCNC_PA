# tests/gui_functional/test_motion_display.py
"""
Функціональні GUI-тести MotionDisplayManager
=============================================
Реальні Qt-віджети: QLabel (координати), QPushButton (jog ±).
cnc — MagicMock.

Групи:
  1. Coordinate labels update  — 7 тестів
  2. Soft limit jog buttons    — 7 тестів
  3. Edge cases                — 3 тести
"""

import pytest
from PyQt5 import QtWidgets

from tests.gui_functional.conftest import base_states, make_cnc


# ---------------------------------------------------------------------------
# Реальні Qt-віджети
# ---------------------------------------------------------------------------

class MotionWidgets(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Joint position labels
        for i in range(6):
            setattr(self, f"txt_j{i}_pos", QtWidgets.QLabel("0.0000", self))
        # World position labels
        for axis in ("x", "y", "z", "a", "b", "c"):
            setattr(self, f"txt_{axis}_pos", QtWidgets.QLabel("0.0000", self))
        # Jog buttons for each joint
        for i in range(6):
            setattr(self, f"btn_j{i}_plus",  QtWidgets.QPushButton(f"J{i}+", self))
            setattr(self, f"btn_j{i}_minus", QtWidgets.QPushButton(f"J{i}-", self))


@pytest.fixture
def motion(qtbot):
    widgets = MotionWidgets()
    qtbot.addWidget(widgets)
    cnc = make_cnc()
    from managers.ui.motion_display import MotionDisplayManager
    mgr = MotionDisplayManager(cnc, widgets)
    return mgr, widgets


# ---------------------------------------------------------------------------
# Група 1: Coordinate labels update
# ---------------------------------------------------------------------------

class TestCoordinateLabels:

    def test_joint_label_updated_on_first_call(self, motion):
        """txt_j0_pos.text() оновлюється при першому виклику."""
        mgr, widgets = motion
        mgr.update_coordinates(
            base_states(joint_position=[12.3456, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert widgets.txt_j0_pos.text() == "12.3456"

    def test_all_6_joint_labels_updated(self, motion):
        """Всі 6 joint labels оновлюються одночасно."""
        mgr, widgets = motion
        positions = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        mgr.update_coordinates(base_states(joint_position=positions))
        for i, expected in enumerate(positions):
            label = getattr(widgets, f"txt_j{i}_pos")
            assert label.text() == f"{expected:.4f}", \
                f"txt_j{i}_pos: expected {expected:.4f}, got {label.text()}"

    def test_world_label_x_updated(self, motion):
        """txt_x_pos.text() оновлюється при зміні actual_position[0]."""
        mgr, widgets = motion
        pos = [55.1234, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        mgr.update_coordinates(base_states(actual_position=pos))
        assert widgets.txt_x_pos.text() == "55.1234"

    def test_world_labels_xyz_updated(self, motion):
        """txt_x/y/z_pos оновлюються одночасно."""
        mgr, widgets = motion
        pos = [10.0, 20.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        mgr.update_coordinates(base_states(actual_position=pos))
        assert widgets.txt_x_pos.text() == "10.0000"
        assert widgets.txt_y_pos.text() == "20.0000"
        assert widgets.txt_z_pos.text() == "30.0000"

    def test_label_not_updated_when_value_unchanged(self, motion):
        """txt_j0_pos.text() не змінюється при повторному виклику без змін."""
        mgr, widgets = motion
        states = base_states(joint_position=[5.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        mgr.update_coordinates(states)
        text_before = widgets.txt_j0_pos.text()
        mgr.update_coordinates(states)
        assert widgets.txt_j0_pos.text() == text_before

    def test_label_updated_when_value_changes(self, motion):
        """txt_j0_pos.text() оновлюється коли значення значно змінилось."""
        mgr, widgets = motion
        mgr.update_coordinates(
            base_states(joint_position=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mgr.update_coordinates(
            base_states(joint_position=[90.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert widgets.txt_j0_pos.text() == "90.0000"

    def test_label_has_4_decimal_places(self, motion):
        """Текст label завжди має рівно 4 знаки після коми."""
        mgr, widgets = motion
        mgr.update_coordinates(
            base_states(joint_position=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        text = widgets.txt_j0_pos.text()
        integer, decimal = text.split(".")
        assert len(decimal) == 4


# ---------------------------------------------------------------------------
# Група 2: Soft limit jog buttons
# ---------------------------------------------------------------------------

class TestSoftLimitJogButtons:

    def test_plus_button_disabled_at_max_limit(self, motion):
        """btn_j0_plus реально disabled при pos >= max (180.0)."""
        mgr, widgets = motion
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True,
                        joint_position=[180.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert not widgets.btn_j0_plus.isEnabled()

    def test_plus_button_enabled_below_max_limit(self, motion):
        """btn_j0_plus реально enabled при pos < max."""
        mgr, widgets = motion
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True,
                        joint_position=[90.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert widgets.btn_j0_plus.isEnabled()

    def test_minus_button_disabled_at_min_limit(self, motion):
        """btn_j0_minus реально disabled при pos <= min (-180.0)."""
        mgr, widgets = motion
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True,
                        joint_position=[-180.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert not widgets.btn_j0_minus.isEnabled()

    def test_minus_button_enabled_above_min_limit(self, motion):
        """btn_j0_minus реально enabled при pos > min."""
        mgr, widgets = motion
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True,
                        joint_position=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert widgets.btn_j0_minus.isEnabled()

    def test_buttons_not_changed_when_not_ready(self, motion):
        """При is_ready=False кнопки залишаються у своєму початковому стані."""
        mgr, widgets = motion
        # Початковий стан — enabled (за замовчуванням QPushButton)
        assert widgets.btn_j0_plus.isEnabled()
        mgr._handle_joint_soft_limits(base_states(is_ready=False))
        # Не змінились
        assert widgets.btn_j0_plus.isEnabled()

    def test_all_plus_buttons_enabled_within_limits(self, motion):
        """Всі btn_jN_plus enabled при позиціях в межах."""
        mgr, widgets = motion
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True, joint_position=[0.0] * 6)
        )
        for i in range(6):
            assert getattr(widgets, f"btn_j{i}_plus").isEnabled(), \
                f"btn_j{i}_plus повинен бути enabled"

    def test_plus_button_re_enabled_after_leaving_limit(self, motion):
        """btn_j0_plus вмикається знову після виходу з max-межі."""
        mgr, widgets = motion
        # Встановлюємо на межу
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True,
                        joint_position=[180.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert not widgets.btn_j0_plus.isEnabled()
        # Виходимо з межі
        mgr._handle_joint_soft_limits(
            base_states(is_ready=True,
                        joint_position=[100.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        assert widgets.btn_j0_plus.isEnabled()


# ---------------------------------------------------------------------------
# Група 3: Edge cases
# ---------------------------------------------------------------------------

class TestMotionEdgeCases:

    def test_empty_joint_position_no_crash(self, motion):
        """Порожній joint_position не кидає виняток."""
        mgr, _ = motion
        mgr.update_coordinates(base_states(joint_position=[]))

    def test_partial_actual_position_fallback_to_zero(self, motion):
        """Відсутні осі у actual_position отримують значення '0.0000'."""
        mgr, widgets = motion
        mgr.update_coordinates(base_states(actual_position=[1.0, 2.0]))
        assert widgets.txt_z_pos.text() == "0.0000"

    def test_no_crash_without_limit_config(self, motion):
        """_handle_joint_soft_limits не падає при порожньому limits."""
        mgr, _ = motion
        mgr.limits = {}
        mgr._handle_joint_soft_limits(base_states(is_ready=True))
