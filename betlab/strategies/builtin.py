"""Les six stratégies livrées. Chacune est volontairement simple et lisible :
la performance vient des données (Pinnacle vs Winamax) et de la discipline, pas de la complexité.
"""
from __future__ import annotations

from ..util import devig, stable_hash
from .base import Candidate, Context, Strategy


class ValueSharp(Strategy):
    """Valeur vs Pinnacle : la référence la plus solide d'un marché efficient."""

    def candidates(self, ctx: Context) -> list[Candidate]:
        bet_q = ctx.bet_quote()
        if not bet_q:
            return []
        probs = ctx.ref_probs(bet_q)
        if not probs:
            return []
        out = self.value_candidates(ctx, probs, bet_q, self.params["min_edge"], self.params["min_odds"], self.params["max_odds"])
        for c in out:
            c.stake = self.kelly(ctx, c)
            c.note = f"Pinnacle p={c.fair_prob:.3f}"
        return [c for c in out if c.stake > 0]


class ValueConsensus(Strategy):
    """Valeur vs consensus dé-margé de tous les books (FR + Pinnacle) — la logique de Midas."""

    def candidates(self, ctx: Context) -> list[Candidate]:
        bet_q = ctx.bet_quote()
        if not bet_q:
            return []
        probs, n = ctx.consensus_probs(int(self.params.get("min_books", 3)), bet_q)
        if not probs:
            return []
        out = self.value_candidates(ctx, probs, bet_q, self.params["min_edge"], self.params["min_odds"], self.params["max_odds"])
        for c in out:
            c.stake = self.kelly(ctx, c)
            c.note = f"consensus {n} books p={c.fair_prob:.3f}"
        return [c for c in out if c.stake > 0]


class Favorites(Strategy):
    """Favoris prudents : le favori net, mise fixe. Témoin du parieur « raisonnable »."""

    def candidates(self, ctx: Context) -> list[Candidate]:
        bet_q = ctx.bet_quote()
        if not bet_q:
            return []
        probs = ctx.ref_probs(bet_q)
        if not probs:
            probs, _ = ctx.consensus_probs(2, bet_q)
        if not probs:
            return []
        side, p = max(probs.items(), key=lambda kv: kv[1])
        if p < float(self.params["min_prob"]):
            return []
        odds = bet_q["prices"].get(side)
        if not odds or odds < self.params["min_odds"] or odds > self.params["max_odds"]:
            return []
        c = Candidate(side, float(odds), float(p), float(p * odds - 1), self.flat(ctx), f"favori p={p:.3f}")
        return [c] if c.stake > 0 else []


class Basket(Strategy):
    """Spécialiste basket : Valeur Pinnacle avec seuil plus bas et Kelly à 20 %."""

    def candidates(self, ctx: Context) -> list[Candidate]:
        if not self.applies_to(ctx.event):
            return []
        bet_q = ctx.bet_quote()
        if not bet_q:
            return []
        probs = ctx.ref_probs(bet_q)
        if not probs:
            return []
        out = self.value_candidates(ctx, probs, bet_q, self.params["min_edge"], self.params["min_odds"], self.params["max_odds"])
        for c in out:
            c.stake = self.kelly(ctx, c)
            c.note = f"basket Pinnacle p={c.fair_prob:.3f}"
        return [c for c in out if c.stake > 0]


class Steam(Strategy):
    """Mouvement sharp : Pinnacle a bougé vers un camp depuis l'ouverture, Winamax traîne."""

    def candidates(self, ctx: Context) -> list[Candidate]:
        bet_q = ctx.bet_quote()
        if not bet_q or not ctx.opening:
            return []
        now_probs = ctx.ref_probs(bet_q)
        open_probs = devig(ctx.opening.get("prices") or {})
        if not now_probs or not open_probs:
            return []
        best = None
        for side, p_now in now_probs.items():
            move = p_now - open_probs.get(side, p_now)
            if move < float(self.params["min_move"]):
                continue
            odds = bet_q["prices"].get(side)
            if not odds or odds < self.params["min_odds"] or odds > self.params["max_odds"]:
                continue
            edge = p_now * odds - 1
            if edge < float(self.params["min_edge"]):
                continue
            if best is None or move > best[0]:
                best = (move, Candidate(side, float(odds), float(p_now), float(edge), 0.0,
                                        f"mouvement {move * 100:+.1f} pts depuis l'ouverture"))
        if best is None:
            return []
        c = best[1]
        c.stake = self.kelly(ctx, c)
        return [c] if c.stake > 0 else []


class Control(Strategy):
    """Témoin : hasard reproductible (graine fixe). Il DOIT être battu."""

    def candidates(self, ctx: Context) -> list[Candidate]:
        bet_q = ctx.bet_quote()
        if not bet_q:
            return []
        seed = int(self.params.get("seed", 1))
        h = stable_hash(seed, ctx.event["id"])
        if h % int(self.params.get("one_in", 3)) != 0:
            return []
        sides = sorted(s for s, o in bet_q["prices"].items() if o and o > 1.0)
        if not sides:
            return []
        side = sides[(h // 7) % len(sides)]
        odds = float(bet_q["prices"][side])
        probs = ctx.ref_probs(bet_q)
        p = float(probs.get(side, 1 / odds))
        c = Candidate(side, odds, p, p * odds - 1, self.flat(ctx), "tirage au sort")
        return [c] if c.stake > 0 else []


REGISTRY = {
    "value_sharp": ValueSharp,
    "value_consensus": ValueConsensus,
    "favorites": Favorites,
    "basket": Basket,
    "steam": Steam,
    "control": Control,
}


def build_strategies(cfg) -> list[Strategy]:
    out = []
    for key, params in cfg.strategies.items():
        cls = REGISTRY.get(key)
        if cls is None:
            continue
        out.append(cls(key, params))
    return out
