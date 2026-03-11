# logic/main_logic.py
from PyQt5 import QtCore
from PyQt5.QtCore import QTranslator, QCoreApplication, QEvent
import os
from core import MachineController
from core import LoggerController
from managers import ControlManager
from managers import UIManager
from managers import JointManager, JointUIBinder
from managers import AxisManager, AxisUIBinder
from managers import OverridesManager, OverridesUIBinder
from managers import FileManager
from managers import CycleManager, CycleUIBinder
from managers import ToolManager, ToolUIBinder
from managers import KeyboardManager
from config import STYLES, MACHINE_PARAMS, MGR_CONTROL, MGR_CYCLE, MGR_FILE, MGR_TOOL
from managers.ui.ui_mapping import UI_TEXT_MAPPING, UI_TOOLTIP_MAPPING

class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.halcomp = halcomp
        self.widgets = widgets
        self.paths = paths
        
        self.translator = QTranslator()
        
        self.STYLE_GCODE_LIST = STYLES.get('GCODE_LIST', '')
        
        # Load machine parameters from config
        self.params = MACHINE_PARAMS
        
        # Initialize core controllers
        self.cnc = MachineController()
        # Initialize logger controller
        self.logger_ctrl = LoggerController(self.cnc)
        # Initialize UI manager
        self.ui_manager = UIManager(self.cnc, self.widgets)
        # Initialize control manager
        self.control = ControlManager(self.cnc, self.widgets)
        # Initialize joint manager
        self.joint_manager = JointManager(self.cnc)
        self.joint_binder = JointUIBinder(self.joint_manager, self.widgets)
        # Initialize axis manager
        self.axis_manager = AxisManager(self.cnc)
        self.axis_ui_binder = AxisUIBinder(self.axis_manager, self.widgets)
        # Initialize overrides manager
        self.overrides_manager = OverridesManager(self.cnc)
        self.overrides_ui_binder = OverridesUIBinder(self.overrides_manager, self.widgets)
        # Initialize file manager
        self.file_manager = FileManager(self.cnc, self.widgets)
        # Initialize cycle manager
        self.cycle_manager = CycleManager(self.cnc)
        self.cycle_ui_binder = CycleUIBinder(self.cycle_manager, self.widgets)
        # Initialize tool manager
        self.tool_manager = ToolManager(self.cnc)
        self.tool_ui_binder = ToolUIBinder(self.tool_manager, self.widgets)
        
        # Create a mapping of manager keys to their instances for easy access from the keyboard manager
        self.managers_map = {
            MGR_CONTROL: self.control,
            MGR_CYCLE:   self.cycle_manager,
            MGR_TOOL:    self.tool_manager,
            MGR_FILE:    self.file_manager
        }
        
        # Initialize keyboard manager with references to other managers for command execution
        self.keyboard_manager = KeyboardManager(self.widgets, self.managers_map)
        

    def initialized__(self):
        # Start the main update loop
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._update_ui)
        self.timer.start(self.params.get("POLL_INTERVAL", 100))
        
        # Start the system message polling loop
        self.msg_timer = QtCore.QTimer()
        self.msg_timer.timeout.connect(self.check_system_messages)
        self.msg_timer.start(self.params.get("POLL_INTERVAL", 100))
        
        # Setup UI connections
        self._setup_connections()
        
        # 
        self.set_default_language("ua")

    def _setup_connections(self):
        # Connect E-Stop button
        if hasattr(self.widgets, 'btn_estop'):
            self.widgets.btn_estop.clicked.connect(self.control.on_btn_estop_clicked)
            print("DEBUG: btn_estop connected to ControlManager")

        # Connect Power button
        if hasattr(self.widgets, 'btn_power_off'):
            self.widgets.btn_power_off.clicked.connect(lambda: self.control.on_btn_power_off_clicked(self.cnc.get_states()))
            print("DEBUG: btn_power_off connected to ControlManager")
            
        # Connect Home All button
        if hasattr(self.widgets, 'btn_home_all'):
            self.widgets.btn_home_all.clicked.connect(self.control.on_btn_home_all_clicked)
            print("DEBUG: btn_home_all connected to HandlerClass")
        
        # Connect coordinate overlay clicks to switch control modes
        if hasattr(self.widgets, 'joint_control_overlay'):
            self.widgets.joint_control_overlay.mousePressEvent = lambda e: self.control.on_overlay_clicked(self.cnc.get_states(), "joint")
        if hasattr(self.widgets, 'axis_control_overlay'):
            self.widgets.axis_control_overlay.mousePressEvent = lambda e: self.control.on_overlay_clicked(self.cnc.get_states(), "axis")
        
        # Connect joint buttons
        self.joint_binder.connect_buttons()
        
        # Connect axis buttons
        self.axis_ui_binder.connect_buttons()
        
        # Connect override sliders
        self.overrides_ui_binder.setup_overrides()
        
        # Populate jog mode ComboBox
        if hasattr(self.widgets, 'combo_joint_mode'):
            self.widgets.combo_joint_mode.clear()
            self.widgets.combo_joint_mode.addItems(self.params.get("JOG_MODES", []))
        
        if hasattr(self.widgets, 'combo_axis_mode'):
            self.widgets.combo_axis_mode.clear()
            self.widgets.combo_axis_mode.addItems(self.params.get("JOG_MODES", []))
        
        # Setup file management buttons
        self.file_manager.connect_file_buttons()
        if hasattr(self.widgets, 'list_gcode_view'):
            self.widgets.list_gcode_view.setStyleSheet(self.STYLE_GCODE_LIST)
            
        # Connect cycle control buttons
        self.cycle_ui_binder.connect_buttons()
        
        # Connect tool management buttons
        self.tool_ui_binder.connect_tool_buttons()
            
        # Allow editing G-code lines directly in the list view
        if hasattr(self.widgets, 'list_gcode_view'):
            self.widgets.list_gcode_view.setEditTriggers(
            self.widgets.list_gcode_view.AnyKeyPressed | 
            self.widgets.list_gcode_view.DoubleClicked
        )
        
        # Setup output panel if the widget exists
        if hasattr(self.widgets, 'list_output_view'):
            self.ui_manager.logger_display_manager.setup_output_panel()
        
        # Connect keyboard events to the keyboard manager
        self.widgets.window().keyPressEvent = lambda event: self.keyboard_manager.processed_key_event(event, True)
        self.widgets.window().keyReleaseEvent = lambda event: self.keyboard_manager.processed_key_event(event, False)
        
        # 
        if hasattr(self.widgets, 'combo_language'):
            self.widgets.combo_language.clear()
            self.widgets.combo_language.addItem("EN", "en")
            self.widgets.combo_language.addItem("UA", "ua")
            self.widgets.combo_language.currentIndexChanged.connect(self.change_language)

    def _update_ui(self):
        """Main loop for polling machine status and updating UI"""
        try:
            self.cnc.poll()
            states = self.cnc.get_states()
            self.ui_manager.update_ui(states)
        except Exception as e:
            print(f"DEBUG: Loop error: {e}") 
            pass
    
    def check_system_messages(self):
        """Check for new messages from LinuxCNC and log them"""
        res = self.cnc.poll_errors()
        if res:
            text, level = res
            self.ui_manager.logger_display_manager.log_message(text, level)

    def log_internal_message(self, message, level="info"):
        """Log internal events or errors to the UI log panel"""
        self.ui_manager.logger_display_manager.log_message(message, level)
        
    def change_language(self, index):
        """"""
        if not hasattr(self.widgets, 'combo_language'):
            return
            
        lang_code = self.widgets.combo_language.itemData(index)
        
        QCoreApplication.removeTranslator(self.translator)
        
        if lang_code == "ua":
            qm_path = os.path.join(os.path.dirname(__file__), "i18n", "lang_ua.qm")
            
            if self.translator.load(qm_path):
                QCoreApplication.installTranslator(self.translator)
                print(f"DEBUG: SUCCESS! Loaded: {qm_path}")
            else:
                print(f"DEBUG: ERROR! File not found at: {qm_path}")
        else:
            print("DEBUG: Language set to English (Default)")

        self.refresh_interface_texts()

    def refresh_interface_texts(self):
        ctx = "MainWindow"
        
        # 1. 
        for obj_name, source_text in UI_TEXT_MAPPING.items():
            if hasattr(self.widgets, obj_name):
                widget = getattr(self.widgets, obj_name)
                translated = QCoreApplication.translate(ctx, source_text)
                widget.setText(translated)

        # 2.
        for obj_name, source_text in UI_TOOLTIP_MAPPING.items():
            if hasattr(self.widgets, obj_name):
                widget = getattr(self.widgets, obj_name)
                translated = QCoreApplication.translate(ctx, source_text)
                widget.setToolTip(translated)

        # 3.
        if hasattr(self.widgets, 'combo_joint_mode'):
            combo = self.widgets.combo_joint_mode
            translated_cont = QCoreApplication.translate(ctx, "Continuous")
            combo.setItemText(0, translated_cont)
            
        if hasattr(self.widgets, 'combo_axis_mode'):
            combo = self.widgets.combo_axis_mode
            translated_cont = QCoreApplication.translate(ctx, "Continuous")
            combo.setItemText(0, translated_cont)
        
        if hasattr(self.widgets, 'combo_language'):
            combo = self.widgets.combo_language
            idx_en = combo.findData("en")
            idx_ua = combo.findData("ua")
            if idx_en >= 0:
                combo.setItemText(idx_en, QCoreApplication.translate(ctx, "EN"))
            if idx_ua >= 0:
                combo.setItemText(idx_ua, QCoreApplication.translate(ctx, "UA"))
            
        # 4.
        self.overrides_ui_binder.refresh_all_labels()
            
    def set_default_language(self, lang_code):
        """Set"""
        if hasattr(self.widgets, 'combo_language'):
            index = self.widgets.combo_language.findData(lang_code)
            if index >= 0:
                self.widgets.combo_language.setCurrentIndex(index)
                print(f"DEBUG: Default language set to: {lang_code}")