"""Tests hors-ligne : parsing des fournisseurs + pipeline complet sur fixtures (aucun appel réseau).

Lancer : python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------- fixtures de données
def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _player(price, created=None, active=True, main=True, outcome="home"):
    d = {"active": active, "betslip": None, "bookmakerOutcomeId": outcome, "changedAt": created or "2026-10-26T08:00:00.000Z",
         "limit": 1000, "playerName": None, "price": price, "mainLine": main, "exchangeMeta": None}
    return d


def make_fixtures(fx: Path, t0: datetime) -> dict:
    """t0 = instant du premier passage (10:00 Paris). Matchs NBA le soir même (01:30 UTC lendemain)."""
    start = (t0 + timedelta(hours=15, minutes=30)).replace(second=0, microsecond=0)   # 01:30 UTC le lendemain
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    op = fx / "oddspapi"
    _w(op / "account.json", {"subscription": {"request_limit": 250, "request_count": 3}})
    _w(op / "sports.json", [{"sportId": 10, "sportName": "Soccer"}, {"sportId": 2, "sportName": "Basketball"},
                            {"sportId": 16, "sportName": "American Football"}, {"sportId": 4, "sportName": "Ice Hockey"},
                            {"sportId": 5, "sportName": "Tennis"}])
    _w(op / "bookmakers.json", [{"bookmakerSlug": "pinnacle", "bookmakerName": "Pinnacle"},
                                {"bookmakerSlug": "winamax.fr", "bookmakerName": "Winamax FR"},
                                {"bookmakerSlug": "betclic.fr", "bookmakerName": "Betclic FR"}])
    _w(op / "tournaments_2.json", [
        {"tournamentId": 300, "tournamentSlug": "nba", "tournamentName": "NBA", "categorySlug": "usa", "categoryName": "USA", "futureFixtures": 120},
        {"tournamentId": 301, "tournamentSlug": "nba-summer-league", "tournamentName": "NBA Summer League", "categorySlug": "usa", "categoryName": "USA", "futureFixtures": 0},
        {"tournamentId": 310, "tournamentSlug": "euroleague", "tournamentName": "Euroleague", "categorySlug": "europe", "categoryName": "Europe", "futureFixtures": 40},
    ])
    _w(op / "markets.json", [
        {"marketId": 101, "marketLength": 3, "marketName": "Full Time Result", "playerProp": False, "sportId": 10, "handicap": 0, "period": "fulltime", "marketType": "1x2",
         "outcomes": [{"outcomeId": 101, "outcomeName": "1"}, {"outcomeId": 102, "outcomeName": "X"}, {"outcomeId": 103, "outcomeName": "2"}]},
        {"marketId": 201, "marketLength": 2, "marketName": "Moneyline (incl. OT)", "playerProp": False, "sportId": 2, "handicap": 0, "period": "fulltime", "marketType": "moneyline",
         "outcomes": [{"outcomeId": 201, "outcomeName": "1"}, {"outcomeId": 202, "outcomeName": "2"}]},
        {"marketId": 203, "marketLength": 3, "marketName": "Full Time Result", "playerProp": False, "sportId": 2, "handicap": 0, "period": "fulltime", "marketType": "1x2",
         "outcomes": [{"outcomeId": 203, "outcomeName": "1"}, {"outcomeId": 204, "outcomeName": "X"}, {"outcomeId": 205, "outcomeName": "2"}]},
        {"marketId": 250, "marketLength": 2, "marketName": "Over Under (incl. OT)", "playerProp": False, "sportId": 2, "handicap": 224.5, "period": "fulltime", "marketType": "totals",
         "outcomes": [{"outcomeId": 250, "outcomeName": "Over"}, {"outcomeId": 251, "outcomeName": "Under"}]},
    ])

    def book(ml_home, ml_away, over=None, under=None, main=True):
        m = {"201": {"bookmakerMarketId": "x", "marketActive": True, "outcomes": {
            "201": {"players": {"0": _player(ml_home, outcome="home")}},
            "202": {"players": {"0": _player(ml_away, outcome="away")}}}}}
        if over:
            m["250"] = {"bookmakerMarketId": "y", "marketActive": True, "outcomes": {
                "250": {"players": {"0": _player(over, main=main, outcome="224.5/over")}},
                "251": {"players": {"0": _player(under, main=main, outcome="224.5/under")}}}}
        return {"bookmakerIsActive": True, "bookmakerFixtureId": "1", "fixturePath": "", "suspended": False, "markets": m}

    fixtures = [
        {"fixtureId": "id9001", "participant1Id": 11, "participant2Id": 12, "sportId": 2, "tournamentId": 300, "seasonId": 1,
         "statusId": 0, "hasOdds": True, "startTime": start_iso, "trueStartTime": None, "trueEndTime": None, "updatedAt": start_iso,
         # Pinnacle: 1.80 / 2.05 -> p_home 0.533 ; Winamax home 2.00 -> edge +6.6 %
         "bookmakerOdds": {"pinnacle": book(1.80, 2.05, 1.92, 1.92), "winamax.fr": book(2.00, 1.78, 1.85, 1.85), "betclic.fr": book(1.95, 1.80)}},
        {"fixtureId": "id9002", "participant1Id": 13, "participant2Id": 14, "sportId": 2, "tournamentId": 300, "seasonId": 1,
         "statusId": 0, "hasOdds": True, "startTime": start_iso, "trueStartTime": None, "trueEndTime": None, "updatedAt": start_iso,
         # gros favori : Pinnacle 1.30 / 3.60 ; Winamax 1.33 / 3.20 -> Favoris prudents (p=0.735, cote 1.33 <1.35 ?) -> 1.36
         "bookmakerOdds": {"pinnacle": book(1.30, 3.60), "winamax.fr": book(1.36, 3.10), "betclic.fr": book(1.34, 3.15)}},
        {"fixtureId": "id9003", "participant1Id": 15, "participant2Id": 16, "sportId": 2, "tournamentId": 310, "seasonId": 1,
         "statusId": 2, "hasOdds": False, "startTime": start_iso, "trueStartTime": None, "trueEndTime": None, "updatedAt": start_iso,
         "bookmakerOdds": {}},
    ]
    _w(op / "odds_by_tournaments.json", fixtures)
    _w(op / "fixtures_300.json", [
        {"fixtureId": "id9001", "participant1Id": 11, "participant2Id": 12, "participant1Name": "Los Angeles Lakers", "participant2Name": "Denver Nuggets"},
        {"fixtureId": "id9002", "participant1Id": 13, "participant2Id": 14, "participant1Name": "Boston Celtics", "participant2Name": "Orlando Magic"},
    ])
    _w(op / "fixtures_310.json", [
        {"fixtureId": "id9003", "participant1Id": 15, "participant2Id": 16, "participant1Name": "Real Madrid", "participant2Name": "Olympiacos"},
    ])
    # historique : clôture Pinnacle 1.72 / 2.18 (le marché a bougé vers home -> CLV positif), Winamax 1.90 / 1.88
    def hist(entries):
        return {"players": {"0": [{"createdAt": c, "price": p, "limit": 500, "active": a, "exchangeMeta": None} for c, p, a in entries]}}
    before = (start - timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%S.000000+00:00")
    after = (start + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000000+00:00")
    early = (t0 - timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S.000000+00:00")
    _w(op / "historical_id9001.json", {"fixtureId": "id9001", "bookmakers": {
        "pinnacle": {"markets": {"201": {"outcomes": {"201": hist([(after, 1.72, False), (before, 1.72, True), (early, 1.80, True)]),
                                                     "202": hist([(after, 2.18, False), (before, 2.18, True), (early, 2.05, True)])}}}},
        "winamax.fr": {"markets": {"201": {"outcomes": {"201": hist([(before, 1.90, True), (early, 2.00, True)]),
                                                       "202": hist([(before, 1.88, True), (early, 1.78, True)])}}}}}})
    _w(op / "historical_id9002.json", {"fixtureId": "id9002", "bookmakers": {
        "pinnacle": {"markets": {"201": {"outcomes": {"201": hist([(before, 1.28, True)]), "202": hist([(before, 3.75, True)])}}}},
        "winamax.fr": {"markets": {"201": {"outcomes": {"201": hist([(before, 1.35, True)]), "202": hist([(before, 3.20, True)])}}}}}})

    # ESPN : scores finaux
    espn = fx / "espn"
    games = {"events": [
        {"id": "e1", "date": start.strftime("%Y-%m-%dT%H:%MZ"), "status": {"type": {"completed": True, "state": "post", "description": "Final"}},
         "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "Los Angeles Lakers"}, "score": "112"},
                                           {"homeAway": "away", "team": {"displayName": "Denver Nuggets"}, "score": "105"}]}]},
        {"id": "e2", "date": start.strftime("%Y-%m-%dT%H:%MZ"), "status": {"type": {"completed": True, "state": "post", "description": "Final"}},
         "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "Boston Celtics"}, "score": "98"},
                                           {"homeAway": "away", "team": {"displayName": "Orlando Magic"}, "score": "101"}]}]},
    ]}
    for d in {start.strftime("%Y%m%d"), (start - timedelta(hours=8)).strftime("%Y%m%d")}:
        _w(espn / f"scoreboard_basketball_nba_{d}.json", games)

    # The Odds API : consensus FR
    toa = fx / "theoddsapi"
    _w(toa / "sports.json", [{"key": "basketball_nba", "active": True, "title": "NBA"}, {"key": "basketball_euroleague", "active": True, "title": "Euroleague"}])
    def toa_book(key, h, a):
        return {"key": key, "title": key, "last_update": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "markets": [{"key": "h2h", "outcomes": [{"name": "Los Angeles Lakers", "price": h}, {"name": "Denver Nuggets", "price": a}]}]}
    _w(toa / "odds_basketball_nba.json", {"status": 200, "headers": {"x-requests-remaining": "480", "x-requests-used": "20", "x-requests-last": "1"}, "json": [
        {"id": "toa-abc", "sport_key": "basketball_nba", "commence_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "home_team": "Los Angeles Lakers", "away_team": "Denver Nuggets",
         "bookmakers": [toa_book("winamax_fr", 2.00, 1.78), toa_book("betclic_fr", 1.95, 1.80), toa_book("unibet_fr", 1.92, 1.85),
                        toa_book("parionssport_fr", 1.90, 1.85), toa_book("pmu_fr", 1.95, 1.82)]}]})
    return {"start": start}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    root.mkdir()
    shutil.copy(ROOT / "config.yaml", root / "config.yaml")
    (root / "docs").mkdir()
    fx = tmp_path / "fixtures"
    monkeypatch.setenv("BETLAB_ROOT", str(root))
    monkeypatch.setenv("BETLAB_OFFLINE", "1")
    monkeypatch.setenv("BETLAB_FIXTURES", str(fx))
    monkeypatch.setenv("ODDSPAPI_KEY", "test")
    monkeypatch.setenv("THEODDSAPI_KEY", "test")
    import importlib
    import betlab.config as c
    importlib.reload(c)
    from betlab import util
    t0 = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)   # 10:00 Paris (créneau basketball/matin)
    info = make_fixtures(fx, t0)
    util.set_fake_now(t0)
    yield {"root": root, "t0": t0, **info}
    util.set_fake_now(None)


# ----------------------------------------------------------------------------- tests unitaires
def test_devig_and_kelly():
    from betlab.util import devig, kelly_stake, margin
    p = devig({"home": 1.80, "away": 2.05})
    assert abs(sum(p.values()) - 1) < 1e-9 and abs(p["home"] - 0.5325) < 0.001
    assert 0.03 < margin({"home": 1.80, "away": 2.05}) < 0.05
    assert kelly_stake(1000, 0.55, 2.0, 0.25, 0.02, 0.0025) == 20.0      # plafond 2 %
    assert kelly_stake(1000, 0.50, 2.0, 0.25, 0.02, 0.0025) == 0.0       # pas d'edge -> 0


def test_name_matching():
    from betlab.matching import match_event
    evs = [{"id": "a", "home": "Los Angeles Lakers", "away": "Denver Nuggets", "start": "2026-11-04T01:30:00Z"},
           {"id": "b", "home": "LA Clippers", "away": "Phoenix Suns", "start": "2026-11-04T03:00:00Z"}]
    ev, swapped = match_event(evs, "Lakers", "Nuggets", "2026-11-04T01:30:00Z")
    assert ev["id"] == "a" and not swapped
    ev, swapped = match_event(evs, "Phoenix Suns", "Los Angeles Clippers", "2026-11-04T03:05:00Z")
    assert ev["id"] == "b" and swapped


# ----------------------------------------------------------------------------- pipeline complet
def test_full_pipeline(lab):
    from betlab.__main__ import App
    from betlab import util

    app = App()
    s = app.run()
    assert s["collect"]["rows"] > 0, s
    store = app.store
    ev = store.events["op:id9001"]
    assert ev["home"] == "Los Angeles Lakers" and ev["names_resolved"]
    assert "toa-abc" in json.dumps(ev["ids"])                     # rattachement The Odds API
    quotes = store.latest_quotes()["op:id9001"]
    assert set(quotes) >= {"pinnacle", "winamax", "betclic", "unibet", "parionssport", "pmu"}
    assert quotes["pinnacle"]["totals"]["line"] == 224.5

    by = {(b["strategy"], b["event_id"]): b for b in store.bets}
    assert ("value_sharp", "op:id9001") in by and by[("value_sharp", "op:id9001")]["selection"] == "home"
    assert by[("value_sharp", "op:id9001")]["stake"] == 16.23     # Kelly/4 : (0.5325×1 − 0.4675)/4 = 1,62 %
    assert ("basket", "op:id9001") in by
    assert ("favorites", "op:id9002") in by and by[("favorites", "op:id9002")]["stake"] == 10.0
    # consensus de 6 books (Pinnacle + 5 FR) : les books mous diluent Pinnacle -> pas d'edge, pas de pari
    assert ("value_consensus", "op:id9001") not in by
    assert store.state["slots"]["basketball:matin"] == "2026-11-03"
    assert store.state["budget"]["oddspapi"]["used"] >= 6         # sports, bookmakers, tournoi, marchés, relevé, noms
    assert store.state["budget"]["theoddsapi"]["used"] == 20     # valeur fiable lue dans le header x-requests-used
    assert store.state["budget"]["theoddsapi"]["used_today"] == 1

    # deuxième passage le même matin : créneau déjà fait, aucune dépense
    used_before = store.state["budget"]["oddspapi"]["used"]
    app2 = App()
    app2.run()
    assert app2.store.state["budget"]["oddspapi"]["used"] == used_before

    # lendemain 10:00 : clôtures + règlement
    util.set_fake_now(lab["t0"] + timedelta(days=1))
    app3 = App()
    s3 = app3.run()
    bets = {(b["strategy"], b["event_id"]): b for b in app3.store.bets}
    vs = bets[("value_sharp", "op:id9001")]
    assert vs["status"] == "won" and vs["pnl"] == 16.23
    assert vs["closing_odds"] == 1.90 and vs["clv"] is not None and vs["clv"] > 0.08   # 2.00 × p_close(0.559) − 1
    fav = bets[("favorites", "op:id9002")]
    assert fav["status"] == "lost" and fav["pnl"] == -10.0
    assert s3["settled"] >= 3 and s3["closing"] >= 2
    dash = json.loads((lab["root"] / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    st = {x["key"]: x for x in dash["strategies"]}
    assert st["value_sharp"]["bankroll"] == 1016.23 and st["favorites"]["bankroll"] == 990.0
    assert st["value_sharp"]["clv_n"] == 1
    assert dash["budget"]["oddspapi"]["used"] == used_before + 1   # un seul relevé le lendemain (catalogues en cache)
