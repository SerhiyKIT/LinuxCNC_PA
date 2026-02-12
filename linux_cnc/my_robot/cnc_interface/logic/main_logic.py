# logic/main_logic.py
import linuxcnc
from PyQt5 import QtCore
from core.machine import MachineController
from core.logger import LoggerController
from managers.control_manager import ControlManager
from managers.style_manager import StyleManager
from managers.ui_manager import UIManager
from managers.jog_manager import JogManager

import config

class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.halcomp = halcomp
        self.widgets = widgets
        self.paths = paths
        
        self.params = config.MACHINE_PARAMS
        
        # Initialize core controllers
        self.cnc = MachineController()
        # Initialize logger controller
        self.logger_ctrl = LoggerController(self.cnc)
        # Initialize style manager
        self.styles = StyleManager()
        # Initialize UI manager
        self.ui_manager = UIManager(self.cnc, self.widgets)
        # Initialize control manager
        self.control = ControlManager(self.cnc, self.widgets)
        # Initialize jog manager
        self.jog = JogManager(self.cnc, self.widgets)

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
        
        # Connect jog buttons
        self.jog._connect_jog_buttons()
        
        # Populate jog mode ComboBox
        if hasattr(self.widgets, 'combo_joint_mode'):
            self.widgets.combo_joint_mode.clear()
            self.widgets.combo_joint_mode.addItems(self.params.get("JOG_MODES", []))
        
        if hasattr(self.widgets, 'list_output_view'):
            self.ui_manager.setup_output_panel()

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
            self.ui_manager.log_message(text, level)

    def log_internal_message(self, message, level="info"):
        """Log internal events or errors to the UI log panel"""
        self.ui_manager.log_message(message, level)