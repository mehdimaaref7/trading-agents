# trading-agents

Agents IA de trading, en **paper trading uniquement** pour l'instant (compte Alpaca fictif).
Le passage au réel se fera seulement après validation de critères définis à l'avance.

## Le plan

1. **Socle** (ce dépôt aujourd'hui) : connexion Alpaca paper, données de marché, règles de risque codées en dur, journal des décisions, branchement MCP.
2. **Premier agent + backtest** : univers restreint (`src/trading_agents/universe.py`), stratégie simple et mesurable, testée sur 5 ans contre le SPY.
3. **Paper trading 2 à 3 mois** : l'agent propose, l'humain valide, tout est journalisé.
4. **Passage au réel** sur critères fixés à l'avance (drawdown, Sharpe, nombre de trades), puis extension à la crypto.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # puis colle tes clés PAPER Alpaca dedans
pytest                 # les tests du gestionnaire de risque
trading-agents status  # état du compte paper
trading-agents check AAPL 4 200 190 220   # simule le contrôle de risque d'un achat
```

Les clés se trouvent sur https://app.alpaca.markets, en mode **Paper Trading**, rubrique API Keys.
Ne jamais commiter `.env`, ne jamais coller les clés dans un chat.

## Règles de risque (`src/trading_agents/risk.py`)

Tout ordre passe par `RiskManager.check_order`. Aucun agent ne peut modifier ces limites.

| Règle | Valeur |
|---|---|
| Taille max d'une ligne | 10 % du capital |
| Perte max par trade (si le stop est touché) | 0,5 % du capital |
| Stop-loss | obligatoire, au plus 8 % sous l'entrée |
| Positions ouvertes | 10 max |
| Levier, vente à découvert | interdits |
| Prix minimum | 5 $ (pas de penny stocks) |
| Univers | liste fermée dans `universe.py` |
| Coupe-circuit journalier | -3 % sur la journée : plus d'achat |
| Coupe-circuit drawdown | -15 % depuis le plus haut : arrêt et revue humaine |

Les ventes qui réduisent une position sont toujours autorisées : on ne bloque jamais une sortie.
Les achats partent en ordre protégé (OTO avec stop, ou bracket stop + objectif).

## Brancher Alpaca en MCP

Le fichier `.mcp.json` déclare le serveur MCP officiel d'Alpaca (`alpaca-mcp-server`, lancé avec `uvx`).
Il faut `uv` installé (https://docs.astral.sh/uv/) et les variables `ALPACA_API_KEY` et `ALPACA_SECRET_KEY` dans ton shell.

**Claude Code** : lance `claude` à la racine du dépôt, le serveur est proposé automatiquement. Vérifie avec `/mcp`.

**Claude Desktop** : ajoute le même bloc `alpaca` dans `claude_desktop_config.json` en remplaçant `${...}` par tes clés paper.

Choix volontaire : le MCP est limité aux outils en **lecture** (`account,assets,stock-data,news`).
L'outil `trading` du MCP permettrait à un agent de passer des ordres sans passer par nos règles de risque,
donc il est désactivé. Les ordres passent uniquement par `AlpacaBroker.submit`.

## Backtest (étape 2)

```bash
trading-agents backtest                 # 5 ans, 10 000 $, télécharge les données Alpaca (clés requises)
trading-agents backtest --top-n 10      # tester une variante
trading-agents backtest --refresh       # forcer le retéléchargement (sinon cache data/bars.pkl)
```

Le rapport est écrit dans `reports/backtest.md` et la courbe de capital dans `reports/equity.csv`.

Stratégie (`strategy.py`) : momentum tendanciel, rééquilibrage mensuel.
- Filtre de marché : SPY sous sa moyenne 200 jours = aucun nouvel achat.
- Titre éligible s'il est au-dessus de sa moyenne 200 jours.
- Classement sur la performance 6 mois en sautant le dernier mois, on garde les 6 meilleurs.
- Stop à 3 x ATR(20), borné entre 3 % et 8 %.

Moteur (`backtest.py`) : décision à la clôture, exécution à l'ouverture suivante, 5 points de base de glissement,
stops vérifiés sur le plus bas (sortie à l'ouverture en cas de gap), même `RiskManager` qu'en paper.
Un test vérifie l'absence de biais d'anticipation (modifier le futur ne change pas le passé).

Limite : l'univers est la liste actuelle des grandes capitalisations, donc biais du survivant. Les résultats sont optimistes.

## Cœur-satellite et optimisation

Le premier backtest réel (juin 2021 à novembre 2026) a donné +3,8 %/an contre +12,2 % pour le SPY.
On passe donc à un cadre **cœur-satellite** : la majorité du capital suit un ETF, et les agents gèrent le satellite.
Ils devront battre le cœur avant de recevoir plus de capital.

```bash
trading-agents optimize                     # 72 variantes, choix sur 2021-2024, validation sur 2025+
trading-agents coresat                      # 75 % SPY + 25 % stratégie, avec 200 €/mois
trading-agents coresat --weight 0.8 --core QQQ --trailing --max-stop 0.15 --risk 0.01
trading-agents backtest --top-n 10 --trailing --max-stop 0.12 --risk 0.01
```

- `optimize` classe les variantes **uniquement** sur la période d'apprentissage (meilleur rendement avec un drawdown sous 20 %),
  puis montre la n°1 sur la période de validation. Si elle s'effondre en validation, c'est du surapprentissage.
- Options de stratégie : `--top-n`, `--atr-mult`, `--max-stop`, `--trailing` (stop suiveur), `--risk` (risque par trade),
  `--sweep SPY` (le cash non utilisé est placé dans le SPY à chaque rééquilibrage, sauf en marché baissier).
- Les limites du `RiskManager` du compte paper restent à leurs valeurs par défaut tant qu'une variante n'a pas été validée.

Rapports : `reports/optimisation.md`, `reports/coeur_satellite.md`, `reports/trades.csv`.

## Journal

Chaque contrôle de risque et chaque ordre est ajouté à `logs/journal.jsonl` (une ligne JSON par événement).
