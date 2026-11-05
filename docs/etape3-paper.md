# Étape 3 : le duel en paper trading

## Le principe

- **A** : la stratégie momentum seule.
- **B** : la même stratégie, mais chaque **nouvel achat** passe d'abord par l'agent analyste (`analyst.py`).
  Il lit les actualités Alpaca des 10 derniers jours et peut mettre un **veto**. Il ne peut rien proposer,
  ni changer une taille ou un stop, ni bloquer une vente.

Chaque jour, A et B sont rejoués avec le moteur de backtest depuis le début du duel, sur les vraies données :
mêmes règles, seuls les vetos diffèrent. B est en plus répliqué sur le compte paper Alpaca.

Si l'analyste est en panne (clé absente, réseau, refus), il n'y a pas de veto : B se comporte comme A.
Une panne ne peut donc pas avantager B.

## Installation

1. `git pull`, puis `pip install -e ".[dev]"` (ajoute la librairie `anthropic`).
2. Dans `.env`, ajoute `ANTHROPIC_API_KEY=...` (console.anthropic.com > API Keys).
3. Test à blanc, après la clôture de New York (22h30 heure de Paris) :
   ```
   trading-agents run-daily --dry-run
   ```
   Le premier lancement crée le duel et prend une première décision. Lis `journal/AAAA-MM-JJ.md`.
   Attention : en `--dry-run`, le duel démarre quand même. Supprime `state/` pour repartir de zéro.
4. Lancement réel : `trading-agents run-daily`.

En cas de souci avec l analyste, `trading-agents analyst-test AAPL` fait un seul appel et affiche le message d erreur complet
(cause la plus fréquente : crédits API à zéro sur console.anthropic.com).

## Planification sous Windows

La routine doit tourner chaque jour de bourse **après 16h15 à New York**, soit 22h45 à Paris.
Le PC doit être allumé à cette heure-là. Dans une invite de commandes :

```
schtasks /Create /TN "trading-agents-daily" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 22:45 /TR "\"C:\Users\Dell\Desktop\dev\trading-agents\scripts\run_daily.bat\""
```

Les sorties vont dans `logs\run_daily.log`. Pour tester tout de suite : `schtasks /Run /TN "trading-agents-daily"`.
Une relance le même jour ne repasse pas d'ordres.

## Suivi

```
trading-agents duel        # A contre B contre SPY depuis le début
trading-agents heartbeat   # alerte si la routine n'a pas tourné depuis plus de 30 h
```

Les décisions n'ont lieu que le dernier jour de bourse du mois (et au premier lancement).
Les autres jours, la routine met seulement à jour le journal et le duel.

## Critères fixés d'avance (fin février 2027, après 3 décisions mensuelles)

L'analyste est jugé utile seulement si **les trois** conditions sont vraies :
1. B fait mieux que A sur le rendement total ;
2. le drawdown max de B n'est pas pire que celui de A ;
3. au moins 3 vetos ont été posés, et le journal montre qu'ils étaient motivés par des faits.

Trois mois, c'est un petit échantillon : un succès justifie de continuer le test, pas de passer en réel.
Si l'analyste ne pose aucun veto ou si B ne fait pas mieux, on le dit et on reste à 100 % ETF.

## Limites

- Si le PC est éteint le dernier jour du mois, aucun ordre ne part et l'analyste n'examine rien ce mois-là :
  B est alors rejoué comme A pour ce mois, et le compte Alpaca ne suit plus exactement B.
- Le compte paper Alpaca vaut 100 000 $, les portefeuilles A et B sont simulés avec 10 000 $ :
  la comparaison se fait sur A et B, le compte Alpaca sert à tester la chaîne d'ordres.
- Coût de l'analyste : environ 6 appels par mois au modèle `claude-opus-5-5`, quelques dizaines de centimes.
