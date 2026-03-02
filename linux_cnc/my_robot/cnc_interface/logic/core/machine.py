# logic/core/machine.py
import linuxcnc
import config
import os

class MachineController:
    """
    Low-level controller to interact with LinuxCNC API.
    Uses logic/config.py for machine parameters and limits.
    """
    def __init__(self):
        # Initialize LinuxCNC communication
        self.status = linuxcnc.stat()
        self.command = linuxcnc.command()
        
        # Channel for receiving error messages from LinuxCNC
        self.error_channel = linuxcnc.error_channel()
        
        # Load local copies of essential config data
        self.params = config.MACHINE_PARAMS
        self.limits = config.JOINT_LIMITS
        
        self.speed = self.params.get("LINEAR_VEL", 1.0) * 60
        
        self.linear_jog_speed = 300.0
        self.angular_jog_speed = 30.0
        
        self.manual_mode = config.DEFAULT_MANUAL_MODE
        
        self.last_loaded_file = None
        self.reload_needed = False
        
        # Parameters for jog control Sand teleop
        self.JOG_CMD_FLAG = self.params.get("JOG_CMD_FLAG", 1)
        self.TELEOP_ENABLE_VAL = self.params.get("TELEOP_ENABLE_VAL", 0)

    # --- POLLING / STATUS ---

    def poll(self):
        """Update machine status data"""
        self.status.poll()

    def poll_errors(self):
        """Check for new messages from LinuxCNC and return them with a severity level"""
        error = self.error_channel.poll()
        if error:
            kind, text = error
            level = "info"
            if kind in (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR):
                level = "error"
            elif kind == linuxcnc.NML_TEXT:
                level = "warning"
            return text, level
        return None
    
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

    def set_teleop(self, enable: bool):
        """Enable or disable teleoperation mode (for jogging)"""
        self.poll()
        state = 1 if enable else 0
        if self.status.kinematics_type != state:
            self.command.teleop_enable(state)
            self.command.wait_complete()

    def is_ready(self):
        try:
            self.status.poll()
            return not self.status.estop and (self.status.task_state == linuxcnc.STATE_ON)
        except:
            return False

    def sync_mode(self, want_teleop):
        """want_teleop: True для World mode (Axes), False для Joint mode"""
        try:
            self.status.poll()
            if self.status.task_mode != linuxcnc.MODE_MANUAL:
                self.command.mode(linuxcnc.MODE_MANUAL)
                self.command.wait_complete()
            
            val = 1 if want_teleop else 0
            self.command.teleop_enable(val)
            self.command.wait_complete()
            return True
        except Exception as e:
            print(f"ERROR: Sync modes failed: {e}")
            return False

    def jog(self, index, direction, speed, increment, is_joint):
        """Jog a joint or axis. Handles both continuous and incremental jogging based on increment value"""
        index = int(index)
        direction = float(direction)
        speed = float(speed)
        increment = float(increment)
        
        flag = self.JOG_CMD_FLAG if is_joint else 0
        vel = (speed / 60.0)
        
        if increment == 0:
            # Continuous
            self.command.jog(linuxcnc.JOG_CONTINUOUS, flag, index, direction * vel)
        else:
            # Increment
            self.command.jog(linuxcnc.JOG_INCREMENT, flag, index, direction * vel, increment)
    
    # --- OVERRIDES ---
    def stop_jog(self, index, is_joint):
        flag = self.JOG_CMD_FLAG if is_joint else 0
        self.command.jog(linuxcnc.JOG_STOP, flag, int(index))
        
    def set_feed_override(self, rate):
        """rate: float (1.0 = 100%)"""
        self.command.feedrate(rate)

    def set_rapid_override(self, rate):
        """rate: float (1.0 = 100%)"""
        self.command.rapidrate(rate)

    def set_spindle_override(self, rate):
        """rate: float (1.0 = 100%)"""
        self.command.spindleoverride(rate)

    def set_max_velocity(self, velocity):
        """velocity: float (units per minute)"""
        self.command.maxvel(velocity / 60.0)
        
    # --- FILE MANAGEMENT ---
    
    def is_interpreter_idle(self):
        """Check if the G-code interpreter is idle (not running or paused). This is used to determine if we can safely load a new program or allow edits to the current program."""
        self.status.poll()
        return self.status.interp_state == linuxcnc.INTERP_IDLE

    def open_program(self, filepath):
        """Load a G-code file into LinuxCNC. Checks if the file exists and if the interpreter is idle before attempting to load."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл не знайдено: {filepath}")
            
        if not self.is_interpreter_idle():
            raise RuntimeError("Неможливо відкрити файл: інтерпретатор зайнятий (RUNNING/PAUSED)")

        try:
            self.command.program_open(filepath)
            self.last_loaded_file = filepath
            return True
        except Exception as e:
            raise Exception(f"LinuxCNC program_open error: {e}")

    def get_last_file(self):
        """Return the last loaded file path, or None if no file has been loaded yet. This is used for the "Reload" functionality to know which file to reload."""
        return self.last_loaded_file
    
    # --- PROGRAM EXECUTION ---

    def cycle_start(self, line_number=0):
        """Start execution of the loaded G-code program from a specific line number (default 0). Checks for necessary conditions before starting."""
        self.status.poll()
        if not self.status.file:
            raise Exception("Файл не завантажено")
        if not all(self.status.homed[:3]):
            raise Exception("Виконайте Home All перед запуском")
            
        self.command.mode(linuxcnc.MODE_AUTO)
        self.command.wait_complete()
        self.command.auto(linuxcnc.AUTO_RUN, line_number)

    def cycle_resume(self):
        """Resume execution of a paused program. If the machine is not in AUTO mode, it switches to AUTO before resuming."""
        self.status.poll()
        if self.status.interp_state == linuxcnc.INTERP_PAUSED:
            if self.status.task_mode != linuxcnc.MODE_AUTO:
                self.command.mode(linuxcnc.MODE_AUTO)
                self.command.wait_complete()
            self.command.auto(linuxcnc.AUTO_RESUME)

    def cycle_pause(self):
        """Pause the currently running program. If the machine is not in AUTO mode, it switches to AUTO before pausing."""
        self.command.auto(linuxcnc.AUTO_PAUSE)

    def cycle_stop(self):
        """Stop the currently running program. This will abort the execution and switch to MANUAL mode."""
        self.command.abort()
        self.command.wait_complete()
        self.command.mode(linuxcnc.MODE_MANUAL)

    def cycle_step(self):
        """Execute one line of G-code in AUTO mode. If the machine is not in AUTO mode, it switches to AUTO before stepping."""
        self.status.poll()
        if not self.status.file or not all(self.status.homed[:3]):
            return
        if self.status.task_mode != linuxcnc.MODE_AUTO:
            self.command.mode(linuxcnc.MODE_AUTO)
            self.command.wait_complete()

        self.command.auto(linuxcnc.AUTO_STEP)
        
    # --- MDI and Custom Commands ---
    
    def send_mdi(self, code):
        """Send an MDI command to LinuxCNC. Checks if the interpreter is idle before sending the command to prevent conflicts with running programs."""
        self.status.poll()
        if self.status.interp_state != linuxcnc.INTERP_IDLE:
            print(f"WARNING: MDI '{code}' rejected: machine is busy")
            return False

        prev_mode = self.status.task_mode
        try:
            if prev_mode != linuxcnc.MODE_MDI:
                self.command.mode(linuxcnc.MODE_MDI)
                self.command.wait_complete()
            
            self.command.mdi(code)
            self.command.wait_complete()
            
            if prev_mode != linuxcnc.MODE_MDI:
                self.command.mode(prev_mode)
                self.command.wait_complete()
            return True
        except Exception as e:
            print(f"ERROR: MDI execution failed: {e}")
            return False

    def set_gripper_force(self, value_0_to_1):
        """
        Set the force of the gripper by writing to an analog output pin in HAL.
        The value should be between 0.0 and 1.0, where 1.0 corresponds to maximum force.
        """
        self.command.set_analog_output(1, float(value_0_to_1))
    
    # --- HELPERS / GETTERS ---

    def is_idle(self):
        """Check if interpreter is doing nothing"""
        self.poll()
        return self.status.interp_state == linuxcnc.INTERP_IDLE

    def get_position(self):
        """Return current Cartesian position (X, Y, Z, A, B, C)"""
        self.poll()
        return self.status.position
    
    def get_states(self):
        """Return a dictionary of key machine states for UI logic and control decisions"""
        self.poll()
        
        # 1. Basic states: Power, E-Stop
        task_state = self.status.task_state
        estop_state = self.status.estop
        
        power_on = (task_state == linuxcnc.STATE_ON)
        estop_off = (estop_state != linuxcnc.STATE_ESTOP)
        
        # 2. States of the interpreter (Idle, Paused, Running)
        interp = self.status.interp_state
        is_idle = (interp == linuxcnc.INTERP_IDLE)
        is_paused = (interp == linuxcnc.INTERP_PAUSED)
        is_running = (interp in [linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING])

        # 3. Homing status 
        homed_status = self.status.homed
        joints_count = self.params.get("JOINTS_COUNT", 6)
        all_homed = all(homed_status[i] for i in range(min(joints_count, len(homed_status))))
        
        # Additionally, we can include actual positions for more detailed state info
        actual_pos = self.status.actual_position
        joint_pos = self.status.joint_actual_position
        
        return {
            'power_on': power_on,
            'estop_off': estop_off,
            'is_ready': power_on and estop_off,
            'all_homed': all_homed,
            
            # States of the interpreter
            'is_idle': is_idle,
            'is_paused': is_paused,
            'is_running': is_running,
            
            # Positions (for potential use in UI or logic)
            'actual_position': actual_pos,
            'joint_position': joint_pos,
            
            # File loaded status
            'has_file': bool(self.status.file),
            'manual_mode': getattr(self, 'manual_mode', 'axis'),
            
            # Kinematics type (for teleop mode)
            'teleop': self.status.kinematics_type == 1,
            
            # G-code and M-code information (for potential use in UI)
            'gcodes': self.status.gcodes,
            'mcodes': self.status.mcodes,
            'settings': self.status.settings,
            
            # Current file loaded in LinuxCNC
            'current_file': self.status.file,        
            'motion_line': self.status.motion_line,
        }

    def can_home(self):
        """"Check if machine is in a state that allows homing (not in error, power on, idle)"""
        self.poll()
        
        is_not_in_error = (self.status.estop != linuxcnc.STATE_ESTOP)
        is_power_on = (self.status.task_state == linuxcnc.STATE_ON)
        is_idle = (self.status.interp_state == linuxcnc.INTERP_IDLE)

        if not (is_not_in_error and is_power_on and is_idle):
            print(f"DEBUG: Homing blocked logic -> NotInError:{is_not_in_error}, "
                  f"PowerOn:{is_power_on}, Idle:{is_idle}")
        
        return is_not_in_error and is_power_on and is_idle

    def is_all_homed(self):
        """Check if all joints are homed. This is used to determine if we need to show the "Re-Home?" confirmation dialog."""
        self.poll()
        count = self.params.get("JOINTS_COUNT", 6)
        return all(self.status.homed[i] for i in range(count))

    def home_all_sequence(self):
        """Command LinuxCNC"""
        self.set_mode(linuxcnc.MODE_MANUAL)
        self.set_teleop(False)
        self.command.home(-1) 