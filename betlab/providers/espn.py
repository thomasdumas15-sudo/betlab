"""ESPN scoreboard (non officiel, gratuit, sans clé) — scores NBA, NFL, NHL, grands championnats de foot.

Si ESPN change son format, le règlement bascule sur les sources de secours (The Odds API,
OddsPapi settlements) : rien ne casse, ça coûte juste quelques crédits.
"""
from __future__ import annotations

from ..util import iso, parse_iso
from .base import HttpClient, ProviderError

BASE = "https://site.api.espn.com/apis/site/v2/sports"


class Espn:
    name = "espn"

    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.http = HttpClient("espn", offline=cfg.offline, fixtures_dir=cfg.fixtures_dir, log=log, timeout=30)
        self._cache: dict[tuple[str, str], list[dict]] = {}

    def scoreboard(self, path: str, yyyymmdd: str) -> list[dict]:
        key = (path, yyyymmdd)
        if key in self._cache:
            return self._cache[key]
        params = {"dates": yyyymmdd}
        if path.startswith("soccer/"):
            params["limit"] = 100
        try:
            _, body, _ = self.http.get(f"{BASE}/{path}/scoreboard", params, endpoint=f"espn:{path}", cooldown=0.5,
                                       fixture_name=f"scoreboard_{path.replace('/', '_')}_{yyyymmdd}")
        except ProviderError as e:
            self.log(f"  espn {path} {yyyymmdd}: {e}")
            self._cache[key] = []
            return []
        games = []
        for ev in (body or {}).get("events") or []:
            start = parse_iso(ev.get("date"))
            comp = (ev.get("competitions") or [{}])[0]
            status = (comp.get("status") or ev.get("status") or {}).get("type") or {}
            home = away = None
            hs = as_ = None
            for c in comp.get("competitors") or []:
                team = c.get("team") or {}
                nm = team.get("displayName") or team.get("name") or c.get("athlete", {}).get("displayName")
                try:
                    sc = int(float(c.get("score"))) if c.get("score") not in (None, "") else None
                except (TypeError, ValueError):
                    sc = None
                if c.get("homeAway") == "home":
                    home, hs = nm, sc
                else:
                    away, as_ = nm, sc
            games.append({"source": "espn", "id": ev.get("id"), "start": iso(start), "home": home, "away": away,
                          "home_score": hs, "away_score": as_, "completed": bool(status.get("completed")),
                          "state": status.get("state"), "detail": status.get("description") or status.get("name")})
        self._cache[key] = games
        return games

    def boxscore(self, path: str, game_id: str) -> dict[str, dict] | None:
        """-> {nom du joueur: {"points", "rebounds", "assists", "threes", "played"}} ; None si indisponible."""
        try:
            _, body, _ = self.http.get(f"{BASE}/{path}/summary", {"event": game_id}, endpoint=f"espn:{path}:summary",
                                       cooldown=0.5, fixture_name=f"summary_{path.replace('/', '_')}_{game_id}")
        except ProviderError as e:
            self.log(f"  espn boxscore {game_id}: {e}")
            return None
        out: dict[str, dict] = {}
        for team in ((body or {}).get("boxscore") or {}).get("players") or []:
            for block in team.get("statistics") or []:
                labels = [str(x).upper() for x in (block.get("labels") or block.get("names") or [])]
                for a in block.get("athletes") or []:
                    name = (a.get("athlete") or {}).get("displayName")
                    if not name:
                        continue
                    stats = a.get("stats") or []
                    if a.get("didNotPlay") or not stats:
                        out[name] = {"played": False}
                        continue
                    row = dict(zip(labels, stats))

                    def num(k):
                        v = str(row.get(k, "")).split("-")[0]
                        try:
                            return int(float(v))
                        except ValueError:
                            return None
                    out[name] = {"played": True, "points": num("PTS"), "rebounds": num("REB"),
                                 "assists": num("AST"), "threes": num("3PT")}
        return out or None
