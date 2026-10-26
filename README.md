# BetLab — agent de paris sportifs simulés

Un agent autonome qui relève les cotes, applique sept stratégies de paris (vainqueur du match et stats joueurs NBA) sur une bankroll **fictive**,
règle les paris automatiquement et mesure ce qui compte vraiment : le **CLV** (Closing Line Value).
Il tourne gratuitement sur GitHub Actions, toutes les heures, et publie un dashboard sur GitHub Pages.

> Aucun argent réel n'est engagé. C'est un laboratoire de statistiques, pas un outil de pari.
> Les cotes « jouées » sont celles de Winamax (site légal en France) ; Pinnacle sert uniquement de référence de prix.

## Ce que fait l'agent, toutes les heures

1. **Collecte** — aux créneaux définis dans `config.yaml` (heure de Paris), une requête OddsPapi ramène les cotes
   Pinnacle / Winamax / Betclic de tout un groupe de sports (basket le matin et le soir, foot à midi, NFL-NHL le soir,
   tennis le matin). The Odds API ajoute, pour la NBA et le foot, le consensus des six bookmakers français.
2. **Clôtures** — après le coup d'envoi, l'historique OddsPapi (gratuit, non compté dans le quota) donne la cote de
   clôture exacte de chaque pari ; l'agent en déduit le CLV.
3. **Règlement** — scores ESPN (gratuit) ; en secours The Odds API puis OddsPapi. Les bankrolls sont mises à jour.
4. **Décisions** — chaque stratégie examine les matchs à venir et place au plus un pari par match.
5. **Rapport** — `docs/data/dashboard.json` et `docs/review.md` sont régénérés et commités ; GitHub Pages les sert.

Un **gestionnaire de budget** répartit les quotas gratuits sur le mois (NBA en priorité) : l'agent ne tombe jamais
en panne de crédits en fin de mois, il relève simplement moins.

## Les sept stratégies (1 000 € fictifs chacune)

| Clé | Nom | Idée |
|---|---|---|
| `value_sharp` | Valeur Pinnacle | Probabilité = Pinnacle dé-margé. Pari si edge ≥ 4 % et cote 1,50–4,50. Kelly/4, plafond 2 %. |
| `value_consensus` | Valeur consensus | Probabilité = moyenne dé-margée de tous les books (la logique de Midas). Même règles. |
| `favorites` | Favoris prudents | Favori à ≥ 58 % de probabilité, cote 1,35–1,90, mise fixe 1 %. Témoin du « parieur raisonnable ». |
| `basket` | Basket spécialiste | Valeur Pinnacle sur NBA / Euroleague / Betclic Élite seulement, edge ≥ 3 %, Kelly 20 %. |
| `steam` | Mouvement sharp | Pinnacle a bougé d'au moins 3 pts vers un camp depuis l'ouverture et Winamax n'a pas suivi. |
| `control` | Témoin | Hasard reproductible (graine fixe), mise fixe 1 %. Toute stratégie doit le battre. |
| `player_props` | Stats joueurs | Points, rebonds, passes, 3 pts et combinés NBA en plus/moins de X : même joueur et même ligne chez Pinnacle et Winamax, edge ≥ 4 %, 2 paris max par match, réglé par la feuille de match ESPN. |

Tout est réglable dans `config.yaml` (seuils, plafonds, sports, créneaux). Ajouter une stratégie = une classe de
30 lignes dans `betlab/strategies/builtin.py` + une entrée dans la config.

## Lire les résultats

- **ROI** = P&L / mises. Sur moins de quelques centaines de paris, c'est du bruit.
- **CLV** = cote jouée × probabilité de clôture Pinnacle (marge retirée) − 1. Positif et stable sur ≥ 200 paris,
  c'est la preuve qu'on bat le marché. Le dashboard affiche l'erreur-type et un z-score : on conclut à z ≥ 2.
- **Drawdown max** = pire baisse depuis un sommet de la bankroll.
- **Témoin** = ce que donne le hasard chez ce bookmaker (≈ −marge). Battre le Témoin en CLV est le premier test.

## Installation sur GitHub (≈ 10 minutes, zéro serveur)

1. **Clé OddsPapi** (gratuite, 250 requêtes/mois) : créer un compte sur oddspapi.io, copier la clé API.
2. **Clé The Odds API** (gratuite, 500 crédits/mois, optionnelle mais recommandée) : the-odds-api.com.
3. **Dépôt** : créer un dépôt GitHub **public** (ex. `betlab`) et y pousser le contenu de ce dossier
   (GitHub Desktop, `git push`, ou « Upload files » sur le site).
