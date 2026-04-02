# logic/managers/gripper_manager.py
"""
GripperManager  – логіка безпеки та виконання команд захвату.
GripperUIBinder – підключення кнопок/слайдера захвату до GripperManager.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt5.QtCore import QCoreApplication

from config import STYLES

if TYPE_CHECKING:
    from core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------

_MDI_GRIP    = "M101"
_MDI_RELEASE = "M102"

_REQUIRED_HOMED_JOINTS = 3

_TXT_ARMED    = "ARMED"
_TXT_DISARMED = "DISARMED"
_TXT_GRIP     = "GRIP"
_TXT_RELEASE  = "RELEASE"

_STATUS_READY   = "STATUS: READY"
_STATUS_LOCKED  = "STATUS: LOCKED"
_STATUS_HOLDING = "STATUS: HOLDING"
_STATUS_OPEN    = "STATUS: OPEN"

_POWER_MIN = 10
_POWER_MAX = 100


# ---------------------------------------------------------------------------
# GripperManager
# ---------------------------------------------------------------------------

class GripperManager:
    """
    Перевіряє блокування безпеки та виконує команди захвату.

    Не містить UI-логіки — вся комунікація з машиною делегується
    MachineController.

    Ланцюжок безпеки для perform_grip_action():
      1. Захват повинен бути активований (is_armed).
      2. Перші _REQUIRED_HOMED_JOINTS суглобів повинні бути захоумлені.
    """

    __slots__ = ("cnc", "__weakref__")

    def __init__(self, machine_controller: "MachineController") -> None:
        self.cnc = machine_controller

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def arm(self, armed: bool) -> bool:
        """
        Активувати або деактивувати захват.

        При деактивації надсилає MDI-команду release якщо суглоби захоумлені.

        Returns:
            armed без змін — дозволяє використовувати повернене значення
            як новий прапор стану.
        """
        if not armed:
            if self._joints_homed():
                self.cnc.send_mdi(_MDI_RELEASE)
            return False
        return True

    def perform_grip_action(self, is_grip: bool, is_armed: bool) -> bool:
        """
        Виконати дію захвату або відпускання.

        Args:
            is_grip:  True — захопити, False — відпустити.
            is_armed: Чи активований захват.

        Returns:
            True якщо MDI-команда прийнята, False при відмові безпеки.
        """
        if not is_armed:
            logger.warning("[GRIPPER] Доступ заборонено: спочатку активуйте захват")
            return False
        if not self._joints_homed():
            logger.warning("[GRIPPER] Доступ заборонено: спочатку захоумте суглоби")
            return False
        cmd = _MDI_GRIP if is_grip else _MDI_RELEASE
        return self.cnc.send_mdi(cmd)

    def set_grip_force(self, percentage: int) -> float:
        """
        Встановити силу захвату у відсотках (10…100).

        Returns:
            Нормалізоване значення (percentage / 100.0).
        """
        force = percentage / 100.0
        self.cnc.set_gripper_force(force)
        return force

    # ------------------------------------------------------------------
    # Приватні хелпери
    # ------------------------------------------------------------------

    def _joints_homed(self) -> bool:
        return all(self.cnc.status.homed[:_REQUIRED_HOMED_JOINTS])

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"


# ---------------------------------------------------------------------------
# GripperUIBinder
# ---------------------------------------------------------------------------

class GripperUIBinder:
    """
    Підключає кнопки керування захватом і слайдер до GripperManager.

    Відповідальності:
      • Налаштування та підключення Arm, Action, Power-слайдера.
      • Оновлення тексту, стилів і статус-лейбла після кожної взаємодії.
      • Не містить логіки руху — всі рішення делегуються GripperManager.
    """

    __slots__ = (
        "manager",
        "widgets",
        "STYLE_ARMED",
        "STYLE_DISARMED",
        "STYLE_GRIP_ACTIVE",
        "STYLE_GRIP_INACTIVE",
        "__weakref__",
    )

    def __init__(self, gripper_manager: GripperManager, widgets: object) -> None:
        self.manager = gripper_manager
        self.widgets = widgets

        self.STYLE_ARMED        = STYLES.get("TOOL_ARMED",    "")
        self.STYLE_DISARMED     = STYLES.get("TOOL_DISARMED", "")
        self.STYLE_GRIP_ACTIVE  = STYLES.get("GRIP_ACTIVE",   "")
        self.STYLE_GRIP_INACTIVE= STYLES.get("GRIP_INACTIVE", "")

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def connect_buttons(self) -> None:
        """Налаштувати і підключити кнопку Arm, кнопку Action і слайдер Power."""
        self._setup_arm_button()
        self._setup_action_button()
        self._setup_power_slider()

    # ------------------------------------------------------------------
    # Обробники сигналів
    # ------------------------------------------------------------------

    def _on_arm_clicked(self) -> None:
        btn      = self.widgets.btn_tool_arm
        is_armed = btn.isChecked()
        self.manager.arm(is_armed)
        self._apply_arm_style(btn, is_armed)
        if not is_armed:
            self._update_action_ui(False)
        self._update_status_label(is_armed)

    def _on_action_clicked(self) -> None:
        btn_action = self.widgets.btn_tool_action
        is_armed   = self.widgets.btn_tool_arm.isChecked()
        is_grip    = btn_action.isChecked()
        success    = self.manager.perform_grip_action(is_grip, is_armed)
        if success:
            self._update_action_ui(is_grip)
        else:
            btn_action.setChecked(False)

    def _on_power_changed(self, value: int) -> None:
        self.manager.set_grip_force(value)
        lbl = getattr(self.widgets, "lbl_tool_power_val", None)
        if lbl is not None:
            lbl.setText(f"{value} %")

    # ------------------------------------------------------------------
    # Налаштування віджетів
    # ------------------------------------------------------------------

    def _setup_arm_button(self) -> None:
        btn = getattr(self.widgets, "btn_tool_arm", None)
        if btn is not None:
            btn.setCheckable(True)
            btn.clicked.connect(self._on_arm_clicked)

    def _setup_action_button(self) -> None:
        btn = getattr(self.widgets, "btn_tool_action", None)
        if btn is not None:
            btn.setCheckable(True)
            btn.clicked.connect(self._on_action_clicked)

    def _setup_power_slider(self) -> None:
        sld = getattr(self.widgets, "sld_tool_power", None)
        if sld is not None:
            sld.setMinimum(_POWER_MIN)
            sld.setMaximum(_POWER_MAX)
            sld.valueChanged.connect(self._on_power_changed)

    # ------------------------------------------------------------------
    # Оновлення UI
    # ------------------------------------------------------------------

    def _apply_arm_style(self, btn: object, is_armed: bool) -> None:
        txt   = _TXT_ARMED if is_armed else _TXT_DISARMED
        style = self.STYLE_ARMED if is_armed else self.STYLE_DISARMED
        btn.setText(QCoreApplication.translate("MainWindow", txt))
        btn.setStyleSheet(style)

    def _update_action_ui(self, is_grip: bool) -> None:
        btn = getattr(self.widgets, "btn_tool_action", None)
        if btn is None:
            return
        btn.setChecked(is_grip)
        btn.setText(QCoreApplication.translate(
            "MainWindow", _TXT_RELEASE if is_grip else _TXT_GRIP))
        btn.setStyleSheet(
            self.STYLE_GRIP_ACTIVE if is_grip else self.STYLE_GRIP_INACTIVE)
        lbl = getattr(self.widgets, "lbl_tool_status", None)
        if lbl is not None:
            lbl.setText(QCoreApplication.translate(
                "MainWindow", _STATUS_HOLDING if is_grip else _STATUS_OPEN))

    def _update_status_label(self, is_armed: bool) -> None:
        lbl = getattr(self.widgets, "lbl_tool_status", None)
        if lbl is not None:
            lbl.setText(QCoreApplication.translate(
                "MainWindow", _STATUS_READY if is_armed else _STATUS_LOCKED))

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"manager={self.manager!r}, widgets={self.widgets!r})")