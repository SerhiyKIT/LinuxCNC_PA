# logic/core/logger.py
from datetime import datetime

class LoggerController:
    def __init__(self, machine_controller):
        # We store a reference to the MachineController to access its error polling
        self.cnc = machine_controller
        
    def check_for_messages(self):
        """Check for new messages from LinuxCNC and return them with a severity level."""
        return self.cnc.poll_errors()

    @staticmethod
    def get_timestamp():
        return datetime.now().strftime("%H:%M:%S")