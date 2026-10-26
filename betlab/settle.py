"""Règlement automatique des paris : scores ESPN (gratuit) → The Odds API → OddsPapi."""
from __future__ import annotations

from datetime import timedelta

from .matching import match_event
from .providers.base import ProviderError
from .util import iso, name_similarity, now_utc, parse_iso

_PROP_PARTS = {"points": ["points"], "rebounds": ["rebounds"], "assists": ["assists"], "threes": ["threes"],
               "pts_reb": ["points", "rebounds"], "pts_ast": ["points", "assists"],
               "pts_reb_ast": ["points", "rebounds", "assists"], "reb_ast": ["rebounds", "assists"]}


def _is_prop(bet: dict) -> bool:
    return str(bet.get("market", "")).startswith("prop:")


def _prop_value(stats: dict, stat: str | None) -> int | None:
    parts = [stats.get(k) for k in _PROP_PARTS.get(stat or "", [])]
    if not parts or any(v is None for v in parts):
        return None
    return sum(parts)


def _find_player(box: dict, name: str | None) -> str | None:
    if not name:
        return None
    best, score = None, 0.0
    for n in box:
        s = name_similarity(n, name)
        if s > score:
            best, score = n, s
    return best if score >= 0.8 else None


def winner_from_scores(kind: str, hs: int | None, as_: int | None) -> str | None:
    if hs is None or as_ is None:
        return None
    if hs > as_:
        return "home"
    if as_ > hs:
        return "away"
    return "draw" if kind == "soccer" else "push"


