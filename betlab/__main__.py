"""CLI : python -m betlab <commande>

  run        pipeline complet (collecte selon créneaux → clôtures → règlement → décisions → rapport)
  collect    force un relevé maintenant  (--group basketball|football|us|tennis)
  decide     applique les stratégies sur les cotes déjà relevées
  settle     règle les paris dont le match est terminé
  closing    récupère les cotes de clôture et calcule le CLV
  report     régénère docs/data/dashboard.json
  review     écrit docs/review.md (revue en Markdown à lire ou à donner à Claude Code)
  doctor     vérifie les clés, les catalogues et le budget (n'utilise ~5 requêtes qu'au premier appel)
  demo       génère un jeu de données fictif pour visualiser le dashboard (n'appelle aucune API)
"""
from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .budget import Budget
from .closing import Closing
from .collector import Collector
from .config import Config
from .engine import Engine
from .ledger import Ledger
from .providers.base import ProviderError, QuotaExhausted
from .providers.espn import Espn
from .providers.oddspapi import OddsPapi
from .providers.theoddsapi import TheOddsApi
from .report import build_dashboard, write_dashboard
from .review import write_review
from .settle import Settler
from .storage import Store
from .util import iso, local_now, now_utc


def log(msg: str) -> None:
    print(msg, flush=True)


class App:
    def __init__(self):
        self.cfg = Config()
        self.store = Store(self.cfg.data_dir)
        self.budget = Budget(self.cfg, self.store.state)
        self.op = OddsPapi(self.cfg, self.store, self.budget, log) if self.cfg.has_oddspapi else None
        self.toa = TheOddsApi(self.cfg, self.store, self.budget, log) if self.cfg.has_theoddsapi else None
        self.espn = Espn(self.cfg, log)
        self.ledger = Ledger(self.cfg, self.store)
        self.collector = Collector(self.cfg, self.store, self.budget, self.op, self.toa, log)
        self.engine = Engine(self.cfg, self.store, self.ledger, log)
        self.closing = Closing(self.cfg, self.store, self.ledger, self.op, log)
        self.settler = Settler(self.cfg, self.store, self.ledger, self.espn, self.toa, self.op, log)
        if self.op is None and self.toa is None:
            log("! Aucune clé API (ODDSPAPI_KEY / THEODDSAPI_KEY) : collecte impossible, le reste fonctionne.")

    # ------------------------------------------------------------ commandes
    def run(self, force_group: str | None = None) -> dict:
        t0 = time.time()
        now_local = local_now(self.cfg.tz)
        log(f"BetLab {__version__} — {now_local.strftime('%d/%m/%Y %H:%M')} {self.cfg.tz} (simulation, aucun argent réel)")
        summary = {"collect": None, "closing": 0, "settled": 0, "placed": 0, "errors": []}
        try:
            summary["collect"] = self.collector.run(now_local, force_group)
        except (ProviderError, QuotaExhausted) as e:
            log(f"! collecte : {e}")
            summary["errors"].append(str(e))
        self.store.flush_odds()
        log("• clôtures / CLV")
        summary["closing"] = self.closing.run()
        log("• règlement")
        summary["settled"] = self.settler.run()
        log("• décisions")
        summary["placed"] = len(self.engine.run())
        self.finish(summary, t0)
        return summary

    def finish(self, summary: dict, t0: float) -> None:
        pruned = self.store.prune_events()
        self.store.state["last_run"] = iso(now_utc())
        self.store.state["last_run_summary"] = summary
        self.store.save()
        data = build_dashboard(self.cfg, self.store, self.budget, summary)
        write_dashboard(self.cfg, data)
        write_review(self.cfg, data)
        for line in self.budget.log:
            log(f"  budget {line}")
        b = self.budget.summary()
        log(f"✓ terminé en {time.time() - t0:.0f}s — paris placés {summary.get('placed', 0)}, réglés {summary.get('settled', 0)}, "
            f"clôtures {summary.get('closing', 0)}, événements {len(self.store.events)} (−{pruned} purgés) — "
            + ", ".join(f"{k} {v['used']}/{v['quota']}" for k, v in b.items()))

    def doctor(self) -> None:
        log(f"BetLab {__version__} — diagnostic")
        log(f"  OddsPapi   : {'clé présente' if self.cfg.key('ODDSPAPI_KEY') else 'ABSENTE'}")
        log(f"  The Odds API: {'clé présente' if self.cfg.key('THEODDSAPI_KEY') else 'absente (optionnel)'}")
        if self.op is not None:
            acc = self.op.account()
            if acc:
                log(f"  OddsPapi compte : {acc['count']}/{acc['limit']} requêtes utilisées ce mois")
            try:
                slugs = self.collector._oddspapi_slugs()
                log(f"  OddsPapi bookmakers : {slugs}")
                for key, sc in self.cfg.sports.items():
                    if "oddspapi" not in sc:
                        continue
                    tours = self.op.resolve_tournaments(key, sc["oddspapi"])
                    ml = self.op.moneyline_market(tours[0]["sport_id"], sc["kind"]) if tours else None
                    log(f"  {key:15s} → " + (", ".join(f"{t['name']} (#{t['id']}, {t['future']} à venir)" for t in tours) if tours else "AUCUN TOURNOI")
                        + (f" | marché vainqueur : {ml.get('marketName')} #{ml.get('marketId')}" if ml else " | marché vainqueur introuvable"))
            except (ProviderError, QuotaExhausted) as e:
                log(f"  ! {e}")
        if self.toa is not None:
            try:
                active = self.toa.active_keys()
                for key, sc in self.cfg.sports.items():
                    k = (sc.get("theoddsapi") or {}).get("key")
                    if k:
                        log(f"  theoddsapi {k:32s} {'actif' if k in active else 'inactif'}")
            except ProviderError as e:
                log(f"  ! {e}")
        self.store.save()
        log("  budget : " + ", ".join(f"{k} {v['used']}/{v['quota']} (alloc/jour {v['daily_allowance']})" for k, v in self.budget.summary().items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="betlab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "collect", "decide", "settle", "closing", "report", "review", "doctor", "demo"])
    ap.add_argument("--group", help="groupe à relever (collect)")
    ap.add_argument("--days", type=int, default=45, help="demo : nombre de jours simulés")
    args = ap.parse_args(argv)

    if args.command == "demo":
        from .demo import run_demo
        run_demo(days=args.days)
        return 0

    app = App()
    t0 = time.time()
    if args.command == "run":
        app.run()
    elif args.command == "collect":
        app.run(force_group=args.group or "basketball")
    elif args.command == "doctor":
        app.doctor()
    else:
        summary = {}
        if args.command == "decide":
            summary["placed"] = len(app.engine.run())
        elif args.command == "settle":
            summary["settled"] = app.settler.run()
        elif args.command == "closing":
            summary["closing"] = app.closing.run()
        app.finish(summary, t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
