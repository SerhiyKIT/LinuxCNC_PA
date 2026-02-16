# logic/main_logic.py
from PyQt5 import QtCore
from core import MachineController
from core import LoggerController
from managers import ControlManager
from managers import UIManager
from managers import JointManager
from managers import AxisManager
from managers import OverridesManager
from managers import FileManager
from managers import CycleManager
from managers import ToolManager
from managers import KeyboardManager
import config

class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.halcomp = halcomp
        self.widgets = widgets
        self.paths = paths
        
        self.STYLE_GCODE_LIST = config.STYLES.get('GCODE_LIST', '')
        
        # Load machine parameters from config
        self.params = config.MACHINE_PARAMS
        
        # Initialize core controllers
        self.cnc = MachineController()
        # Initialize logger controller
        self.logger_ctrl = LoggerController(self.cnc)
        # Initialize UI manager
        self.ui_manager = UIManager(self.cnc, self.widgets)
        # Initialize control manager
        self.control = ControlManager(self.cnc, self.widgets)
        # Initialize joint manager
        self.joint_manager = JointManager(self.cnc, self.widgets)
        # Initialize axis manager
        self.axis_manager = AxisManager(self.cnc, self.widgets)
        # Initialize overrides manager
        self.overrides_manager = OverridesManager(self.cnc, self.widgets)
        # Initialize file manager
        self.file_manager = FileManager(self.cnc, self.widgets)
        # Initialize cycle manager
        self.cycle_manager = CycleManager(self.cnc, self.widgets)
        # Initialize tool manager
        self.tool_manager = ToolManager(self.cnc, self.widgets)
        
        # Create a mapping of manager keys to their instances for easy access from the keyboard manager
        self.managers_map = {
            config.MGR_CONTROL: self.control,
            config.MGR_CYCLE:   self.cycle_manager,
            config.MGR_TOOL:    self.tool_manager,
            config.MGR_FILE:    self.file_manager
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
        self.joint_manager.connect_all_jog_buttons()
        
        # Connect axis buttons
        self.axis_manager.connect_all_axis_buttons()
        
        # Connect override sliders
        self.overrides_manager.setup_overrides()
        
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
        self.cycle_manager.connect_cycle_buttons()
        
        # Connect tool management buttons
        self.tool_manager.connect_tool_buttons()
            
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