4. **Secrets** : Settings → Secrets and variables → Actions → New repository secret :
   `ODDSPAPI_KEY` et `THEODDSAPI_KEY`.
5. **Pages** : Settings → Pages → Source « Deploy from a branch » → branche `main`, dossier `/docs`.
   Le dashboard sera à `https://<compte>.github.io/<dépôt>/`.
6. **Premier test** : onglet Actions → « BetLab — agent horaire » → Run workflow → command = `doctor`.
   Le journal liste les tournois trouvés et le marché « vainqueur » choisi pour chaque sport. Si un sport est
   mal reconnu, ajuster `match` / `category` / `exclude` (ou forcer `market_id`) dans `config.yaml`.
7. **Mise en service** : Run workflow avec command = `run` (ou attendre le prochain passage horaire).
   Le premier relevé consomme ~6 requêtes OddsPapi (catalogues mis en cache ensuite).

Le workflow commite `data/` et `docs/` à chaque passage. Le dashboard affiche « DÉMO » tant que les données
viennent de `python -m betlab demo` ; le premier vrai passage les remplace.

## Exécution locale (ou via Claude Code)

```bash
pip install -r requirements.txt
cp .env.example .env          # y coller les clés
python -m betlab doctor       # vérifie clés, catalogues, budget
python -m betlab run          # un passage complet
python -m betlab demo         # 45 jours fictifs pour voir le dashboard (aucune API appelée)
python -m betlab review       # écrit docs/review.md — à donner à Claude Code : « analyse docs/review.md et data/bets.json »
python -m pytest tests -q     # tests hors-ligne
```

Pour voir le dashboard en local : `python -m http.server 8000 --directory docs` puis http://localhost:8000.

## Structure

```
config.yaml                 sports, créneaux, budgets, stratégies
betlab/
  __main__.py               CLI (run, collect, decide, settle, closing, report, review, doctor, demo)
  collector.py              créneaux de relevé, appels fournisseurs, rattachement des matchs
  engine.py                 applique les stratégies
  ledger.py                 bankrolls, placement, règlement, CLV
  closing.py / settle.py    clôtures et règlement
  budget.py                 répartition mensuelle des quotas gratuits
  report.py / review.py     stats, dashboard.json, revue Markdown
  providers/                oddspapi.py, theoddsapi.py, espn.py
  strategies/               base.py, builtin.py (les sept stratégies)
data/                       events.json, bets.json, state.json, odds/AAAA-MM-JJ.jsonl, cache/
docs/                       index.html (dashboard), data/dashboard.json, review.md
.github/workflows/          betlab.yml (toutes les heures)
```

## Limites, dites franchement

- **1 à 2 relevés par jour et par sport** avec les quotas gratuits : les stratégies voient les cotes du matin et
  du soir, pas chaque mouvement. Un abonnement (≈ 30 €/mois) = changer `monthly_quota` et ajouter des créneaux.
- **GitHub Actions** peut décaler un passage de 10 à 30 minutes aux heures chargées ; les fenêtres sont larges
  pour l'absorber. Les workflows planifiés sont désactivés après 60 jours sans activité : une action keepalive
  s'en occupe.
- **ESPN** n'est pas une API officielle ; en cas de panne, les sources de secours prennent le relais (coût : quelques crédits).
- **Les offres gratuites changent** (odds-api.io a fermé la sienne en 2026). Les fournisseurs sont des modules
  indépendants : en remplacer un ne touche pas au reste.
- **Simulation ≠ réel.** En réel : les cotes bougent entre la décision et la mise, les comptes gagnants sont
  limités, et les montants Kelly ne sont pas toujours acceptés. Ce labo répond à une seule question :
  « est-ce qu'une règle simple bat le marché de clôture, de façon mesurable ? » — pas « vais-je gagner de l'argent ».

## Ajouter / modifier

- **Un sport** : une entrée dans `sports:` (tournoi OddsPapi par mots-clés, clé The Odds API, chemin ESPN, groupe, priorité).
- **Un bookmaker joué** : changer `bet_bookmaker` et l'inclure dans `oddspapi_bookmakers` (3 max par requête).
- **Une stratégie** : classe héritant de `Strategy` avec une méthode `candidates(ctx)`, enregistrée dans `REGISTRY`.
- **Un seuil** : on ne touche un paramètre qu'après ≥ 200 paris, et on note la date du changement dans la revue.

Jouer comporte des risques : endettement, isolement, dépendance. Appelez le 09 74 75 13 13 (appel non surtaxé).
