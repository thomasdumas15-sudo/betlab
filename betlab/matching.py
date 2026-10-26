"""Rapprochement d'un match entre fournisseurs (noms d'équipes + heure de début)."""
from __future__ import annotations

from datetime import timedelta

from .util import name_similarity, parse_iso


def match_event(events: list[dict], home: str | None, away: str | None, start_iso: str | None,
                tolerance_hours: float = 6.0, min_score: float = 0.55) -> tuple[dict | None, bool]:
    """-> (événement, inversé?) ; inversé = home/away échangés chez la source."""
    start = parse_iso(start_iso)
    best, best_score, best_swapped = None, 0.0, False
    for ev in events:
        est = parse_iso(ev.get("start"))
        if start and est and abs((est - start).total_seconds()) > tolerance_hours * 3600:
            continue
        s_direct = min(name_similarity(ev.get("home"), home), name_similarity(ev.get("away"), away))
        s_swap = min(name_similarity(ev.get("home"), away), name_similarity(ev.get("away"), home))
        s, swapped = (s_direct, False) if s_direct >= s_swap else (s_swap, True)
        # proximité temporelle en départage
        if start and est:
            s += 0.05 * max(0.0, 1 - abs((est - start).total_seconds()) / (tolerance_hours * 3600))
        if s > best_score:
            best, best_score, best_swapped = ev, s, swapped
    if best is not None and best_score >= min_score:
        return best, best_swapped
    return None, False


def merge_duplicate(existing_events: dict[str, dict], new_ev: dict) -> dict | None:
    """Un même match vu par deux fournisseurs : rattache le nouvel id à l'événement existant."""
    same_sport = [e for e in existing_events.values()
                  if e.get("sport") == new_ev.get("sport") and e["id"] != new_ev["id"]]
    ev, swapped = match_event(same_sport, new_ev.get("home"), new_ev.get("away"), new_ev.get("start"),
                              tolerance_hours=3.0, min_score=0.7)
    if ev is None or swapped:
        return None
    return ev
