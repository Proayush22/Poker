# screen_reader.py
import cv2
import numpy as np
import pytesseract
import pyautogui
from PIL import Image
import mss
from typing import Dict, List, Optional, Tuple
import time

from card_recognizer import CardRecognizer

class ScreenReader:
    def __init__(self, config):
        self.config = config
        self.sct = mss.mss()
        self.last_position_source = 'unreadable'
        self.last_dealer_seat: Optional[str] = None

    def _pyautogui_region(self, region: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        return self.config.scale_region(region, pyautogui.size())

    def _pyautogui_point(self, point: Tuple[int, int]) -> Tuple[int, int]:
        return self.config.scale_point(point, pyautogui.size())
        
    def capture_screen(self) -> np.ndarray:
        """Capture the current screen"""
        monitor_size = (self.sct.monitors[1]['width'], self.sct.monitors[1]['height'])
        left, top, width, height = self.config.scale_region(self.config.table_region, monitor_size)
        monitor = {'left': left, 'top': top, 'width': width, 'height': height}
        screenshot = self.sct.grab(monitor)
        return np.array(screenshot)
    
    def read_player_stats(self, position: Tuple[int, int]) -> Optional[Dict[str, float]]:
        """
        Read VPIP, PFR, 3-Bet, and C-Bet stats when hovering over a player
        Returns dict with stats or None if not visible
        """
        try:
            # Hover over player
            x, y = self._pyautogui_point(position)
            pyautogui.moveTo(x, y, duration=0.3)
            time.sleep(0.5)
            
            # Capture the hover tooltip area
            tooltip_region = self._pyautogui_region((position[0] - 175, position[1] - 175, 350, 262))
            screenshot = pyautogui.screenshot(region=tooltip_region)
            
            # Use OCR to read stats
            text = pytesseract.image_to_string(screenshot)
            
            # Parse stats (adjust parsing based on your interface)
            stats = {}
            lines = text.split('\n')
            for line in lines:
                line_upper = line.upper()
                if 'VPIP' in line_upper or 'VP' in line_upper:
                    try:
                        # Extract number from line
                        import re
                        numbers = re.findall(r'\d+\.?\d*', line)
                        if numbers:
                            stats['vpip'] = float(numbers[0])
                    except:
                        pass
                elif 'PFR' in line_upper or 'PF' in line_upper:
                    try:
                        import re
                        numbers = re.findall(r'\d+\.?\d*', line)
                        if numbers:
                            stats['pfr'] = float(numbers[0])
                    except:
                        pass
                elif '3BET' in line_upper or '3-BET' in line_upper or '3B' in line_upper:
                    try:
                        import re
                        numbers = re.findall(r'\d+\.?\d*', line)
                        if numbers:
                            stats['three_bet'] = float(numbers[0])
                    except:
                        pass
                elif 'CBET' in line_upper or 'C-BET' in line_upper or 'CB' in line_upper:
                    try:
                        import re
                        numbers = re.findall(r'\d+\.?\d*', line)
                        if numbers:
                            stats['c_bet'] = float(numbers[0])
                    except:
                        pass
            
            return stats if stats else None
        except Exception as e:
            print(f"Error reading player stats: {e}")
            return None

    def read_player_name(self, position: Tuple[int, int]) -> Optional[str]:
        """Read the table-visible screen name beneath a player's avatar."""
        try:
            # In the calibrated CoinPoker layout, the nameplate sits just below
            # the avatar. This read does not move the mouse or open a profile.
            name_region = self._pyautogui_region(
                (position[0] - 122, position[1] + 78, 244, 52)
            )
            screenshot = pyautogui.screenshot(region=name_region)
            text = pytesseract.image_to_string(screenshot, config='--psm 7')
            cleaned = ''.join(character for character in text.strip() if character.isalnum() or character in '_-')
            if not cleaned or cleaned.upper() in {'FOLD', 'BB', 'SB'}:
                return None
            return cleaned
        except Exception as error:
            print(f"Error reading player name: {error}")
            return None

    def read_player_action(self, position: Tuple[int, int]) -> Optional[str]:
        """Read a visible Fold, Call, Check, Bet, or Raise label at a seat."""
        try:
            action_region = self._pyautogui_region(
                (position[0] - 101, position[1] + 44, 202, 52)
            )
            screenshot = pyautogui.screenshot(region=action_region)
            text = pytesseract.image_to_string(screenshot, config='--psm 7').upper()
            for action in ('ALL IN', 'RAISE', 'BET', 'CALL', 'CHECK', 'FOLD'):
                if action in text:
                    return action
            return None
        except Exception:
            return None

    def read_to_call(self) -> float:
        """Read the amount shown on CoinPoker's Call button in BB."""
        _, amount = self.read_call_control()
        return amount

    def read_call_control(self) -> Tuple[str, float]:
        """Return ``check``/``call`` only when the control text is trustworthy."""
        try:
            region = self._pyautogui_region(self.config.call_button_region)
            return self.read_call_control_image(np.array(pyautogui.screenshot(region=region)))
        except Exception:
            return 'unknown', 0.0

    @staticmethod
    def read_call_control_image(image_rgb: np.ndarray) -> Tuple[str, float]:
        """Distinguish a free Check from a priced Call before allowing a click."""
        image_rgb = image_rgb[:, :, :3]
        enlarged = cv2.resize(image_rgb, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 145, 255, cv2.THRESH_BINARY)
        texts = [
            pytesseract.image_to_string(enlarged, config='--psm 6'),
            pytesseract.image_to_string(binary, config='--psm 6'),
            pytesseract.image_to_string(enlarged, config='--psm 11'),
        ]
        combined = ' '.join(text.upper() for text in texts)
        letters = ''.join(character for character in combined if character.isalpha())
        if 'CHECK' in letters:
            return 'check', 0.0
        if 'CALL' in letters:
            amount = ScreenReader.read_button_amount_image(image_rgb, 'call')
            if amount > 0:
                return 'call', amount
        return 'unknown', 0.0

    def read_raise_amount(self) -> float:
        """Read the amount shown on the Raise button in BB."""
        try:
            region = self._pyautogui_region(self.config.raise_button_region)
            return self.read_button_amount_image(np.array(pyautogui.screenshot(region=region)), 'raise')
        except Exception:
            return 0.0

    def read_bet_input_amount(self) -> float:
        """Read the current numeric amount in the bet input field."""
        try:
            region = self._pyautogui_region(self.config.bet_input_region)
            return self.read_button_amount_image(np.array(pyautogui.screenshot(region=region)))
        except Exception:
            return 0.0

    @staticmethod
    def read_button_amount_image(image_rgb: np.ndarray, label: Optional[str] = None) -> float:
        """OCR a numeric BB amount from one tightly cropped control."""
        import re
        image_rgb = image_rgb[:, :, :3]
        enlarged = cv2.resize(image_rgb, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        texts = [
            pytesseract.image_to_string(binary, config='--psm 6'),
            pytesseract.image_to_string(enlarged, config='--psm 6'),
        ]
        for text in texts:
            normalized = ' '.join(text.lower().split())
            search_text = normalized
            if label and label in normalized:
                search_text = normalized.split(label, 1)[1]
            match = re.search(r'([0-9]+(?:\.[0-9]+)?)', search_text)
            if match:
                return ScreenReader._normalize_bb_number(match.group(1))
        return 0.0

    @staticmethod
    def _normalize_bb_number(token: str) -> float:
        """Remove common OCR renderings of the small trailing 'BB' label."""
        if '.' in token:
            decimal = token.split('.', 1)[1]
            if len(decimal) > 2 and token.endswith(('58', '88')):
                token = token[:-2]
            elif len(decimal) > 2 and token.endswith(('5', '8')):
                token = token[:-1]
        elif len(token) > 2 and token.endswith(('58', '88')):
            token = token[:-2]
        try:
            return float(token)
        except ValueError:
            return 0.0

    @staticmethod
    def read_numeric_region_image(image_rgb: np.ndarray) -> float:
        image_rgb = image_rgb[:, :, :3]
        enlarged = cv2.resize(image_rgb, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text = pytesseract.image_to_string(
            enlarged,
            config='--psm 7 -c tessedit_char_whitelist=0123456789.',
        )
        import re
        match = re.search(r'[0-9]+(?:\.[0-9]+)?', text)
        return ScreenReader._normalize_bb_number(match.group(0)) if match else 0.0
    
    def read_hero_cards(self) -> Tuple[str, str]:
        """Read hero's hole cards"""
        card_region = self._pyautogui_region(self.config.hero_cards_region)
        
        try:
            screenshot = pyautogui.screenshot(region=card_region)
            return self.recognize_hero_cards_image(np.array(screenshot))
        except Exception:
            return ("??", "??")

    @classmethod
    def recognize_hero_cards_image(cls, image_rgb: np.ndarray) -> Tuple[str, str]:
        """Recognize the two fixed hero-card rank corners and suit glyphs."""
        image_rgb = image_rgb[:, :, :3]
        height, width = image_rgb.shape[:2]

        def crop_fraction(x1, y1, x2, y2):
            return image_rgb[
                round(height * y1):round(height * y2),
                round(width * x1):round(width * x2),
            ]

        rank_regions = (
            crop_fraction(0.06, 0.05, 0.29, 0.49),
            crop_fraction(0.46, 0.01, 0.72, 0.41),
        )
        suit_regions = (
            crop_fraction(0.06, 0.28, 0.34, 0.76),
            crop_fraction(0.45, 0.24, 0.78, 0.72),
        )
        ranks = [cls._read_rank(region) for region in rank_regions]
        suits = [cls._read_suit(region) for region in suit_regions]
        cards = []
        for rank, suit in zip(ranks, suits):
            cards.append(f'{rank}{suit}' if rank and suit else '??')
        return tuple(cards)

    @staticmethod
    def _read_rank(region_rgb: np.ndarray) -> Optional[str]:
        from collections import Counter
        import re

        region_rgb = region_rgb[:, :, :3]
        enlarged = cv2.resize(region_rgb, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

        # A second OCR view isolates the printed card glyph from the white card
        # face. This is especially useful for red ranks and dimmed/folded cards.
        foreground = CardRecognizer.foreground_mask(region_rgb)
        contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [
            contour for contour in contours
            if cv2.contourArea(contour) >= max(4, foreground.size * 0.002)
        ]
        glyph_view = None
        if contours:
            x1 = min(cv2.boundingRect(contour)[0] for contour in contours)
            y1 = min(cv2.boundingRect(contour)[1] for contour in contours)
            x2 = max(cv2.boundingRect(contour)[0] + cv2.boundingRect(contour)[2] for contour in contours)
            y2 = max(cv2.boundingRect(contour)[1] + cv2.boundingRect(contour)[3] for contour in contours)
            glyph = foreground[y1:y2, x1:x2]
            if glyph.size:
                padding = max(8, round(max(glyph.shape) * 0.25))
                glyph_view = cv2.copyMakeBorder(
                    255 - glyph,
                    padding,
                    padding,
                    padding,
                    padding,
                    cv2.BORDER_CONSTANT,
                    value=255,
                )
                glyph_view = cv2.resize(
                    glyph_view,
                    None,
                    fx=5,
                    fy=5,
                    interpolation=cv2.INTER_NEAREST,
                )

        ocr_reads = []
        candidates = [enlarged, binary]
        if glyph_view is not None:
            candidates.append(glyph_view)
        for candidate in candidates:
            text = pytesseract.image_to_string(
                candidate,
                config='--psm 10 -c tessedit_char_whitelist=0123456789TJQKA',
            ).upper()
            match = re.search(r'10|[2-9TJQKA]', text)
            if match:
                ocr_reads.append('T' if match.group(0) == '10' else match.group(0))

        ocr_rank = Counter(ocr_reads).most_common(1)[0][0] if ocr_reads else None
        template_rank, template_score, template_margin = CardRecognizer.recognize_rank_scored(
            region_rgb
        )

        # OCR remains the primary rank reader. The CoinPoker Q and J are a
        # known ambiguous pair at small sizes, so a confident font-shape match
        # corrects only that disagreement. Very strong matches also guard other
        # single-pass OCR slips without affecting ordinary text reads.
        if (
            ocr_rank
            and template_rank
            and ocr_rank != template_rank
            and {ocr_rank, template_rank} == {'Q', 'J'}
            and template_score >= 0.52
            and template_margin >= 0.05
        ):
            return template_rank
        if (
            ocr_rank
            and template_rank
            and ocr_rank != template_rank
            and template_score >= 0.82
            and template_margin >= 0.10
        ):
            return template_rank
        return ocr_rank or template_rank

    @staticmethod
    def _read_suit(region_rgb: np.ndarray) -> Optional[str]:
        template_suit = CardRecognizer.recognize_suit(region_rgb)
        if template_suit:
            return template_suit
        hsv = cv2.cvtColor(region_rgb, cv2.COLOR_RGB2HSV)
        red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array([0, 75, 45]), np.array([12, 255, 255])),
            cv2.inRange(hsv, np.array([165, 75, 45]), np.array([180, 255, 255])),
        )
        gray = cv2.cvtColor(region_rgb, cv2.COLOR_RGB2GRAY)
        black = cv2.inRange(gray, 0, 105)
        red_area, black_area = np.count_nonzero(red), np.count_nonzero(black)
        mask, is_red = (red, True) if red_area > black_area * 0.35 else (black, False)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [contour for contour in contours if cv2.contourArea(contour) > mask.size * 0.01]
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, True)
        vertices = len(cv2.approxPolyDP(contour, 0.04 * perimeter, True))
        if is_red:
            return '♦' if vertices <= 5 else '♥'
        return '♠' if vertices <= 7 else '♣'

    def read_hero_position(self) -> Tuple[Optional[str], Dict[str, str]]:
        """Infer positions from the dealer puck, with blind badges as backup."""
        self.last_position_source = 'unreadable'
        self.last_dealer_seat = None

        # The red dealer puck is much larger and more stable than CoinPoker's
        # tiny blue SB/BB badges. Capture the whole calibrated table so the puck
        # can be found regardless of which of the six seats currently has it.
        try:
            table_region = self._pyautogui_region(self.config.table_region)
            table_image = np.array(pyautogui.screenshot(region=table_region))[:, :, :3]
            dealer_point = self.find_dealer_button_image(table_image)
            if dealer_point:
                image_height, image_width = table_image.shape[:2]
                table_left, table_top, table_width, table_height = self.config.table_region
                local_seats = {
                    seat: (
                        (point[0] - table_left) * image_width / table_width,
                        (point[1] - table_top) * image_height / table_height,
                    )
                    for seat, point in self.config.player_positions.items()
                }
                hero_position, seat_to_position, dealer_seat = self.infer_positions_from_dealer(
                    dealer_point,
                    local_seats,
                    self.config.seat_clockwise_order,
                )
                if hero_position:
                    self.last_position_source = 'dealer button'
                    self.last_dealer_seat = dealer_seat
                    return hero_position, seat_to_position
        except Exception as error:
            print(f"Dealer-button detection error: {error}")

        # Fall back to the former badge OCR path if the dealer puck is obscured.
        badges = {}
        for seat, point in self.config.player_positions.items():
            badge = self.read_position_badge(point)
            if badge:
                badges[seat] = badge

        hero_position, seat_to_position = self.infer_positions_from_badges(
            badges,
            self.config.seat_clockwise_order,
        )
        if hero_position:
            self.last_position_source = 'SB/BB badge OCR (fallback)'
        return hero_position, seat_to_position

    @staticmethod
    def find_dealer_button_image(image_rgb: np.ndarray) -> Optional[Tuple[float, float]]:
        """Locate CoinPoker's red dealer puck by its white ``D`` glyph."""
        image_rgb = image_rgb[:, :, :3]
        image_height, image_width = image_rgb.shape[:2]
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array([0, 115, 70]), np.array([12, 255, 255])),
            cv2.inRange(hsv, np.array([168, 115, 70]), np.array([180, 255, 255])),
        )
        red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        minimum_side = max(8, round(min(image_width, image_height) * 0.012))
        maximum_side = max(40, round(min(image_width, image_height) * 0.10))
        minimum_area = image_width * image_height * 0.00004
        candidates = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            aspect = width / max(height, 1)
            if not (
                minimum_side <= width <= maximum_side
                and minimum_side <= height <= maximum_side
                and 0.55 <= aspect <= 1.45
                and area >= minimum_area
            ):
                continue

            padding = max(5, round(max(width, height) * 0.25))
            crop = image_rgb[
                max(0, y - padding):min(image_height, y + height + padding),
                max(0, x - padding):min(image_width, x + width + padding),
            ]
            enlarged = cv2.resize(crop, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
            _, white_glyph = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
            texts = (
                pytesseract.image_to_string(
                    enlarged,
                    config='--psm 10 -c tessedit_char_whitelist=D',
                ),
                pytesseract.image_to_string(
                    white_glyph,
                    config='--psm 10 -c tessedit_char_whitelist=D',
                ),
            )
            if any('D' in text.upper() for text in texts):
                candidates.append((area, (x + width / 2, y + height / 2)))

        # There should be only one D. If anti-aliasing splits its red outline,
        # the largest matching red component is the complete puck.
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    @staticmethod
    def infer_positions_from_dealer(
        dealer_point: Tuple[float, float],
        seat_points: Dict[str, Tuple[float, float]],
        order: List[str],
    ) -> Tuple[Optional[str], Dict[str, str], Optional[str]]:
        """Anchor Button to the nearest seat and assign six-max positions."""
        eligible_seats = [seat for seat in order if seat in seat_points]
        if not eligible_seats:
            return None, {}, None

        dealer_x, dealer_y = dealer_point
        dealer_seat = min(
            eligible_seats,
            key=lambda seat: (
                (seat_points[seat][0] - dealer_x) ** 2
                + (seat_points[seat][1] - dealer_y) ** 2
            ),
        )
        positions = ('button', 'sb', 'bb', 'utg', 'hijack', 'cutoff')
        start = order.index(dealer_seat)
        seat_to_position = {
            order[(start + offset) % len(order)]: position
            for offset, position in enumerate(positions[:len(order)])
        }
        return seat_to_position.get('hero'), seat_to_position, dealer_seat

    @staticmethod
    def infer_positions_from_badges(
        badges: Dict[str, str], order: List[str]
    ) -> Tuple[Optional[str], Dict[str, str]]:
        """Map physical seats to positions using an SB or BB anchor."""
        sb_seat = next((seat for seat, badge in badges.items() if badge == 'sb'), None)
        if not sb_seat:
            bb_seat = next((seat for seat, badge in badges.items() if badge == 'bb'), None)
            if bb_seat in order:
                sb_seat = order[(order.index(bb_seat) - 1) % len(order)]
        if sb_seat not in order:
            return None, {}

        positions = ('sb', 'bb', 'utg', 'hijack', 'cutoff', 'button')
        start = order.index(sb_seat)
        seat_to_position = {
            order[(start + offset) % len(order)]: position
            for offset, position in enumerate(positions)
        }
        return seat_to_position.get('hero'), seat_to_position

    def read_position_badge(self, position: Tuple[int, int]) -> Optional[str]:
        try:
            region = self._pyautogui_region((position[0] - 125, position[1] + 35, 105, 75))
            image_rgb = np.array(pyautogui.screenshot(region=region))[:, :, :3]
            return self.read_position_badge_image(image_rgb)
        except Exception:
            return None

    @staticmethod
    def read_position_badge_image(image_rgb: np.ndarray) -> Optional[str]:
        hsv = cv2.cvtColor(image_rgb[:, :, :3], cv2.COLOR_RGB2HSV)
        blue = cv2.inRange(hsv, np.array([90, 100, 70]), np.array([125, 255, 255]))
        contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [contour for contour in contours if cv2.contourArea(contour) > 25]
        if not contours:
            return None
        x, y, width, height = cv2.boundingRect(max(contours, key=cv2.contourArea))
        crop = image_rgb[max(0, y - 3):y + height + 3, max(0, x - 3):x + width + 3]
        crop = cv2.resize(crop, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        text = pytesseract.image_to_string(crop, config='--psm 10 -c tessedit_char_whitelist=SB').upper().strip()
        if 'SB' in text:
            return 'sb'
        if 'BB' in text:
            return 'bb'
        return None
    
    def read_board_cards(self) -> list:
        """Read community cards"""
        board_region = self._pyautogui_region(self.config.board_cards_region)
        
        try:
            screenshot = pyautogui.screenshot(region=board_region)
            return self.recognize_board_cards_image(np.array(screenshot))
        except Exception:
            return []

    @staticmethod
    def recognize_board_cards_image(image_rgb: np.ndarray) -> List[str]:
        """Locate and recognize up to five community cards in the board row."""
        image_rgb = image_rgb[:, :, :3]
        white = cv2.inRange(image_rgb, np.array([180, 180, 180]), np.array([255, 255, 255]))
        contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if width >= image_rgb.shape[1] * 0.12 and height >= image_rgb.shape[0] * 0.45:
                boxes.append((x, y, width, height))
        boxes.sort(key=lambda box: box[0])

        cards = []
        for x, y, width, height in boxes[:5]:
            rank_region = image_rgb[
                y + round(height * 0.01):y + round(height * 0.35),
                x + round(width * 0.02):x + round(width * 0.45),
            ]
            suit_region = image_rgb[
                y + round(height * 0.27):y + round(height * 0.70),
                x + round(width * 0.01):x + round(width * 0.58),
            ]
            rank = ScreenReader._read_rank(rank_region)
            suit = ScreenReader._read_suit(suit_region)
            if rank and suit:
                cards.append(f'{rank}{suit}')
        return cards
    
    def read_pot_size(self) -> float:
        """Read current pot size in BB"""
        pot_region = self._pyautogui_region(self.config.pot_region)
        
        try:
            screenshot = pyautogui.screenshot(region=pot_region)
            return self.read_numeric_region_image(np.array(screenshot))
        except Exception:
            return 0.0
    
    def read_hero_stack(self) -> float:
        """Read hero's stack size in BB"""
        stack_region = self._pyautogui_region(self.config.hero_stack_region)
        
        try:
            screenshot = pyautogui.screenshot(region=stack_region)
            return self.read_numeric_region_image(np.array(screenshot))
        except Exception:
            return 100.0
    
    def is_our_turn(self) -> bool:
        """Detect the Fold / Call / Raise control group when it is our turn."""
        try:
            button_region = self._pyautogui_region(self.config.action_region)
            screenshot = pyautogui.screenshot(region=button_region)
            return self.has_action_controls(np.array(screenshot))
        except Exception:
            return False

    @staticmethod
    def has_action_controls(screenshot_np: np.ndarray) -> bool:
        """Return whether an RGB screenshot contains the three action buttons."""
        screenshot_rgb = screenshot_np[:, :, :3]
        hsv = cv2.cvtColor(screenshot_rgb, cv2.COLOR_RGB2HSV)

        # CoinPoker presents a red Fold, teal Call, and orange Raise button
        # together. Requiring all three avoids treating a table highlight or
        # a single coloured chip as an actionable turn.
        red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array([0, 110, 90]), np.array([8, 255, 255])),
            cv2.inRange(hsv, np.array([170, 110, 90]), np.array([180, 255, 255])),
        )
        teal = cv2.inRange(hsv, np.array([70, 90, 70]), np.array([105, 255, 255]))
        orange = cv2.inRange(hsv, np.array([8, 110, 100]), np.array([28, 255, 255]))

        pixel_count = hsv.shape[0] * hsv.shape[1]
        ratios = [
            np.count_nonzero(mask) / pixel_count
            for mask in (red, teal, orange)
        ]
        return all(ratio >= 0.015 for ratio in ratios)
