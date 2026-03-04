from PyQt5.QtCore import QCoreApplication
from config import STYLES

class ToolManager:
    """Відповідає за безпеку та логіку керування інструментом (Gripper)"""
    def __init__(self, machine_controller):
        self.cnc = machine_controller

    def arm_tool(self, armed: bool):
        """Логіка активації живлення інструменту"""
        if not armed:
            # При знятті з озброєння — безпечне розтискання
            if all(self.cnc.status.homed[:3]):
                self.cnc.send_mdi("M102")
            return False
        return True

    def perform_action(self, is_grip: bool, is_armed: bool) -> bool:
        """Спроба затиснути або розтиснути інструмент"""
        # Перевірка безпеки 1: Чи озброєний інструмент?
        if not is_armed:
            print("WARNING: [GRIPPER] Access Denied: Arm Tool first!")
            return False

        # Перевірка безпеки 2: Чи зроблено Home?
        if not all(self.cnc.status.homed[:3]):
            print("WARNING: [GRIPPER] Access Denied: Home joints first!")
            return False

        cmd = "M101" if is_grip else "M102"
        return self.cnc.send_mdi(cmd)

    def set_power(self, percentage: int):
        """Встановлення сили затискання (0.1 - 1.0)"""
        force = percentage / 100.0
        self.cnc.set_gripper_force(force)
        return force


class ToolUIBinder:
    """Відповідає за стан кнопок, слайдери та стилі інструменту в UI"""
    def __init__(self, tool_manager, widgets):
        self.manager = tool_manager
        self.widgets = widgets
        
        # Стилі з конфігу
        self.STYLE_TOOL_ARMED = STYLES.get('TOOL_ARMED', '')
        self.STYLE_TOOL_DISARMED = STYLES.get('TOOL_DISARMED', '')
        self.STYLE_GRIP_ACTIVE = STYLES.get('GRIP_ACTIVE', '')
        self.STYLE_GRIP_INACTIVE = STYLES.get('GRIP_INACTIVE', '')

    def connect_tool_buttons(self):
        # Налаштування кнопки Arm
        btn_arm = getattr(self.widgets, 'btn_tool_arm', None)
        if btn_arm:
            btn_arm.setCheckable(True)
            btn_arm.clicked.connect(self._on_arm_clicked)

        # Налаштування кнопки Action (Grip/Release)
        btn_action = getattr(self.widgets, 'btn_tool_action', None)
        if btn_action:
            btn_action.setCheckable(True)
            btn_action.clicked.connect(self._on_action_clicked)

        # Налаштування слайдера потужності
        sld_power = getattr(self.widgets, 'sld_tool_power', None)
        if sld_power:
            sld_power.setMinimum(10)
            sld_power.setMaximum(100)
            sld_power.valueChanged.connect(self._on_power_changed)

    def _on_arm_clicked(self):
        btn = self.widgets.btn_tool_arm
        is_armed = btn.isChecked()
        
        self.manager.arm_tool(is_armed)
        
        # Оновлення UI
        txt = "ARMED" if is_armed else "DISARMED"
        btn.setText(QCoreApplication.translate("MainWindow", txt))
        btn.setStyleSheet(self.STYLE_TOOL_ARMED if is_armed else self.STYLE_TOOL_DISARMED)
        
        if not is_armed:
            self._update_action_ui(False) # Скидання кнопки затискання

        self._update_status_label(is_armed)

    def _on_action_clicked(self):
        btn_action = self.widgets.btn_tool_action
        is_armed = self.widgets.btn_tool_arm.isChecked()
        is_grip = btn_action.isChecked()

        success = self.manager.perform_action(is_grip, is_armed)
        
        if success:
            self._update_action_ui(is_grip)
        else:
            btn_action.setChecked(False) # Відкат стану при помилці

    def _on_power_changed(self, value):
        self.manager.set_power(value)
        lbl = getattr(self.widgets, 'lbl_tool_power_val', None)
        if lbl: lbl.setText(f"{value} %")

    def _update_action_ui(self, is_grip):
        btn = getattr(self.widgets, 'btn_tool_action', None)
        if not btn: return
        
        btn.setChecked(is_grip)
        btn.setText(QCoreApplication.translate("MainWindow", "RELEASE" if is_grip else "GRIP"))
        btn.setStyleSheet(self.STYLE_GRIP_ACTIVE if is_grip else self.STYLE_GRIP_INACTIVE)
        
        # Оновлення статусу текстом
        lbl = getattr(self.widgets, 'lbl_tool_status', None)
        if lbl:
            status_txt = "STATUS: HOLDING" if is_grip else "STATUS: OPEN"
            lbl.setText(QCoreApplication.translate("MainWindow", status_txt))

    def _update_status_label(self, is_armed):
        lbl = getattr(self.widgets, 'lbl_tool_status', None)
        if lbl:
            status_msg = "STATUS: READY" if is_armed else "STATUS: LOCKED"
            lbl.setText(QCoreApplication.translate("MainWindow", status_msg))