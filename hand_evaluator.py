# hand_evaluator.py
from collections import Counter
from itertools import combinations
from typing import List, Tuple, Dict, Optional
from enum import Enum

class HandStrength(Enum):
    HIGH_CARD = 0
    PAIR = 1
    TWO_PAIR = 2
    TRIPS = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    QUADS = 7
    STRAIGHT_FLUSH = 8

class HandEvaluator:
    def __init__(self):
        self.card_ranks = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, 
                          '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        
    def preflop_hand_strength(self, cards: List[str]) -> Dict:
        """Evaluate preflop hand strength"""
        if len(cards) != 2 or cards[0] == "??" or cards[1] == "??":
            return {
                'category': 'unknown',
                'strength': 0,
                'high_rank': 0,
                'low_rank': 0,
                'is_pair': False,
                'is_suited': False
            }
        
        try:
            rank1 = cards[0][0].upper()
            rank2 = cards[1][0].upper()
            suit1 = cards[0][1] if len(cards[0]) > 1 else ''
            suit2 = cards[1][1] if len(cards[1]) > 1 else ''
            
            if rank1 not in self.card_ranks or rank2 not in self.card_ranks:
                return {
                    'category': 'unknown',
                    'strength': 0,
                    'high_rank': 0,
                    'low_rank': 0,
                    'is_pair': False,
                    'is_suited': False
                }
            
            is_pair = rank1 == rank2
            is_suited = suit1 == suit2
            
            high_rank = max(self.card_ranks[rank1], self.card_ranks[rank2])
            low_rank = min(self.card_ranks[rank1], self.card_ranks[rank2])
            
            # Hand categories
            if is_pair:
                category = 'pair'
                strength = high_rank
            elif is_suited:
                category = 'suited'
                strength = high_rank * 4 + low_rank
            else:
                category = 'offsuit'
                strength = high_rank * 4 + low_rank
            
            return {
                'category': category,
                'strength': strength,
                'high_rank': high_rank,
                'low_rank': low_rank,
                'is_pair': is_pair,
                'is_suited': is_suited
            }
        except:
            return {
                'category': 'unknown',
                'strength': 0,
                'high_rank': 0,
                'low_rank': 0,
                'is_pair': False,
                'is_suited': False
            }
    
    def is_in_premium_range(self, hand_info: Dict) -> bool:
        """Check if hand is in premium range"""
        if hand_info['category'] == 'unknown':
            return False
        
        if hand_info['is_pair']:
            return hand_info['high_rank'] >= 7  # 77+
        
        if hand_info['is_suited']:
            # ATs+, KQs
            if hand_info['high_rank'] == 14 and hand_info['low_rank'] >= 10:
                return True
            if hand_info['high_rank'] == 13 and hand_info['low_rank'] == 12:
                return True
        
        # AQo+, KQs
        if not hand_info['is_suited']:
            if hand_info['high_rank'] == 14 and hand_info['low_rank'] >= 12:
                return True
        
        return False
    
    def evaluate_postflop(self, hero_cards: List[str], board_cards: List[str]) -> Dict:
        """Describe hero's made hand, pair quality, draws, and approximate outs."""
        parsed_hero = [self._parse_card(card) for card in hero_cards]
        parsed_board = [self._parse_card(card) for card in board_cards]
        if (
            len(parsed_hero) != 2
            or len(parsed_board) < 3
            or any(card is None for card in parsed_hero + parsed_board)
        ):
            return {'valid': False, 'label': 'unreadable', 'category': 'unknown'}

        hero = [card for card in parsed_hero if card is not None]
        board = [card for card in parsed_board if card is not None]
        all_cards = hero + board
        best_score = max(self._five_card_score(combo) for combo in combinations(all_cards, 5))
        category_value = best_score[0]
        category = HandStrength(category_value).name.lower()

        hero_ranks = [rank for rank, _ in hero]
        board_ranks = [rank for rank, _ in board]
        board_unique = sorted(set(board_ranks), reverse=True)
        pocket_pair = hero_ranks[0] == hero_ranks[1]
        overpair = pocket_pair and hero_ranks[0] > max(board_ranks)
        paired_board_ranks = [rank for rank in hero_ranks if rank in board_ranks]
        top_pair = bool(paired_board_ranks and max(paired_board_ranks) == max(board_ranks))
        middle_pair = bool(
            paired_board_ranks
            and not top_pair
            and len(board_unique) >= 2
            and max(paired_board_ranks) == board_unique[1]
        )
        bottom_pair = bool(paired_board_ranks and not top_pair and not middle_pair)
        hero_has_pair = pocket_pair or bool(paired_board_ranks)

        if category_value >= HandStrength.TWO_PAIR.value:
            label = category.replace('_', ' ')
        elif category_value == HandStrength.PAIR.value and overpair:
            label = 'overpair'
        elif category_value == HandStrength.PAIR.value and top_pair:
            label = 'top pair'
        elif category_value == HandStrength.PAIR.value and middle_pair:
            label = 'middle pair'
        elif category_value == HandStrength.PAIR.value and bottom_pair:
            label = 'bottom pair'
        elif category_value == HandStrength.PAIR.value and hero_has_pair:
            label = 'pocket pair'
        elif category_value == HandStrength.PAIR.value:
            label = 'paired board / high card'
        else:
            label = category.replace('_', ' ')

        suit_counts = Counter(suit for _, suit in all_cards)
        flush_draw_suits = [
            suit for suit, count in suit_counts.items()
            if count == 4 and any(hero_suit == suit for _, hero_suit in hero)
        ]
        has_flush = category_value >= HandStrength.FLUSH.value
        flush_draw = bool(flush_draw_suits) and not has_flush

        unique_ranks = set(rank for rank, _ in all_cards)
        straight_missing = set()
        for straight in (
            {14, 2, 3, 4, 5},
            {2, 3, 4, 5, 6}, {3, 4, 5, 6, 7}, {4, 5, 6, 7, 8},
            {5, 6, 7, 8, 9}, {6, 7, 8, 9, 10}, {7, 8, 9, 10, 11},
            {8, 9, 10, 11, 12}, {9, 10, 11, 12, 13}, {10, 11, 12, 13, 14},
        ):
            missing = straight - unique_ranks
            if len(missing) == 1:
                straight_missing.update(missing)
        if category_value >= HandStrength.STRAIGHT.value:
            straight_missing.clear()
        open_ended = len(straight_missing) >= 2
        gutshot = len(straight_missing) == 1

        flush_outs = 9 if flush_draw else 0
        straight_outs = 8 if open_ended else 4 if gutshot else 0
        # A straight-completing card can also complete a flush; discount the
        # overlap rather than presenting impossible 17-out combo draws.
        outs = flush_outs + straight_outs
        if flush_draw and straight_outs:
            outs -= 2
        overcards = sum(rank > max(board_ranks) for rank in hero_ranks)

        kicker = 0
        if top_pair:
            matching = max(paired_board_ranks)
            kicker = max((rank for rank in hero_ranks if rank != matching), default=matching)

        return {
            'valid': True,
            'category': category,
            'category_value': category_value,
            'label': label,
            'score': best_score,
            'pocket_pair': pocket_pair,
            'overpair': overpair,
            'top_pair': top_pair,
            'middle_pair': middle_pair,
            'bottom_pair': bottom_pair,
            'hero_has_pair': hero_has_pair,
            'kicker': kicker,
            'flush_draw': flush_draw,
            'open_ended': open_ended,
            'gutshot': gutshot,
            'strong_draw': flush_draw or open_ended,
            'combo_draw': flush_draw and (open_ended or gutshot),
            'outs': outs,
            'overcards': overcards,
        }

    def _parse_card(self, card: str) -> Optional[Tuple[int, str]]:
        if not isinstance(card, str) or len(card) < 2 or card == '??':
            return None
        rank = self.card_ranks.get(card[0].upper())
        suit = card[1]
        if rank is None or suit not in {'♣', '♦', '♥', '♠'}:
            return None
        return rank, suit

    @staticmethod
    def _five_card_score(cards: Tuple[Tuple[int, str], ...]) -> Tuple[int, ...]:
        """Return a comparable standard poker score for exactly five cards."""
        ranks = [rank for rank, _ in cards]
        counts = Counter(ranks)
        groups = sorted(
            ((count, rank) for rank, count in counts.items()),
            reverse=True,
        )
        flush = len({suit for _, suit in cards}) == 1
        unique = set(ranks)
        straight_high = 5 if {14, 2, 3, 4, 5}.issubset(unique) else 0
        for high in range(14, 5, -1):
            if set(range(high - 4, high + 1)).issubset(unique):
                straight_high = high
                break

        if flush and straight_high:
            return (HandStrength.STRAIGHT_FLUSH.value, straight_high)
        if groups[0][0] == 4:
            quad = groups[0][1]
            kicker = max(rank for rank in ranks if rank != quad)
            return (HandStrength.QUADS.value, quad, kicker)
        if groups[0][0] == 3 and groups[1][0] == 2:
            return (HandStrength.FULL_HOUSE.value, groups[0][1], groups[1][1])
        if flush:
            return (HandStrength.FLUSH.value, *sorted(ranks, reverse=True))
        if straight_high:
            return (HandStrength.STRAIGHT.value, straight_high)
        if groups[0][0] == 3:
            trips = groups[0][1]
            kickers = sorted((rank for rank in ranks if rank != trips), reverse=True)
            return (HandStrength.TRIPS.value, trips, *kickers)
        pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
        if len(pairs) >= 2:
            kicker = max(rank for rank in ranks if rank not in pairs[:2])
            return (HandStrength.TWO_PAIR.value, pairs[0], pairs[1], kicker)
        if len(pairs) == 1:
            pair = pairs[0]
            kickers = sorted((rank for rank in ranks if rank != pair), reverse=True)
            return (HandStrength.PAIR.value, pair, *kickers)
        return (HandStrength.HIGH_CARD.value, *sorted(ranks, reverse=True))
