# logic/main_logic.py
"""
HandlerClass – головний обробник LinuxCNC UI.

Порядок ініціалізації:
  __init__      – викликається ДО loadUi. Тут лише об'єкти що НЕ
                  звертаються до конкретних дочірніх віджетів (btn_*, list_*).
  initialized__ – викликається ПІСЛЯ loadUi. Всі widgets існують.
                  Тут підключаємо кнопки, редактор, таймери.

Власник FileManager і GCodeEditorManager – HandlerClass.
GCodeDisplayManager і GCodeEditorManager отримують їх ззовні через
параметри, а не створюють самостійно.
"""
from PyQt5 import QtCore
from PyQt5.QtCore import QTranslator, QCoreApplication
import logging
import os

logger = logging.getLogger(__name__)

from core import MachineController, LoggerController
from managers import (
    ControlManager, UIManager,
    JointManager, JointUIBinder,
    AxisManager, AxisUIBinder,
    OverridesManager, OverridesUIBinder,
    CycleManager, CycleUIBinder,
    ToolManager, ToolUIBinder,
    KeyboardManager,
)
from managers.ui.gcode_editor import GCodeEditorManager
from managers.project_manager import ProjectManager
from config import STYLES, MACHINE_PARAMS, MGR_CONTROL, MGR_CYCLE, MGR_TOOL
from managers.ui.ui_mapping import UI_TEXT_MAPPING, UI_TOOLTIP_MAPPING


