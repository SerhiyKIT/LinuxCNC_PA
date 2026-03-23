# logic/core/__init__.py
"""
logic.core
==========
Core machine-control services.

Exported symbols
----------------
MachineController
    Low-level interface to the LinuxCNC API.  Handles state control,
    motion commands, program execution, and status polling.

LoggerController
    Thin adapter that bridges LinuxCNC error polling with the
    application logging layer.

Usage::

    from logic.core import MachineController, LoggerController
"""

from .logger import LoggerController
from .machine import MachineController

__all__: list[str] = [
    "MachineController",
    "LoggerController",
]