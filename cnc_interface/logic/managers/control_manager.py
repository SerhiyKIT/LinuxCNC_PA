# logic/managers/control_manager.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt5.QtWidgets import QMessageBox

from config import STYLES

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AXIS_MODE  = "axis"
_REHOME_TITLE   = "Warning"
_REHOME_TEXT    = "Joint is already homed. Are you sure you want to re-home?"
_REHOME_SUBTEXT = (
    "This will reset the current coordinates and may cause unexpected motion."
)


# ---------------------------------------------------------------------------
# MachineDialogs
# ---------------------------------------------------------------------------

class MachineDialogs:
    """
    Factory for modal confirmation dialogs.

    Intentionally stateless — all methods are static so the class acts as a
    plain namespace.  Keeping dialog construction here isolates PyQt5 from
    the rest of the control logic and makes it straightforward to stub in
    tests.
    """

    @staticmethod
    def confirm_rehome(parent_widget: object | None = None) -> bool:
        """
        Ask the operator to confirm a re-home operation.

        Args:
            parent_widget: Optional Qt parent widget for correct window
                           stacking and style inheritance.

        Returns:
            ``True`` when the operator clicks *OK*; ``False`` on *Cancel*
            or when the dialog is closed without a choice.
        """
        msg = QMessageBox(parent_widget)
        msg.setWindowTitle(_REHOME_TITLE)
        msg.setText(_REHOME_TEXT)
        msg.setInformativeText(_REHOME_SUBTEXT)
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.setStyleSheet(STYLES.get("MSGBOX", ""))
        return msg.exec_() == QMessageBox.Ok


# ---------------------------------------------------------------------------
# ControlManager
# ---------------------------------------------------------------------------

class ControlManager:
    """
    Coordinates high-level machine control actions and routes UI button
    events to the appropriate logic.

    All direct machine communication is delegated to
    :class:`~logic.core.machine.MachineController`; this class contains
    only orchestration and guard logic.

    Attributes:
        cnc:                    Reference to the active machine controller.
        widgets:                UI widget container.
        homing_complete_shown:  Tracks whether the post-homing notification
                                has already been displayed in this session.
        SPEED:                  Cached linear speed from the machine config.
    """

    __slots__ = ("cnc", "widgets", "homing_complete_shown", "SPEED", "__weakref__")

    def __init__(
        self,
        machine_controller: MachineController,
        widgets: object,
    ) -> None:
        self.cnc                   = machine_controller
        self.widgets               = widgets
        self.homing_complete_shown = False
        self.SPEED                 = self.cnc.speed

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def toggle_estop(self) -> None:
        """
        Toggle the Emergency Stop state.

        Any exception raised by the machine controller is caught and logged
        so that a hardware fault cannot crash the UI event loop.
        """
        try:
            self.cnc.toggle_estop()
            logger.debug("E-STOP toggled")
        except Exception as exc:
            logger.error("Failed to toggle E-STOP: %s", exc)

    def toggle_power(self, current_power_state: bool) -> None:
        """
        Flip the machine power state.

        Refreshes the machine status before issuing the command so the
        decision is based on current hardware state rather than a cached
        value.  Resets :attr:`homing_complete_shown` whenever power is
        switched off.

        Args:
            current_power_state: The power state as known to the caller
                                 (``True`` = currently ON).
        """
        try:
            self.cnc.poll()
            new_state = not current_power_state
            self.cnc.set_power(new_state)

            if not new_state:
                self.homing_complete_shown = False

            logger.debug("Power set to %s", new_state)
        except Exception as exc:
            logger.error("Failed to set power: %s", exc)

    def execute_homing(self) -> None:
        """
        Validate pre-conditions and start the homing sequence.

        The sequence is blocked when the machine is not ready.  When all
        joints are already homed the operator is asked to confirm before
        proceeding.
        """
        if not self.cnc.can_home():
            logger.warning("Machine not ready for homing")
            return

        if self.cnc.is_all_homed():
            parent = getattr(self.widgets, "main_window", None)
            if not MachineDialogs.confirm_rehome(parent):
                return

        self.cnc.home_all_sequence()
        logger.debug("Homing sequence started")

    def switch_control_mode(
        self,
        panel_type: str,
        is_ready: bool,
        all_homed: bool,
    ) -> None:
        """
        Switch between *Axis* (World) and *Joint* control modes.

        The switch is only performed when the machine is ready **and** all
        joints are homed, matching the safety requirements of LinuxCNC.

        Args:
            panel_type: ``"axis"`` for World/teleop mode; any other value
                        selects Joint mode.
            is_ready:   Whether the machine is powered on and out of E-Stop.
            all_homed:  Whether every configured joint has been homed.
        """
        if not (is_ready and all_homed):
            return

        self.cnc.manual_mode = panel_type
        self.cnc.set_teleop(panel_type == _AXIS_MODE)
        logger.debug("Control mode → %s", panel_type)

    # ------------------------------------------------------------------
    # UI button handlers
    # ------------------------------------------------------------------

    def on_btn_estop_clicked(self) -> None:
        """Handle E-Stop button press."""
        self.toggle_estop()

    def on_btn_power_off_clicked(self, states: dict[str, Any]) -> None:
        """Handle Power button press.

        Args:
            states: Machine state dictionary as returned by
                    :meth:`~logic.core.machine.MachineController.get_states`.
        """
        self.toggle_power(states.get("power_on", False))

    def on_btn_home_all_clicked(self) -> None:
        """Handle Home All button press."""
        self.execute_homing()

    def on_overlay_clicked(
        self,
        states: dict[str, Any],
        panel_type: str,
    ) -> None:
        """Handle control-mode overlay click.

        Args:
            states:     Machine state dictionary.
            panel_type: Target mode identifier (``"axis"`` or ``"joint"``).
        """
        self.switch_control_mode(
            panel_type,
            states.get("is_ready", False),
            states.get("all_homed", False),
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"speed={self.SPEED!r}, "
            f"homing_complete_shown={self.homing_complete_shown!r})"
        )