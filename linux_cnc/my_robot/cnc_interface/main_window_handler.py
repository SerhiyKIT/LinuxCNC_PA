#!/usr/bin/env python3
import os
import sys
import traceback
from PyQt5 import QtWidgets

# Adding the logic/managers directory to the path for imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'logic'))

try:
    # Importing the main logic handler class that will manage all interactions between the CNC and the UI
    from logic.main_logic import HandlerClass
    print("DEBUG: Successfully imported HandlerClass from logic.main_logic")
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import HandlerClass from logic.main_logic\n{e}")
    traceback.print_exc()
    # 
    class HandlerClass:
        def __init__(self, *args): 
            print("WARNING: Using dummy HandlerClass due to import failure. Functionality will be limited.")

def get_handlers(halcomp, widgets, paths):
    """ Factory function to create and return a list of handler instances"""
    window = getattr(widgets, 'main_window', widgets)
    return [HandlerClass(halcomp, window, paths)]

if __name__ == "__main__":
    # Standalone mode for testing the HandlerClass without running the full application. This allows us to verify that the HandlerClass can be instantiated without errors and that its methods can be called without a full LinuxCNC environment.
    app = QtWidgets.QApplication(sys.argv)
    
    # Creating dummy objects to pass to the HandlerClass constructor
    class Fake: pass
    fake_hal = Fake()
    fake_widgets = Fake()
    fake_paths = Fake()
    
    try:
        handler = HandlerClass(fake_hal, fake_widgets, fake_paths)
        print("DEBUG: Successfully instantiated HandlerClass in standalone mode")
    except Exception as e:
        print(f"ERROR during instantiation of HandlerClass: {e}")
        traceback.print_exc()
        
    sys.exit(app.exec_())