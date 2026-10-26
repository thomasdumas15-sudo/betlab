"""Cotes de clôture et CLV (Closing Line Value) — la métrique n°1 du labo.

Source exacte : OddsPapi /historical-odds (gratuit). Secours : dernier relevé avant le coup d'envoi.
"""
from __future__ import annotations

from .providers.base import ProviderError
from .util import iso, now_utc, parse_iso


class Closing:
    def __init__(self, cfg, store, ledger, oddspapi, log=print):
        self.cfg = cfg
        self.store = store
        self.ledger = ledger
        self.op = oddspapi
        self.log = log

    def pending_events(self) -> list[dict]:
        now = now_utc()
        need = {b["event_id"] for b in self.store.bets if b.get("clv") is None and b.get("closing_source") != "none"}
        out = []
        for eid in need:
            ev = self.store.events.get(eid)
            if not ev or ev.get("closing_fetched"):
                continue
            st = parse_iso(ev.get("start"))
            if st and st <= now:
                out.append(ev)
        out.sort(key=lambda e: e.get("start") or "")
        return out

    def run(self) -> int:
        cap = int(self.cfg.get("limits", {}).get("closing_fetch_per_run", 12))
        done = 0
        for ev in self.pending_events():
            if done >= cap:
                break
            closing, source = {}, "snapshot"
            fid = (ev.get("ids") or {}).get("oddspapi")
            if self.op is not None and fid:
                slugs = (self.store.state.get("oddspapi_slugs") or {}).get("slugs") or []
                try:
                    override = (self.cfg.sports.get(ev.get("sport"), {}).get("oddspapi") or {}).get("market_id")
                    closing = self.op.closing_lines(fid, slugs, parse_iso(ev["start"]),
                                                    int(ev["ids"].get("oddspapi_sport_id") or 0), ev.get("kind", ""), override)
                    source = "oddspapi_history"
                except ProviderError as e:
                    self.log(f"  clôture {ev['id']}: {e}")
                done += 1
            if not closing:
                closing = self._from_snapshots(ev)
                source = "snapshot"
            if closing:
                ev["closing"] = closing
                ev["closing_source"] = source
                for b in self.store.bets:
                    if b["event_id"] == ev["id"] and b.get("clv") is None:
                        self.ledger.apply_closing(b, closing, source)
            ev["closing_fetched"] = iso(now_utc())
        return done

    def _from_snapshots(self, ev: dict) -> dict:
        start = parse_iso(ev.get("start"))
        out = {}
        for book in {self.cfg.get("reference_bookmaker", "pinnacle"), self.cfg.get("bet_bookmaker", "winamax")}:
            q = self.store.last_quote_before(ev["id"], book, start)
            if q:
                out[book] = {**q["prices"], "ts": q["ts"]}
        return out