class Settler:
    def __init__(self, cfg, store, ledger, espn, theoddsapi, oddspapi, log=print):
        self.cfg = cfg
        self.store = store
        self.ledger = ledger
        self.espn = espn
        self.toa = theoddsapi
        self.op = oddspapi
        self.log = log

    def pending(self) -> list[dict]:
        now = now_utc()
        open_events = {b["event_id"] for b in self.store.bets if b["status"] == "open"}
        out = []
        for eid in open_events:
            ev = self.store.events.get(eid)
            if not ev:
                continue
            if ev.get("result"):
                out.append(ev)
                continue
            st = parse_iso(ev.get("start"))
            dur = int(self.cfg.sports.get(ev.get("sport"), {}).get("duration_min", 150))
            if st and st + timedelta(minutes=dur) <= now:
                out.append(ev)
        return out

    def run(self) -> int:
        events = self.pending()
        if not events:
            return 0
        settled = 0
        void_after = timedelta(days=float(self.cfg.get("betting", {}).get("void_after_days", 5)))
        fallback_cap = int(self.cfg.get("limits", {}).get("settlement_fallback_per_run", 3))
        fallback_used = 0
        toa_cache: dict[str, list[dict]] = {}

        for ev in events:
            result = ev.get("result")
            if not result:
                result = self._espn(ev)
            if not result and self.toa is not None:
                result = self._theoddsapi(ev, toa_cache)
            if not result and self.op is not None and fallback_used < fallback_cap and (ev.get("ids") or {}).get("oddspapi"):
                fallback_used += 1
                result = self._oddspapi(ev)
            if result:
                ev["result"] = result
                ev["status"] = "cancelled" if result.get("status") == "cancelled" else "finished"
                for b in self.store.bets:
                    if b["event_id"] == ev["id"] and b["status"] == "open" and not _is_prop(b):
                        self.ledger.settle(b, result.get("winner"), result.get("status", "settled"))
                        settled += 1
                        self.log(f"  = {b['strategy']}: {b['match']} → {b['result']} ({b['pnl']:+.2f} €)")
                settled += self._settle_props(ev, result)
            st = parse_iso(ev.get("start"))
            if result and not any(b["event_id"] == ev["id"] and b["status"] == "open" for b in self.store.bets):
                continue
            if st and now_utc() - st > void_after:
                for b in self.store.bets:
                    if b["event_id"] == ev["id"] and b["status"] == "open":
                        self.ledger.void(b, "aucun résultat trouvé")
                        settled += 1
                if not result:
                    ev["status"] = "unknown"
        return settled

    # ------------------------------------------------------------ stats joueurs
    def _settle_props(self, ev: dict, result: dict) -> int:
        bets = [b for b in self.store.bets if b["event_id"] == ev["id"] and b["status"] == "open" and _is_prop(b)]
        if not bets:
            return 0
        if result.get("status") == "cancelled":
            for b in bets:
                self.ledger.settle(b, None, "cancelled")
            return len(bets)
        path = self.cfg.sports.get(ev.get("sport"), {}).get("espn")
        if not path or self.espn is None:
            return 0
        gid = result.get("espn_id")
        if not gid:
            g = self._espn_game(ev)
            gid = g["id"] if g else None
        box = self.espn.boxscore(path, gid) if gid else None
        if not box:
            return 0
        n = 0
        for b in bets:
            player = _find_player(box, b.get("player"))
            stats = box.get(player) if player else None
            if stats is None or not stats.get("played"):
                self.ledger.void(b, "joueur absent de la feuille de match")
                n += 1
                continue
            value = _prop_value(stats, b.get("stat"))
            if value is None:
                continue
            line = float(b["line"])
            winner = "push" if value == line else ("over" if value > line else "under")
            self.ledger.settle(b, winner)
            b["result_value"] = value
            n += 1
            self.log(f"  = {b['strategy']}: {b['selection_name']} → {value} ({b['pnl']:+.2f} €)")
        return n

    # ------------------------------------------------------------ sources
    def _espn_game(self, ev: dict) -> dict | None:
        """Match ESPN correspondant (avec "_swapped" si domicile/extérieur sont inversés)."""
        path = self.cfg.sports.get(ev.get("sport"), {}).get("espn")
        if not path or self.espn is None:
            return None
        st = parse_iso(ev["start"])
        dates = sorted({(st - timedelta(hours=h)).strftime("%Y%m%d") for h in (0, 8)} | {st.strftime("%Y%m%d")})
        games = []
        for d in dates:
            games.extend(self.espn.scoreboard(path, d))
        if not games:
            return None
        cands = [{"home": g["home"], "away": g["away"], "start": g["start"], "_g": g} for g in games]
        m, swapped = match_event(cands, ev["home"], ev["away"], ev["start"], tolerance_hours=4)
        if not m:
            return None
        return {**m["_g"], "_swapped": swapped}

    def _espn(self, ev: dict) -> dict | None:
        g = self._espn_game(ev)
        if not g or not g.get("completed"):
            return None
        swapped = g["_swapped"]
        hs, as_ = g["home_score"], g["away_score"]
        if swapped:
            hs, as_ = as_, hs
        w = winner_from_scores(ev.get("kind", ""), hs, as_)
        if w is None:
            return None
        return {"winner": w, "status": "settled", "home_score": hs, "away_score": as_, "source": "espn",
                "espn_id": g.get("id"), "at": iso(now_utc())}

    def _theoddsapi(self, ev: dict, cache: dict) -> dict | None:
        spec = self.cfg.sports.get(ev.get("sport"), {}).get("theoddsapi") or {}
        key = spec.get("key")
        if not key:
            return None
        if key not in cache:
            try:
                if key not in self.toa.active_keys():
                    cache[key] = []
                else:
                    cache[key] = self.toa.scores(key, days_from=2)
            except ProviderError as e:
                self.log(f"  scores theoddsapi {key}: {e}")
                cache[key] = []
        games = cache[key]
        toa_id = (ev.get("ids") or {}).get("theoddsapi")
        g = next((x for x in games if toa_id and x["id"] == toa_id), None)
        swapped = False
        if g is None:
            m, swapped = match_event(games, ev["home"], ev["away"], ev["start"], tolerance_hours=4)
            g = m
        if not g or not g.get("completed"):
            return None
        hs, as_ = g["home_score"], g["away_score"]
        if swapped:
            hs, as_ = as_, hs
        w = winner_from_scores(ev.get("kind", ""), hs, as_)
        if w is None:
            return None
        return {"winner": w, "status": "settled", "home_score": hs, "away_score": as_, "source": "theoddsapi", "at": iso(now_utc())}

    def _oddspapi(self, ev: dict) -> dict | None:
        try:
            override = (self.cfg.sports.get(ev.get("sport"), {}).get("oddspapi") or {}).get("market_id")
            r = self.op.settlement(ev["ids"]["oddspapi"], int(ev["ids"].get("oddspapi_sport_id") or 0), ev.get("kind", ""), override)
        except ProviderError as e:
            self.log(f"  settlement oddspapi {ev['id']}: {e}")
            return None
        if not r or r.get("status") == "pending":
            return None
        return {**r, "source": "oddspapi", "at": iso(now_utc())}
