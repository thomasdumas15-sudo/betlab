"""Collecte des cotes selon les créneaux de config.yaml, dans la limite des budgets."""
from __future__ import annotations

from .matching import match_event
from .providers.base import ProviderError, QuotaExhausted
from .util import in_window, iso, now_utc


class Collector:
    def __init__(self, cfg, store, budget, oddspapi, theoddsapi, log=print):
        self.cfg = cfg
        self.store = store
        self.budget = budget
        self.op = oddspapi
        self.toa = theoddsapi
        self.log = log

    # ------------------------------------------------------------ créneaux
    def due_slots(self, now_local) -> list[dict]:
        done = self.store.state.setdefault("slots", {})
        today = now_local.date().isoformat()
        out = []
        for slot in self.cfg.get("slots", []):
            key = f"{slot['group']}:{slot['name']}"
            if done.get(key) == today:
                continue
            if in_window(now_local, slot["window"]):
                out.append(slot)
        return out

    def mark_done(self, slot: dict, now_local) -> None:
        self.store.state.setdefault("slots", {})[f"{slot['group']}:{slot['name']}"] = now_local.date().isoformat()

    def run(self, now_local, force_group: str | None = None) -> dict:
        summary = {"slots": [], "events": 0, "rows": 0}
        slots = self.due_slots(now_local)
        if force_group:
            slots = [{"group": force_group, "name": "manuel", "window": "00:00-23:59", "priority": 1}]
        for slot in slots:
            self.log(f"• créneau {slot['group']}/{slot['name']} (priorité {slot['priority']})")
            try:
                n_ev, n_rows, ok = self.collect_group(slot["group"], int(slot.get("priority", 5)))
            except QuotaExhausted as e:
                self.log(f"  quota épuisé : {e}")
                n_ev, n_rows, ok = 0, 0, False
            summary["events"] += n_ev
            summary["rows"] += n_rows
            summary["slots"].append({"slot": f"{slot['group']}:{slot['name']}", "events": n_ev, "rows": n_rows, "ok": ok})
            if ok and not force_group:
                self.mark_done(slot, now_local)
        return summary

    # ------------------------------------------------------------ groupe
    def collect_group(self, group: str, priority: int) -> tuple[int, int, bool]:
        sports = {k: v for k, v in self.cfg.sports.items() if v.get("group") == group}
        ts = iso(now_utc())
        n_ev = n_rows = 0
        ok = False

        # ---------- OddsPapi : 1 requête pour tout le groupe
        if self.op is not None and any("oddspapi" in v for v in sports.values()):
            try:
                ev, rows = self._collect_oddspapi(sports, ts, priority)
                n_ev += ev
                n_rows += rows
                ok = True      # la requête a abouti (même sans match ce jour-là) : le créneau est consommé
            except ProviderError as e:
                self.log(f"  oddspapi: {e}")

        # ---------- The Odds API : consensus FR (sports configurés avec regions)
        if self.toa is not None:
            for key, sc in sports.items():
                spec = sc.get("theoddsapi") or {}
                if not spec.get("key") or spec.get("scores_only") or not spec.get("regions"):
                    continue
                try:
                    ev, rows = self._collect_theoddsapi(key, sc, spec, ts, priority)
                    n_ev += ev
                    n_rows += rows
                    ok = True
                except ProviderError as e:
                    self.log(f"  theoddsapi {key}: {e}")
        return n_ev, n_rows, ok

    def _oddspapi_slugs(self) -> list[str]:
        st = self.store.state
        cached = st.get("oddspapi_slugs")
        if cached and cached.get("month") == now_utc().strftime("%Y-%m"):
            return cached["slugs"]
        slugs = []
        for canon in self.cfg.get("oddspapi_bookmakers", []):
            s = self.op.resolve_bookmaker_slug(canon)
            if s:
                slugs.append(s)
            else:
                self.log(f"  oddspapi: bookmaker '{canon}' introuvable dans le catalogue")
        if not slugs:
            slugs = [self.cfg.book_slug(c, "oddspapi") for c in self.cfg.get("oddspapi_bookmakers", [])]
        st["oddspapi_slugs"] = {"month": now_utc().strftime("%Y-%m"), "slugs": slugs[:3]}
        return slugs[:3]

    def _collect_oddspapi(self, sports: dict, ts: str, priority: int) -> tuple[int, int]:
        lookup: dict[int, tuple[str, dict]] = {}
        resolved = self.store.state.setdefault("oddspapi_tournaments", {})
        for key, sc in sports.items():
            spec = sc.get("oddspapi")
            if not spec:
                continue
            try:
                tours = self.op.resolve_tournaments(key, spec)
            except ProviderError as e:
                self.log(f"  oddspapi tournois {key}: {e}")
                continue
            if not tours:
                self.log(f"  oddspapi: aucun tournoi trouvé pour {key}")
                continue
            resolved[key] = [{"id": t["id"], "name": t["name"], "future": t["future"]} for t in tours]
            for t in tours:
                cfg_copy = dict(sc)
                cfg_copy["_sport_id"] = t["sport_id"]
                lookup[t["id"]] = (key, cfg_copy)
        if not lookup:
            return 0, 0
        slugs = self._oddspapi_slugs()
        fixtures = self.op.snapshot(sorted(lookup), slugs, priority=priority,
                                   what=f"relevé {', '.join(sorted(sports))}")
        events, rows, missing = self.op.parse_snapshot(fixtures, lookup, ts)

        # noms manquants : 1 requête par tournoi (plafonné), puis ré-application
        for tid in sorted(missing)[:2]:
            try:
                self.op.fetch_names(tid, priority=min(priority, 3))
            except ProviderError as e:
                self.log(f"  oddspapi noms {tid}: {e}")
        names = self.store.cache_get("oddspapi_participants") or {}
        for ev in events:
            if not ev.get("names_resolved"):
                h = names.get(ev["ids"].get("oddspapi_p1"))
                a = names.get(ev["ids"].get("oddspapi_p2"))
                if h and a:
                    ev["home"], ev["away"], ev["names_resolved"] = h, a, True

        for ev in events:
            ev["ids"]["oddspapi_sport_id"] = lookup[ev["ids"]["oddspapi_tournament"]][1]["_sport_id"]
            self.store.upsert_event(ev)
        for r in rows:
            self.store.add_odds(r)
        self.log(f"  oddspapi: {len(events)} matchs, {len(rows)} cotes ({', '.join(slugs)})")
        return len(events), len(rows)

    def _collect_theoddsapi(self, sport_key: str, sc: dict, spec: dict, ts: str, priority: int) -> tuple[int, int]:
        if spec["key"] not in self.toa.active_keys():
            self.log(f"  theoddsapi: {spec['key']} inactif (hors saison ?)")
            return 0, 0
        raw = self.toa.odds(spec["key"], spec["regions"], ["h2h"], priority=priority)
        events, rows = self.toa.parse_odds(raw, sport_key, sc["kind"], ts)
        same_sport = [e for e in self.store.events.values() if e.get("sport") == sport_key]
        remap = {}
        for ev in events:
            match, swapped = match_event(same_sport, ev["home"], ev["away"], ev["start"], tolerance_hours=3, min_score=0.7)
            if match is not None and not swapped:
                match.setdefault("ids", {})["theoddsapi"] = ev["ids"]["theoddsapi"]
                remap[ev["id"]] = match["id"]
            else:
                self.store.upsert_event(ev)
        for r in rows:
            r["event_id"] = remap.get(r["event_id"], r["event_id"])
            self.store.add_odds(r)
        self.log(f"  theoddsapi {spec['key']}: {len(events)} matchs ({len(remap)} rattachés), {len(rows)} cotes")
        return len(events) - len(remap), len(rows)
