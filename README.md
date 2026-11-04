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

## Journal

Chaque contrôle de risque et chaque ordre est ajouté à `logs/journal.jsonl` (une ligne JSON par événement).
