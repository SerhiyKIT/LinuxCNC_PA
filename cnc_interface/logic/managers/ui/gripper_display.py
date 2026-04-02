# logic/managers/ui/gripper_display.py
"""
GripperDisplayManager – оновлення стану UI захвату на основі стану машини.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class GripperDisplayManager:
    """
    Відстежує стан машини і блокує/розблоковує елементи керування захватом.

    Не містить логіки захвату — лише реагує на зовнішні стани.

    Args:
        gripper_ui_binder: GripperUIBinder для безпечного роззброєння
                           захвату при E-Stop.
        widgets:           Контейнер віджетів UI.
    """

    def __init__(self, gripper_ui_binder, widgets: object) -> None:
        self._binder  = gripper_ui_binder
        self.widgets  = widgets

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def update_gripper_ui_state(self, states: dict) -> None:
        """
        Оновити стан кнопок і слайдера захвату відповідно до стану машини.

        Логіка:
          1. E-Stop активний → примусово роззброїти захват.
          2. Машина готова і не виконує програму → дозволити ручне керування.
        """
        power_on   = states.get("power_on",   False)
        estop_off  = states.get("estop_off",  False)
        all_homed  = states.get("all_homed",  False)
        is_running = states.get("is_running", False)

        # 1. Примусове роззброєння при E-Stop
        if not estop_off:
            self._force_disarm()

        # 2. Ручне керування дозволено лише якщо машина готова і не в роботі
        can_control = power_on and estop_off and all_homed and not is_running

        for widget_name in ("btn_tool_action", "sld_tool_power"):
            w = getattr(self.widgets, widget_name, None)
            if w is not None:
                w.setEnabled(can_control)

        btn_arm = getattr(self.widgets, "btn_tool_arm", None)
        if btn_arm is not None:
            btn_arm.setEnabled(power_on and estop_off)

    # ------------------------------------------------------------------
    # Приватні хелпери
    # ------------------------------------------------------------------

    def _force_disarm(self) -> None:
        """
        Примусово роззброїти захват через GripperUIBinder.
        Безпечно якщо binder або btn_tool_arm відсутні.
        """
        btn_arm = getattr(self.widgets, "btn_tool_arm", None)
        if btn_arm is None or not btn_arm.isChecked():
            return
        btn_arm.setChecked(False)
        # Делегуємо оновлення UI до binder щоб уникнути дублювання логіки
        if self._binder is not None:
            self._binder._on_arm_clicked()
        else:
            logger.warning("GripperDisplayManager: binder не встановлено")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(widgets={self.widgets!r})"