"""
Tests for logic/managers/cycle_manager.py  –  CycleManager & CycleUIBinder
===========================================================================

Run with:
    pytest test_cycle_manager.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from logic.managers.cycle_manager import (
    CycleManager,
    CycleUIBinder,
    _BUTTON_METHOD_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cnc() -> MagicMock:
    cnc = MagicMock()
    cnc.status = MagicMock()
    return cnc


@pytest.fixture()
def manager(mock_cnc: MagicMock) -> CycleManager:
    return CycleManager(mock_cnc)


@pytest.fixture()
def mock_widgets() -> MagicMock:
    """Widget container with all cycle buttons pre-created."""
    widgets = MagicMock()
    for btn_name, _ in _BUTTON_METHOD_MAP:
        btn = MagicMock()
        btn.clicked = MagicMock()
        setattr(widgets, btn_name, btn)
    return widgets


@pytest.fixture()
def binder(manager: CycleManager, mock_widgets: MagicMock) -> CycleUIBinder:
    return CycleUIBinder(manager, mock_widgets)


# ===========================================================================
# CycleManager – initialisation
# ===========================================================================

class TestCycleManagerInit:
    def test_stores_cnc_reference(self, mock_cnc):
        m = CycleManager(mock_cnc)
        assert m.cnc is mock_cnc

    def test_slots_prevent_arbitrary_attributes(self, manager):
        with pytest.raises(AttributeError):
            manager.unexpected = "oops"

    def test_repr_contains_class_name(self, manager):
        assert "CycleManager" in repr(manager)


# ===========================================================================
# start_cycle
# ===========================================================================

class TestStartCycle:
    def test_default_line_is_zero(self, manager, mock_cnc):
        manager.start_cycle()
        mock_cnc.cycle_start.assert_called_once_with(0)

    def test_specific_line_number(self, manager, mock_cnc):
        manager.start_cycle(start_line=42)
        mock_cnc.cycle_start.assert_called_once_with(42)

    def test_non_integer_coerced_to_zero(self, manager, mock_cnc):
        manager.start_cycle(start_line="bad")
        mock_cnc.cycle_start.assert_called_once_with(0)

    def test_none_coerced_to_zero(self, manager, mock_cnc):
        manager.start_cycle(start_line=None)
        mock_cnc.cycle_start.assert_called_once_with(0)

    def test_float_coerced_to_zero(self, manager, mock_cnc):
        """Floats are not ints — must fall back to 0."""
        manager.start_cycle(start_line=3.5)
        mock_cnc.cycle_start.assert_called_once_with(0)

    def test_zero_line_explicitly(self, manager, mock_cnc):
        manager.start_cycle(start_line=0)
        mock_cnc.cycle_start.assert_called_once_with(0)

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.cycle_start.side_effect = Exception("Not in Auto mode")
        manager.start_cycle()   # must not raise

    def test_exception_is_logged_as_warning(self, manager, mock_cnc):
        mock_cnc.cycle_start.side_effect = Exception("err")
        with patch("logic.managers.cycle_manager.logger") as mock_log:
            manager.start_cycle()
            mock_log.warning.assert_called_once()


# ===========================================================================
# resume_cycle
# ===========================================================================

class TestResumeCycle:
    def test_delegates_to_cnc(self, manager, mock_cnc):
        manager.resume_cycle()
        mock_cnc.cycle_resume.assert_called_once()

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.cycle_resume.side_effect = Exception("Not paused")
        manager.resume_cycle()

    def test_exception_is_logged_as_error(self, manager, mock_cnc):
        mock_cnc.cycle_resume.side_effect = Exception("err")
        with patch("logic.managers.cycle_manager.logger") as mock_log:
            manager.resume_cycle()
            mock_log.error.assert_called_once()


# ===========================================================================
# pause_cycle
# ===========================================================================

class TestPauseCycle:
    def test_delegates_to_cnc(self, manager, mock_cnc):
        manager.pause_cycle()
        mock_cnc.cycle_pause.assert_called_once()

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.cycle_pause.side_effect = Exception("Not running")
        manager.pause_cycle()

    def test_exception_is_logged_as_error(self, manager, mock_cnc):
        mock_cnc.cycle_pause.side_effect = Exception("err")
        with patch("logic.managers.cycle_manager.logger") as mock_log:
            manager.pause_cycle()
            mock_log.error.assert_called_once()


# ===========================================================================
# stop_cycle
# ===========================================================================

class TestStopCycle:
    def test_delegates_to_cnc(self, manager, mock_cnc):
        manager.stop_cycle()
        mock_cnc.cycle_stop.assert_called_once()

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.cycle_stop.side_effect = Exception("Abort failed")
        manager.stop_cycle()

    def test_exception_is_logged_as_error(self, manager, mock_cnc):
        mock_cnc.cycle_stop.side_effect = Exception("err")
        with patch("logic.managers.cycle_manager.logger") as mock_log:
            manager.stop_cycle()
            mock_log.error.assert_called_once()


# ===========================================================================
# step_cycle
# ===========================================================================

class TestStepCycle:
    def test_delegates_to_cnc(self, manager, mock_cnc):
        manager.step_cycle()
        mock_cnc.cycle_step.assert_called_once()

    def test_polls_status_after_step(self, manager, mock_cnc):
        """status.poll() must be called to refresh UI after every step."""
        manager.step_cycle()
        mock_cnc.status.poll.assert_called_once()

    def test_poll_called_after_step(self, manager, mock_cnc):
        """step must precede poll — order matters for correct state refresh."""
        manager.step_cycle()
        assert mock_cnc.mock_calls == [
            call.cycle_step(),
            call.status.poll(),
        ]

    def test_exception_is_swallowed(self, manager, mock_cnc):
        mock_cnc.cycle_step.side_effect = Exception("Interpreter busy")
        manager.step_cycle()

    def test_exception_is_logged_as_warning(self, manager, mock_cnc):
        mock_cnc.cycle_step.side_effect = Exception("err")
        with patch("logic.managers.cycle_manager.logger") as mock_log:
            manager.step_cycle()
            mock_log.warning.assert_called_once()

    def test_poll_not_called_when_step_raises(self, manager, mock_cnc):
        """If cycle_step raises, status.poll() must not be called."""
        mock_cnc.cycle_step.side_effect = Exception("step failed")
        manager.step_cycle()
        mock_cnc.status.poll.assert_not_called()


# ===========================================================================
# CycleUIBinder – initialisation
# ===========================================================================

class TestCycleUIBinderInit:
    def test_stores_manager_reference(self, manager, mock_widgets):
        b = CycleUIBinder(manager, mock_widgets)
        assert b.manager is manager

    def test_stores_widgets_reference(self, manager, mock_widgets):
        b = CycleUIBinder(manager, mock_widgets)
        assert b.widgets is mock_widgets

    def test_slots_prevent_arbitrary_attributes(self, binder):
        with pytest.raises(AttributeError):
            binder.unexpected = "oops"

    def test_repr_contains_class_name(self, binder):
        assert "CycleUIBinder" in repr(binder)


# ===========================================================================
# CycleUIBinder.connect_buttons
# ===========================================================================

class TestConnectButtons:
    def test_all_buttons_connected(self, binder, mock_widgets):
        binder.connect_buttons()
        for btn_name, _ in _BUTTON_METHOD_MAP:
            btn = getattr(mock_widgets, btn_name)
            btn.clicked.connect.assert_called_once()

    def test_each_button_connected_to_correct_method(self, binder, mock_widgets):
        binder.connect_buttons()
        for btn_name, method_name in _BUTTON_METHOD_MAP:
            btn = getattr(mock_widgets, btn_name)
            expected_method = getattr(binder.manager, method_name)
            btn.clicked.connect.assert_called_once_with(expected_method)

    def test_missing_button_skipped_silently(self, manager):
        """Absent widgets must not raise — partial layouts are valid."""
        widgets = MagicMock(spec=[])
        binder = CycleUIBinder(manager, widgets)
        binder.connect_buttons()   # must not raise

    def test_partial_widgets_only_bind_present(self, manager):
        """Only btn_cycle_start present — others skipped."""
        widgets = MagicMock(spec=["btn_cycle_start"])
        btn = MagicMock()
        btn.clicked = MagicMock()
        widgets.btn_cycle_start = btn

        binder = CycleUIBinder(manager, widgets)
        binder.connect_buttons()

        btn.clicked.connect.assert_called_once_with(manager.start_cycle)

    def test_connect_buttons_idempotent_on_second_call(self, binder, mock_widgets):
        """Calling connect_buttons() twice must wire each signal twice —
        documenting the current behaviour so regressions are visible."""
        binder.connect_buttons()
        binder.connect_buttons()
        for btn_name, _ in _BUTTON_METHOD_MAP:
            btn = getattr(mock_widgets, btn_name)
            assert btn.clicked.connect.call_count == 2