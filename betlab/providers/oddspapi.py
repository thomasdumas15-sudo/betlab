"""OddsPapi (api.oddspapi.io v4) — source principale.

Budget : 250 requêtes/mois en gratuit. 1 appel = 1 requête quelle que soit la
réponse. /v4/historical-odds est GRATUIT et non compté (clôtures exactes).
"""
from __future__ import annotations

import re

from ..util import iso, norm_name, now_utc, parse_iso
from .base import HttpClient, ProviderError

BASE = "https://api.oddspapi.io/v4"

_MONEYLINE_TYPES = {"1x2", "moneyline", "money_line", "winner", "h2h", "match_winner", "12", "ml",
                    "matchwinner", "match winner"}
_MONEYLINE_NAMES = re.compile(
    r"^(full ?time result|match result|match winner|money ?line|winner|moneyline.*|"
    r"result|game winner|to win|1x2|home/away|match odds)", re.I)
_PARTIAL_PERIOD = re.compile(r"half|1st|2nd|3rd|4th|quarter|set|period|inning|map|round|overtime_only|first|second", re.I)
_SPREAD_TYPES = {"handicap", "spread", "asian_handicap", "asian handicap", "spreads", "point_spread"}
_TOTAL_TYPES = {"totals", "total", "over_under", "over/under", "ou"}


