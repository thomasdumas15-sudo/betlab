"""Persistance : JSON (événements, paris, état) et JSONL (relevés de cotes)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .util import now_utc, parse_iso


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
    tmp.replace(path)


class Store:
    """Toutes les données vivent dans data/ (commité par GitHub Actions)."""

    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "odds").mkdir(exist_ok=True)
        (self.dir / "cache").mkdir(exist_ok=True)
        self.events: dict[str, dict] = _read_json(self.dir / "events.json", {})
        self.bets: list[dict] = _read_json(self.dir / "bets.json", [])
        self.state: dict = _read_json(self.dir / "state.json", {})
        self._odds_buffer: list[dict] = []

    # ------------------------------------------------------------ save
    def save(self) -> None:
        self.state["last_saved"] = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_json(self.dir / "events.json", self.events)
        _write_json(self.dir / "bets.json", self.bets)
        _write_json(self.dir / "state.json", self.state)
        self.flush_odds()

    # ------------------------------------------------------------ cache
    def cache_get(self, name: str, max_age_hours: float | None = None):
        obj = _read_json(self.dir / "cache" / f"{name}.json", None)
        if obj is None:
            return None
        if max_age_hours is not None:
            fetched = parse_iso(obj.get("fetched_at"))
            if not fetched or now_utc() - fetched > timedelta(hours=max_age_hours):
                return None
        return obj.get("data")

    def cache_set(self, name: str, data) -> None:
        _write_json(self.dir / "cache" / f"{name}.json",
                    {"fetched_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data})

    # ------------------------------------------------------------ odds
    def add_odds(self, row: dict) -> None:
        self._odds_buffer.append(row)

    def flush_odds(self) -> None:
        if not self._odds_buffer:
            return
        by_day: dict[str, list[dict]] = {}
        for r in self._odds_buffer:
            by_day.setdefault(r["ts"][:10], []).append(r)
        for day, rows in by_day.items():
            p = self.dir / "odds" / f"{day}.jsonl"
            with open(p, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self._odds_buffer = []

    def iter_odds(self, days_back: int = 3):
        """Lignes de cotes des N derniers jours (fichiers) + le buffer courant."""
        today = now_utc().date()
        for i in range(days_back, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            p = self.dir / "odds" / f"{d}.jsonl"
            if not p.exists():
                continue
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
        for r in self._odds_buffer:
            yield r

    def latest_quotes(self, days_back: int = 3) -> dict[str, dict]:
        """event_id -> { book -> { market_key -> {"ts":..., "prices":{...}, "line":...} } }
        market_key = "h2h" | "spreads" | "totals" (ligne principale) | "prop:<stat>:<joueur>:<ligne>".
        """
        out: dict[str, dict] = {}
        for r in self.iter_odds(days_back):
            ev = out.setdefault(r["event_id"], {})
            bk = ev.setdefault(r["book"], {})
            prev = bk.get(r["market"])
            if prev is None or r["ts"] >= prev["ts"]:
                bk[r["market"]] = {"ts": r["ts"], "prices": r["prices"], "line": r.get("line"),
                                   "provider": r.get("provider")}
                if r.get("player"):
                    bk[r["market"]].update(player=r["player"], stat=r.get("stat"))
        return out

    def first_quotes(self, event_ids: set[str], book: str, days_back: int = 10) -> dict[str, dict]:
        """Première cote vue (ouverture) pour chaque event_id, pour un book donné, marché h2h."""
        out: dict[str, dict] = {}
        for r in self.iter_odds(days_back):
            if r["event_id"] in event_ids and r["book"] == book and r["market"] == "h2h":
                prev = out.get(r["event_id"])
                if prev is None or r["ts"] < prev["ts"]:
                    out[r["event_id"]] = {"ts": r["ts"], "prices": r["prices"]}
        return out

    def last_quote_before(self, event_id: str, book: str, before: datetime, days_back: int = 10,
                          market: str = "h2h") -> dict | None:
        best = None
        for r in self.iter_odds(days_back):
            if r["event_id"] != event_id or r["book"] != book or r["market"] != market:
                continue
            ts = parse_iso(r["ts"])
            if ts and ts <= before and (best is None or r["ts"] > best["ts"]):
                best = {"ts": r["ts"], "prices": r["prices"]}
        return best

    # ------------------------------------------------------------ events
    def upsert_event(self, ev: dict) -> dict:
        cur = self.events.get(ev["id"])
        if cur is None:
            self.events[ev["id"]] = ev
            return ev
        # ne jamais écraser un résultat / une clôture déjà enregistrés
        for k, v in ev.items():
            if k in ("result", "closing") and cur.get(k):
                continue
            if k == "status" and cur.get("status") not in (None, "scheduled", "live"):
                continue
            if k == "ids":
                cur.setdefault("ids", {}).update(v or {})
                continue
            if v is not None:
                cur[k] = v
        return cur

    def prune_events(self, keep_days: int = 45) -> int:
        cutoff = now_utc() - timedelta(days=keep_days)
        with_bets = {b["event_id"] for b in self.bets}
        dead = []
        for eid, ev in self.events.items():
            st = parse_iso(ev.get("start"))
            if st and st < cutoff and eid not in with_bets:
                dead.append(eid)
        for eid in dead:
            del self.events[eid]
        return len(dead)