class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.halcomp = halcomp
        self.widgets = widgets
        self.paths   = paths

        self.translator = QTranslator()
        self.STYLE_GCODE_LIST       = STYLES.get('GCODE_LIST', '')
        self.STYLE_LINE_NUMBER_AREA = STYLES.get('LINE_NUMBER_AREA', '')
        self.params = MACHINE_PARAMS

        # ── Об'єкти що НЕ потребують дочірніх widgets ───────────────────
        self.cnc         = MachineController()
        self.logger_ctrl = LoggerController(self.cnc)

        self.cycle_manager     = CycleManager(self.cnc)
        self.joint_manager     = JointManager(self.cnc)
        self.axis_manager      = AxisManager(self.cnc)
        self.overrides_manager = OverridesManager(self.cnc)
        self.tool_manager      = ToolManager(self.cnc)

        self.control    = ControlManager(self.cnc, self.widgets)
        self.ui_manager = UIManager(self.cnc, self.widgets, self.cycle_manager)

        # GCodeEditorManager буде створений в initialized__ коли
        # list_gcode_edit вже існує
        self.editor_manager = None

        # Binders і keyboard – теж в initialized__
        self.cycle_ui_binder     = None
        self.joint_binder        = None
        self.axis_ui_binder      = None
        self.overrides_ui_binder = None
        self.tool_ui_binder      = None
        self.keyboard_manager    = None
        self.context_menu_manager = None
        self.project_manager      = None

    # ------------------------------------------------------------------
    # initialized__ – викликається ПІСЛЯ loadUi, всі widgets існують
    # ------------------------------------------------------------------

    def initialized__(self):
        # ── ProjectManager ────────────────────────────────────────────────
        self.project_manager = ProjectManager(self.widgets)
        self.project_manager.connect_buttons()
        # Callback: відкрити файл проекту у GCodeEditor
        self.project_manager.set_open_file_callback(self._on_project_open_file)

        # ── GCodeEditorManager (потребує list_gcode_edit) ────────────────
        self.editor_manager = GCodeEditorManager(
            self.cnc,
            self.widgets,
            self.cycle_manager,
        )

        # Передати editor_manager у gcode_display_manager
        self.ui_manager.gcode_display_manager.editor_manager = self.editor_manager

        # Передати editor_manager у project_manager —
        # потрібен для clear_editor() при видаленні проекту/файлу
        self.project_manager.set_editor_manager(self.editor_manager)

        # ── Binders ──────────────────────────────────────────────────────
        self.cycle_ui_binder      = CycleUIBinder(self.cycle_manager, self.widgets)
        self.joint_binder         = JointUIBinder(self.joint_manager, self.widgets)
        self.axis_ui_binder       = AxisUIBinder(self.axis_manager, self.widgets)
        self.overrides_ui_binder  = OverridesUIBinder(self.overrides_manager, self.widgets)
        self.tool_ui_binder       = ToolUIBinder(self.tool_manager, self.widgets)

        self.managers_map = {
            MGR_CONTROL: self.control,
            MGR_CYCLE:   self.cycle_manager,
            MGR_TOOL:    self.tool_manager,
        }
        self.keyboard_manager = KeyboardManager(self.widgets, self.managers_map)

        # ── Таймери ───────────────────────────────────────────────────────
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._update_ui)
        self.timer.start(self.params.get("POLL_INTERVAL", 100))

        self.msg_timer = QtCore.QTimer()
        self.msg_timer.timeout.connect(self.check_system_messages)
        self.msg_timer.start(self.params.get("POLL_INTERVAL", 100))

        # ── З'єднання ─────────────────────────────────────────────────────
        self._setup_connections()
        self.set_default_language("ua")

    # ------------------------------------------------------------------

    def _setup_connections(self):
        # E-Stop
        if hasattr(self.widgets, 'btn_estop'):
            self.widgets.btn_estop.clicked.connect(
                self.control.on_btn_estop_clicked)

        # Power Off
        if hasattr(self.widgets, 'btn_power_off'):
            self.widgets.btn_power_off.clicked.connect(
                lambda: self.control.on_btn_power_off_clicked(self.cnc.get_states()))

        # Home All
        if hasattr(self.widgets, 'btn_home_all'):
            self.widgets.btn_home_all.clicked.connect(
                self.control.on_btn_home_all_clicked)

        # Overlays
        if hasattr(self.widgets, 'joint_control_overlay'):
            self.widgets.joint_control_overlay.mousePressEvent = (
                lambda e: self.control.on_overlay_clicked(self.cnc.get_states(), "joint"))
        if hasattr(self.widgets, 'axis_control_overlay'):
            self.widgets.axis_control_overlay.mousePressEvent = (
                lambda e: self.control.on_overlay_clicked(self.cnc.get_states(), "axis"))

        # Joint / Axis / Overrides
        self.joint_binder.connect_buttons()
        self.axis_ui_binder.connect_buttons()
        self.overrides_ui_binder.setup_overrides()

        # Jog ComboBoxes
        for combo_name in ('combo_joint_mode', 'combo_axis_mode'):
            combo = getattr(self.widgets, combo_name, None)
            if combo:
                combo.clear()
                combo.addItems(self.params.get("JOG_MODES", []))

        # Cycle
        self.cycle_ui_binder.connect_buttons()

        # Tool
        self.tool_ui_binder.connect_tool_buttons()

        # Output panel
        if hasattr(self.widgets, 'list_output_view'):
            self.ui_manager.logger_display_manager.setup_output_panel()

        # Keyboard
        self.widgets.window().keyPressEvent = (
            lambda event: self.keyboard_manager.processed_key_event(event, True))
        self.widgets.window().keyReleaseEvent = (
            lambda event: self.keyboard_manager.processed_key_event(event, False))

        # Language
        if hasattr(self.widgets, 'combo_language'):
            self.widgets.combo_language.clear()
            self.widgets.combo_language.addItem("EN", "en")
            self.widgets.combo_language.addItem("UA", "ua")
            self.widgets.combo_language.currentIndexChanged.connect(self.change_language)

    # ------------------------------------------------------------------

    def _on_project_open_file(self, filepath: str, read_only: bool) -> None:
        """
        Відкрити файл проекту у GCodeEditor.
        Використовує editor_manager.load_file() напряму.
        .ngc/.gcode файли ігноруються — editor_manager їх відкине.
        """
        if self.editor_manager is None:
            return
        self.editor_manager.load_file(filepath, read_only=read_only)

    def _update_ui(self):
        try:
            self.cnc.poll()
            states = self.cnc.get_states()
            self.ui_manager.update_ui(states)
        except Exception as e:
            print(f"DEBUG: Loop error: {e}")

    def check_system_messages(self):
        res = self.cnc.poll_errors()
        if res:
            text, level = res
            self.ui_manager.logger_display_manager.log_message(text, level)

    def log_internal_message(self, message, level="info"):
        self.ui_manager.logger_display_manager.log_message(message, level)

    # ------------------------------------------------------------------
    # Мова
    # ------------------------------------------------------------------

    def change_language(self, index):
        if not hasattr(self.widgets, 'combo_language'):
            return
        lang_code = self.widgets.combo_language.itemData(index)
        QCoreApplication.removeTranslator(self.translator)
        if lang_code == "ua":
            qm_path = os.path.join(os.path.dirname(__file__), "i18n", "lang_ua.qm")
            if self.translator.load(qm_path):
                QCoreApplication.installTranslator(self.translator)
                print(f"DEBUG: Loaded: {qm_path}")
            else:
                print(f"DEBUG: Not found: {qm_path}")
        else:
            print("DEBUG: Language set to English")
        self.refresh_interface_texts()

    def refresh_interface_texts(self):
        ctx = "MainWindow"
        for obj_name, source_text in UI_TEXT_MAPPING.items():
            if hasattr(self.widgets, obj_name):
                getattr(self.widgets, obj_name).setText(
                    QCoreApplication.translate(ctx, source_text))
        for obj_name, source_text in UI_TOOLTIP_MAPPING.items():
            if hasattr(self.widgets, obj_name):
                getattr(self.widgets, obj_name).setToolTip(
                    QCoreApplication.translate(ctx, source_text))
        for combo_name in ('combo_joint_mode', 'combo_axis_mode'):
            combo = getattr(self.widgets, combo_name, None)
            if combo:
                combo.setItemText(0, QCoreApplication.translate(ctx, "Continuous"))
        if hasattr(self.widgets, 'combo_language'):
            combo  = self.widgets.combo_language
            idx_en = combo.findData("en")
            idx_ua = combo.findData("ua")
            if idx_en >= 0:
                combo.setItemText(idx_en, QCoreApplication.translate(ctx, "EN"))
            if idx_ua >= 0:
                combo.setItemText(idx_ua, QCoreApplication.translate(ctx, "UA"))
        self.overrides_ui_binder.refresh_all_labels()

    def set_default_language(self, lang_code):
        if hasattr(self.widgets, 'combo_language'):
            index = self.widgets.combo_language.findData(lang_code)
            if index >= 0:
                self.widgets.combo_language.setCurrentIndex(index)

    def _setup_gcode_sync(self):
        """No-op: збережено для сумісності."""