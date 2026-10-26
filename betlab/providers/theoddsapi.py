"""The Odds API (api.the-odds-api.com v4) — complément : consensus des books FR, scores de secours.

Coût : 1 crédit × marchés × régions par appel de cotes ; scores = 2 crédits (daysFrom) ;
/sports et /events gratuits. 500 crédits/mois en gratuit.
"""
from __future__ import annotations

from ..util import iso, parse_iso
from .base import HttpClient, ProviderError

BASE = "https://api.the-odds-api.com/v4"


class TheOddsApi:
    name = "theoddsapi"

    def __init__(self, cfg, store, budget, log=print):
        self.cfg = cfg
        self.store = store
        self.budget = budget
        self.log = log
        self.key = cfg.key("THEODDSAPI_KEY") or "offline"
        self.http = HttpClient("theoddsapi", offline=cfg.offline, fixtures_dir=cfg.fixtures_dir, log=log)

    def _call(self, path: str, params: dict, *, cost: int, fixture: str, priority: int = 5, what: str = ""):
        if cost > 0 and not self.budget.can_spend("theoddsapi", cost, priority):
            raise ProviderError(f"theoddsapi: budget refusé pour {what or path}")
        p = dict(params)
        p["apiKey"] = self.key
        status, body, headers = self.http.get(f"{BASE}{path}", p, endpoint=path, cooldown=0.5, fixture_name=fixture)
        # les headers donnent le coût réel et le restant
        h = {k.lower(): v for k, v in (headers or {}).items()}
        try:
            last = int(h.get("x-requests-last", cost))
        except (TypeError, ValueError):
            last = cost
        if last > 0 or cost > 0:
            self.budget.spend("theoddsapi", last if last else cost, what or path)
        try:
            rem = h.get("x-requests-remaining")
            used = h.get("x-requests-used")
            self.budget.report_remaining("theoddsapi", int(rem) if rem is not None else None,
                                         int(used) if used is not None else None)
        except (TypeError, ValueError):
            pass
        return body

    def sports(self) -> list[dict]:
        data = self.store.cache_get("theoddsapi_sports", max_age_hours=24 * 7)
        if data is None:
            data = self._call("/sports", {}, cost=0, fixture="sports", what="catalogue sports")
            self.store.cache_set("theoddsapi_sports", data)
        return data or []

    def active_keys(self) -> set[str]:
        return {s["key"] for s in self.sports() if s.get("active")}

    def odds(self, sport_key: str, regions: list[str], markets: list[str] | None = None,
             priority: int = 5) -> list[dict]:
        markets = markets or ["h2h"]
        cost = len(regions) * len(markets)
        params = {"regions": ",".join(regions), "markets": ",".join(markets),
                  "oddsFormat": "decimal", "dateFormat": "iso"}
        return self._call(f"/sports/{sport_key}/odds", params, cost=cost, fixture=f"odds_{sport_key}",
                          priority=priority, what=f"cotes {sport_key}") or []

    def parse_odds(self, events_raw: list[dict], sport_key: str, kind: str, ts: str) -> tuple[list[dict], list[dict]]:
        events, rows = [], []
        for e in events_raw:
            start = parse_iso(e.get("commence_time"))
            if not start or not e.get("id"):
                continue
            ev = {"id": f"toa:{e['id']}", "sport": sport_key, "kind": kind, "home": e.get("home_team"),
                  "away": e.get("away_team"), "start": iso(start), "ids": {"theoddsapi": e["id"]},
                  "status": "scheduled", "names_resolved": True}
            events.append(ev)
            for bk in e.get("bookmakers") or []:
                canon = self.cfg.canonical_book("theoddsapi", bk.get("key", ""))
                if not canon:
                    continue
                for m in bk.get("markets") or []:
                    if m.get("key") != "h2h":
                        continue
                    prices = {}
                    for o in m.get("outcomes") or []:
                        nm, price = o.get("name"), o.get("price")
                        if not price:
                            continue
                        if nm == e.get("home_team"):
                            prices["home"] = float(price)
                        elif nm == e.get("away_team"):
                            prices["away"] = float(price)
                        elif str(nm).lower() == "draw":
                            prices["draw"] = float(price)
                    if len(prices) >= 2:
                        rows.append({"ts": ts, "event_id": ev["id"], "provider": "theoddsapi", "book": canon,
                                     "market": "h2h", "line": None, "prices": prices,
                                     "book_ts": bk.get("last_update")})
        return events, rows

    def scores(self, sport_key: str, days_from: int = 2, priority: int = 4) -> list[dict]:
        body = self._call(f"/sports/{sport_key}/scores", {"daysFrom": days_from, "dateFormat": "iso"},
                          cost=2, fixture=f"scores_{sport_key}", priority=priority, what=f"scores {sport_key}")
        out = []
        for g in body or []:
            start = parse_iso(g.get("commence_time"))
            if not start:
                continue
            hs = as_ = None
            for s in g.get("scores") or []:
                try:
                    val = int(float(s.get("score")))
                except (TypeError, ValueError):
                    continue
                if s.get("name") == g.get("home_team"):
                    hs = val
                elif s.get("name") == g.get("away_team"):
                    as_ = val
            out.append({"source": "theoddsapi", "id": g.get("id"), "start": iso(start), "home": g.get("home_team"),
                        "away": g.get("away_team"), "home_score": hs, "away_score": as_,
                        "completed": bool(g.get("completed"))})
        return out
