# Skills tiers (copiés, licence MIT)

Copiés plutôt qu'installés en plugin pour figer une version relue et ne garder que ce qui sert le projet.
Pour mettre à jour : recopier depuis l'amont et relire le diff avant de commiter.

| Skill | Source | Commit | Données |
|---|---|---|---|
| backtest-expert | tradermonty/claude-trading-skills | d8e71ce | aucune (méthodologie) |
| position-sizer | tradermonty/claude-trading-skills | d8e71ce | aucune (calcul local) |
| market-breadth-analyzer | tradermonty/claude-trading-skills | d8e71ce | CSV publics tradermonty.github.io |
| uptrend-analyzer | tradermonty/claude-trading-skills | d8e71ce | CSV publics raw.githubusercontent.com/tradermonty |
| walk-forward-validation | agiprolabs/claude-trading-skills | 981e1d7 | aucune |

Aucun de ces skills ne passe d'ordre. Les ordres passent uniquement par `AlpacaBroker.submit` et le `RiskManager`.

Non retenus pour l'instant : les skills crypto/DeFi d'agiprolabs (phase crypto plus tard, via le marketplace déclaré
dans `.claude/settings.json`, non activé), et les skills tradermonty qui demandent une clé FMP ou FINVIZ payante.
