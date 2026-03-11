# logic/managers/keyboard_manager.py
from __future__ import annotations

import logging
from typing import Any

from PyQt5 import QtCore, QtWidgets

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Widget types that capture keyboard input — hotkeys are suppressed while
# any of these holds focus (except Escape, which clears focus).
_INPUT_WIDGET_TYPES: tuple[type, ...] = (
    QtWidgets.QLineEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QPlainTextEdit,
)

# Mapping of hotkey config key → (manager key, method name).
# Order matters only for readability; _match short-circuits on first hit.
_HOTKEY_DISPATCH: tuple[tuple[str, str, str], ...] = (
    # config key        manager key          method name
    ("ESTOP",           config.MGR_CONTROL,  "on_btn_estop_clicked"),
    ("POWER",           config.MGR_CONTROL,  "on_btn_power_off_clicked"),
    ("HOME_ALL",        config.MGR_CONTROL,  "on_btn_home_all_clicked"),
    ("OPEN_FILE",       config.MGR_FILE,     "on_btn_file_open_clicked"),
    ("SAVE_AS",         config.MGR_FILE,     "on_btn_file_save_as_clicked"),
    ("RELOAD",          config.MGR_FILE,     "on_btn_file_reload_clicked"),
    ("RUN",             config.MGR_CYCLE,    "start_cycle"),
    ("STOP",            config.MGR_CYCLE,    "stop_cycle"),
    ("PAUSE",           config.MGR_CYCLE,    "pause_cycle"),
    ("RESUME",          config.MGR_CYCLE,    "resume_cycle"),
    ("STEP",            config.MGR_CYCLE,    "step_cycle"),
)


# ---------------------------------------------------------------------------
# KeyboardManager
# ---------------------------------------------------------------------------

class KeyboardManager:
    """
    Routes keyboard events to the appropriate manager method.

    The dispatch table :data:`_HOTKEY_DISPATCH` maps each hotkey config key
    to a ``(manager_key, method_name)`` pair.  Adding a new hotkey requires
    only a single entry in that table — no changes to ``processed_key_event``
    or ``_call``.

    Focus guard: while a text-input widget holds focus, all hotkeys are
    suppressed.  Pressing *Escape* clears focus and re-enables hotkeys.

    Attributes:
        widgets:  UI widget container (used indirectly via Qt focus queries).
        managers: Mapping of manager-key → manager instance.
    """

    __slots__ = ("widgets", "managers", "__weakref__")

    def __init__(
        self,
        widgets: object,
        managers_map: dict[str, Any],
    ) -> None:
        self.widgets  = widgets
        self.managers = managers_map

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def processed_key_event(self, event: QtCore.QEvent, is_pressed: bool) -> None:
        """
        Handle a key event forwarded from the main window.

        Key-release events are ignored; only key-press events are dispatched.
        While a text-input widget has focus, only *Escape* is processed (to
        clear focus); all other hotkeys are suppressed.

        Args:
            event:      The Qt key event.
            is_pressed: ``True`` for ``keyPressEvent``, ``False`` for
                        ``keyReleaseEvent``.
        """
        if not is_pressed:
            return

        key       = event.key()
        modifiers = event.modifiers()

        if self._is_input_focused(key):
            return

        hk = config.HOTKEYS
        for hk_key, mgr_key, method_name in _HOTKEY_DISPATCH:
            if self._match(key, modifiers, hk.get(hk_key)):
                self._call(mgr_key, method_name)
                return   # only the first matching hotkey fires

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_input_focused(key: int) -> bool:
        """
        Return ``True`` when a text-input widget has focus, clearing it
        first if *Escape* was pressed.

        Args:
            key: Qt key code of the pressed key.

        Returns:
            ``True``  — caller should suppress hotkey processing.
            ``False`` — caller may proceed with hotkey dispatch.
        """
        focus_widget = QtWidgets.QApplication.focusWidget()
        if not isinstance(focus_widget, _INPUT_WIDGET_TYPES):
            return False

        if key == QtCore.Qt.Key_Escape:
            focus_widget.clearFocus()

        return True

    @staticmethod
    def _match(key: int, current_mods: QtCore.Qt.KeyboardModifiers, target: Any) -> bool:
        """
        Check whether the pressed key matches a hotkey target from the config.

        Two target formats are supported:

        * **Plain key** (``int``): matches when the key equals *target* and
          no modifier keys are held.
        * **Key + modifier** (``tuple[int, Qt.Modifier]``): matches when the
          key equals ``target[0]`` and at least ``target[1]`` is active.

        Args:
            key:          Qt key code of the pressed key.
            current_mods: Active modifier flags from the key event.
            target:       Config value — either a bare key code or a
                          ``(key_code, modifier)`` tuple.  ``None`` is
                          accepted and always returns ``False``.

        Returns:
            ``True`` when the event matches *target*.
        """
        if target is None:
            return False

        if isinstance(target, tuple):
            target_key, target_mod = target
            return key == target_key and bool(current_mods & target_mod)

        return key == target and current_mods == QtCore.Qt.NoModifier

    def _call(self, mgr_key: str, func_name: str) -> None:
        """
        Invoke *func_name* on the manager identified by *mgr_key*.

        The method is first attempted with a *states* dict (required by
        handlers such as ``on_btn_power_off_clicked``).  If the method does
        not accept arguments, it is retried without them.

        Missing manager keys and absent method names are logged as warnings
        rather than raising, so a misconfigured hotkey cannot crash the UI.

        Args:
            mgr_key:   Key used to look up the manager in :attr:`managers`.
            func_name: Name of the method to invoke.
        """
        manager = self.managers.get(mgr_key)
        if manager is None or not hasattr(manager, func_name):
            logger.warning("Manager or method not found: %s.%s", mgr_key, func_name)
            return

        method = getattr(manager, func_name)
        states: dict[str, Any] = (
            manager.cnc.get_states() if hasattr(manager, "cnc") else {}
        )

        try:
            method(states)
            logger.debug("Keyboard dispatch %s.%s(states) OK", mgr_key, func_name)
        except TypeError:
            method()
            logger.debug("Keyboard dispatch %s.%s() OK (no states)", mgr_key, func_name)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"managers={list(self.managers.keys())!r})"
        )