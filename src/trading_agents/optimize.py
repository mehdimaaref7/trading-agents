"""Recherche de paramètres avec validation hors échantillon.

Critère de choix : le meilleur rendement annuel parmi les variantes dont le
drawdown reste sous 20 % (on veut battre le marché avec un risque limité ;
classer au Sharpe favoriserait les variantes qui dorment en cash).

Règle anti-surapprentissage : on classe les variantes UNIQUEMENT sur la
période d'apprentissage, on retient la n°1, et on regarde ensuite comment
elle se comporte sur la période de validation, jamais utilisée pour choisir.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import pandas as pd

from .backtest import run_backtest
from .metrics import perf_stats, trade_stats
from .risk import RiskLimits, RiskManager
from .strategy import MomentumTrend

GRID = {
    "top_n": [6, 10],
    "atr_mult": [2.0, 3.0, 4.0],
    "max_stop": [0.08, 0.12, 0.15],
    "trailing": [False, True],
    "risk_per_trade": [0.005, 0.01],
}


@dataclass
class Variant:
    top_n: int
    atr_mult: float
    max_stop: float
    trailing: bool
    risk_per_trade: float

    def strategy(self) -> MomentumTrend:
        return MomentumTrend(top_n=self.top_n, atr_mult=self.atr_mult,
                             max_stop=self.max_stop, trailing=self.trailing)

    def risk(self) -> RiskManager:
        return RiskManager(RiskLimits(max_stop_distance_pct=self.max_stop,
                                      max_risk_per_trade_pct=self.risk_per_trade))

    def label(self) -> str:
        return (f"top {self.top_n}, stop {self.atr_mult:g}xATR max {self.max_stop:.0%}"
                f"{', suiveur' if self.trailing else ''}, risque {self.risk_per_trade:.1%}")


def variants(grid: dict | None = None):
    grid = grid or GRID
    keys = list(grid)
    for combo in itertools.product(*(grid[k] for k in keys)):
        yield Variant(**dict(zip(keys, combo)))


def evaluate(v: Variant, panel, universe, start=None, end=None, cash_sweep=None) -> dict:
    res = run_backtest(panel, universe, v.strategy(), v.risk(), start=start, end=end,
                       cash_sweep=cash_sweep)
    s, t = perf_stats(res.equity), trade_stats(res.trades)
    return {**s, "nb_trades": t["nb_trades"], "result": res}


def walk_forward(panel, universe, split: str = "2025-01-01", min_trades: int = 20,
                 max_drawdown: float = 0.20, progress=None, grid: dict | None = None,
                 cash_sweep: str | None = None) -> tuple[pd.DataFrame, Variant, dict]:
    split_ts = pd.Timestamp(split)
    train_end = split_ts - pd.Timedelta(days=1)
    rows = []
    all_v = list(variants(grid))
    for k, v in enumerate(all_v):
        if progress:
            progress(k + 1, len(all_v))
        r = evaluate(v, panel, universe, end=train_end, cash_sweep=cash_sweep)
        rows.append({"variante": v, "sharpe": r["sharpe"], "cagr": r["cagr"],
                     "drawdown_max": r["drawdown_max"], "nb_trades": r["nb_trades"]})
    df = pd.DataFrame(rows)
    ok = df[(df.nb_trades >= min_trades) & (df.drawdown_max >= -max_drawdown)]
    if ok.empty:
        raise ValueError("Aucune variante ne respecte les contraintes (trades, drawdown).")
    df = ok.sort_values("cagr", ascending=False)
    best = df.iloc[0]["variante"]
    oos = evaluate(best, panel, universe, start=split_ts, cash_sweep=cash_sweep)
    return df, best, oos
