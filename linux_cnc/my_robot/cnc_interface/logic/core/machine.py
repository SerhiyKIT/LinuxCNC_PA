import linuxcnc
import config

class MachineController:
    """
    Low-level controller to interact with LinuxCNC API.
    Uses logic/config.py for machine parameters and limits.
    """
    def __init__(self):
        # Initialize LinuxCNC communication
        self.status = linuxcnc.stat()
        self.command = linuxcnc.command()
        
        # Load local copies of essential config data
        self.params = config.MACHINE_PARAMS
        self.limits = config.JOINT_LIMITS

    def poll(self):
        """Update machine status data"""
        self.status.poll()

    # --- STATE CONTROL ---

    def toggle_estop(self):
        """Toggle Emergency Stop state"""
        self.poll()
        new_state = linuxcnc.STATE_ESTOP_RESET if self.status.estop == linuxcnc.STATE_ESTOP else linuxcnc.STATE_ESTOP
        self.command.state(new_state)

    def set_power(self, state: bool):
        """Switch Machine Power ON/OFF"""
        new_state = linuxcnc.STATE_ON if state else linuxcnc.STATE_OFF
        self.command.state(new_state)

    def set_mode(self, mode):
        """
        Switch task mode (MANUAL, MDI, AUTO).
        mode: linuxcnc.MODE_MANUAL, etc.
        """
        self.poll()
        if self.status.task_mode != mode:
            self.command.mode(mode)
            self.command.wait_complete()

    # --- MOTION CONTROL ---

    def home_axis(self, axis_num):
        """
        Home a specific axis or all axes (-1).
        Enforces Manual mode and disables teleop.
        """
        self.set_mode(linuxcnc.MODE_MANUAL)
        self.command.teleop_enable(0)
        self.command.home(int(axis_num))

    def jog(self, axis_index, direction, speed, increment=0):
        """
        Execute jogging command.
        axis_index: 0 for X, 1 for Y, etc.
        direction: 1 (positive) or -1 (negative)
        speed: actual velocity
        increment: 0 for continuous, >0 for incremental
        """
        self.set_mode(linuxcnc.MODE_MANUAL)
        
        if increment == 0:
            # Continuous movement
            self.command.jog(linuxcnc.JOG_CONTINUOUS, axis_index, direction * speed)
        else:
            # Incremental movement
            self.command.jog(linuxcnc.JOG_INCREMENT, axis_index, direction * speed, increment)

    def stop_jog(self, axis_index):
        """Stop movement on specific axis"""
        self.command.jog(linuxcnc.JOG_STOP, axis_index)

    # --- PROGRAM EXECUTION ---

    def run_program(self, line_number=0):
        """Start G-code execution from specific line"""
        self.set_mode(linuxcnc.MODE_AUTO)
        self.command.auto(linuxcnc.AUTO_RUN, line_number)

    def abort(self):
        """Stop all motions and program execution immediately"""
        self.command.abort()

    # --- HELPERS / GETTERS ---

    def is_idle(self):
        """Check if interpreter is doing nothing"""
        self.poll()
        return self.status.interp_state == linuxcnc.INTERP_IDLE

    def get_position(self):
        """Return current Cartesian position (X, Y, Z, A, B, C)"""
        self.poll()
        return self.status.position
    
    # --- SPECIFIC ROBOT LOGIC (Puma 560 / Switchkins) ---

    def set_kinematics_type(self, kins_type: int):
        """
        Switch between different kinematics types using motion.analog-out-03.
        Commonly: 0 = Identity (Joints), 1 = XYZ (World)
        """
        # M68 E3 Q[kins_type]
        self.command.analog_output(3, float(kins_type))
        self.log.info(f"Kinematics type changed to: {kins_type}")

    def set_teleop(self, enable: bool):
        """
        Enable/Disable Teleop mode.
        Must be 0 for Homing and Joint-jogging.
        Must be 1 for Cartesian-jogging (XYZ movement).
        """
        self.poll()
        state = 1 if enable else 0
        if self.status.kinematics_type != state:
            self.command.teleop_enable(state)
            self.command.wait_complete()

    def home_all_sequence(self):
        """
        Execute homing sequence for a robot.
        Robots usually require Joint mode for homing.
        """
        self.set_teleop(False) # Ensure we are in Joint mode
        for i in range(config.MACHINE_PARAMS["JOINTS_COUNT"]):
            self.home_axis(i)
            self.command.wait_complete()