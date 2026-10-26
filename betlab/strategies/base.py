"""Socle des stratégies : accès aux cotes, probabilité juste, mise."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..util import devig, kelly_stake, parse_iso


@dataclass
class Context:
    now: datetime
    event: dict
    quotes: dict                      # book -> market -> {"ts", "prices", "line"}
    bet_book: str
    ref_book: str
    bankroll: float
    available: float
    opening: dict | None              # première cote vue du book de référence (h2h)
    settings: dict                    # section betting de config.yaml
    rng_seed: int = 0
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ cotes jouables
    def bet_quote(self) -> dict | None:
        q = (self.quotes.get(self.bet_book) or {}).get("h2h")
        if not q:
            return None
        ts = parse_iso(q["ts"])
        if not ts or self.now - ts > timedelta(hours=float(self.settings.get("max_quote_age_hours", 14))):
            return None
        return q

    def ref_quote(self, bet_q: dict | None = None) -> dict | None:
        q = (self.quotes.get(self.ref_book) or {}).get("h2h")
        if not q:
            return None
        ts = parse_iso(q["ts"])
        if not ts or self.now - ts > timedelta(hours=float(self.settings.get("max_quote_age_hours", 14))):
            return None
        if bet_q:
            bts = parse_iso(bet_q["ts"])
            if bts and abs((bts - ts).total_seconds()) > 60 * float(self.settings.get("max_ref_gap_minutes", 180)):
                return None
        return q

    def fresh(self, q: dict | None, other: dict | None = None) -> bool:
        """Cote assez récente (et, si `other` est donné, relevée à moins de max_ref_gap_minutes de lui)."""
        if not q:
            return False
        ts = parse_iso(q["ts"])
        if not ts or self.now - ts > timedelta(hours=float(self.settings.get("max_quote_age_hours", 14))):
            return False
        if other:
            ots = parse_iso(other["ts"])
            if ots and abs((ots - ts).total_seconds()) > 60 * float(self.settings.get("max_ref_gap_minutes", 180)):
                return False
        return True

    def ref_probs(self, bet_q: dict | None = None) -> dict[str, float]:
        q = self.ref_quote(bet_q)
        return devig(q["prices"]) if q else {}

    def consensus_probs(self, min_books: int = 3, bet_q: dict | None = None) -> tuple[dict[str, float], int]:
        """Moyenne des probabilités dé-margées de tous les books disposant d'une cote fraîche."""
        acc: dict[str, list[float]] = {}
        n = 0
        max_age = timedelta(hours=float(self.settings.get("max_quote_age_hours", 14)))
        for book, mk in self.quotes.items():
            q = mk.get("h2h")
            if not q:
                continue
            ts = parse_iso(q["ts"])
            if not ts or self.now - ts > max_age:
                continue
            probs = devig(q["prices"])
            if not probs:
                continue
            n += 1
            for side, p in probs.items():
                acc.setdefault(side, []).append(p)
        if n < min_books:
            return {}, n
        probs = {s: sum(v) / len(v) for s, v in acc.items()}
        tot = sum(probs.values())
        return ({s: p / tot for s, p in probs.items()} if tot else {}), n


@dataclass
class Candidate:
    selection: str          # home | away | draw | over | under
    odds: float
    fair_prob: float
    edge: float
    stake: float
    note: str = ""
    market: str = "h2h"     # ou "prop:<stat>:<joueur>:<ligne>"
    label: str = ""         # libellé lisible de la sélection (stats joueurs)


class Strategy:
    key = "base"
    max_per_event = 1       # paris max par match ; > 1 seulement pour les marchés joueurs

    def __init__(self, key: str, params: dict):
        self.key = key
        self.params = params
        self.label = params.get("label", key)
        self.sports = set(params.get("sports") or [])

    def applies_to(self, event: dict) -> bool:
        return not self.sports or event.get("sport") in self.sports

    # ---- helpers
    def value_candidates(self, ctx: Context, probs: dict[str, float], bet_q: dict, min_edge: float,
                         min_odds: float, max_odds: float) -> list[Candidate]:
        out = []
        for side, p in probs.items():
            odds = bet_q["prices"].get(side)
            if not odds or odds < min_odds or odds > max_odds:
                continue
            edge = p * odds - 1.0
            if edge >= min_edge:
                out.append(Candidate(side, float(odds), float(p), float(edge), 0.0))
        out.sort(key=lambda c: -c.edge)
        return out[:1]   # au plus un pari par match et par stratégie

    def kelly(self, ctx: Context, c: Candidate) -> float:
        return kelly_stake(ctx.bankroll, c.fair_prob, c.odds, float(self.params.get("kelly_fraction", 0.25)),
                           float(self.params.get("max_stake_pct", 0.02)), float(self.params.get("min_stake_pct", 0.0025)))

    def flat(self, ctx: Context) -> float:
        return round(ctx.bankroll * float(self.params.get("flat_stake_pct", 0.01)), 2)

    def candidates(self, ctx: Context) -> list[Candidate]:
        raise NotImplementedError
