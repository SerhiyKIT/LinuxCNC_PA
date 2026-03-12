# tests/gui/test_motion_display.py
"""
Unit-тести MotionDisplayManager
==================================
Групи:
  1. update_coordinates        —  6 тестів
  2. _handle_joint_soft_limits —  7 тестів
  3. Edge cases                —  3 тести
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.gui.conftest import base_states


@pytest.fixture
def motion_mgr(mock_cnc, mock_widgets):
    with patch("managers.ui.motion_display.StyleManager") as MockStyle:
        MockStyle.return_value.STYLE_JOG_ACTIVE  = "jog_active"
        MockStyle.return_value.STYLE_JOG_LIMITED = "jog_limited"
        from managers.ui.motion_display import MotionDisplayManager
        yield MotionDisplayManager(mock_cnc, mock_widgets)


# ---------------------------------------------------------------------------
# Група 1: update_coordinates
# ---------------------------------------------------------------------------

class TestUpdateCoordinates:

    def test_updates_joint_labels_on_first_call(self, motion_mgr, mock_widgets):
        """Перший виклик → txt_jN_pos.setText для кожного joint."""
        motion_mgr.update_coordinates(
            base_states(joint_position=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        )
        mock_widgets.txt_j0_pos.setText.assert_called_with("1.0000")
        mock_widgets.txt_j1_pos.setText.assert_called_with("2.0000")
        mock_widgets.txt_j2_pos.setText.assert_called_with("3.0000")

    def test_updates_world_labels(self, motion_mgr, mock_widgets):
        """Перший виклик → txt_x/y/z_pos оновлюються."""
        motion_mgr.update_coordinates(
            base_states(actual_position=[10.0, 20.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.txt_x_pos.setText.assert_called_with("10.0000")
        mock_widgets.txt_y_pos.setText.assert_called_with("20.0000")
        mock_widgets.txt_z_pos.setText.assert_called_with("30.0000")

    def test_skips_update_when_value_unchanged(self, motion_mgr, mock_widgets):
        """setText не викликається повторно якщо значення не змінилось."""
        states = base_states(joint_position=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        motion_mgr.update_coordinates(states)
        mock_widgets.txt_j0_pos.setText.reset_mock()
        motion_mgr.update_coordinates(states)
        mock_widgets.txt_j0_pos.setText.assert_not_called()

    def test_updates_when_value_changes_significantly(self, motion_mgr, mock_widgets):
        """setText викликається коли зміна > 0.00005."""
        motion_mgr.update_coordinates(
            base_states(joint_position=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.txt_j0_pos.setText.reset_mock()
        motion_mgr.update_coordinates(
            base_states(joint_position=[1.5, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.txt_j0_pos.setText.assert_called_with("1.5000")

    def test_does_not_update_below_threshold(self, motion_mgr, mock_widgets):
        """setText НЕ викликається коли зміна < 0.00005 (гістерезис)."""
        motion_mgr.update_coordinates(
            base_states(joint_position=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.txt_j0_pos.setText.reset_mock()
        motion_mgr.update_coordinates(
            base_states(joint_position=[1.000001, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.txt_j0_pos.setText.assert_not_called()

    def test_formats_with_4_decimal_places(self, motion_mgr, mock_widgets):
        """Координати форматуються з 4 знаками після коми."""
        motion_mgr.update_coordinates(
            base_states(joint_position=[1.23456789, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.txt_j0_pos.setText.assert_called_with("1.2346")


# ---------------------------------------------------------------------------
# Група 2: _handle_joint_soft_limits
# ---------------------------------------------------------------------------

class TestHandleJointSoftLimits:

    def test_disables_plus_at_max(self, motion_mgr, mock_widgets):
        """btn_j0_plus вимкнений і LIMITED стиль при pos >= max (180.0)."""
        motion_mgr._handle_joint_soft_limits(
            base_states(is_ready=True, joint_position=[180.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.btn_j0_plus.setEnabled.assert_called_with(False)
        mock_widgets.btn_j0_plus.setStyleSheet.assert_called_with("jog_limited")

    def test_enables_plus_below_max(self, motion_mgr, mock_widgets):
        """btn_j0_plus увімкнений при pos < max."""
        motion_mgr._handle_joint_soft_limits(
            base_states(is_ready=True, joint_position=[90.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.btn_j0_plus.setEnabled.assert_called_with(True)
        mock_widgets.btn_j0_plus.setStyleSheet.assert_called_with("jog_active")

    def test_disables_minus_at_min(self, motion_mgr, mock_widgets):
        """btn_j0_minus вимкнений при pos <= min (-180.0)."""
        motion_mgr._handle_joint_soft_limits(
            base_states(is_ready=True, joint_position=[-180.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.btn_j0_minus.setEnabled.assert_called_with(False)
        mock_widgets.btn_j0_minus.setStyleSheet.assert_called_with("jog_limited")

    def test_enables_minus_above_min(self, motion_mgr, mock_widgets):
        """btn_j0_minus увімкнений при pos > min."""
        motion_mgr._handle_joint_soft_limits(
            base_states(is_ready=True, joint_position=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        )
        mock_widgets.btn_j0_minus.setEnabled.assert_called_with(True)

    def test_skips_when_not_ready(self, motion_mgr, mock_widgets):
        """Ранній вихід при is_ready=False — кнопки не чіпаються."""
        motion_mgr._handle_joint_soft_limits(base_states(is_ready=False))
        mock_widgets.btn_j0_plus.setEnabled.assert_not_called()
        mock_widgets.btn_j0_minus.setEnabled.assert_not_called()

    def test_skips_joint_without_limits_config(self, motion_mgr, mock_widgets):
        """Joint без limits у конфізі — кнопки не змінюються."""
        motion_mgr.limits = {}
        motion_mgr._handle_joint_soft_limits(base_states(is_ready=True))
        mock_widgets.btn_j0_plus.setEnabled.assert_not_called()

    def test_all_6_joints_processed(self, motion_mgr, mock_widgets):
        """Всі 6 joints обробляються при позиції в межах."""
        motion_mgr._handle_joint_soft_limits(
            base_states(is_ready=True, joint_position=[0.0] * 6)
        )
        for i in range(6):
            getattr(mock_widgets, f"btn_j{i}_plus").setEnabled.assert_called_with(True)
            getattr(mock_widgets, f"btn_j{i}_minus").setEnabled.assert_called_with(True)


# ---------------------------------------------------------------------------
# Група 3: Edge cases
# ---------------------------------------------------------------------------

class TestMotionDisplayEdgeCases:

    def test_empty_joint_position_no_crash(self, motion_mgr):
        """Порожній joint_position не кидає виняток."""
        motion_mgr.update_coordinates(base_states(joint_position=[]))

    def test_empty_actual_position_no_crash(self, motion_mgr):
        """Порожній actual_position — fallback 0.0."""
        motion_mgr.update_coordinates(base_states(actual_position=[]))

    def test_partial_actual_position_uses_fallback(self, motion_mgr, mock_widgets):
        """actual_position з 2 елементами → Z отримує 0.0."""
        motion_mgr.update_coordinates(base_states(actual_position=[1.0, 2.0]))
        mock_widgets.txt_z_pos.setText.assert_called_with("0.0000")
