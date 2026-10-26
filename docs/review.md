# BetLab — revue

_Générée le 2026-10-26T19:32:02Z — simulation, aucun argent réel._

## Stratégies

| Stratégie | Bankroll | P&L | ROI | Paris (réglés) | Réussite | CLV moyen (n) | z CLV | DD max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Valeur Pinnacle | 982,77 € | -17,23 € | -23,5 % | 10 (10) | 30 % | +5,1 % (10) | 15,8 | -3,0 % |
| Valeur consensus | 1000,00 € | 0,00 € | — | 0 (0) | — | — (0) | — | +0,0 % |
| Favoris prudents | 884,97 € | -115,03 € | -4,2 % | 300 (300) | 64 % | -4,3 % (300) | -23,1 | -15,7 % |
| Basket spécialiste | 996,67 € | -3,33 € | -5,8 % | 11 (11) | 36 % | +4,1 % (11) | 12,4 | -1,6 % |
| Mouvement sharp | 1007,13 € | 7,13 € | +171,0 % | 1 (1) | 100 % | +2,9 % (1) | — | +0,0 % |
| Témoin | 991,77 € | -8,23 € | -0,3 % | 227 (227) | 51 % | -4,8 % (227) | -19,5 | -28,9 % |

## Lecture

- **Valeur Pinnacle** : 10 paris avec clôture — trop tôt pour conclure (objectif ≥ 200).
- **Valeur consensus** : 0 paris avec clôture — trop tôt pour conclure (objectif ≥ 200).
- **Favoris prudents** : CLV -4,3 % (z = -23,1) — paie la marge du bookmaker, pas d'avantage détectable.
  - fait moins bien que le Témoin en bankroll (-115,03 € vs -8,23 €).
- **Basket spécialiste** : 11 paris avec clôture — trop tôt pour conclure (objectif ≥ 200).
- **Mouvement sharp** : 1 paris avec clôture — trop tôt pour conclure (objectif ≥ 200).

## Meilleurs CLV récents

- Strasbourg – Lille → Lille @ 3.098 (value_sharp) : CLV +7,1 %
- Golden State Warriors – Milwaukee Bucks → Golden State Warriors @ 2.778 (value_sharp) : CLV +6,6 %
- Golden State Warriors – Milwaukee Bucks → Golden State Warriors @ 2.778 (basket) : CLV +6,6 %
- Lens – Rennes → Lens @ 2.617 (value_sharp) : CLV +5,2 %
- Oklahoma City Thunder – Miami Heat → Oklahoma City Thunder @ 2.911 (basket) : CLV +4,0 %

## Pires CLV récents

- Toronto Maple Leafs – Boston Bruins → Toronto Maple Leafs @ 2.771 (control) : CLV -14,7 %
- Edmonton Oilers – Dallas Stars → Dallas Stars @ 2.295 (control) : CLV -13,5 %
- Vegas Golden Knights – Dallas Stars → Dallas Stars @ 1.442 (favorites) : CLV -13,1 %
- Sacramento Kings – Denver Nuggets → Sacramento Kings @ 1.399 (favorites) : CLV -12,9 %
- Florida Panthers – Edmonton Oilers → Florida Panthers @ 2.509 (control) : CLV -12,4 %

## Budget données

- oddspapi : 0/250 ce mois (refus : 0)
- theoddsapi : 0/500 ce mois (refus : 0)

## Questions à se poser

- Les stratégies à CLV positif ont-elles assez de paris pour conclure ? Sinon : patience, ne rien changer.
- Un paramètre (seuil d'edge, plafond de mise) ne doit être modifié qu'après ≥ 200 paris, et on note la date du changement.
- Le Témoin est-il battu en CLV ? C'est le seul test qui compte à court terme.
