"""Registre des paris simulés : bankrolls, placement, règlement, CLV."""
from __future__ import annotations

import uuid

from .util import devig, iso, now_utc


class Ledger:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.start = float(cfg.get("bankroll_start", 1000))

    # ------------------------------------------------------------ bankroll
    def bankroll(self, strategy: str) -> float:
        pnl = sum(float(b.get("pnl") or 0) for b in self.store.bets if b["strategy"] == strategy and b["status"] != "open")
        return round(self.start + pnl, 2)

    def exposure(self, strategy: str) -> float:
        return round(sum(float(b["stake"]) for b in self.store.bets if b["strategy"] == strategy and b["status"] == "open"), 2)

    def already_bet(self, strategy: str, event_id: str, market: str = "h2h") -> bool:
        return any(b["strategy"] == strategy and b["event_id"] == event_id and b.get("market", "h2h") == market
                   for b in self.store.bets)

    def bets_on_event(self, strategy: str, event_id: str) -> int:
        return sum(1 for b in self.store.bets if b["strategy"] == strategy and b["event_id"] == event_id)

    # ------------------------------------------------------------ placement
    def place(self, strategy: str, event: dict, cand, bet_book: str, quotes: dict, note: str = "") -> dict:
        ref = self.cfg.get("reference_bookmaker", "pinnacle")
        market = getattr(cand, "market", "h2h") or "h2h"
        ref_q = (quotes.get(ref) or {}).get(market) or {}
        bet_q = (quotes.get(bet_book) or {}).get(market) or {}
        names = {"home": event.get("home"), "away": event.get("away"), "draw": "Nul"}
        bet = {
            "id": uuid.uuid4().hex[:12],
            "strategy": strategy,
            "event_id": event["id"],
            "sport": event.get("sport"),
            "match": f"{event.get('home')} – {event.get('away')}",
            "start": event.get("start"),
            "market": market,
            "line": bet_q.get("line") if market != "h2h" else None,
            "player": bet_q.get("player"),
            "stat": bet_q.get("stat"),
            "selection": cand.selection,
            "selection_name": getattr(cand, "label", "") or names.get(cand.selection, cand.selection),
            "book": bet_book,
            "odds": round(float(cand.odds), 3),
            "fair_prob": round(float(cand.fair_prob), 4),
            "edge": round(float(cand.edge), 4),
            "stake": round(float(cand.stake), 2),
            "bankroll_before": self.bankroll(strategy),
            "placed_at": iso(now_utc()),
            "quote_ts": bet_q.get("ts"),
            "ref_prices": ref_q.get("prices"),
            "note": note or getattr(cand, "note", ""),
            "status": "open",
            "pnl": None,
            "settled_at": None,
            "result": None,
            "closing_odds": None,       # cote de clôture du book joué (Winamax)
            "closing_ref": None,        # cotes de clôture Pinnacle (dict)
            "clv": None,                # EV à la clôture : odds × p_close(Pinnacle) − 1
            "clv_book": None,           # odds / clôture Winamax − 1
            "closing_source": None,
        }
        self.store.bets.append(bet)
        return bet

    # ------------------------------------------------------------ règlement
    def settle(self, bet: dict, winner: str | None, status: str = "settled") -> None:
        """winner: 'home' | 'away' | 'draw' | 'over' | 'under' | 'push' ; status 'cancelled' -> remboursé."""
        if bet["status"] != "open":
            return
        stake, odds = float(bet["stake"]), float(bet["odds"])
        if status == "cancelled" or winner == "push":
            bet["status"], bet["pnl"], bet["result"] = "void", 0.0, "annulé"
        elif winner == bet["selection"]:
            bet["status"], bet["pnl"], bet["result"] = "won", round(stake * (odds - 1), 2), "gagné"
        else:
            bet["status"], bet["pnl"], bet["result"] = "lost", round(-stake, 2), "perdu"
        bet["settled_at"] = iso(now_utc())
        bet["bankroll_after"] = self.bankroll(bet["strategy"])

    def void(self, bet: dict, reason: str) -> None:
        if bet["status"] != "open":
            return
        bet.update({"status": "void", "pnl": 0.0, "result": "annulé", "settled_at": iso(now_utc()), "note": f"{bet.get('note', '')} | {reason}".strip(" |")})

    # ------------------------------------------------------------ CLV
    def apply_closing(self, bet: dict, closing: dict, source: str) -> None:
        """closing = { book: {"home":..,"away":..,"draw":..,"ts":..} }"""
        ref = self.cfg.get("reference_bookmaker", "pinnacle")
        sel = bet["selection"]
        ref_close = closing.get(ref)
        if ref_close:
            prices = {k: v for k, v in ref_close.items() if k in ("home", "away", "draw", "over", "under")}
            probs = devig(prices)
            if sel in probs:
                bet["closing_ref"] = prices
                bet["clv"] = round(float(bet["odds"]) * probs[sel] - 1.0, 4)
        book_close = closing.get(bet["book"])
        if book_close and book_close.get(sel):
            bet["closing_odds"] = float(book_close[sel])
            bet["clv_book"] = round(float(bet["odds"]) / float(book_close[sel]) - 1.0, 4)
        if bet.get("clv") is not None or bet.get("clv_book") is not None:
            bet["closing_source"] = source
