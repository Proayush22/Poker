# poker_bot.py
import time
import threading
from typing import Any, Callable, Dict, Optional
from screen_reader import ScreenReader
from strategy_engine import StrategyEngine, Action, Street
from action_executer import ActionExecutor
from hand_evaluator import HandEvaluator
from config import PokerConfig
from hotkey_manager import HotkeyManager

class PokerBot:
    def __init__(self, config: PokerConfig):
        self.config = config
        self.screen_reader = ScreenReader(config)
        self.strategy_engine = StrategyEngine(config)
        self.action_executor = ActionExecutor(config)
        self.hand_evaluator = HandEvaluator()
        self.hotkey_manager = HotkeyManager()
        
        self.running = False
        self.paused = False
        self.current_street = Street.PREFLOP
        self.game_state = {}
        self.player_profiles: Dict[str, Dict[str, Any]] = self.config.player_profiles
        self.seat_players: Dict[str, str] = self.config.seat_players
        self.observer: Optional[Callable[[str, Dict], None]] = None
        self._turn_confirmations = 0
        self._turn_action_taken = False
        self._hero_preflop_aggressor = False
        self._hero_preflop_raise_level = 0
        self._last_observed_street: Optional[Street] = None
        self._profile_seats = [seat for seat in self.config.player_positions if seat != 'hero']
        self._profile_scan_index = 0
        self._next_profile_scan = time.monotonic() + self.config.profile_scan_interval
        self._profile_hand_number = 0
        self._profile_dealer_seat = None
        self._seen_profile_events = set()
        self._profile_preflop_raisers = set()
        
        # Register hotkeys
        self.hotkey_manager.register_hotkey('f9', self.start_bot)
        self.hotkey_manager.register_hotkey('f10', self.stop_bot)
        self.hotkey_manager.register_hotkey('f8', self.toggle_pause)

    def set_observer(self, observer: Callable[[str, Dict], None]):
        """Receive state and decision summaries for a local interface."""
        self.observer = observer

    def _publish(self, event: str, payload: Dict):
        if self.observer:
            try:
                self.observer(event, payload)
            except Exception:
                pass
        
    def start_bot(self):
        """Start the bot"""
        if not self.running:
            self.running = True
            self.paused = False
            print("Poker Bot started. Press F10 to stop, F8 to pause/resume.")
            print(
                f"Turn detector checks every {self.config.turn_poll_interval:.1f}s "
                f"and requires {self.config.turn_confirmations_required} confirmation."
            )
            
            # Start bot in separate thread
            bot_thread = threading.Thread(target=self._bot_loop, daemon=True)
            bot_thread.start()
    
    def stop_bot(self):
        """Stop the bot"""
        self.running = False
        print("Poker Bot stopped.")
    
    def toggle_pause(self):
        """Toggle pause state"""
        self.paused = not self.paused
        print(f"Bot {'paused' if self.paused else 'resumed'}.")
    
    def _bot_loop(self):
        """Main bot loop"""
        while self.running:
            if not self.paused:
                try:
                    turn_visible = self.screen_reader.is_our_turn()
                    self._turn_confirmations = self._turn_confirmations + 1 if turn_visible else 0
                    if not turn_visible:
                        self._turn_action_taken = False
                    confirmed = (
                        self._turn_confirmations
                        >= self.config.turn_confirmations_required
                    )
                    self._publish('turn', {
                        'visible': turn_visible,
                        'confirmed': confirmed,
                        'action_taken': self._turn_action_taken,
                    })
                    if confirmed and not self._turn_action_taken:
                        self._turn_action_taken = self.play_hand()
                    elif not turn_visible and time.monotonic() >= self._next_profile_scan:
                        self._refresh_next_player_profile()
                        self._next_profile_scan = time.monotonic() + self.config.profile_scan_interval
                    time.sleep(self.config.turn_poll_interval)
                except Exception as e:
                    print(f"Error in bot loop: {e}")
                    time.sleep(2)
            else:
                time.sleep(0.5)
    
    def play_hand(self):
        """Play a complete hand"""
        # Gather game state
        self.gather_game_state()
        
        # Get action from strategy engine
        action, amount = self.strategy_engine.get_action(self.game_state)
        self._publish_decision(action, amount)

        if action == Action.WAIT:
            return False

        if self.current_street == Street.PREFLOP:
            if action in (Action.RAISE, Action.ALL_IN):
                self._hero_preflop_aggressor = True
                if self.game_state.get('facing_three_bet'):
                    self._hero_preflop_raise_level = 4
                elif self.game_state.get('facing_raise'):
                    self._hero_preflop_raise_level = 3
                else:
                    self._hero_preflop_raise_level = 2
            elif action in (Action.CALL, Action.FOLD):
                self._hero_preflop_aggressor = False
                self._hero_preflop_raise_level = 0
        
        # Execute action
        self.action_executor.execute_action(action, amount)
        
        # Log the action
        print(f"Street: {self.current_street}, Action: {action.value}, Amount: {amount}")
        return True
    
    def gather_game_state(self):
        """Gather all relevant game state information"""
        # Read hero cards
        hero_cards = self.screen_reader.read_hero_cards()
        
        # Read board cards
        board_cards = self.screen_reader.read_board_cards()
        
        # Determine street based on board cards
        if len(board_cards) == 0:
            street = Street.PREFLOP
        elif len(board_cards) == 3:
            street = Street.FLOP
        elif len(board_cards) == 4:
            street = Street.TURN
        elif len(board_cards) == 5:
            street = Street.RIVER
        else:
            street = Street.PREFLOP

        if street == Street.PREFLOP and self._last_observed_street not in (None, Street.PREFLOP):
            self._hero_preflop_aggressor = False
            self._hero_preflop_raise_level = 0
        self._last_observed_street = street
        
        # Read pot size
        pot_size = self.screen_reader.read_pot_size()
        
        # Read hero stack
        hero_stack = self.screen_reader.read_hero_stack()

        # The Call button reflects the live amount required to continue. This
        # replaces the previous hard-coded "2 BB" assumption.
        call_control, to_call = self.screen_reader.read_call_control()
        raise_amount = self.screen_reader.read_raise_amount()
        bet_input_amount = self.screen_reader.read_bet_input_amount()

        # The button cannot move after the flop. Reuse the preflop mapping on
        # later streets instead of spending roughly 2.5 seconds finding D again.
        hero_position, seat_to_position = self.screen_reader.read_hero_position(
            use_cached=street != Street.PREFLOP
        )

        observed_actions = {}
        seat_actions = {}
        for seat, coords in self.config.player_positions.items():
            if seat == 'hero':
                continue
            action = self.screen_reader.read_player_action(coords)
            if action:
                seat_actions[seat] = action
                observed_actions[seat_to_position.get(seat, seat)] = action

        raiser_position = next(
            (position for position, action in observed_actions.items() if action in ('BET', 'RAISE')),
            None,
        )
        raises_seen = sum(action == 'RAISE' for action in observed_actions.values())
        facing_raise = bool(
            street == Street.PREFLOP
            and (
                to_call > 1.0
                or raises_seen >= 1
                or (hero_position == 'bb' and call_control == 'call')
            )
        )
        facing_bet = bool(street != Street.PREFLOP and to_call > 0.05)
        facing_three_bet = False
        facing_four_bet = False
        if facing_raise:
            if self._hero_preflop_raise_level >= 3:
                facing_four_bet = True
            elif self._hero_preflop_raise_level == 2:
                facing_three_bet = True
            elif raises_seen >= 3 or to_call >= 12.0:
                facing_four_bet = True
            elif raises_seen >= 2 or to_call >= 4.0:
                facing_three_bet = True

        self._record_profile_observations(
            street,
            seat_actions,
            self.screen_reader.last_dealer_seat,
            facing_three_bet,
        )
        opponent_profiles = self._profiles_by_position(seat_to_position)
        
        # Update game state
        self.game_state = {
            'hero_cards': hero_cards,
            'board_cards': board_cards,
            'street': street,
            'position': hero_position or 'unknown',
            'pot_size': pot_size,
            'hero_stack': hero_stack,
            'observed_actions': observed_actions,
            'opponent_profiles': opponent_profiles,
            'to_call': to_call,
            'call_control': call_control,
            'to_call_source': f'{call_control.title()}-button OCR',
            'raise_amount': raise_amount,
            'bet_input_amount': bet_input_amount,
            'current_bet': to_call,
            'position_source': self.screen_reader.last_position_source,
            'dealer_seat': self.screen_reader.last_dealer_seat,
            'facing_raise': facing_raise,
            'facing_three_bet': facing_three_bet,
            'facing_four_bet': facing_four_bet,
            'preflop_raise_level': (
                'four_bet' if facing_four_bet
                else 'three_bet' if facing_three_bet
                else 'open_raise' if facing_raise
                else 'unraised'
            ),
            'is_preflop_aggressor': self._hero_preflop_aggressor,
            'facing_bet': facing_bet,
            'bet_count': raises_seen if street == Street.PREFLOP else int(facing_bet),
            'facing_check_raise': False,
            'raiser_position': raiser_position,
        }
        self.current_street = street
        self._publish('state', self.game_state.copy())

    @staticmethod
    def _empty_observed_profile() -> Dict[str, int]:
        return {
            'hands': 0,
            'vpip_actions': 0,
            'pfr_actions': 0,
            'three_bets': 0,
            'cbet_opportunities': 0,
            'c_bets': 0,
            'postflop_actions': 0,
            'aggressive_actions': 0,
            'passive_actions': 0,
            'folds': 0,
        }

    def _refresh_next_player_profile(self):
        """Maintain one profile between turns without delaying an action."""
        if not self._profile_seats:
            return
        seat = self._profile_seats[self._profile_scan_index % len(self._profile_seats)]
        self._profile_scan_index += 1
        coords = self.config.player_positions[seat]
        screen_name = self.screen_reader.read_player_name(coords)
        if not screen_name:
            return

        changed = self.seat_players.get(seat) != screen_name
        self.seat_players[seat] = screen_name
        profile = self.player_profiles.setdefault(screen_name, {
            'screen_name': screen_name,
            'external_stats': {},
            'tooltip_scanned': False,
            'observed': self._empty_observed_profile(),
        })
        if changed or not profile.get('tooltip_scanned'):
            external = self.screen_reader.read_player_stats(coords)
            if external:
                profile['external_stats'] = external
            profile['tooltip_scanned'] = True

        self._save_profiles()
        self._publish('player_profile', {
            'seat': seat,
            'screen_name': screen_name,
            'changed': changed,
            'summary': self._profile_summary(profile),
        })

    def _record_profile_observations(
        self,
        street: Street,
        seat_actions: Dict[str, str],
        dealer_seat: Optional[str],
        facing_three_bet: bool,
    ):
        """Learn from visible actions while preventing duplicate samples."""
        changed = False
        if street == Street.PREFLOP and dealer_seat and dealer_seat != self._profile_dealer_seat:
            self._profile_dealer_seat = dealer_seat
            self._profile_hand_number += 1
            self._seen_profile_events.clear()
            self._profile_preflop_raisers.clear()
            for screen_name in set(self.seat_players.values()):
                profile = self.player_profiles.get(screen_name)
                if profile:
                    observed = profile.setdefault('observed', self._empty_observed_profile())
                    observed['hands'] = observed.get('hands', 0) + 1
                    changed = True

        for seat, action in seat_actions.items():
            screen_name = self.seat_players.get(seat)
            if not screen_name:
                continue
            event = (self._profile_hand_number, street.value, seat, action)
            if event in self._seen_profile_events:
                continue
            self._seen_profile_events.add(event)
            profile = self.player_profiles.setdefault(screen_name, {
                'screen_name': screen_name,
                'external_stats': {},
                'tooltip_scanned': False,
                'observed': self._empty_observed_profile(),
            })
            observed = profile.setdefault('observed', self._empty_observed_profile())
            if street == Street.PREFLOP:
                if action in ('CALL', 'BET', 'RAISE', 'ALL IN'):
                    observed['vpip_actions'] = observed.get('vpip_actions', 0) + 1
                if action in ('BET', 'RAISE', 'ALL IN'):
                    observed['pfr_actions'] = observed.get('pfr_actions', 0) + 1
                    self._profile_preflop_raisers.add(screen_name)
                    if facing_three_bet:
                        observed['three_bets'] = observed.get('three_bets', 0) + 1
            else:
                observed['postflop_actions'] = observed.get('postflop_actions', 0) + 1
                if street == Street.FLOP and screen_name in self._profile_preflop_raisers:
                    cbet_event = (
                        self._profile_hand_number,
                        street.value,
                        screen_name,
                        'cbet_opportunity',
                    )
                    if cbet_event not in self._seen_profile_events:
                        self._seen_profile_events.add(cbet_event)
                        observed['cbet_opportunities'] = observed.get('cbet_opportunities', 0) + 1
                        if action in ('BET', 'RAISE', 'ALL IN'):
                            observed['c_bets'] = observed.get('c_bets', 0) + 1
                if action in ('BET', 'RAISE', 'ALL IN'):
                    observed['aggressive_actions'] = observed.get('aggressive_actions', 0) + 1
                elif action in ('CALL', 'CHECK'):
                    observed['passive_actions'] = observed.get('passive_actions', 0) + 1
                elif action == 'FOLD':
                    observed['folds'] = observed.get('folds', 0) + 1
            changed = True
        if changed:
            self._save_profiles()

    def _profile_summary(self, profile: Dict[str, Any]) -> Dict[str, float]:
        external = profile.get('external_stats', {})
        observed = profile.get('observed', {})
        hands = max(int(observed.get('hands', 0)), 0)
        postflop_actions = max(int(observed.get('postflop_actions', 0)), 0)

        def percentage(key, denominator):
            return round(100 * observed.get(key, 0) / denominator, 1) if denominator else None

        summary = {
            'hands': hands,
            'has_external_stats': bool(external),
            'vpip': external.get('vpip', percentage('vpip_actions', hands)),
            'pfr': external.get('pfr', percentage('pfr_actions', hands)),
            'three_bet': external.get('three_bet', percentage('three_bets', hands)),
            'c_bet': external.get(
                'c_bet',
                percentage('c_bets', observed.get('cbet_opportunities', 0)),
            ),
            'fold_rate': percentage('folds', postflop_actions),
            'aggression_factor': round(
                observed.get('aggressive_actions', 0)
                / max(observed.get('passive_actions', 0), 1),
                2,
            ),
        }
        return summary

    def _profiles_by_position(self, seat_to_position: Dict[str, str]) -> Dict[str, Dict]:
        profiles = {}
        for seat, position in seat_to_position.items():
            if seat == 'hero':
                continue
            screen_name = self.seat_players.get(seat)
            profile = self.player_profiles.get(screen_name) if screen_name else None
            if profile:
                profiles[position] = {
                    'screen_name': screen_name,
                    **self._profile_summary(profile),
                }
        return profiles

    def _save_profiles(self):
        self.config.player_profiles = self.player_profiles
        self.config.seat_players = self.seat_players
        self.config.save()

    def analyze_screen(self):
        """Read the table and publish a suggested action without clicking."""
        self.gather_game_state()
        action, amount = self.strategy_engine.get_action(self.game_state)
        self._publish_decision(action, amount)

    def _publish_decision(self, action: Action, amount: Optional[float]):
        cards = self.game_state.get('hero_cards', ('??', '??'))
        board = self.game_state.get('board_cards', [])
        if '??' in cards:
            reason = 'Card text is not yet readable. Waiting and retrying without clicking.'
        elif self.game_state.get('position') == 'unknown':
            reason = 'Dealer button and blind badges are not readable. Waiting without clicking.'
        elif self.strategy_engine.last_reason:
            reason = self.strategy_engine.last_reason
        elif self.game_state.get('street') == Street.PREFLOP:
            if self.game_state.get('facing_four_bet'):
                reason = 'A four-bet was detected, so the preflop four-bet branch was used.'
            elif self.game_state.get('facing_three_bet'):
                reason = 'A three-bet was detected, so the preflop three-bet branch was used.'
            elif self.game_state.get('to_call', 0) > 1:
                reason = 'A raise to call was detected, so the facing-raise branch was used.'
            else:
                reason = 'No raise to call was detected, so the unopened-pot range was used.'
        else:
            reason = self.strategy_engine.last_reason or 'The post-flop rule set was used for the detected street.'

        self._publish('decision', {
            'hero_cards': cards,
            'board_cards': board,
            'street': self.game_state.get('street', Street.PREFLOP).value,
            'pot_size': self.game_state.get('pot_size', 0),
            'hero_stack': self.game_state.get('hero_stack', 0),
            'to_call': self.game_state.get('to_call', 0),
            'action': action.value,
            'amount': amount,
            'reason': reason,
            'hand_analysis': self.strategy_engine.last_analysis.copy(),
            'profile_adjustment': self.strategy_engine.last_profile_adjustment,
        })
        trace = {
            'hero_cards': ' '.join(cards),
            'position': self.game_state.get('position', 'unknown'),
            'position_source': self.game_state.get('position_source', 'unknown'),
            'dealer_seat': self.game_state.get('dealer_seat'),
            'street': self.game_state.get('street', Street.PREFLOP).value,
            'to_call': self.game_state.get('to_call', 0),
            'call_control': self.game_state.get('call_control', 'unknown'),
            'to_call_source': self.game_state.get('to_call_source', 'unknown'),
            'preflop_raise_level': self.game_state.get('preflop_raise_level'),
            'raise_amount': self.game_state.get('raise_amount', 0),
            'bet_input_amount': self.game_state.get('bet_input_amount', 0),
            'observed_actions': self.game_state.get('observed_actions', {}),
            'action': action.value,
            'amount': amount,
            'reason': reason,
            'hand_analysis': self.strategy_engine.last_analysis.copy(),
            'profile_adjustment': self.strategy_engine.last_profile_adjustment,
            'opponent_profiles': self.game_state.get('opponent_profiles', {}),
        }
        amount_text = f" {amount:.2f} BB" if amount is not None else ''
        print("\n=== Decision Trace ===")
        dealer_text = f" | Dealer seat: {trace['dealer_seat']}" if trace['dealer_seat'] else ''
        print(f"Hand: {trace['hero_cards']} | Position: {trace['position']} ({trace['position_source']}){dealer_text}")
        print(f"Street: {trace['street']} | To call: {trace['to_call']:.2f} BB ({trace['to_call_source']})")
        if trace.get('preflop_raise_level'):
            print(f"Preflop pressure: {trace['preflop_raise_level']}")
        print(f"Controls: Raise {trace['raise_amount']:.2f} BB | Input {trace['bet_input_amount']:.2f} BB")
        print(f"Visible actions: {trace['observed_actions'] or 'none detected'}")
        if trace.get('opponent_profiles'):
            profile_text = {
                position: {
                    'name': profile.get('screen_name'),
                    'hands': profile.get('hands'),
                    'vpip': profile.get('vpip'),
                    'pfr': profile.get('pfr'),
                    '3bet': profile.get('three_bet'),
                    'AF': profile.get('aggression_factor'),
                    'fold': profile.get('fold_rate'),
                }
                for position, profile in trace['opponent_profiles'].items()
            }
            print(f"Profiles: {profile_text}")
        if trace.get('profile_adjustment'):
            print(f"Profile adjustment: {trace['profile_adjustment']}")
        analysis = trace.get('hand_analysis') or {}
        if analysis.get('valid'):
            draw_bits = []
            if analysis.get('flush_draw'):
                draw_bits.append('flush draw')
            if analysis.get('open_ended'):
                draw_bits.append('open-ended draw')
            elif analysis.get('gutshot'):
                draw_bits.append('gutshot')
            draws = ', '.join(draw_bits) or 'none'
            print(
                f"Hand class: {analysis.get('label')} | Draws: {draws} | "
                f"Bet/pot: {analysis.get('bet_fraction', 0):.0%} | "
                f"Pot odds: {analysis.get('pot_odds', 0):.0%}"
            )
        print(f"Decision: {trace['action'].upper()}{amount_text}")
        print(f"Reason: {trace['reason']}")
        print("======================\n")
        self._publish('trace', trace)
    
    def calibrate(self):
        """Calibration mode to set up screen positions"""
        import pyautogui
        from pynput import keyboard
        
        print("Calibration Mode")
        print("================")
        print("Press 'p' to capture player positions")
        print("Press 'b' to capture button positions")
        print("Press 'c' to capture card positions")
        print("Press 'esc' to exit calibration")
        print("")
        
        def capture_position(label: str):
            x, y = pyautogui.position()
            print(f"{label} position: ({x}, {y})")

        def on_press(key):
            if key == keyboard.Key.esc:
                return False

            try:
                commands = {'p': 'Player', 'b': 'Button', 'c': 'Card'}
                label = commands.get(key.char.lower()) if key.char else None
                if label:
                    capture_position(label)
            except AttributeError:
                pass

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

# main.py
def main():
    # Load or create config
    config = PokerConfig.load()
    
    # Create bot
    bot = PokerBot(config)
    
    # Start hotkey listener
    bot.hotkey_manager.start()
    
    print("Poker Bot Ready")
    print("===============")
    print("Press F9 to start the bot")
    print("Press F8 to pause/resume")
    print("Press F10 to stop the bot")
    print("Press Ctrl+C to exit the program")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        bot.stop_bot()
        bot.hotkey_manager.stop()

if __name__ == "__main__":
    main()
