"""Revue hebdo en Markdown (docs/review.md) : à lire soi-même ou à donner à Claude Code pour analyse."""
from __future__ import annotations

from pathlib import Path

from .util import pct


def _f(x, d=2):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def markdown_review(data: dict) -> str:
    L = ["# BetLab — revue", "", f"_Générée le {data.get('generated_at')} — simulation, aucun argent réel._", ""]
    L += ["## Stratégies", "", "| Stratégie | Bankroll | P&L | ROI | Paris (réglés) | Réussite | CLV moyen (n) | z CLV | DD max |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in data["strategies"]:
        L.append(f"| {s['label']} | {_f(s['bankroll'])} € | {_f(s['pnl'])} € | {pct(s['roi'])} | {s['bets']} ({s['settled']}) | "
                 f"{'—' if s['win_rate'] is None else str(round(s['win_rate'] * 100)) + ' %'} | {pct(s['clv'])} ({s['clv_n']}) | {_f(s['clv_z'], 1)} | {pct(s['max_drawdown'])} |")
    ctrl = next((s for s in data["strategies"] if s["key"] == "control"), None)
    L += ["", "## Lecture", ""]
    for s in data["strategies"]:
        if s["key"] == "control":
            continue
        n = s["clv_n"]
        if n < 30:
            L.append(f"- **{s['label']}** : {n} paris avec clôture — trop tôt pour conclure (objectif ≥ 200).")
        elif s["clv"] is not None and s["clv_z"] is not None and s["clv_z"] >= 2 and s["clv"] > 0:
            L.append(f"- **{s['label']}** : CLV {pct(s['clv'])} (z = {_f(s['clv_z'], 1)}) sur {n} paris — bat le marché de clôture. "
                     f"Si le ROI ne suit pas encore, c'est de la variance.")
        elif s["clv"] is not None and s["clv_z"] is not None and s["clv_z"] <= -2:
            L.append(f"- **{s['label']}** : CLV {pct(s['clv'])} (z = {_f(s['clv_z'], 1)}) — paie la marge du bookmaker, pas d'avantage détectable.")
        else:
            L.append(f"- **{s['label']}** : CLV {pct(s['clv'])} sur {n} paris — pas concluant.")
        if ctrl and s["pnl"] < ctrl["pnl"] and s["settled"] >= 50:
            L.append(f"  - fait moins bien que le Témoin en bankroll ({_f(s['pnl'])} € vs {_f(ctrl['pnl'])} €).")
    bets = [b for b in data.get("recent_bets", []) if b.get("clv") is not None]
    if bets:
        best = sorted(bets, key=lambda b: -b["clv"])[:5]
        worst = sorted(bets, key=lambda b: b["clv"])[:5]
        L += ["", "## Meilleurs CLV récents", ""] + [f"- {b['match']} → {b['selection_name']} @ {b['odds']} ({b['strategy']}) : CLV {pct(b['clv'])}" for b in best]
        L += ["", "## Pires CLV récents", ""] + [f"- {b['match']} → {b['selection_name']} @ {b['odds']} ({b['strategy']}) : CLV {pct(b['clv'])}" for b in worst]
    B = data.get("budget", {})
    L += ["", "## Budget données", ""] + [f"- {k} : {v['used']}/{v['quota']} ce mois (refus : {v['denied']})" for k, v in B.items()]
    if any(v.get("denied", 0) > 5 for v in B.values()):
        L.append("- Des relevés ont été refusés faute de budget : réduire les sports suivis ou passer un fournisseur en payant.")
    L += ["", "## Questions à se poser", "",
          "- Les stratégies à CLV positif ont-elles assez de paris pour conclure ? Sinon : patience, ne rien changer.",
          "- Un paramètre (seuil d'edge, plafond de mise) ne doit être modifié qu'après ≥ 200 paris, et on note la date du changement.",
          "- Le Témoin est-il battu en CLV ? C'est le seul test qui compte à court terme."]
    return "\n".join(L) + "\n"


def write_review(cfg, data: dict) -> Path:
    p = cfg.docs_dir / "review.md"
    p.write_text(markdown_review(data), encoding="utf-8")
    return p
