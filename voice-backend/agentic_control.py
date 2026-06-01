import pyautogui
import os
import subprocess

class PCController:
    def __init__(self):
        # Fail-safe feature for pyautogui
        pyautogui.FAILSAFE = True

    def execute_command(self, action: str, params: dict):
        """
        Base method to execute a PC command based on a mapped action.
        This will be expanded as the agent becomes more complex.
        """
        print(f"[Agentic] Executing action: {action} with params: {params}")
        
        try:
            if action == "open_application":
                app_name = params.get("app_name")
                self._open_application(app_name)
                return f"Application {app_name} opened."
            
            elif action == "press_key":
                key = params.get("key")
                pyautogui.press(key)
                return f"Key {key} pressed."
                
            elif action == "type_text":
                text = params.get("text")
                pyautogui.write(text, interval=0.05)
                return f"Typed text: {text}"
                
            else:
                return f"Unknown action: {action}"
                
        except Exception as e:
            return f"Error executing {action}: {str(e)}"

    def _open_application(self, app_name: str):
        # A simple implementation for Windows
        if os.name == 'nt':
            # Try to start via cmd
            os.system(f"start {app_name}")
        else:
            raise NotImplementedError("Only Windows is supported in this demo.")
