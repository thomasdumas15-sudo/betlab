"""Moteur de décision : applique chaque stratégie aux matchs éligibles."""
from __future__ import annotations

from datetime import timedelta

from .strategies import Context, build_strategies
from .util import now_utc, parse_iso


class Engine:
    def __init__(self, cfg, store, ledger, log=print):
        self.cfg = cfg
        self.store = store
        self.ledger = ledger
        self.log = log
        self.strategies = build_strategies(cfg)
        self.settings = cfg.get("betting", {})
        self.bet_book = cfg.get("bet_bookmaker", "winamax")
        self.ref_book = cfg.get("reference_bookmaker", "pinnacle")

    def eligible_events(self, now) -> list[dict]:
        lo = now + timedelta(minutes=float(self.settings.get("min_minutes_before_start", 15)))
        hi = now + timedelta(hours=float(self.settings.get("max_hours_before_start", 40)))
        out = []
        for ev in self.store.events.values():
            if ev.get("status") not in (None, "scheduled"):
                continue
            if not ev.get("names_resolved", True):
                continue
            st = parse_iso(ev.get("start"))
            if st and lo <= st <= hi:
                out.append(ev)
        return out

    def run(self) -> list[dict]:
        now = now_utc()
        events = self.eligible_events(now)
        quotes_all = self.store.latest_quotes(days_back=3)
        opening = self.store.first_quotes({e["id"] for e in events}, self.ref_book, days_back=10)
        placed = []
        bankrolls = {s.key: self.ledger.bankroll(s.key) for s in self.strategies}
        exposures = {s.key: self.ledger.exposure(s.key) for s in self.strategies}
        for ev in events:
            quotes = quotes_all.get(ev["id"])
            if not quotes or self.bet_book not in quotes:
                continue
            for strat in self.strategies:
                if not strat.applies_to(ev) or self.ledger.already_bet(strat.key, ev["id"]):
                    continue
                bankroll = bankrolls[strat.key]
                available = bankroll - exposures[strat.key]
                if available <= 0:
                    continue
                ctx = Context(now=now, event=ev, quotes=quotes, bet_book=self.bet_book, ref_book=self.ref_book,
                              bankroll=bankroll, available=available, opening=opening.get(ev["id"]), settings=self.settings)
                try:
                    cands = strat.candidates(ctx)
                except Exception as e:  # une stratégie ne doit jamais bloquer les autres
                    self.log(f"  ! stratégie {strat.key} sur {ev['id']}: {e}")
                    continue
                for c in cands[:1]:
                    if c.stake <= 0:
                        continue
                    if c.stake > available:
                        c.stake = round(available, 2)
                    bet = self.ledger.place(strat.key, ev, c, self.bet_book, quotes, note=c.note)
                    exposures[strat.key] += bet["stake"]
                    placed.append(bet)
                    self.log(f"  + {strat.label}: {bet['match']} → {bet['selection_name']} @ {bet['odds']} "
                             f"mise {bet['stake']} € (edge {bet['edge'] * 100:+.1f} %)")
        return placed
