# logic/managers/overrides_manager.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QCoreApplication

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Each entry: (slider_attr, label_attr, divisor, manager_method_name, unit_template)
# Keeping this as a module-level tuple makes it trivial to add/remove overrides
# without touching any method logic.
_SLIDER_CONFIG: tuple[tuple[str, str, float, str, str], ...] = (
    ("sld_feed_override",      "val_feed_override",      100.0,  "set_feed",         "%1 %"),
    ("sld_rapid_override",     "val_rapid_override",     100.0,  "set_rapid",        "%1 %"),
    ("sld_spindle_override",   "val_spindle_override",   100.0,  "set_spindle",      "%1 %"),
    ("sld_linear_jog_speed",   "val_linear_jog_speed",   1.0, "set_linear_speed", "%1 in/min "),
    ("sld_angular_jog_speed",  "val_angular_jog_speed",  1.0,  "set_angular_speed","%1 deg/min "),
    ("sld_max_velocity",       "val_max_velocity",       1.0,    "set_max_velocity", "%1 in/min"),
)

_PRECISION_HIGH  = 1000.0   # divisor that triggers 3-decimal formatting
_PRECISION_DEG   = "deg"    # unit substring that triggers 2-decimal formatting


# ---------------------------------------------------------------------------
# OverridesManager
# ---------------------------------------------------------------------------

class OverridesManager:
    """
    Forwards override values from the UI to
    :class:`~logic.core.machine.MachineController`.

    Contains no UI logic; all scaling and label updates live in
    :class:`OverridesUIBinder`.

    Attributes:
        cnc: Reference to the active machine controller.
    """

    __slots__ = ("cnc", "__weakref__")

    def __init__(self, machine_controller: MachineController) -> None:
        self.cnc = machine_controller

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_feed(self, scale: float) -> None:
        """Forward feed-rate override *scale* (0.0 … 2.0) to the controller."""
        self.cnc.set_feed_override(scale)

    def set_rapid(self, scale: float) -> None:
        """Forward rapid-rate override *scale* to the controller."""
        self.cnc.set_rapid_override(scale)

    def set_spindle(self, scale: float) -> None:
        """Forward spindle-speed override *scale* to the controller."""
        self.cnc.set_spindle_override(scale)

    def set_linear_speed(self, value: float) -> None:
        """Set the linear jog speed (units/min) on the controller."""
        self.cnc.linear_jog_speed = value

    def set_angular_speed(self, value: float) -> None:
        """Set the angular jog speed (deg/min) on the controller."""
        self.cnc.angular_jog_speed = value

    def set_max_velocity(self, value: float) -> None:
        """
        Set the machine maximum velocity.

        Hardware exceptions are caught and logged so that a slider interaction
        cannot propagate an error into the Qt event loop.

        Args:
            value: Requested maximum velocity in machine units/min.
        """
        try:
            self.cnc.set_max_velocity(value)
        except Exception as exc:
            logger.error("Max Velocity Update: %s", exc)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"


# ---------------------------------------------------------------------------
# OverridesUIBinder
# ---------------------------------------------------------------------------

class OverridesUIBinder:
    """
    Wires override sliders to :class:`OverridesManager` and keeps labels
    in sync with slider positions.

    The mapping between sliders, labels, divisors, manager methods, and unit
    templates is defined in the module-level constant :data:`_SLIDER_CONFIG`
    so that adding a new override requires only one line there.

    Attributes:
        manager: The :class:`OverridesManager` that receives scaled values.
        widgets: UI widget container exposing slider and label attributes.
    """

    __slots__ = ("manager", "widgets", "_configs", "__weakref__")

    def __init__(self, overrides_manager: OverridesManager, widgets: object) -> None:
        self.manager  = overrides_manager
        self.widgets  = widgets
        self._configs: dict[str, tuple[str, float, str, str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setup_overrides(self) -> None:
        """
        Build the internal config map and wire every slider's
        ``valueChanged`` signal.

        Each slider also receives an initial ``_handle_change`` call so
        the label reflects the slider's current position immediately.
        Missing sliders are silently skipped.
        """
        self._configs = {
            sld: (lbl, div, method_name, unit)
            for sld, lbl, div, method_name, unit in _SLIDER_CONFIG
        }

        for sld_name in self._configs:
            slider = getattr(self.widgets, sld_name, None)
            if slider is not None:
                slider.valueChanged.connect(
                    lambda val, name=sld_name: self._handle_change(name, val)
                )
                self._handle_change(sld_name, slider.value())

    def refresh_all_labels(self) -> None:
        """
        Redraw all labels from their slider's current value.

        Useful after a locale change or after programmatic slider updates.
        Missing sliders are silently skipped.
        """
        for sld_name in self._configs:
            slider = getattr(self.widgets, sld_name, None)
            if slider is not None:
                self._handle_change(sld_name, slider.value())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _handle_change(self, name: str, raw_value: int | float) -> None:
        """
        Scale *raw_value*, dispatch to the manager, and update the label.

        Args:
            name:      Slider attribute name (key in :attr:`_configs`).
            raw_value: Raw integer value emitted by the slider.
        """
        label_name, divisor, method_name, unit_tpl = self._configs[name]
        actual_value = raw_value / divisor

        self._dispatch(method_name, actual_value)
        self._update_label(label_name, raw_value, actual_value, divisor, unit_tpl)

    def _dispatch(self, method_name: str, value: float) -> None:
        """
        Call *method_name* on :attr:`manager` with *value*.

        Args:
            method_name: Name of the :class:`OverridesManager` method.
            value:       Already-scaled float to pass as the sole argument.
        """
        getattr(self.manager, method_name)(value)

    def _update_label(
        self,
        label_name: str,
        raw_value: int | float,
        actual_value: float,
        divisor: float,
        unit_tpl: str,
    ) -> None:
        """
        Format *actual_value* and push the result to the UI label.

        Formatting rules (in order of precedence):
        * divisor == 1000  → 3 decimal places  (e.g. ``"0.600 in/min"``)
        * unit contains "deg" → 2 decimal places  (e.g. ``"1.50 deg/min"``)
        * otherwise → integer display of the raw slider value (e.g. ``"75 %"``)

        Args:
            label_name:   Widget attribute name of the ``QLabel`` to update.
            raw_value:    Unscaled slider integer (used for integer formatting).
            actual_value: Scaled float (used for decimal formatting).
            divisor:      Divisor that determined the scaling.
            unit_tpl:     Qt translation template, e.g. ``"%1 %"``.
        """
        label = getattr(self.widgets, label_name, None)
        if label is None:
            return

        fmt_val = self._format_value(raw_value, actual_value, divisor, unit_tpl)
        template = QCoreApplication.translate("MainWindow", unit_tpl)
        label.setText(template.replace("%1", fmt_val))

    @staticmethod
    def _format_value(
        raw_value: int | float,
        actual_value: float,
        divisor: float,
        unit_tpl: str,
    ) -> str:
        """
        Choose the appropriate numeric format for a slider value.

        Args:
            raw_value:    Unscaled slider integer.
            actual_value: Scaled float.
            divisor:      Scaling divisor.
            unit_tpl:     Unit template string (inspected for ``"deg"``).

        Returns:
            A formatted string ready to substitute ``%1`` in *unit_tpl*.
        """
        if divisor == _PRECISION_HIGH:
            return f"{actual_value:.3f}"
        if _PRECISION_DEG in unit_tpl:
            return f"{actual_value:.2f}"
        return str(int(raw_value))

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"manager={self.manager!r}, "
            f"widgets={self.widgets!r})"
        )