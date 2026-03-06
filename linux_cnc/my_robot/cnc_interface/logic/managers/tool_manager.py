# logic/managers/tool_manager.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt5.QtCore import QCoreApplication

from config import STYLES

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MDI_GRIP    = "M101"
_MDI_RELEASE = "M102"

# Number of joints that must be homed before tool actions are allowed
_REQUIRED_HOMED_JOINTS = 3

# UI text constants
_TXT_ARMED    = "ARMED"
_TXT_DISARMED = "DISARMED"
_TXT_GRIP     = "GRIP"
_TXT_RELEASE  = "RELEASE"
_STATUS_READY   = "STATUS: READY"
_STATUS_LOCKED  = "STATUS: LOCKED"
_STATUS_HOLDING = "STATUS: HOLDING"
_STATUS_OPEN    = "STATUS: OPEN"

# Slider bounds
_POWER_MIN = 10
_POWER_MAX = 100


# ---------------------------------------------------------------------------
# ToolManager
# ---------------------------------------------------------------------------

class ToolManager:
    """
    Enforces safety interlocks and executes gripper commands.

    All machine communication is delegated to
    :class:`~logic.core.machine.MachineController`; this class contains no
    UI logic.

    Safety chain for :meth:`perform_action`:

    1. Tool must be armed (``is_armed`` flag from the UI).
    2. The first :data:`_REQUIRED_HOMED_JOINTS` joints must all be homed.

    Attributes:
        cnc: Reference to the active machine controller.
    """

    __slots__ = ("cnc", "__weakref__")

    def __init__(self, machine_controller: MachineController) -> None:
        self.cnc = machine_controller

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def arm_tool(self, armed: bool) -> bool:
        """
        Activate or deactivate the tool.

        When *armed* is ``False`` and the required joints are homed, a safe
        release MDI command is sent before disarming.

        Args:
            armed: ``True`` to arm the tool, ``False`` to disarm.

        Returns:
            *armed* unchanged — allows the caller to use the return value
            directly as the new armed-state flag.
        """
        if not armed:
            if self._joints_homed():
                self.cnc.send_mdi(_MDI_RELEASE)
            return False
        return True

    def perform_action(self, is_grip: bool, is_armed: bool) -> bool:
        """
        Attempt a grip or release action.

        Two safety checks are performed in order:

        1. The tool must be armed — otherwise the action is denied.
        2. The required joints must be homed — otherwise the action is denied.

        Args:
            is_grip:  ``True`` to grip, ``False`` to release.
            is_armed: Whether the tool is currently armed.

        Returns:
            ``True`` when the MDI command was accepted by the controller,
            ``False`` otherwise (safety denial or command failure).
        """
        if not is_armed:
            logger.warning("[GRIPPER] Access Denied: Arm Tool first!")
            return False

        if not self._joints_homed():
            logger.warning("[GRIPPER] Access Denied: Home joints first!")
            return False

        cmd = _MDI_GRIP if is_grip else _MDI_RELEASE
        return self.cnc.send_mdi(cmd)

    def set_power(self, percentage: int) -> float:
        """
        Set the gripper force as a percentage.

        Args:
            percentage: Desired force in the range ``10`` … ``100``.

        Returns:
            The normalised force value actually sent to the controller
            (``percentage / 100.0``).
        """
        force = percentage / 100.0
        self.cnc.set_gripper_force(force)
        return force

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _joints_homed(self) -> bool:
        """Return ``True`` when the first :data:`_REQUIRED_HOMED_JOINTS` joints are homed."""
        return all(self.cnc.status.homed[:_REQUIRED_HOMED_JOINTS])

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"


# ---------------------------------------------------------------------------
# ToolUIBinder
# ---------------------------------------------------------------------------

