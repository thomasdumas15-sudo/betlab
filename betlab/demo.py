"""Démo hors-ligne : simule N jours de matchs, de cotes, de paris et de résultats
avec le VRAI moteur (stratégies, Kelly, règlement, CLV), sans appeler aucune API.

Sert à voir le dashboard avant la mise en service et à vérifier que tout s'enchaîne.
Les données vont dans data_demo/ ; le dashboard est écrit dans docs/data/ avec un badge DÉMO.
"""
from __future__ import annotations

import random
import shutil
from datetime import datetime, timedelta, timezone

from .budget import Budget
from .config import Config
from .engine import Engine
from .ledger import Ledger
from .report import build_dashboard, write_dashboard
from .review import write_review
from .storage import Store
from .util import iso, set_fake_now

NBA = ["Boston Celtics", "Denver Nuggets", "Los Angeles Lakers", "Golden State Warriors", "Milwaukee Bucks",
       "Phoenix Suns", "Dallas Mavericks", "Miami Heat", "New York Knicks", "Philadelphia 76ers", "Oklahoma City Thunder",
       "Minnesota Timberwolves", "Cleveland Cavaliers", "Sacramento Kings", "Indiana Pacers", "Orlando Magic",
       "Houston Rockets", "Memphis Grizzlies", "San Antonio Spurs", "Atlanta Hawks"]
EURO = ["Real Madrid", "Olympiacos", "Panathinaikos", "Fenerbahçe", "Monaco", "Barcelona", "Anadolu Efes",
        "Bayern Munich", "Paris Basketball", "Virtus Bologna", "Partizan", "Zalgiris"]
L1 = ["Paris Saint-Germain", "Marseille", "Lyon", "Monaco", "Lille", "Nice", "Lens", "Rennes", "Strasbourg", "Toulouse"]
NFL = ["Kansas City Chiefs", "Buffalo Bills", "Philadelphia Eagles", "Detroit Lions", "Baltimore Ravens",
       "San Francisco 49ers", "Dallas Cowboys", "Green Bay Packers", "Houston Texans", "Minnesota Vikings"]
NHL = ["Edmonton Oilers", "Florida Panthers", "Colorado Avalanche", "Toronto Maple Leafs", "Boston Bruins",
       "Dallas Stars", "Vegas Golden Knights", "New York Rangers", "Carolina Hurricanes", "Winnipeg Jets"]


def _price(p: float, margin: float) -> float:
    return round(1.0 / (p * (1 + margin)), 3)


def _market(rng: random.Random, kind: str):
    """-> probabilités vraies (home/away[/draw])."""
    if kind == "soccer":
        h = rng.uniform(0.28, 0.62)
        d = rng.uniform(0.20, 0.30)
        a = max(0.08, 1 - h - d)
        tot = h + d + a
        return {"home": h / tot, "draw": d / tot, "away": a / tot}
    h = rng.uniform(0.25, 0.78)
    return {"home": h, "away": 1 - h}


def _book_prices(rng: random.Random, probs: dict, margin: float, noise: float) -> dict:
    out = {}
    for side, p in probs.items():
        q = min(0.97, max(0.03, p * (1 + rng.gauss(0, noise))))
        out[side] = _price(q, margin)
    return out


