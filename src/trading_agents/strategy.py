"""Première stratégie : momentum tendanciel, rééquilibrage mensuel.

Règles (toutes calculées avec les données disponibles à la clôture du jour,
jamais avec le futur) :
1. Filtre de marché : si le SPY clôture sous sa moyenne 200 jours, on ne
   prend aucune nouvelle position (on reste en cash).
2. Filtre de tendance : un titre n'est éligible que s'il clôture au-dessus de
   sa propre moyenne 200 jours.
3. Classement : performance de t-126 à t-21 jours (6 mois en sautant le
   dernier mois, pour éviter l'effet de retournement à court terme).
   On garde les `top_n` meilleurs avec une performance positive.
4. Stop : `atr_mult` x ATR(20) sous l'entrée, borné entre 3 % et 8 %.

Pourquoi des règles fixes et pas un LLM qui décide : une stratégie ne vaut
que si on peut la backtester honnêtement. Un LLM « connaît » déjà le passé
(biais d'anticipation) et ne répond pas deux fois pareil. Le LLM viendra
plus tard comme analyste qui commente et peut mettre un veto, pas comme
générateur de signaux.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Pick:
    symbol: str
    stop_pct: float      # distance du stop sous le prix d'entrée (0.05 = 5 %)
    rationale: str


@dataclass
class MomentumTrend:
    lookback: int = 126
    skip: int = 21
    sma: int = 200
    top_n: int = 6
    atr_window: int = 20
    atr_mult: float = 3.0
    min_stop: float = 0.03
    max_stop: float = 0.08
    benchmark: str = "SPY"
    trailing: bool = False   # stop suiveur : le stop remonte avec le cours

    @property
    def warmup(self) -> int:
        return max(self.lookback, self.sma, self.atr_window) + 1

    def risk_on(self, close: pd.DataFrame) -> bool:
        """Marché haussier : le benchmark clôture au-dessus de sa moyenne 200 jours."""
        if self.benchmark not in close or len(close) < self.sma:
            return True
        b = close[self.benchmark]
        return bool(b.iloc[-1] >= b.iloc[-self.sma:].mean())

    def picks(self, close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame,
              universe: list[str]) -> list[Pick]:
        """`close`, `high`, `low` doivent s'arrêter au jour de décision inclus."""
        if len(close) < self.warmup:
            return []
        last = close.iloc[-1]
        sma = close.iloc[-self.sma:].mean()

        if not self.risk_on(close):
            return []  # marché baissier : cash

        mom = close.iloc[-1 - self.skip] / close.iloc[-1 - self.lookback] - 1
        n = self.atr_window + 1
        h, l, c = high.iloc[-n:], low.iloc[-n:], close.iloc[-n:]
        pc = c.shift(1)
        tr = np.maximum(np.maximum(h - l, (h - pc).abs()), (l - pc).abs())
        atr = tr.iloc[1:].mean()

        cands = []
        for s in universe:
            if s not in close or pd.isna(last.get(s)) or pd.isna(mom.get(s)):
                continue
            if last[s] <= sma[s] or mom[s] <= 0:
                continue
            cands.append((mom[s], s))
        cands.sort(reverse=True)

        out = []
        for m, s in cands[: self.top_n]:
            stop = min(max(self.atr_mult * atr[s] / last[s], self.min_stop), self.max_stop)
            out.append(Pick(s, float(stop),
                            f"{s} : momentum 6 mois {m:+.1%}, au-dessus de sa MM200, stop {stop:.1%}"))
        return out
