"""Native dashboard for monitoring and controlling the poker bot locally."""

import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import mss
from PIL import Image, ImageTk

from config import PokerConfig
from poker_bot import PokerBot


class PokerBotApp(tk.Tk):
    BG = "#0b1220"
    PANEL = "#131f31"
    PANEL_ALT = "#192a40"
    TEXT = "#f2f6fc"
    MUTED = "#9aacbf"
    GREEN = "#54d99a"
    AMBER = "#f9c66a"
    RED = "#ff7272"
    BLUE = "#68b7ff"

    def __init__(self):
        super().__init__()
        self.title("Poker Bot · Control Center")
        self.geometry("1180x780")
        self.minsize(1000, 680)
        self.configure(bg=self.BG)

        self.config_data = PokerConfig.load()
        self.bot = PokerBot(self.config_data)
        self.events = queue.Queue()
        self.bot.set_observer(self._receive_bot_event)
        self.screenshotter = mss.mss()
        self.preview_image = None

        self.status_var = tk.StringVar(value="STOPPED")
        self.status_detail = tk.StringVar(value="Ready for calibration")
        self.preview_status = tk.StringVar(value="Waiting for screen access…")
        self.hero_var = tk.StringVar(value="—  —")
        self.board_var = tk.StringVar(value="—")
        self.pot_var = tk.StringVar(value="—")
        self.stack_var = tk.StringVar(value="—")
        self.action_var = tk.StringVar(value="ANALYZE TO SEE A RECOMMENDATION")
        self.reason_var = tk.StringVar(value="Take a screen-only reading to populate the decision map.")
        self.step_vars = [
            tk.StringVar(value="Awaiting screen reading"),
            tk.StringVar(value="Awaiting detected table state"),
            tk.StringVar(value="Awaiting strategy branch"),
            tk.StringVar(value="No action selected"),
        ]

        self._configure_style()
        self._build_dashboard()
        self.bot.hotkey_manager.start()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._refresh_status()
        self._drain_events()
        self._update_preview()

    def _configure_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Helvetica", 11))
        style.configure("Card.TLabel", background=self.PANEL, foreground=self.TEXT, font=("Helvetica", 11))
        style.configure("Muted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("Helvetica", 10))
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("Helvetica", 26, "bold"))
        style.configure("Subtitle.TLabel", background=self.BG, foreground=self.MUTED, font=("Helvetica", 11))
        style.configure("Metric.TLabel", background=self.PANEL_ALT, foreground=self.TEXT, font=("Helvetica", 18, "bold"))
        style.configure("MetricLabel.TLabel", background=self.PANEL_ALT, foreground=self.MUTED, font=("Helvetica", 9, "bold"))
        style.configure("TEntry", fieldbackground="#0c1624", foreground=self.TEXT, insertcolor=self.TEXT)

    def _build_dashboard(self):
        header = ttk.Frame(self, padding=(32, 25, 32, 16))
        header.pack(fill="x")
        title = ttk.Frame(header)
        title.pack(side="left")
        ttk.Label(title, text="Poker Bot", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title, text="Local table monitoring & decision dashboard", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))

        status = tk.Label(header, textvariable=self.status_var, bg="#1c3b38", fg=self.GREEN,
                          padx=14, pady=8, font=("Helvetica", 11, "bold"))
        status.pack(side="right", padx=(10, 0))
        ttk.Button(header, text="Settings", command=self._open_settings).pack(side="right")

        content = ttk.Frame(self, padding=(32, 0, 32, 28))
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=6, uniform="columns")
        content.columnconfigure(1, weight=4, uniform="columns")
        content.rowconfigure(0, weight=1)

        left = ttk.Frame(content, style="Card.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._build_preview(left)

        right = ttk.Frame(content)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self._build_summary(right)
        self._build_decision_map(right)

        footer = ttk.Frame(self, padding=(32, 0, 32, 28))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_detail, style="Subtitle.TLabel").pack(side="left")
        ttk.Label(footer, text="F9 start  •  F8 pause  •  F10 stop", style="Subtitle.TLabel").pack(side="right")

    def _build_preview(self, parent):
        top = ttk.Frame(parent, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="LIVE TABLE VIEW", style="Card.TLabel", font=("Helvetica", 12, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.preview_status, style="Muted.TLabel").pack(side="right")

        self.preview_label = tk.Label(parent, text="Screen preview will appear here", bg="#08101b", fg=self.MUTED,
                                      font=("Helvetica", 13), anchor="center")
        self.preview_label.pack(fill="both", expand=True)

        controls = ttk.Frame(parent, style="Card.TFrame", padding=(0, 16, 0, 0))
        controls.pack(fill="x")
        self._accent_button(controls, "Analyze screen", self._analyze_screen, self.BLUE).pack(side="left")
        self._accent_button(controls, "Start bot", self._start, self.GREEN).pack(side="left", padx=8)
        self._accent_button(controls, "Pause / resume", self._pause, self.AMBER).pack(side="left", padx=8)
        self._accent_button(controls, "Stop", self._stop, self.RED).pack(side="right")

    def _build_summary(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.pack(fill="x")
        ttk.Label(card, text="WHAT THE BOT SEES", style="Card.TLabel", font=("Helvetica", 12, "bold")).pack(anchor="w")
        grid = ttk.Frame(card, style="Card.TFrame", padding=(0, 14, 0, 0))
        grid.pack(fill="x")
        for column in range(2):
            grid.columnconfigure(column, weight=1)
        self._metric(grid, "YOUR CARDS", self.hero_var, 0, 0)
        self._metric(grid, "BOARD", self.board_var, 0, 1)
        self._metric(grid, "POT", self.pot_var, 1, 0)
        self._metric(grid, "STACK", self.stack_var, 1, 1)

    def _metric(self, parent, label, value, row, column):
        card = ttk.Frame(parent, style="Card.TFrame", padding=5)
        card.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
        surface = ttk.Frame(card, style="Card.TFrame", padding=10)
        surface.pack(fill="both", expand=True)
        tk.Label(surface, text=label, bg=self.PANEL_ALT, fg=self.MUTED, font=("Helvetica", 9, "bold"), padx=10, pady=5).pack(fill="x")
        tk.Label(surface, textvariable=value, bg=self.PANEL_ALT, fg=self.TEXT, font=("Helvetica", 16, "bold"), padx=10, pady=8).pack(fill="x")

    def _build_decision_map(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True, pady=(16, 0))
        ttk.Label(card, text="DECISION MAP", style="Card.TLabel", font=("Helvetica", 12, "bold")).pack(anchor="w")
        ttk.Label(card, text="A readable summary of the rule path used for the current recommendation.", style="Muted.TLabel", wraplength=350).pack(anchor="w", pady=(5, 14))
        labels = ("1  Read", "2  Interpret", "3  Apply rule", "4  Suggest")
        for index, label in enumerate(labels):
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg="#233a57", fg=self.BLUE, font=("Helvetica", 9, "bold"), padx=8, pady=6).pack(side="left")
            ttk.Label(row, textvariable=self.step_vars[index], style="Muted.TLabel", wraplength=265).pack(side="left", padx=10)

        divider = ttk.Separator(card, orient="horizontal")
        divider.pack(fill="x", pady=14)
        ttk.Label(card, text="RECOMMENDED ACTION", style="Muted.TLabel").pack(anchor="w")
        tk.Label(card, textvariable=self.action_var, bg=self.PANEL, fg=self.GREEN, font=("Helvetica", 16, "bold"), pady=5).pack(anchor="w")
        ttk.Label(card, textvariable=self.reason_var, style="Muted.TLabel", wraplength=350, justify="left").pack(anchor="w")
        ttk.Label(card, text="DECISION TRACE", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        self.trace_box = tk.Text(card, height=6, bg="#0a1421", fg="#c9d8e8", insertbackground="#c9d8e8",
                                 relief="flat", wrap="word", font=("Menlo", 9), padx=8, pady=7)
        self.trace_box.pack(fill="x")
        self.trace_box.configure(state="disabled")

    def _accent_button(self, parent, label, command, color):
        return tk.Button(parent, text=label, command=command, bg=color, fg="#07111a", activebackground=color,
                         activeforeground="#07111a", relief="flat", padx=14, pady=9, cursor="hand2",
                         font=("Helvetica", 10, "bold"))

    def _receive_bot_event(self, event, payload):
        self.events.put((event, payload))

    def _drain_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "decision":
                    self._show_decision(payload)
                elif event == "state":
                    self._show_state(payload)
                elif event == "turn":
                    self._show_turn(payload)
                elif event == "trace":
                    self._show_trace(payload)
                elif event == "error":
                    self.status_detail.set(payload)
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _show_state(self, state):
        self.hero_var.set("  ".join(state.get("hero_cards", ("??", "??"))))
        self.board_var.set("  ".join(state.get("board_cards", [])) or "No board cards")
        self.pot_var.set(f"{state.get('pot_size', 0):.2f} BB")
        self.stack_var.set(f"{state.get('hero_stack', 0):.2f} BB")
        self.step_vars[0].set("Read cards, board, pot, stack, and player tooltips.")
        self.step_vars[1].set(f"Detected {state.get('street').value} with {state.get('to_call', 0):.2f} BB to call.")

    def _show_decision(self, decision):
        amount = decision.get("amount")
        action = decision["action"].replace("_", " ").upper()
        if amount is not None:
            action += f"  ·  {amount:.2f} BB"
        self.action_var.set(action)
        self.reason_var.set(decision["reason"])
        self.step_vars[2].set(decision["reason"])
        self.step_vars[3].set(f"{decision['action'].replace('_', ' ').title()} selected for this state.")
        self.status_detail.set(f"Last analysis: {datetime.now().strftime('%I:%M:%S %p')}")

    def _show_turn(self, turn):
        if turn["confirmed"]:
            if turn["action_taken"]:
                self.status_detail.set("Your turn was handled. Waiting for the action controls to disappear.")
            else:
                self.status_detail.set("Your turn detected — reading the table before acting.")
        elif turn["visible"]:
            self.status_detail.set("Action controls detected — confirming your turn.")
        else:
            self.status_detail.set(
                f"Checking for Fold / Check / Call / Raise every "
                f"{self.config_data.turn_poll_interval:.1f} second."
            )

    def _show_trace(self, trace):
        actions = ', '.join(f"{seat}: {action}" for seat, action in trace['observed_actions'].items()) or 'none detected'
        amount = f" {trace['amount']:.2f} BB" if trace['amount'] is not None else ''
        dealer = f" · dealer at {trace['dealer_seat']}" if trace.get('dealer_seat') else ''
        analysis = trace.get('hand_analysis') or {}
        postflop = ''
        if analysis.get('valid'):
            draws = []
            if analysis.get('flush_draw'):
                draws.append('flush draw')
            if analysis.get('open_ended'):
                draws.append('open-ended draw')
            elif analysis.get('gutshot'):
                draws.append('gutshot')
            postflop = (
                f"Hand class: {analysis.get('label')} · Draws: {', '.join(draws) or 'none'}\n"
                f"Bet/pot: {analysis.get('bet_fraction', 0):.0%} · "
                f"Pot odds: {analysis.get('pot_odds', 0):.0%}\n"
            )
        message = (
            f"Hand: {trace['hero_cards']}\n"
            f"Position: {trace['position']} ({trace['position_source']}{dealer})\n"
            f"To call: {trace['to_call']:.2f} BB ({trace['to_call_source']})\n"
            f"Preflop pressure: {trace.get('preflop_raise_level') or '—'}\n"
            f"Raise button: {trace['raise_amount']:.2f} BB · Input: {trace['bet_input_amount']:.2f} BB\n"
            f"Actions seen: {actions}\n"
            f"{postflop}"
            f"Decision: {trace['action'].upper()}{amount}\n"
            f"Why: {trace['reason']}"
        )
        self.trace_box.configure(state="normal")
        self.trace_box.delete("1.0", "end")
        self.trace_box.insert("1.0", message)
        self.trace_box.configure(state="disabled")

    def _update_preview(self):
        try:
            monitor = self.screenshotter.monitors[1]
            x, y, width, height = self.config_data.scale_region(
                self.config_data.table_region, (monitor["width"], monitor["height"])
            )
            image = self.screenshotter.grab({"left": x, "top": y, "width": width, "height": height})
            preview = Image.frombytes("RGB", image.size, image.bgra, "raw", "BGRX")
            preview.thumbnail((660, 470), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_image, text="")
            self.preview_status.set("Updating locally")
        except Exception as error:
            self.preview_label.configure(image="", text="Screen preview unavailable\nAllow Screen Recording access, then restart the terminal.")
            self.preview_status.set("Screen permission needed")
            self.status_detail.set(f"Preview unavailable: {error}")
        self.after(1250, self._update_preview)

    def _analyze_screen(self):
        self.status_detail.set("Reading the screen — this does not click anything.")
        threading.Thread(target=self._run_analysis, daemon=True).start()

    def _run_analysis(self):
        try:
            self.bot.analyze_screen()
        except Exception as error:
            self.events.put(("error", f"Screen analysis failed: {error}"))

    def _start(self):
        self.bot.start_bot()
        self.status_detail.set("Bot started. It will act only when its turn detector is positive.")

    def _pause(self):
        if self.bot.running:
            self.bot.toggle_pause()
        else:
            self.status_detail.set("Start the bot before pausing it.")

    def _stop(self):
        self.bot.stop_bot()
        self.status_detail.set("Bot stopped. No new actions will be taken.")

    def _refresh_status(self):
        if self.bot.running and self.bot.paused:
            self.status_var.set("PAUSED")
        elif self.bot.running:
            self.status_var.set("RUNNING")
        else:
            self.status_var.set("STOPPED")
        self.after(250, self._refresh_status)

    def _open_settings(self):
        dialog = tk.Toplevel(self)
        dialog.title("Poker Bot · Coordinates")
        dialog.configure(bg=self.BG)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Button coordinates", font=("Helvetica", 17, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text="Update these values for your poker table, then save.", style="Subtitle.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 16))
        variables = {}
        for row, (label, attribute) in enumerate((("Fold", "fold_button"), ("Call / check", "call_button"), ("Raise", "raise_button"), ("Bet input", "bet_input")), start=2):
            coordinates = getattr(self.config_data, attribute)
            x, y = coordinates if coordinates else ("", "")
            x_var, y_var = tk.StringVar(value=str(x)), tk.StringVar(value=str(y))
            variables[attribute] = (x_var, y_var)
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 28), pady=6)
            ttk.Entry(body, textvariable=x_var, width=10).grid(row=row, column=1, padx=4, pady=6)
            ttk.Entry(body, textvariable=y_var, width=10).grid(row=row, column=2, padx=4, pady=6)

        def save():
            try:
                for attribute, (x_var, y_var) in variables.items():
                    x_text, y_text = x_var.get().strip(), y_var.get().strip()
                    if not x_text and not y_text:
                        setattr(self.config_data, attribute, None)
                    elif x_text and y_text:
                        setattr(self.config_data, attribute, (int(x_text), int(y_text)))
                    else:
                        raise ValueError
                self.config_data.save()
                self.status_detail.set("Configuration saved to poker_config.json.")
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Invalid coordinate", "Each coordinate must be a whole number.", parent=dialog)

        self._accent_button(body, "Save configuration", save, self.GREEN).grid(row=6, column=0, columnspan=3, sticky="w", pady=(18, 0))

    def _close(self):
        self.bot.stop_bot()
        self.bot.hotkey_manager.stop()
        self.screenshotter.close()
        self.destroy()


def run_app():
    PokerBotApp().mainloop()
