# Comparaison avec l'article MindStudio (agent Claude Code + Alpaca)

Source : https://www.mindstudio.ai/blog/build-ai-trading-agent-claude-code-alpaca (18/04/2026).

## Ce que fait l'article

Claude Code tourne en routine trois fois par jour (recherche 9h45, trading 10h, journal 16h15, heure de New York).
Claude lit un `CLAUDE.md` (règles), une `watchlist.json`, appelle des scripts Python qui parlent à l'API Alpaca,
décide lui-même des trades, puis écrit un journal Markdown quotidien envoyé par e-mail.

## Comparaison

| Sujet | Article | Notre projet |
|---|---|---|
| Qui décide | Le LLM, au jugement | Règles fixes backtestables ; le LLM viendra comme analyste avec droit de veto |
| Limites de risque | Écrites dans le prompt ; la fonction `validate_order` existe mais n'est jamais appelée | Codées dans `RiskManager`, appliquées à chaque ordre, 32 tests |
| Stop-loss | Instruction au LLM (« ferme à -8 % »), aucun ordre stop posé | Ordre OTO/bracket chez le broker, actif même si l'agent ne tourne pas |
| Ordres au marché | Interdits dans le prompt, autorisés dans le code | Protégés par stop systématique |
| Backtest | Aucun | Moteur + optimisation hors échantillon + cœur-satellite |
| Passage au réel | Changer une URL | Double verrou dans le code, critères fixés à l'avance |
| Automatisation | Routines planifiées, heartbeat | **Pas encore** |
| Journal | Markdown quotidien avec raisonnement et réflexion de fin de journée | JSONL technique, **pas de synthèse lisible** |
| Actualités | Lues avant chaque décision | **Pas encore** |

## Ce qu'on reprend (étape 3, paper trading)

1. **Routine planifiée** : une exécution par jour de bourse, qui commence par vérifier que le marché est ouvert.
2. **Journal Markdown quotidien** : positions, ordres, raisonnement, et une courte réflexion de fin de journée, en plus du JSONL.
3. **Heartbeat** : un fichier mis à jour à chaque exécution, avec une alerte si la routine n'a pas tourné.
4. **Agent analyste** : lit les actualités (outil `news` du MCP Alpaca) et peut mettre un veto motivé sur un achat proposé par la stratégie, sans jamais pouvoir en créer un.

## Ce qu'on ne reprend pas

- Laisser le LLM décider seul des trades : impossible à backtester honnêtement, et non reproductible.
- Des limites seulement dans le prompt : un prompt n'est pas un garde-fou.
