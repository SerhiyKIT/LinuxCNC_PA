# logic/managers/joint_manager.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NUM_JOINTS        = 6
_CONTINUOUS_MODE   = "Continuous"
_CONTINUOUS_INCREMENT = 0.0


# ---------------------------------------------------------------------------
# JointManager
# ---------------------------------------------------------------------------

class JointManager:
    """
    Coordinates jog commands for all robot joints (Joint mode).

    Delegates all machine communication to
    :class:`~logic.core.machine.MachineController` and contains no UI logic.
    Mirrors the structure of :class:`~logic.managers.axis_manager.AxisManager`
    but uses ``is_joint=True`` and ``angular_jog_speed`` instead of linear
    speed, and activates Joint mode (``want_teleop=False``) before every jog.

    Attributes:
        cnc:        Reference to the active machine controller.
        num_joints: Number of joints exposed by the robot kinematics.
    """

    __slots__ = ("cnc", "num_joints", "__weakref__")

    def __init__(self, machine_controller: MachineController) -> None:
        self.cnc        = machine_controller
        self.num_joints = _NUM_JOINTS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_jog(self, joint_idx: int, direction: int, mode_text: str) -> None:
        """
        Begin jogging *joint_idx* in *direction* at the angular speed
        configured on the machine controller.

        The machine must be ready (powered on, out of E-Stop); if it is not,
        the call is a silent no-op.  Joint mode (``want_teleop=False``) is
        activated before issuing the jog command.

        Args:
            joint_idx:  Zero-based joint index (0 … ``num_joints - 1``).
            direction:  ``+1`` for positive, ``-1`` for negative rotation.
            mode_text:  Human-readable mode string from the UI combo box.
                        ``"Continuous"`` maps to an unlimited jog; any other
                        value is parsed as a numeric increment (degrees).
        """
        if not self.cnc.is_ready():
            return

        self.cnc.sync_mode(want_teleop=False)
        increment = self._parse_increment(mode_text)

        try:
            self.cnc.jog(
                joint_idx,
                direction,
                self.cnc.angular_jog_speed,
                increment,
                is_joint=True,
            )
        except Exception as exc:
            logger.error("Joint jogging failed on J%d: %s", joint_idx, exc)

    def stop_jog(self, joint_idx: int, mode_text: str) -> None:
        """
        Stop an active jog on *joint_idx*.

        The stop command is only issued in ``"Continuous"`` mode because
        incremental jogs stop automatically after travelling the requested
        angle.

        Args:
            joint_idx:  Zero-based joint index.
            mode_text:  Current UI mode string.
        """
        if mode_text == _CONTINUOUS_MODE:
            self.cnc.stop_jog(joint_idx, is_joint=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_increment(self, text: str) -> float:
        """
        Convert a UI mode string to a numeric jog increment (degrees).

        Returns:
            ``0.0`` for ``"Continuous"`` mode or any unparseable input;
            otherwise the parsed ``float`` value.
        """
        if text == _CONTINUOUS_MODE:
            return _CONTINUOUS_INCREMENT

        try:
            return float(text)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid joint increment %r — falling back to Continuous.", text
            )
            return _CONTINUOUS_INCREMENT

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"num_joints={self.num_joints!r})"
        )


# ---------------------------------------------------------------------------
# JointUIBinder
# ---------------------------------------------------------------------------

class JointUIBinder:
    """
    Connects joint-jog buttons to :class:`JointManager`.

    Responsibilities are limited to widget discovery and signal wiring;
    all motion logic lives in :class:`JointManager`.

    Button names follow the convention ``btn_j<n>_plus`` / ``btn_j<n>_minus``
    where ``n`` is the zero-based joint index (e.g. ``btn_j0_plus``).
    Missing widgets are silently skipped so partial UI layouts do not raise.

    Attributes:
        manager: The :class:`JointManager` that handles jog commands.
        widgets: UI widget container exposing button and combo-box attributes.
    """

    __slots__ = ("manager", "widgets", "__weakref__")

    def __init__(self, joint_manager: JointManager, widgets: object) -> None:
        self.manager = joint_manager
        self.widgets = widgets

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_buttons(self) -> None:
        """
        Wire ``pressed`` / ``released`` signals for every joint button pair
        (J0 … J\ ``num_joints - 1``).

        Uses default-argument capture (``idx=j``) in lambdas to avoid the
        classic late-binding closure bug.
        """
        for j in range(self.manager.num_joints):
            self._bind_joint_pair(j)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _bind_joint_pair(self, idx: int) -> None:
        """
        Locate the ``+`` and ``−`` buttons for joint *idx* and connect
        their ``pressed`` / ``released`` signals.

        Args:
            idx: Zero-based joint index.
        """
        btn_plus  = getattr(self.widgets, f"btn_j{idx}_plus",  None)
        btn_minus = getattr(self.widgets, f"btn_j{idx}_minus", None)

        if btn_plus is not None:
            btn_plus.pressed.connect(lambda idx=idx: self._handle_press(idx, +1))
            btn_plus.released.connect(lambda idx=idx: self._handle_release(idx))

        if btn_minus is not None:
            btn_minus.pressed.connect(lambda idx=idx: self._handle_press(idx, -1))
            btn_minus.released.connect(lambda idx=idx: self._handle_release(idx))

    def _get_current_mode(self) -> str:
        """
        Read the current joint mode from the UI combo box.

        Returns:
            The selected text, or ``"Continuous"`` when the combo box is
            absent.
        """
        combo = getattr(self.widgets, "combo_joint_mode", None)
        return combo.currentText() if combo is not None else _CONTINUOUS_MODE

    def _handle_press(self, idx: int, direction: int) -> None:
        """Translate a button-press signal into a :meth:`JointManager.start_jog` call."""
        self.manager.start_jog(idx, direction, self._get_current_mode())

    def _handle_release(self, idx: int) -> None:
        """Translate a button-release signal into a :meth:`JointManager.stop_jog` call."""
        self.manager.stop_jog(idx, self._get_current_mode())

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"manager={self.manager!r}, "
            f"widgets={self.widgets!r})"
        )