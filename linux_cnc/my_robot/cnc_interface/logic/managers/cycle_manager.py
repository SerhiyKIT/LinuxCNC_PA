# logic/managers/cycle_manager.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUTTON_METHOD_MAP: tuple[tuple[str, str], ...] = (
    ("btn_cycle_start",    "start_cycle"),
    ("btn_cycle_pause",    "pause_cycle"),
    ("btn_cycle_continue", "resume_cycle"),
    ("btn_cycle_stop",     "stop_cycle"),
    ("btn_cycle_step",     "step_cycle"),
)


# ---------------------------------------------------------------------------
# CycleManager
# ---------------------------------------------------------------------------

class CycleManager:
    """
    Manages G-code programme execution cycle.

    Delegates all machine communication to
    :class:`~logic.core.machine.MachineController` and contains no UI logic.
    Every public method catches hardware exceptions so that a fault in the
    controller layer cannot propagate into the UI event loop.

    Attributes:
        cnc: Reference to the active machine controller.
    """

    __slots__ = ("cnc", "__weakref__")

    def __init__(self, machine_controller: MachineController) -> None:
        self.cnc = machine_controller

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_cycle(self, start_line: int = 0, *args, **kwargs) -> None:
        """
        Start G-code execution from *start_line*.

        Non-integer values for *start_line* are silently coerced to ``0``
        so that UI callers passing unexpected types do not cause a crash.

        Args:
            start_line: Zero-based line number from which to begin execution.
        """
        line = start_line if isinstance(start_line, int) else 0
        try:
            self.cnc.cycle_start(line)
            logger.debug("Cycle started from line %d", line)
        except Exception as exc:
            logger.warning("Failed to start cycle: %s", exc)

    def resume_cycle(self) -> None:
        """Resume a paused G-code programme."""
        try:
            self.cnc.cycle_resume()
            logger.debug("Cycle resumed")
        except Exception as exc:
            logger.error("Resume failed: %s", exc)

    def pause_cycle(self) -> None:
        """Pause the running programme (Feed Hold)."""
        try:
            self.cnc.cycle_pause()
            logger.debug("Feed Hold activated")
        except Exception as exc:
            logger.error("Pause failed: %s", exc)

    def stop_cycle(self) -> None:
        """Abort programme execution and return to MANUAL mode."""
        try:
            self.cnc.cycle_stop()
            logger.debug("Programme stopped")
        except Exception as exc:
            logger.error("Stop failed: %s", exc)

    def step_cycle(self) -> None:
        """
        Execute a single G-code line and refresh machine status.

        The status poll after the step ensures that the UI reflects the
        updated interpreter position immediately.
        """
        try:
            self.cnc.cycle_step()
            self.cnc.status.poll()
            logger.debug("Single step executed")
        except Exception as exc:
            logger.warning("Step execution unavailable: %s", exc)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"


# ---------------------------------------------------------------------------
# CycleUIBinder
# ---------------------------------------------------------------------------

class CycleUIBinder:
    """
    Wires cycle-control UI buttons to :class:`CycleManager`.

    Responsibilities are limited to widget discovery and signal connection;
    all execution logic lives in :class:`CycleManager`.

    Button–method mapping is defined by the module-level constant
    :data:`_BUTTON_METHOD_MAP` so that changes to widget names require
    editing exactly one place.

    Attributes:
        manager: The :class:`CycleManager` that handles execution commands.
        widgets: UI widget container exposing button attributes by name.
    """

    __slots__ = ("manager", "widgets", "__weakref__")

    def __init__(self, cycle_manager: CycleManager, widgets: object) -> None:
        self.manager = cycle_manager
        self.widgets = widgets

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_buttons(self) -> None:
        """
        Connect each cycle-control button's ``clicked`` signal to the
        corresponding :class:`CycleManager` method.

        Buttons absent from the widget container are silently skipped so
        that partial UI layouts do not raise errors.
        """
        for btn_name, method_name in _BUTTON_METHOD_MAP:
            btn = getattr(self.widgets, btn_name, None)
            if btn is not None:
                method = getattr(self.manager, method_name)
                btn.clicked.connect(method)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"manager={self.manager!r}, "
            f"widgets={self.widgets!r})"
        )