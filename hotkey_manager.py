# hotkey_manager.py
from pynput import keyboard
from typing import Callable
import threading

class HotkeyManager:
    def __init__(self):
        self.listener = None
        self.hotkeys = {}
        self.running = False
        
    def register_hotkey(self, key: str, callback: Callable):
        """Register a hotkey with callback"""
        self.hotkeys[key] = callback
        
    def start(self):
        """Start listening for hotkeys"""
        self.running = True
        self.listener = keyboard.Listener(
            on_press=self._on_press
        )
        self.listener.start()
        
    def stop(self):
        """Stop listening"""
        self.running = False
        if self.listener:
            self.listener.stop()
            
    def _on_press(self, key):
        """Handle key press events"""
        try:
            # Convert key to string
            if hasattr(key, 'char'):
                key_str = key.char.lower() if key.char else ''
            else:
                key_str = str(key).replace('Key.', '').lower()
            
            # Check if it's a registered hotkey
            if key_str in self.hotkeys:
                # Run callback in separate thread to not block listener
                threading.Thread(target=self.hotkeys[key_str], daemon=True).start()
                
        except Exception as e:
            print(f"Hotkey error: {e}")