class ToolUIBinder:
    """
    Wires gripper-control buttons and slider to :class:`ToolManager`.

    Responsibilities:

    * Configure and connect the *Arm*, *Action*, and *Power* widgets.
    * Reflect state changes (text, style, status label) after every
      user interaction.
    * Never contain motion logic — all decisions delegate to
      :class:`ToolManager`.

    Styles are read once from :data:`config.STYLES` during construction so
    that a missing key safely falls back to an empty string.

    Attributes:
        manager:            The :class:`ToolManager` that handles commands.
        widgets:            UI widget container.
        STYLE_TOOL_ARMED:   Stylesheet for the armed state of the arm button.
        STYLE_TOOL_DISARMED:Stylesheet for the disarmed state.
        STYLE_GRIP_ACTIVE:  Stylesheet when gripper is holding.
        STYLE_GRIP_INACTIVE:Stylesheet when gripper is open.
    """

    __slots__ = (
        "manager",
        "widgets",
        "STYLE_TOOL_ARMED",
        "STYLE_TOOL_DISARMED",
        "STYLE_GRIP_ACTIVE",
        "STYLE_GRIP_INACTIVE",
        "__weakref__",
    )

    def __init__(self, tool_manager: ToolManager, widgets: object) -> None:
        self.manager = tool_manager
        self.widgets = widgets

        self.STYLE_TOOL_ARMED    = STYLES.get("TOOL_ARMED",    "")
        self.STYLE_TOOL_DISARMED = STYLES.get("TOOL_DISARMED", "")
        self.STYLE_GRIP_ACTIVE   = STYLES.get("GRIP_ACTIVE",   "")
        self.STYLE_GRIP_INACTIVE = STYLES.get("GRIP_INACTIVE", "")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_tool_buttons(self) -> None:
        """
        Configure and wire the Arm button, Action button, and Power slider.

        Missing widgets are silently skipped so partial UI layouts do not
        raise.
        """
        self._setup_arm_button()
        self._setup_action_button()
        self._setup_power_slider()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_arm_clicked(self) -> None:
        """Handle Arm button toggle: delegate to manager, then refresh UI."""
        btn      = self.widgets.btn_tool_arm
        is_armed = btn.isChecked()

        self.manager.arm_tool(is_armed)

        self._apply_arm_style(btn, is_armed)

        if not is_armed:
            self._update_action_ui(False)

        self._update_status_label(is_armed)

    def _on_action_clicked(self) -> None:
        """Handle Action button toggle: attempt grip/release, rollback on failure."""
        btn_action = self.widgets.btn_tool_action
        is_armed   = self.widgets.btn_tool_arm.isChecked()
        is_grip    = btn_action.isChecked()

        success = self.manager.perform_action(is_grip, is_armed)

        if success:
            self._update_action_ui(is_grip)
        else:
            btn_action.setChecked(False)

    def _on_power_changed(self, value: int) -> None:
        """Handle Power slider change: delegate to manager and update label."""
        self.manager.set_power(value)
        lbl = getattr(self.widgets, "lbl_tool_power_val", None)
        if lbl is not None:
            lbl.setText(f"{value} %")

    # ------------------------------------------------------------------
    # Private setup helpers
    # ------------------------------------------------------------------

    def _setup_arm_button(self) -> None:
        """Make the Arm button checkable and connect its signal."""
        btn = getattr(self.widgets, "btn_tool_arm", None)
        if btn is not None:
            btn.setCheckable(True)
            btn.clicked.connect(self._on_arm_clicked)

    def _setup_action_button(self) -> None:
        """Make the Action button checkable and connect its signal."""
        btn = getattr(self.widgets, "btn_tool_action", None)
        if btn is not None:
            btn.setCheckable(True)
            btn.clicked.connect(self._on_action_clicked)

    def _setup_power_slider(self) -> None:
        """Set slider bounds and connect its signal."""
        sld = getattr(self.widgets, "sld_tool_power", None)
        if sld is not None:
            sld.setMinimum(_POWER_MIN)
            sld.setMaximum(_POWER_MAX)
            sld.valueChanged.connect(self._on_power_changed)

    # ------------------------------------------------------------------
    # Private UI-update helpers
    # ------------------------------------------------------------------

    def _apply_arm_style(self, btn: object, is_armed: bool) -> None:
        """Update arm-button text and stylesheet to reflect *is_armed*."""
        txt   = _TXT_ARMED if is_armed else _TXT_DISARMED
        style = self.STYLE_TOOL_ARMED if is_armed else self.STYLE_TOOL_DISARMED
        btn.setText(QCoreApplication.translate("MainWindow", txt))
        btn.setStyleSheet(style)

    def _update_action_ui(self, is_grip: bool) -> None:
        """
        Synchronise the Action button's check state, text, and stylesheet
        with *is_grip*, and refresh the status label.

        Args:
            is_grip: ``True`` when the gripper is currently holding.
        """
        btn = getattr(self.widgets, "btn_tool_action", None)
        if btn is None:
            return

        btn.setChecked(is_grip)
        btn.setText(QCoreApplication.translate(
            "MainWindow", _TXT_RELEASE if is_grip else _TXT_GRIP
        ))
        btn.setStyleSheet(
            self.STYLE_GRIP_ACTIVE if is_grip else self.STYLE_GRIP_INACTIVE
        )

        lbl = getattr(self.widgets, "lbl_tool_status", None)
        if lbl is not None:
            lbl.setText(QCoreApplication.translate(
                "MainWindow", _STATUS_HOLDING if is_grip else _STATUS_OPEN
            ))

    def _update_status_label(self, is_armed: bool) -> None:
        """
        Set the status label to READY or LOCKED based on *is_armed*.

        Args:
            is_armed: ``True`` when the tool is armed.
        """
        lbl = getattr(self.widgets, "lbl_tool_status", None)
        if lbl is not None:
            lbl.setText(QCoreApplication.translate(
                "MainWindow", _STATUS_READY if is_armed else _STATUS_LOCKED
            ))

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"manager={self.manager!r}, "
            f"widgets={self.widgets!r})"
        )