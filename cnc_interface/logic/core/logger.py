# logic/core/logger.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logic.core.machine import MachineController

_TIMESTAMP_FORMAT = "%H:%M:%S"


class LoggerController:
    """
    Thin adapter that bridges LinuxCNC error polling with the application
    logging layer.

    Holds a reference to :class:`~logic.core.machine.MachineController` and
    delegates error retrieval to it, keeping the logger decoupled from the
    LinuxCNC API directly.
    """

    __slots__ = ("cnc",)

    def __init__(self, machine_controller: MachineController) -> None:
        self.cnc = machine_controller

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_for_messages(self) -> tuple[str, str] | None:
        """
        Poll LinuxCNC for pending messages.

        Returns:
            ``(message_text, severity)`` where severity is one of
            ``"info"``, ``"warning"``, or ``"error"``; or ``None`` when
            there is no pending message.
        """
        return self.cnc.poll_errors()

    @staticmethod
    def get_timestamp() -> str:
        """
        Return the current wall-clock time as a formatted string.

        Returns:
            Time string in ``HH:MM:SS`` format.
        """
        return datetime.now().strftime(_TIMESTAMP_FORMAT)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"