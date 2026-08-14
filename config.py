# requirements.txt
"""
pyautogui==0.9.54
opencv-python==4.8.1.78
numpy==1.24.3
pytesseract==0.3.10
Pillow==10.0.0
mss==9.0.1
pandas==2.0.3
pynput==1.7.6
"""

# config.py
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

@dataclass
class PokerConfig:
    # Native-pixel calibration from the supplied 3456 x 2234 screenshots.
    # PyAutoGUI logical coordinates are derived from this reference at runtime.
    reference_screen_size: Tuple[int, int] = (3456, 2234)
    table_region: Tuple[int, int, int, int] = (908, 574, 1638, 1203)
    hero_cards_region: Tuple[int, int, int, int] = (1605, 1428, 245, 170)
    # Wide enough for every community-card slot, not only the three-card flop.
    board_cards_region: Tuple[int, int, int, int] = (1413, 1030, 650, 175)
    pot_region: Tuple[int, int, int, int] = (1625, 970, 220, 62)
    hero_stack_region: Tuple[int, int, int, int] = (1625, 1635, 205, 52)
    action_region: Tuple[int, int, int, int] = (1875, 1585, 670, 192)
    call_button_region: Tuple[int, int, int, int] = (2108, 1672, 207, 99)
    raise_button_region: Tuple[int, int, int, int] = (2332, 1672, 207, 99)
    bet_input_region: Tuple[int, int, int, int] = (2230, 1595, 160, 65)
    player_positions: Dict[str, Tuple[int, int]] = field(default_factory=lambda: {
        # Seat centers used for action labels and dealer-position mapping.
        'hero': (1720, 1518),
        'left_bottom': (1117, 1293),
        'left_top': (1134, 794),
        'top': (1731, 679),
        'right_top': (2321, 794),
        'right_bottom': (2337, 1293),
    })
    seat_clockwise_order: List[str] = field(default_factory=lambda: [
        'top', 'right_top', 'right_bottom', 'hero', 'left_bottom', 'left_top'
    ])
    # Profiling branch: profiles follow screen names, while seats only point to
    # the player currently occupying them.
    player_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    seat_players: Dict[str, str] = field(default_factory=dict)
    # Betting buttons
    fold_button: Optional[Tuple[int, int]] = (1988, 1721)
    call_button: Optional[Tuple[int, int]] = (2212, 1721)
    raise_button: Optional[Tuple[int, int]] = (2436, 1721)
    bet_input: Optional[Tuple[int, int]] = (2308, 1627)
    
    # Raise sizings
    preflop_raise_size: float = 3.0  # in BB
    three_bet_size_ip: float = 3.0
    three_bet_size_oop: float = 3.5
    four_bet_size: float = 2.5
    
    # Timing: action controls are distinctive enough for one confirmation.
    turn_poll_interval: float = 1.0
    turn_confirmations_required: int = 1
    profile_scan_interval: float = 5.0
    minimum_profile_hands: int = 5

    def scale_point(self, point: Tuple[int, int], screen_size: Tuple[int, int]) -> Tuple[int, int]:
        """Scale a point from the reference screenshot to the active display."""
        ref_width, ref_height = self.reference_screen_size
        width, height = screen_size
        return (round(point[0] * width / ref_width), round(point[1] * height / ref_height))

    def scale_region(self, region: Tuple[int, int, int, int], screen_size: Tuple[int, int]) -> Tuple[int, int, int, int]:
        """Scale a capture region from the reference screenshot to the active display."""
        ref_width, ref_height = self.reference_screen_size
        width, height = screen_size
        return (
            round(region[0] * width / ref_width),
            round(region[1] * height / ref_height),
            round(region[2] * width / ref_width),
            round(region[3] * height / ref_height),
        )
    
    def save(self, filename: str = 'poker_config.json'):
        with open(filename, 'w') as f:
            json.dump(self.__dict__, f, indent=4)
    
    @classmethod
    def load(cls, filename: str = 'poker_config.json'):
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                data = json.load(f)
            return cls(**data)
        return cls()
