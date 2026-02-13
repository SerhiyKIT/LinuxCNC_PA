# logic/managers/tool_manager.py

class ToolManager:
    def __init__(self, cnc):
        self.cnc = cnc

    def change_tool(self, tool_number):
        try:
            self.cnc.command(f"tool change {tool_number}")
        except Exception as e:
            print(f"ERROR: Не вдалося змінити інструмент: {e}")