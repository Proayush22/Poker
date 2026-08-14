# strategy_engine.py
from typing import Dict, List, Optional, Tuple
from enum import Enum
import random

from hand_evaluator import HandEvaluator

class Action(Enum):
    WAIT = 'wait'
    FOLD = 'fold'
    CHECK = 'check'
    CALL = 'call'
    RAISE = 'raise'
    ALL_IN = 'all_in'

class Street(Enum):
    PREFLOP = 'preflop'
    FLOP = 'flop'
    TURN = 'turn'
    RIVER = 'river'

class StrategyEngine:
    def __init__(self, config):
        self.config = config
        self.hand_evaluator = HandEvaluator()
        self.position_order = ['utg', 'hijack', 'cutoff', 'button', 'sb', 'bb']
        self.last_reason = ''
        self.last_analysis = {}
        
    def get_action(self, game_state: Dict) -> Tuple[Action, Optional[float]]:
        """
        Main decision function
        game_state contains:
        - hero_cards
        - board_cards
        - position
        - pot_size
        - hero_stack
        - current_bet
        - to_call
        - opponents_stats (dict of position -> stats)
        - action_history
        """
        self.last_reason = ''
        self.last_analysis = {}
        street = game_state['street']
        
        if street == Street.PREFLOP:
            return self.preflop_strategy(game_state)
        elif street == Street.FLOP:
            return self.flop_strategy(game_state)
        elif street == Street.TURN:
            return self.turn_strategy(game_state)
        elif street == Street.RIVER:
            return self.river_strategy(game_state)
        
        return Action.FOLD, None
    
    def preflop_strategy(self, state: Dict) -> Tuple[Action, Optional[float]]:
        """Apply the configured tight-aggressive preflop framework."""
        hero_cards = state['hero_cards']
        position = state['position']
        hand_info = self.hand_evaluator.preflop_hand_strength(hero_cards)
        
        # If we can't read cards, fold
        if hand_info['category'] == 'unknown':
            return Action.WAIT, None
        if position not in self.position_order:
            return Action.WAIT, None
        if state.get('call_control') == 'unknown':
            self.last_reason = 'Check/Call control is unreadable; waiting to avoid an accidental call.'
            return Action.WAIT, None
        
        # Check if we're facing a raise
        facing_raise = state.get('facing_raise', False) or state.get('to_call', 0) > 1
        facing_three_bet = state.get('facing_three_bet', False)
        facing_four_bet = state.get('facing_four_bet', False)
        
        # Get aggressive opponent info
        opponent_stats = self.get_aggressive_opponent_stats(state)
        
        # Facing a 4-bet after we 3-bet: continue only with the top of range.
        if facing_four_bet:
            if self._is_pair_at_least(hand_info, 13):  # KK+
                self.last_reason = 'Top-of-range hand versus a four-bet; continuing all-in.'
                return Action.ALL_IN, state['hero_stack']
            if self._is_ak(hand_info, suited=True):
                self.last_reason = 'AK suited versus a four-bet; continuing by calling.'
                return Action.CALL, None
            self.last_reason = 'Outside the TAG continue range versus a four-bet; folding.'
            return Action.FOLD, None
        
        # TAG 4-bet framework after we open and face a 3-bet.
        if facing_three_bet:
            if self._is_four_bet_value(hand_info):
                self.last_reason = 'In the pure-value four-bet range (QQ+ or AK); raising.'
                return Action.RAISE, self.calculate_four_bet_size(state)
            if (
                self._is_wheel_ace(hand_info)
                and opponent_stats.get('three_bet', 0) >= self.config.three_bet_threshold
            ):
                self.last_reason = 'Wheel-ace bluff enabled against a highly aggressive three-bettor.'
                return Action.RAISE, self.calculate_four_bet_size(state)
            if self._is_trap_hand(hand_info):  # TT/JJ/AQs/AQo
                self.last_reason = 'Trap-range hand versus a three-bet; calling rather than four-betting.'
                return Action.CALL, None
            self.last_reason = 'Outside the TAG continue range versus a three-bet; folding.'
            return Action.FOLD, None
        
        # Unraised pot
        if not facing_raise:
            return self.unraised_pot_strategy(hand_info, position, state)
        
        # Facing a single raise
        return self.facing_raise_strategy(hand_info, position, state, opponent_stats)
    
    def unraised_pot_strategy(self, hand_info: Dict, position: str, 
                              state: Dict) -> Tuple[Action, Optional[float]]:
        """TAG open ranges: tight early, wider late, aggressive on the button."""
        if position == 'bb':
            self.last_reason = 'Unraised pot in the big blind; checking the option.'
            return Action.CHECK, None
        if self._is_open_raise_hand(hand_info, position):
            self.last_reason = f'Hand is inside the TAG open range for {position.upper()}; raising.'
            return Action.RAISE, self.config.preflop_raise_size
        self.last_reason = f'Hand is outside the TAG open range for {position.upper()}; folding.'
        return Action.FOLD, None
    
    def facing_raise_strategy(self, hand_info: Dict, position: str, 
                              state: Dict, opponent_stats: Dict) -> Tuple[Action, Optional[float]]:
        """Strategy when facing a raise"""
        raiser_position = state.get('raiser_position')

        # Do not fold premium hands merely because seat detection has not yet
        # identified the raiser. Use the tighter early-position value range.
        if raiser_position is None:
            raiser_position = 'utg'

        if self._is_tag_three_bet(hand_info, position, raiser_position):
            size = self.calculate_three_bet_size(state, position)
            self.last_reason = (
                f'Hand is inside the {position.upper()} TAG three-bet range versus '
                f'{raiser_position.upper()}; raising to {size:.2f} BB.'
            )
            return Action.RAISE, size
        if position != 'sb' and self._is_tag_flat_call(hand_info, position):
            self.last_reason = f'Hand is inside the defined {position.upper()} flat-call range.'
            return Action.CALL, None
        self.last_reason = f'Hand is outside the {position.upper()} continue range versus this open; folding.'
        return Action.FOLD, None

    @staticmethod
    def _is_pair_at_least(hand: Dict, rank: int) -> bool:
        return hand['is_pair'] and hand['high_rank'] >= rank

    @staticmethod
    def _is_exact(hand: Dict, high: int, low: int, suited: Optional[bool] = None) -> bool:
        return (
            not hand['is_pair']
            and hand['high_rank'] == high
            and hand['low_rank'] == low
            and (suited is None or hand['is_suited'] == suited)
        )

    def _is_ace_x(self, hand: Dict, minimum_kicker: int, suited: Optional[bool] = None) -> bool:
        return hand['high_rank'] == 14 and hand['low_rank'] >= minimum_kicker and (
            suited is None or hand['is_suited'] == suited
        )

    def _is_ak(self, hand: Dict, suited: Optional[bool] = None) -> bool:
        return self._is_exact(hand, 14, 13, suited)

    def _is_wheel_ace(self, hand: Dict) -> bool:
        return hand['is_suited'] and hand['high_rank'] == 14 and hand['low_rank'] in (4, 5)

    def _is_four_bet_value(self, hand: Dict) -> bool:
        return self._is_pair_at_least(hand, 12) or self._is_ak(hand)

    def _is_trap_hand(self, hand: Dict) -> bool:
        return (
            (hand['is_pair'] and hand['high_rank'] in (10, 11))
            or self._is_exact(hand, 14, 12, suited=True)
            or self._is_exact(hand, 14, 12, suited=False)
        )

    def _is_open_raise_hand(self, hand: Dict, position: str) -> bool:
        if position in ('utg', 'hijack'):
            return (
                self._is_pair_at_least(hand, 7)
                or self._is_ace_x(hand, 12, suited=False)
                or self._is_ace_x(hand, 11, suited=True)
                or self._is_exact(hand, 13, 12, suited=True)
            )
        if position in ('cutoff', 'sb'):
            return (
                self._is_pair_at_least(hand, 5)
                or self._is_ace_x(hand, 10, suited=False)
                or self._is_ace_x(hand, 8, suited=True)
                or (hand['high_rank'] == 13 and hand['low_rank'] >= 11 and not hand['is_suited'])
                or (hand['high_rank'] == 13 and hand['low_rank'] >= 10 and hand['is_suited'])
                or self._is_exact(hand, 12, 11, suited=True)
                or self._is_exact(hand, 11, 10, suited=True)
            )
        if position == 'button':
            return (
                hand['is_pair']
                or self._is_ace_x(hand, 8, suited=False)
                or self._is_ace_x(hand, 2, suited=True)
                or (hand['high_rank'] == 13 and hand['low_rank'] >= 10 and not hand['is_suited'])
                or (hand['high_rank'] == 13 and hand['low_rank'] >= 8 and hand['is_suited'])
                or (hand['high_rank'] == 12 and hand['low_rank'] >= 10 and not hand['is_suited'])
                or (hand['high_rank'] == 12 and hand['low_rank'] >= 8 and hand['is_suited'])
                or (hand['high_rank'] == 11 and hand['low_rank'] >= 9 and hand['is_suited'])
                or self._is_exact(hand, 10, 9, suited=True)
                or self._is_exact(hand, 9, 8, suited=True)
                or self._is_exact(hand, 8, 7, suited=True)
            )
        return False

    def _is_tag_three_bet(self, hand: Dict, position: str, raiser_position: str) -> bool:
        early_opener = raiser_position in ('utg', 'hijack')
        late_opener = raiser_position in ('cutoff', 'button', 'sb')
        if position == 'sb':
            return (
                self._is_pair_at_least(hand, 10)
                or self._is_ace_x(hand, 12, suited=True)
                or self._is_ak(hand, suited=False)
                or self._is_exact(hand, 13, 12, suited=True)
                or self._is_wheel_ace(hand)
            )
        if position == 'bb':
            if early_opener:
                return self._is_pair_at_least(hand, 12) or self._is_ak(hand) or self._is_wheel_ace(hand)
            if late_opener:
                return (
                    self._is_pair_at_least(hand, 11)
                    or self._is_ace_x(hand, 12, suited=True)
                    or self._is_ak(hand, suited=False)
                    or self._is_wheel_ace(hand)
                    or self._is_exact(hand, 13, 10, suited=True)
                    or self._is_exact(hand, 12, 11, suited=True)
                    or self._is_exact(hand, 11, 10, suited=True)
                    or self._is_exact(hand, 8, 7, suited=True)
                )
        if position in ('cutoff', 'button'):
            if early_opener:
                return self._is_pair_at_least(hand, 12) or self._is_ak(hand) or self._is_wheel_ace(hand)
            if late_opener:
                return (
                    self._is_pair_at_least(hand, 10)
                    or self._is_ace_x(hand, 11, suited=True)
                    or self._is_ace_x(hand, 12, suited=False)
                    or self._is_exact(hand, 13, 12, suited=True)
                    or self._is_wheel_ace(hand)
                    or self._is_exact(hand, 13, 9, suited=True)
                    or self._is_exact(hand, 12, 9, suited=True)
                    or self._is_exact(hand, 11, 10, suited=True)
                    or self._is_exact(hand, 10, 9, suited=True)
                    or self._is_exact(hand, 9, 8, suited=True)
                )
        return self._is_pair_at_least(hand, 12) or self._is_ak(hand) or self._is_wheel_ace(hand)

    def _is_tag_flat_call(self, hand: Dict, position: str) -> bool:
        if position == 'button':
            return (
                hand['is_pair'] and hand['high_rank'] <= 10
                or self._is_ace_x(hand, 10, suited=True)
                or self._is_exact(hand, 13, 12, suited=True)
                or self._is_exact(hand, 13, 11, suited=True)
                or self._is_exact(hand, 12, 11, suited=True)
                or any(self._is_exact(hand, high, low, suited=True) for high, low in ((11, 10), (10, 9), (9, 8), (8, 7), (7, 6)))
            )
        if position == 'bb':
            return (
                hand['is_pair'] and hand['high_rank'] <= 10
                or self._is_ace_x(hand, 2, suited=True) and hand['low_rank'] <= 9
                or any(self._is_exact(hand, high, low, suited=True) for high, low in ((11, 10), (11, 9), (10, 8), (9, 7), (8, 7), (7, 6), (6, 5), (5, 4)))
                or self._is_exact(hand, 13, 12, suited=False)
                or self._is_exact(hand, 14, 11, suited=False)
                or self._is_exact(hand, 14, 10, suited=False)
                or self._is_exact(hand, 13, 11, suited=False)
            )
        return False
    
    def flop_strategy(self, state: Dict) -> Tuple[Action, Optional[float]]:
        return self._postflop_strategy(state, Street.FLOP)
    
    def missed_flop(self, state: Dict) -> bool:
        analysis = self._postflop_analysis(state)
        return bool(
            analysis.get('valid')
            and analysis.get('category_value', 0) == 0
            and not analysis.get('strong_draw')
            and not analysis.get('gutshot')
        )
    
    def has_made_hand(self, state: Dict) -> bool:
        analysis = self._postflop_analysis(state)
        return bool(analysis.get('valid') and analysis.get('category_value', 0) >= 1)
    
    def has_strong_draw(self, state: Dict) -> bool:
        return bool(self._postflop_analysis(state).get('strong_draw'))
    
    def has_one_pair(self, state: Dict) -> bool:
        return self._postflop_analysis(state).get('category_value') == 1
    
    def is_top_pair(self, state: Dict) -> bool:
        return bool(self._postflop_analysis(state).get('top_pair'))
    
    def turn_strategy(self, state: Dict) -> Tuple[Action, Optional[float]]:
        return self._postflop_strategy(state, Street.TURN)
    
    def river_strategy(self, state: Dict) -> Tuple[Action, Optional[float]]:
        return self._postflop_strategy(state, Street.RIVER)
    
    def has_strong_hand(self, state: Dict) -> bool:
        return self._postflop_analysis(state).get('category_value', 0) >= 2

    def _postflop_analysis(self, state: Dict) -> Dict:
        return self.hand_evaluator.evaluate_postflop(
            state.get('hero_cards', []),
            state.get('board_cards', []),
        )

    def _postflop_strategy(
        self, state: Dict, street: Street
    ) -> Tuple[Action, Optional[float]]:
        """TAG post-flop rules driven by hand class, draws, and pot odds."""
        analysis = self._postflop_analysis(state)
        if not analysis.get('valid'):
            self.last_reason = 'Cards or board are incomplete; waiting without clicking.'
            self.last_analysis = analysis
            return Action.WAIT, None
        if state.get('call_control') == 'unknown':
            self.last_reason = 'Check/Call control is unreadable; waiting to avoid an accidental call.'
            self.last_analysis = analysis
            return Action.WAIT, None

        pot = max(float(state.get('pot_size', 0) or 0), 0.0)
        to_call = max(float(state.get('to_call', 0) or 0), 0.0)
        facing_bet = bool(state.get('facing_bet', False) or to_call > 0.05)
        bet_fraction = to_call / pot if pot > 0 else (1.0 if facing_bet else 0.0)
        pot_odds = to_call / (pot + to_call) if facing_bet and pot + to_call > 0 else 0.0
        cards_to_come = 2 if street == Street.FLOP else 1
        draw_equity = min(
            0.95,
            analysis.get('outs', 0) * (0.04 if cards_to_come == 2 else 0.02),
        )
        analysis.update({
            'street': street.value,
            'facing_bet': facing_bet,
            'bet_fraction': bet_fraction,
            'pot_odds': pot_odds,
            'draw_equity': draw_equity,
        })
        self.last_analysis = analysis
        label = analysis['label']
        category = analysis.get('category_value', 0)

        if not facing_bet:
            if category >= 2:
                self.last_reason = f'{label.title()} detected; value betting about 70% of the pot.'
                return Action.RAISE, self._postflop_raise_size(state, 0.70)
            if analysis.get('overpair') or analysis.get('top_pair'):
                if street == Street.RIVER and analysis.get('top_pair') and analysis.get('kicker', 0) < 11:
                    self.last_reason = f'{label.title()} with a weak kicker; checking for pot control.'
                    return Action.CHECK, None
                self.last_reason = f'{label.title()} detected; making a controlled value bet.'
                return Action.RAISE, self._postflop_raise_size(state, 0.55)
            if street != Street.RIVER and analysis.get('strong_draw'):
                draw_name = self._draw_name(analysis)
                self.last_reason = f'{draw_name} detected; semi-bluffing about 60% of the pot.'
                return Action.RAISE, self._postflop_raise_size(state, 0.60)
            if (
                street == Street.FLOP
                and state.get('is_preflop_aggressor', False)
                and analysis.get('overcards', 0) == 2
            ):
                self.last_reason = 'Two overcards as the preflop aggressor; making a small continuation bet.'
                return Action.RAISE, self._postflop_raise_size(state, 0.33)
            self.last_reason = f'{label.title()} without enough value to bet; checking.'
            return Action.CHECK, None

        # Facing a post-flop bet.
        if category >= 4:  # straight or better
            self.last_reason = f'{label.title()} versus a bet; raising for value.'
            return Action.RAISE, self._postflop_raise_size(state, 0.75)
        if category == 3:  # trips
            if bet_fraction <= 0.75:
                self.last_reason = 'Three of a kind versus a normal-sized bet; raising for value.'
                return Action.RAISE, self._postflop_raise_size(state, 0.75)
            self.last_reason = 'Three of a kind versus a large bet; continuing by calling.'
            return Action.CALL, None
        if category == 2:  # two pair
            if street == Street.FLOP and bet_fraction <= 0.60:
                self.last_reason = 'Two pair on the flop versus a normal bet; raising for value and protection.'
                return Action.RAISE, self._postflop_raise_size(state, 0.75)
            self.last_reason = 'Two pair has sufficient showdown value to call this bet.'
            return Action.CALL, None

        if analysis.get('overpair') or analysis.get('top_pair'):
            thresholds = {Street.FLOP: 0.75, Street.TURN: 0.60, Street.RIVER: 0.45}
            threshold = thresholds[street]
            if bet_fraction <= threshold:
                self.last_reason = (
                    f'{label.title()} versus a {bet_fraction:.0%}-pot bet; '
                    f'calling within the {street.value} threshold.'
                )
                return Action.CALL, None
            self.last_reason = f'{label.title()} versus an oversized {bet_fraction:.0%}-pot bet; folding.'
            return Action.FOLD, None

        if street != Street.RIVER and analysis.get('combo_draw') and bet_fraction <= 0.65:
            self.last_reason = 'Combo draw with strong equity; raising as a semi-bluff.'
            return Action.RAISE, self._postflop_raise_size(state, 0.75)
        if street != Street.RIVER and analysis.get('outs', 0) > 0:
            if draw_equity + 0.03 >= pot_odds:
                self.last_reason = (
                    f"{self._draw_name(analysis)} with about {analysis['outs']} outs; "
                    f'calling {pot_odds:.0%} pot odds with approximately {draw_equity:.0%} draw equity.'
                )
                return Action.CALL, None
            self.last_reason = (
                f"{self._draw_name(analysis)} lacks the pot odds: "
                f'{pot_odds:.0%} required versus approximately {draw_equity:.0%} draw equity.'
            )
            return Action.FOLD, None

        if analysis.get('middle_pair') or analysis.get('bottom_pair') or analysis.get('pocket_pair'):
            threshold = 0.28 if street == Street.FLOP else 0.20
            if bet_fraction <= threshold:
                self.last_reason = f'{label.title()} versus a small bet; calling once for pot control.'
                return Action.CALL, None
            self.last_reason = f'{label.title()} versus meaningful aggression; folding.'
            return Action.FOLD, None

        self.last_reason = f'{label.title()} with no profitable draw against a bet; folding.'
        return Action.FOLD, None

    @staticmethod
    def _draw_name(analysis: Dict) -> str:
        if analysis.get('combo_draw'):
            return 'Combo straight-and-flush draw'
        if analysis.get('flush_draw'):
            return 'Flush draw'
        if analysis.get('open_ended'):
            return 'Open-ended straight draw'
        if analysis.get('gutshot'):
            return 'Gutshot straight draw'
        return 'Draw'

    @staticmethod
    def _postflop_raise_size(state: Dict, pot_fraction: float) -> float:
        pot = max(float(state.get('pot_size', 0) or 0), 1.0)
        to_call = max(float(state.get('to_call', 0) or 0), 0.0)
        minimum_raise = max(float(state.get('raise_amount', 0) or 0), 0.0)
        if to_call > 0.05:
            target = max(minimum_raise, to_call * 3.0, pot * pot_fraction)
        else:
            target = max(minimum_raise, pot * pot_fraction)
        stack = max(float(state.get('hero_stack', 0) or 0), 0.0)
        if stack > 0:
            target = min(target, stack)
        return round(target, 2)

    def calculate_three_bet_size(self, state: Dict, position: str) -> float:
        """Return a target 3-bet size based on the opener's total wager."""
        posted_blind = 0.5 if position == 'sb' else 1.0 if position == 'bb' else 0.0
        open_size = max(float(state.get('to_call', 0) or 0) + posted_blind, 2.0)
        multiplier = (
            self.config.three_bet_size_ip
            if position in ('cutoff', 'button')
            else self.config.three_bet_size_oop
        )
        target = open_size * multiplier
        minimum_raise = float(state.get('raise_amount', 0) or 0)
        stack = float(state.get('hero_stack', 0) or 0)
        target = max(target, minimum_raise)
        if stack > 0:
            target = min(target, stack)
        return round(target, 2)
    
    def calculate_four_bet_size(self, state: Dict) -> float:
        """Calculate 4-bet size"""
        return self.config.four_bet_size * state.get('current_bet', 1)
    
    def get_aggressive_opponent_stats(self, state: Dict) -> Dict:
        """Get stats for the most aggressive opponent"""
        max_three_bet = 0
        aggressive_stats = {}
        
        for pos, stats in state.get('opponents_stats', {}).items():
            if stats.get('three_bet', 0) > max_three_bet:
                max_three_bet = stats['three_bet']
                aggressive_stats = stats
        
        return aggressive_stats
