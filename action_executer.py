# action_executor.py
import pyautogui
import time
from typing import Tuple, Optional
from strategy_engine import Action

class ActionExecutor:
    def __init__(self, config):
        self.config = config
    
    def execute_action(self, action: Action, amount: Optional[float] = None):
        """Execute the chosen action on the poker table"""
        try:
            if action == Action.WAIT:
                print("Cards are not readable yet; no action was taken.")
                return
            if action == Action.FOLD:
                self.click_button('fold')
            elif action == Action.CHECK:
                self.click_button('call')  # Check button is usually same as call
            elif action == Action.CALL:
                self.click_button('call')
            elif action == Action.RAISE:
                if amount:
                    self.enter_bet_amount(amount)
                    self.click_button('raise')
                else:
                    self.click_button('raise')
            elif action == Action.ALL_IN:
                self.click_button('all_in')
            
            # Small delay to prevent issues
            time.sleep(0.5)
        except Exception as e:
            print(f"Error executing action: {e}")
    
    def click_button(self, button: str):
        """Click a specific button"""
        button_positions = {
            'fold': self.config.fold_button,
            'call': self.config.call_button,
            'raise': self.config.raise_button,
            'all_in': self.config.raise_button  # All-in is usually via raise
        }
        
        coordinates = button_positions.get(button)
        if not coordinates:
            print(f"Action button '{button}' is not configured; no click was made.")
            return
        x, y = self.config.scale_point(coordinates, pyautogui.size())
        pyautogui.click(x, y)
    
    def enter_bet_amount(self, amount: float):
        """Enter a specific bet amount"""
        # Click on bet input field
        if not self.config.bet_input:
            print("Bet input is not configured; no text was entered.")
            return
        x, y = self.config.scale_point(self.config.bet_input, pyautogui.size())
        pyautogui.click(x, y)
        
        # Clear existing text
        pyautogui.hotkey('command', 'a')  # macOS uses command instead of ctrl
        pyautogui.press('delete')
        
        # Type the amount
        pyautogui.typewrite(str(round(amount, 2)))
