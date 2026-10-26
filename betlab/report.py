"""Statistiques par stratégie et export pour le dashboard (docs/data/*.json)."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from .util import iso, mean, now_utc, parse_iso, stdev


def _dd(equity: list[float]) -> float:
    peak, worst = -1e18, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak)
    return worst


def strategy_stats(key: str, params: dict, bets: list[dict], start: float) -> dict:
    mine = [b for b in bets if b["strategy"] == key]
    settled = [b for b in mine if b["status"] in ("won", "lost")]
    settled.sort(key=lambda b: b.get("settled_at") or "")
    won = [b for b in settled if b["status"] == "won"]
    open_ = [b for b in mine if b["status"] == "open"]
    void = [b for b in mine if b["status"] == "void"]
    pnl = round(sum(float(b["pnl"] or 0) for b in settled), 2)
    staked = round(sum(float(b["stake"]) for b in settled), 2)
    bankroll = round(start + pnl, 2)
    roi = pnl / staked if staked else None
    returns = [float(b["pnl"]) / float(b["stake"]) for b in settled if b["stake"]]
    sd = stdev(returns)
    roi_se = (sd / math.sqrt(len(returns))) if sd is not None and returns else None
    equity, eq = [start], start
    curve = []
    for b in settled:
        eq = round(eq + float(b["pnl"] or 0), 2)
        equity.append(eq)
        curve.append([b.get("settled_at", "")[:10], eq])
    clvs = [b["clv"] for b in mine if b.get("clv") is not None]
    clv_books = [b["clv_book"] for b in mine if b.get("clv_book") is not None]
    clv_sd = stdev(clvs)
    clv_se = (clv_sd / math.sqrt(len(clvs))) if clv_sd is not None and clvs else None
    by_sport = defaultdict(lambda: {"n": 0, "pnl": 0.0, "staked": 0.0})
    for b in settled:
        s = by_sport[b.get("sport") or "?"]
        s["n"] += 1
        s["pnl"] = round(s["pnl"] + float(b["pnl"] or 0), 2)
        s["staked"] = round(s["staked"] + float(b["stake"]), 2)
    for s in by_sport.values():
        s["roi"] = round(s["pnl"] / s["staked"], 4) if s["staked"] else None
    return {
        "key": key,
        "label": params.get("label", key),
        "description": params.get("description", []),
        "bankroll": bankroll,
        "pnl": pnl,
        "pnl_pct": round(pnl / start, 4) if start else None,
        "roi": round(roi, 4) if roi is not None else None,
        "roi_se": round(roi_se, 4) if roi_se is not None else None,
        "z": round(roi / roi_se, 2) if roi is not None and roi_se else None,
        "bets": len(mine),
        "open": len(open_),
        "settled": len(settled),
        "void": len(void),
        "won": len(won),
        "win_rate": round(len(won) / len(settled), 4) if settled else None,
        "avg_odds": round(mean([float(b["odds"]) for b in settled]) or 0, 3) if settled else None,
        "avg_edge": round(mean([float(b["edge"]) for b in mine]) or 0, 4) if mine else None,
        "staked": staked,
        "exposure": round(sum(float(b["stake"]) for b in open_), 2),
        "max_drawdown": round(_dd(equity), 4),
        "clv": round(mean(clvs), 4) if clvs else None,
        "clv_n": len(clvs),
        "clv_se": round(clv_se, 4) if clv_se is not None else None,
        "clv_z": round(mean(clvs) / clv_se, 2) if clvs and clv_se else None,
        "clv_book": round(mean(clv_books), 4) if clv_books else None,
        "by_sport": dict(by_sport),
        "equity": curve[-400:],
    }


def build_dashboard(cfg, store, budget, extra: dict | None = None) -> dict:
    start = float(cfg.get("bankroll_start", 1000))
    strategies = [strategy_stats(k, p, store.bets, start) for k, p in cfg.strategies.items()]
    control = next((s for s in strategies if s["key"] == "control"), None)
    for s in strategies:
        s["vs_control_pnl"] = round(s["pnl"] - control["pnl"], 2) if control and s is not control else None
    now = now_utc()
    upcoming = [e for e in store.events.values() if e.get("status") == "scheduled" and (parse_iso(e.get("start")) or now) > now]
    events_by_sport = defaultdict(int)
    for e in upcoming:
        events_by_sport[e.get("sport")] += 1
    sports_labels = {k: v.get("label", k) for k, v in cfg.sports.items()}
    recent = sorted(store.bets, key=lambda b: b.get("placed_at") or "", reverse=True)
    return {
        "generated_at": iso(now),
        "bankroll_start": start,
        "bet_bookmaker": cfg.bookmakers.get(cfg.get("bet_bookmaker"), {}).get("label", cfg.get("bet_bookmaker")),
        "reference_bookmaker": cfg.bookmakers.get(cfg.get("reference_bookmaker"), {}).get("label", cfg.get("reference_bookmaker")),
        "strategies": strategies,
        "sports": sports_labels,
        "upcoming_events": dict(events_by_sport),
        "events_tracked": len(store.events),
        "bets_total": len(store.bets),
        "budget": budget.summary(),
        "slots_done": store.state.get("slots", {}),
        "tournaments": store.state.get("oddspapi_tournaments", {}),
        "last_run": store.state.get("last_run"),
        "run": extra or {},
        "recent_bets": [_bet_view(b, sports_labels) for b in recent[:300]],
    }


def _bet_view(b: dict, sports_labels: dict) -> dict:
    return {k: b.get(k) for k in ("id", "strategy", "sport", "match", "start", "selection", "selection_name", "odds",
                                   "fair_prob", "edge", "stake", "placed_at", "status", "result", "pnl",
                                   "clv", "clv_book", "closing_odds", "note")} | {"sport_label": sports_labels.get(b.get("sport"), b.get("sport"))}


def write_dashboard(cfg, data: dict) -> Path:
    out = cfg.docs_dir / "data"
    out.mkdir(parents=True, exist_ok=True)
    p = out / "dashboard.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return p