def _get(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


class OddsPapi:
    name = "oddspapi"

    def __init__(self, cfg, store, budget, log=print):
        self.cfg = cfg
        self.store = store
        self.budget = budget
        self.log = log
        self.key = cfg.key("ODDSPAPI_KEY") or "offline"
        self.http = HttpClient("oddspapi", offline=cfg.offline, fixtures_dir=cfg.fixtures_dir, log=log)
        self._markets_index: dict[int, dict] | None = None

    # ------------------------------------------------------------ bas niveau
    def _call(self, path: str, params: dict, *, billable: bool, cooldown: float,
              fixture: str, priority: int = 5, what: str = ""):
        if billable:
            if not self.budget.can_spend("oddspapi", 1, priority):
                raise ProviderError(f"oddspapi: budget refusé pour {what or path}")
        p = dict(params)
        p["apiKey"] = self.key
        status, body, headers = self.http.get(f"{BASE}{path}", p, endpoint=path, cooldown=cooldown,
                                             fixture_name=fixture)
        if billable:
            self.budget.spend("oddspapi", 1, what or path)
        return body

    # ------------------------------------------------------------ catalogues (cachés)
    def account(self) -> dict | None:
        """Gratuit et jamais bloqué : usage réel du quota."""
        try:
            body = self._call("/account", {}, billable=False, cooldown=1, fixture="account")
        except ProviderError as e:
            self.log(f"  oddspapi account: {e}")
            return None
        if not isinstance(body, dict):
            return None
        sub = body.get("subscription") or body.get("activeSubscription") or body
        limit = _get(sub, "request_limit", "requestLimit")
        count = _get(sub, "request_count", "requestCount")
        if limit is not None and count is not None:
            self.budget.report_remaining("oddspapi", int(limit) - int(count), int(count))
        return {"limit": limit, "count": count}

    def sports(self) -> list[dict]:
        data = self.store.cache_get("oddspapi_sports", max_age_hours=24 * 60)
        if data is None:
            data = self._call("/sports", {}, billable=True, cooldown=1, fixture="sports", priority=1,
                              what="catalogue sports")
            self.store.cache_set("oddspapi_sports", data)
        return data if isinstance(data, list) else []

    def sport_id(self, sport_name: str) -> int | None:
        target = norm_name(sport_name)
        alt = {"soccer": {"football", "soccer"}, "football": {"football", "soccer"},
               "american football": {"american football", "nfl"}, "ice hockey": {"ice hockey", "hockey"}}
        candidates = alt.get(target, {target})
        for s in self.sports():
            sid = _get(s, "sportId", "id")
            nm = norm_name(str(_get(s, "sportName", "name", "slug", "sportSlug", default="")))
            slug = norm_name(str(_get(s, "sportSlug", "slug", default="")))
            if nm in candidates or slug in candidates:
                return int(sid)
        return None

    def bookmakers(self) -> list[dict]:
        data = self.store.cache_get("oddspapi_bookmakers", max_age_hours=24 * 30)
        if data is None:
            data = self._call("/bookmakers", {}, billable=True, cooldown=1, fixture="bookmakers",
                              priority=1, what="catalogue bookmakers")
            self.store.cache_set("oddspapi_bookmakers", data)
        return data if isinstance(data, list) else []

    def resolve_bookmaker_slug(self, canonical: str) -> str | None:
        """Slug configuré s'il existe chez OddsPapi, sinon recherche par nom."""
        wanted = (self.cfg.book_slug(canonical, "oddspapi") or canonical).lower()
        try:
            books = self.bookmakers()
        except ProviderError as e:
            self.log(f"  oddspapi bookmakers: {e}")
            return wanted
        slugs = {}
        for b in books:
            slug = str(_get(b, "bookmakerSlug", "slug", "bookmaker", default="")).lower()
            nm = str(_get(b, "bookmakerName", "name", default="")).lower()
            if slug:
                slugs[slug] = nm
        if not slugs:
            return wanted
        if wanted in slugs:
            return wanted
        base = canonical.lower()
        for slug, nm in slugs.items():
            if base in slug and (".fr" in slug or "fr" in slug.split(".") or base == "pinnacle"):
                return slug
        for slug, nm in slugs.items():
            if base in slug or base in nm:
                return slug
        return None

    def tournaments(self, sport_id: int, max_age_hours: float = 24 * 7) -> list[dict]:
        name = f"oddspapi_tournaments_{sport_id}"
        data = self.store.cache_get(name, max_age_hours=max_age_hours)
        if data is None:
            data = self._call("/tournaments", {"sportId": sport_id}, billable=True, cooldown=1,
                              fixture=f"tournaments_{sport_id}", priority=2, what=f"tournois sport {sport_id}")
            self.store.cache_set(name, data)
        return data if isinstance(data, list) else []

    def resolve_tournaments(self, sport_key: str, spec: dict) -> list[dict]:
        """Trouve le(s) tournoi(s) OddsPapi correspondant à un sport de config.yaml."""
        sid = self.sport_id(spec["sport"])
        if sid is None:
            self.log(f"  oddspapi: sport introuvable pour {sport_key} ({spec['sport']})")
            return []
        is_tennis = norm_name(spec["sport"]) == "tennis"
        tours = self.tournaments(sid, max_age_hours=24 * 3 if is_tennis else 24 * 7)
        match = [norm_name(m) for m in spec.get("match", [])]
        cats = [norm_name(c) for c in spec.get("category", [])]
        excl = [norm_name(x) for x in spec.get("exclude", [])]
        found = []
        for t in tours:
            tid = _get(t, "tournamentId", "id")
            nm = norm_name(str(_get(t, "tournamentName", "name", default="")))
            slug = norm_name(str(_get(t, "tournamentSlug", "slug", default="")))
            cat = norm_name(str(_get(t, "categorySlug", default="")) + " " + str(_get(t, "categoryName", default="")))
            hay = f"{nm} {slug}"
            if not any(m and m in hay for m in match):
                continue
            if cats and not any(c in cat for c in cats):
                continue
            if any(x and x in hay for x in excl):
                continue
            fut = int(_get(t, "futureFixtures", "upcomingFixtures", default=0) or 0)
            found.append({"id": int(tid), "name": _get(t, "tournamentName", "name"), "slug": slug,
                          "category": cat, "future": fut, "sport_id": sid})
        if not found:
            return []
        if spec.get("multi"):
            found = [f for f in found if f["future"] > 0] or found
            found.sort(key=lambda f: -f["future"])
            return found[: int(spec.get("max", 6))]
        # un seul tournoi : le plus "exact" (nom court) avec des matchs à venir
        found.sort(key=lambda f: (0 if f["future"] > 0 else 1, len(f["name"] or "")))
        return [found[0]]

    def markets_index(self) -> dict[int, dict]:
        if self._markets_index is not None:
            return self._markets_index
        data = self.store.cache_get("oddspapi_markets", max_age_hours=24 * 30)
        if data is None:
            data = self._call("/markets", {"language": "en"}, billable=True, cooldown=1,
                              fixture="markets", priority=1, what="catalogue marchés")
            self.store.cache_set("oddspapi_markets", data)
        idx = {}
        for m in data or []:
            try:
                idx[int(m["marketId"])] = m
            except (KeyError, TypeError, ValueError):
                continue
        self._markets_index = idx
        return idx

    def moneyline_market(self, sport_id: int, kind: str, override: int | None = None) -> dict | None:
        """Choisit le marché 'vainqueur du match' pour un sport (2 issues, sauf foot = 3).

        override : marketId forcé dans config.yaml (sports.<x>.oddspapi.market_id) si l'heuristique se trompe.
        """
        idx = self.markets_index()
        if override and int(override) in idx:
            return idx[int(override)]
        want_len = 3 if kind == "soccer" else 2
        best, best_score = None, -1
        for m in idx.values():
            if int(m.get("sportId", -1)) != int(sport_id) or m.get("playerProp"):
                continue
            period = str(m.get("period", "")).lower()
            if _PARTIAL_PERIOD.search(period):
                continue
            try:
                if float(m.get("handicap") or 0) != 0:
                    continue
            except (TypeError, ValueError):
                continue
            mtype = str(m.get("marketType", "")).lower()
            mname = str(m.get("marketName", ""))
            if not (mtype in _MONEYLINE_TYPES or _MONEYLINE_NAMES.match(mname)):
                continue
            if re.search(r"half|1st|2nd|quarter|period|inning|\bset\b|map", mname, re.I) and not re.search(r"match|incl", mname, re.I):
                continue
            score = 0
            if int(m.get("marketLength", 0)) == want_len:
                score += 10
            if kind in ("basketball", "ice_hockey", "american_football") and re.search(r"incl|overtime|ot\b", mname, re.I):
                score += 5
            if kind in ("basketball", "ice_hockey", "american_football") and re.search(r"regul|excl", mname, re.I):
                score -= 5
            if mtype in ("1x2", "moneyline"):
                score += 2
            if score > best_score:
                best, best_score = m, score
        return best

    @staticmethod
    def outcome_sides(market: dict) -> dict[int, str]:
        """outcomeId -> 'home' | 'draw' | 'away' d'après l'ordre/les noms du catalogue."""
        outs = market.get("outcomes") or []
        sides: dict[int, str] = {}
        n = len(outs)
        for i, o in enumerate(outs):
            oid = int(o["outcomeId"])
            nm = str(o.get("outcomeName", "")).strip().lower()
            if nm in ("1", "home", "h", "player 1", "p1"):
                sides[oid] = "home"
            elif nm in ("x", "draw", "d", "tie"):
                sides[oid] = "draw"
            elif nm in ("2", "away", "a", "player 2", "p2"):
                sides[oid] = "away"
            elif i == 0:
                sides[oid] = "home"
            elif i == n - 1:
                sides[oid] = "away"
            else:
                sides[oid] = "draw"
        return sides

    # ------------------------------------------------------------ relevé
    def snapshot(self, tournament_ids: list[int], book_slugs: list[str], priority: int = 5,
                 what: str = "") -> list[dict]:
        if not tournament_ids:
            return []
        params = {"tournamentIds": ",".join(str(t) for t in tournament_ids),
                  "bookmakers": ",".join(book_slugs[:3]), "language": "en", "verbosity": 3}
        fixture = "odds_by_tournaments"
        body = self._call("/odds-by-tournaments", params, billable=True, cooldown=1, fixture=fixture,
                          priority=priority, what=what or "relevé")
        if isinstance(body, dict):
            body = body.get("fixtures") or body.get("data") or [body]
        return body or []

    def parse_snapshot(self, fixtures: list[dict], sport_lookup: dict[int, tuple[str, dict]],
                       ts: str) -> tuple[list[dict], list[dict], set[int]]:
        """-> (événements, lignes de cotes, tournamentIds dont il manque des noms)."""
        events, rows, missing_names = [], [], set()
        names: dict = self.store.cache_get("oddspapi_participants") or {}
        for fx in fixtures:
            try:
                tid = int(fx.get("tournamentId"))
            except (TypeError, ValueError):
                continue
            if tid not in sport_lookup:
                continue
            sport_key, sport_cfg = sport_lookup[tid]
            fid = str(fx.get("fixtureId"))
            start = parse_iso(fx.get("startTime"))
            if not fid or not start:
                continue
            status_id = int(fx.get("statusId") or 0)
            p1, p2 = str(fx.get("participant1Id")), str(fx.get("participant2Id"))
            home = fx.get("participant1Name") or names.get(p1)
            away = fx.get("participant2Name") or names.get(p2)
            if not home or not away:
                missing_names.add(tid)
            sid = int(fx.get("sportId") or sport_cfg.get("_sport_id") or 0)
            mkt = self.moneyline_market(sid, sport_cfg["kind"], (sport_cfg.get("oddspapi") or {}).get("market_id")) if sid else None
            ev = {
                "id": f"op:{fid}", "sport": sport_key, "kind": sport_cfg["kind"],
                "home": home or f"#{p1}", "away": away or f"#{p2}", "start": iso(start),
                "ids": {"oddspapi": fid, "oddspapi_p1": p1, "oddspapi_p2": p2, "oddspapi_tournament": tid},
                "status": {0: "scheduled", 1: "live", 2: "finished", 3: "cancelled"}.get(status_id, "scheduled"),
                "names_resolved": bool(home and away),
            }
            events.append(ev)
            if status_id != 0 or not mkt:
                continue
            sides = self.outcome_sides(mkt)
            ml_id = int(mkt["marketId"])
            for slug, bo in (fx.get("bookmakerOdds") or {}).items():
                canon = self.cfg.canonical_book("oddspapi", slug) or slug
                if bo.get("suspended"):
                    continue
                markets = bo.get("markets") or {}
                # --- moneyline
                m = markets.get(str(ml_id)) or markets.get(ml_id)
                if m and m.get("marketActive", True):
                    prices = {}
                    for oid, o in (m.get("outcomes") or {}).items():
                        side = sides.get(int(oid))
                        pl = (o.get("players") or {}).get("0") or next(iter((o.get("players") or {}).values()), None)
                        if side and pl and pl.get("active", True) and pl.get("price"):
                            prices[side] = float(pl["price"])
                    if len(prices) >= 2:
                        rows.append({"ts": ts, "event_id": ev["id"], "provider": "oddspapi", "book": canon,
                                     "market": "h2h", "line": None, "prices": prices})
                # --- spreads / totals (ligne principale) : stockés pour plus tard
                for mid, mm in markets.items():
                    cat = self.markets_index().get(int(mid)) if str(mid).isdigit() else None
                    if not cat or cat.get("playerProp"):
                        continue
                    mtype = str(cat.get("marketType", "")).lower()
                    mname = str(cat.get("marketName", "")).lower()
                    period = str(cat.get("period", "")).lower()
                    if _PARTIAL_PERIOD.search(period):
                        continue
                    outs = mm.get("outcomes") or {}
                    pls = []
                    for oid, o in outs.items():
                        pl = (o.get("players") or {}).get("0")
                        if pl:
                            pls.append((int(oid), pl))
                    if len(pls) != 2 or not all(p.get("mainLine") for _, p in pls):
                        continue
                    line = cat.get("handicap")
                    if mtype in _SPREAD_TYPES or ("handicap" in mname and "asian" not in mname and "european" not in mname):
                        pls.sort(key=lambda x: x[0])
                        rows.append({"ts": ts, "event_id": ev["id"], "provider": "oddspapi", "book": canon,
                                     "market": "spreads", "line": line,
                                     "prices": {"home": float(pls[0][1]["price"]), "away": float(pls[1][1]["price"])}})
                    elif mtype in _TOTAL_TYPES and ("over" in mname or "total" in mname) and "team" not in mname and "both" not in mname:
                        over = under = None
                        cat_names = {int(x["outcomeId"]): str(x.get("outcomeName", "")) for x in (cat.get("outcomes") or []) if "outcomeId" in x}
                        for oid, pl in pls:
                            onm = (cat_names.get(oid) or str(pl.get("bookmakerOutcomeId", ""))).lower()
                            if "over" in onm:
                                over = float(pl["price"])
                            elif "under" in onm:
                                under = float(pl["price"])
                        if over and under:
                            rows.append({"ts": ts, "event_id": ev["id"], "provider": "oddspapi", "book": canon,
                                         "market": "totals", "line": line, "prices": {"over": over, "under": under}})
        return events, rows, missing_names

    def fetch_names(self, tournament_id: int, priority: int = 3) -> dict[str, str]:
        """1 requête : noms des participants de tous les matchs à venir d'un tournoi."""
        body = self._call("/fixtures", {"tournamentId": tournament_id, "statusId": 0, "language": "en"},
                          billable=True, cooldown=2, fixture=f"fixtures_{tournament_id}",
                          priority=priority, what=f"noms tournoi {tournament_id}")
        names: dict = self.store.cache_get("oddspapi_participants") or {}
        if isinstance(body, dict):
            body = body.get("fixtures") or body.get("data") or [body]
        for fx in body or []:
            for pid_key, nm_key in (("participant1Id", "participant1Name"), ("participant2Id", "participant2Name")):
                pid, nm = fx.get(pid_key), fx.get(nm_key)
                if pid is not None and nm:
                    names[str(pid)] = nm
        self.store.cache_set("oddspapi_participants", names)
        return names

    # ------------------------------------------------------------ clôture (gratuit)
    def closing_lines(self, fixture_id: str, book_slugs: list[str], start, sport_id: int, kind: str,
                      override: int | None = None) -> dict:
        """-> { canonical_book: {"home":x,"away":y,("draw":z), "ts":iso, "open":{...}} }"""
        body = self._call("/historical-odds", {"fixtureId": fixture_id, "bookmakers": ",".join(book_slugs[:3])},
                          billable=False, cooldown=5.2, fixture=f"historical_{fixture_id}", what="clôture")
        mkt = self.moneyline_market(sport_id, kind, override)
        if not body or not mkt:
            return {}
        sides = self.outcome_sides(mkt)
        ml_id = str(mkt["marketId"])
        out = {}
        deadline = start
        for slug, bo in (body.get("bookmakers") or {}).items():
            canon = self.cfg.canonical_book("oddspapi", slug) or slug
            m = (bo.get("markets") or {}).get(ml_id)
            if not m:
                continue
            closing, opening, close_ts = {}, {}, None
            for oid, o in (m.get("outcomes") or {}).items():
                side = sides.get(int(oid))
                if not side:
                    continue
                entries = (o.get("players") or {}).get("0") or []
                entries = [e for e in entries if e.get("price") and parse_iso(e.get("createdAt"))]
                entries.sort(key=lambda e: parse_iso(e["createdAt"]))
                if not entries:
                    continue
                opening[side] = float(entries[0]["price"])
                before = [e for e in entries if parse_iso(e["createdAt"]) <= deadline]
                active_before = [e for e in before if e.get("active", True)]
                pick = (active_before or before or entries)[-1]
                closing[side] = float(pick["price"])
                ts = parse_iso(pick["createdAt"])
                if close_ts is None or ts > close_ts:
                    close_ts = ts
            if len(closing) >= 2:
                out[canon] = {**closing, "ts": iso(close_ts), "open": opening}
        return out

    # ------------------------------------------------------------ règlement (payant, secours)
    def settlement(self, fixture_id: str, sport_id: int, kind: str, override: int | None = None) -> dict | None:
        """-> {"winner": "home|away|draw|push", "status": "settled|cancelled|pending"}"""
        if not self.budget.can_spend("oddspapi", 1, 4):
            return None
        body = self._call("/settlements", {"fixtureId": fixture_id}, billable=True, cooldown=2,
                          fixture=f"settlement_{fixture_id}", priority=4, what="règlement")
        mkt = self.moneyline_market(sport_id, kind, override)
        if not body or not mkt:
            return None
        sides = self.outcome_sides(mkt)
        m = (body.get("markets") or {}).get(str(mkt["marketId"]))
        if not m:
            return {"winner": None, "status": "pending"}
        results = {}
        for oid, o in (m.get("outcomes") or {}).items():
            side = sides.get(int(oid))
            pl = (o.get("players") or {}).get("0") or {}
            if side and pl.get("result"):
                results[side] = str(pl["result"]).upper()
        if not results or "UNDECIDED" in results.values():
            return {"winner": None, "status": "pending"}
        if all(r == "CANCELLED" for r in results.values()):
            return {"winner": None, "status": "cancelled"}
        if all(r == "PUSH" for r in results.values()):
            return {"winner": "push", "status": "settled"}
        for side, r in results.items():
            if r == "WIN":
                return {"winner": side, "status": "settled"}
        return {"winner": None, "status": "pending"}
