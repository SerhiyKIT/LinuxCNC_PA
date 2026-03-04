# logic/core/axis_manager.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AXES: tuple[str, ...] = ("x", "y", "z", "a", "b", "c")
_CONTINUOUS_MODE = "Continuous"
_CONTINUOUS_INCREMENT = 0.0


# ---------------------------------------------------------------------------
# AxisManager
# ---------------------------------------------------------------------------

class AxisManager:
    """
    Coordinates jog commands for all linear and rotary axes.

    Delegates all machine communication to
    :class:`~logic.core.machine.MachineController` and contains no UI logic.

    Attributes:
        cnc:  Reference to the active machine controller.
        axes: Ordered sequence of axis names used for index→name mapping.
    """

    __slots__ = ("cnc", "axes")

    def __init__(self, machine_controller: MachineController) -> None:
        self.cnc  = machine_controller
        self.axes = list(_AXES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_jog(self, axis_idx: int, direction: int, mode_text: str) -> None:
        """
        Begin jogging *axis_idx* in *direction* at the speed configured on
        the machine controller.

        The machine must be ready (powered on, out of E-Stop); if it is not,
        the call is a silent no-op.  Teleop (World) mode is activated before
        issuing the jog command.

        Args:
            axis_idx:  Zero-based axis index (0 = X … 5 = C).
            direction: ``+1`` for positive, ``-1`` for negative travel.
            mode_text: Human-readable mode string from the UI combo box.
                       ``"Continuous"`` maps to an unlimited jog;
                       any other value is parsed as a numeric increment.
        """
        if not self.cnc.is_ready():
            return

        self.cnc.sync_mode(want_teleop=True)
        increment = self._parse_increment(mode_text)

        try:
            self.cnc.jog(
                axis_idx,
                direction,
                self.cnc.linear_jog_speed,
                increment,
                is_joint=False,
            )
        except Exception as exc:
            logger.error("Jogging axis %d failed: %s", axis_idx, exc)

    def stop_jog(self, axis_idx: int, mode_text: str) -> None:
        """
        Stop an active jog on *axis_idx*.

        The stop command is only issued in ``"Continuous"`` mode because
        incremental jogs stop automatically after travelling the requested
        distance.

        Args:
            axis_idx:  Zero-based axis index.
            mode_text: Current UI mode string.
        """
        if mode_text == _CONTINUOUS_MODE:
            self.cnc.stop_jog(axis_idx, is_joint=False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_increment(self, text: str) -> float:
        """
        Convert a UI mode string to a numeric jog increment.

        Returns:
            ``0.0`` for ``"Continuous"`` mode or any unparseable input
            (falls back to continuous jogging); otherwise the parsed
            ``float`` value.
        """
        if text == _CONTINUOUS_MODE:
            return _CONTINUOUS_INCREMENT

        try:
            return float(text)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid jog increment %r — falling back to Continuous.", text
            )
            return _CONTINUOUS_INCREMENT

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(axes={self.axes})"


# ---------------------------------------------------------------------------
# AxisUIBinder
# ---------------------------------------------------------------------------

class AxisUIBinder:
    """
    Connects UI axis-jog buttons to :class:`AxisManager`.

    Responsibilities are intentionally limited to widget discovery and
    signal wiring; all motion logic lives in :class:`AxisManager`.

    Attributes:
        manager: The :class:`AxisManager` instance that handles jog commands.
        widgets: The UI widget container exposing button and combo-box attributes.
    """

    __slots__ = ("manager", "widgets")

    def __init__(self, axis_manager: AxisManager, widgets: object) -> None:
        self.manager = axis_manager
        self.widgets = widgets

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_buttons(self) -> None:
        """
        Wire press/release signals for every axis button pair.

        Button names are resolved by convention:
        ``btn_<axis>_plus`` and ``btn_<axis>_minus`` (e.g. ``btn_x_plus``).
        Missing widgets are silently skipped.
        """
        for idx, axis in enumerate(self.manager.axes):
            self._bind_axis_pair(idx, axis)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _bind_axis_pair(self, idx: int, axis_name: str) -> None:
        """
        Locate the ``+`` and ``−`` buttons for *axis_name* and connect
        their ``pressed`` / ``released`` signals.

        Args:
            idx:       Zero-based axis index passed through to the jog call.
            axis_name: Lowercase axis letter (e.g. ``"x"``).
        """
        btn_plus  = getattr(self.widgets, f"btn_{axis_name}_plus",  None)
        btn_minus = getattr(self.widgets, f"btn_{axis_name}_minus", None)

        if btn_plus is not None:
            btn_plus.pressed.connect(lambda: self._handle_press(idx, +1))
            btn_plus.released.connect(lambda: self._handle_release(idx))

        if btn_minus is not None:
            btn_minus.pressed.connect(lambda: self._handle_press(idx, -1))
            btn_minus.released.connect(lambda: self._handle_release(idx))

    def _get_current_mode(self) -> str:
        """
        Read the current jog mode from the UI combo box.

        Returns:
            The selected text, or ``"Continuous"`` when the combo box is
            absent.
        """
        combo = getattr(self.widgets, "combo_axis_mode", None)
        return combo.currentText() if combo is not None else _CONTINUOUS_MODE

    def _handle_press(self, axis_idx: int, direction: int) -> None:
        """Translate a button-press signal into a :meth:`AxisManager.start_jog` call."""
        self.manager.start_jog(axis_idx, direction, self._get_current_mode())

    def _handle_release(self, axis_idx: int) -> None:
        """Translate a button-release signal into a :meth:`AxisManager.stop_jog` call."""
        self.manager.stop_jog(axis_idx, self._get_current_mode())

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"manager={self.manager!r}, "
            f"widgets={self.widgets!r})"
        )