def run_demo(days: int = 45, seed: int = 7) -> None:
    rng = random.Random(seed)
    cfg = Config()
    demo_dir = cfg.root / "data_demo"
    if demo_dir.exists():
        shutil.rmtree(demo_dir)
    store = Store(demo_dir)
    budget = Budget(cfg, store.state)
    ledger = Ledger(cfg, store)
    engine = Engine(cfg, store, ledger, log=lambda m: None)
    bet_book, ref_book = cfg.get("bet_bookmaker"), cfg.get("reference_bookmaker")

    day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    n_games = 0
    for d in range(days):
        day = day0 + timedelta(days=d)
        games = []
        for i in range(rng.randint(5, 10)):
            h, a = rng.sample(NBA, 2)
            games.append(("nba", "basketball", h, a, day + timedelta(hours=24 + rng.choice([0, 0.5, 1, 1.5, 2, 2.5, 3.5]))))
        if day.weekday() in (1, 3):
            for i in range(rng.randint(3, 5)):
                h, a = rng.sample(EURO, 2)
                games.append(("euroleague", "basketball", h, a, day + timedelta(hours=18 + rng.choice([0, 0.5, 1.5, 2]))))
        if day.weekday() in (4, 5, 6):
            for i in range(rng.randint(2, 4)):
                h, a = rng.sample(L1, 2)
                games.append(("ligue1", "soccer", h, a, day + timedelta(hours=16 + rng.choice([0, 2, 3, 4.5]))))
        if day.weekday() == 6:
            for i in range(rng.randint(5, 8)):
                h, a = rng.sample(NFL, 2)
                games.append(("nfl", "american_football", h, a, day + timedelta(hours=18 + rng.choice([0, 0, 3.5, 7]))))
        for i in range(rng.randint(2, 6)):
            h, a = rng.sample(NHL, 2)
            games.append(("nhl", "ice_hockey", h, a, day + timedelta(hours=23 + rng.choice([0, 0.5, 1, 2]))))

        snapshots = [day + timedelta(hours=8), day + timedelta(hours=20)]
        truths = {}
        for (sport, kind, home, away, start) in games:
            n_games += 1
            eid = f"demo:{d}:{n_games}"
            store.upsert_event({"id": eid, "sport": sport, "kind": kind, "home": home, "away": away, "start": iso(start),
                                "ids": {"demo": eid}, "status": "scheduled", "names_resolved": True})
            p_open = _market(rng, kind)
            drift = {s: rng.gauss(0, 0.025) for s in p_open}
            truths[eid] = (p_open, drift, start)
            # Winamax : marge ~6,5 %, bruit 3 %, et retard sur le mouvement du marché (ligne "stale")
            wm_base = _book_prices(rng, p_open, 0.055, 0.045)
            bc_base = _book_prices(rng, p_open, 0.06, 0.045)
            for k, ts in enumerate(snapshots):
                frac = 0.35 if k == 0 else 1.0
                p_now = {s: min(0.97, max(0.03, p_open[s] + drift[s] * frac)) for s in p_open}
                tot = sum(p_now.values())
                p_now = {s: v / tot for s, v in p_now.items()}
                pin = _book_prices(rng, p_now, 0.025, 0.004)
                lag = 0.15 if k == 0 else 0.55
                wm = {s: round(wm_base[s] * (1 - lag) + _price(p_now[s] * (1 + rng.gauss(0, 0.04)), 0.055) * lag, 3) for s in p_open}
                bc = {s: round(bc_base[s] * (1 - lag) + _price(p_now[s] * (1 + rng.gauss(0, 0.04)), 0.06) * lag, 3) for s in p_open}
                for book, prices in ((ref_book, pin), (bet_book, wm), ("betclic", bc)):
                    store.add_odds({"ts": iso(ts), "event_id": eid, "provider": "demo", "book": book, "market": "h2h",
                                    "line": None, "prices": prices})
            truths[eid] = (p_open, drift, start, pin)
        store.flush_odds()

        # décisions aux deux relevés
        for ts in snapshots:
            set_fake_now(ts + timedelta(minutes=5))
            engine.run()

        # clôture + règlement après les matchs (le lendemain matin)
        set_fake_now(day + timedelta(hours=31))
        for eid, (p_open, drift, start, pin_close) in truths.items():
            ev = store.events[eid]
            p_final = {s: min(0.97, max(0.03, p_open[s] + drift[s])) for s in p_open}
            tot = sum(p_final.values())
            p_final = {s: v / tot for s, v in p_final.items()}
            closing = {ref_book: {**pin_close, "ts": iso(start - timedelta(minutes=3))},
                       bet_book: {**_book_prices(rng, p_final, 0.055, 0.02), "ts": iso(start - timedelta(minutes=10))}}
            ev["closing"], ev["closing_source"], ev["closing_fetched"] = closing, "demo", iso(start)
            r, acc, winner = rng.random(), 0.0, None
            for s, p in p_final.items():
                acc += p
                if r <= acc:
                    winner = s
                    break
            winner = winner or next(iter(p_final))
            ev["result"] = {"winner": winner, "status": "settled", "source": "demo"}
            ev["status"] = "finished"
            for b in store.bets:
                if b["event_id"] == eid:
                    if b.get("clv") is None:
                        ledger.apply_closing(b, closing, "demo")
                    if b["status"] == "open":
                        ledger.settle(b, winner)

    set_fake_now(None)
    store.state["last_run"] = iso(datetime.now(timezone.utc))
    store.state["slots"] = {"basketball:matin": datetime.now(timezone.utc).date().isoformat()}
    store.save()
    data = build_dashboard(cfg, store, budget, {"demo": True, "days": days, "games": n_games})
    data["demo"] = True
    write_dashboard(cfg, data)
    write_review(cfg, data)
    print(f"Démo : {days} jours, {n_games} matchs, {len(store.bets)} paris → docs/data/dashboard.json")
    for s in data["strategies"]:
        clv = f"{s['clv'] * 100:+.1f} %" if s["clv"] is not None else "—"
        roi = f"{s['roi'] * 100:+.1f} %" if s["roi"] is not None else "—"
        print(f"  {s['label']:18s} bankroll {s['bankroll']:8.2f} €  paris {s['bets']:4d}  ROI {roi:>8s}  CLV {clv:>8s}  DD {s['max_drawdown'] * 100:.1f} %")
