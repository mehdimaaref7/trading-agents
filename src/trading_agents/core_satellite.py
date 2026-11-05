"""Cadre cœur-satellite et simulation de versements mensuels.

- Cœur : un ETF large (SPY par défaut) acheté et conservé.
- Satellite : la stratégie active des agents.
Les deux poches sont rééquilibrées vers leurs poids cibles chaque mois.
"""
from __future__ import annotations

import pandas as pd


def buy_and_hold(close: pd.Series, initial: float = 10_000.0) -> pd.Series:
    close = close.dropna()
    return initial * close / close.iloc[0]


def blend(core: pd.Series, satellite: pd.Series, core_weight: float = 0.75) -> pd.Series:
    """Portefeuille cœur-satellite rééquilibré le premier jour de chaque mois."""
    idx = core.index.intersection(satellite.index)
    rc = core.loc[idx].pct_change().fillna(0.0)
    rs = satellite.loc[idx].pct_change().fillna(0.0)
    total = float(core.loc[idx].iloc[0])
    vc, vs = total * core_weight, total * (1 - core_weight)
    out = {}
    prev = None
    for d in idx:
        if prev is not None and d.month != prev.month:
            total = vc + vs
            vc, vs = total * core_weight, total * (1 - core_weight)
        vc *= 1 + rc[d]
        vs *= 1 + rs[d]
        out[d] = vc + vs
        prev = d
    return pd.Series(out, name=f"coeur_{core_weight:.0%}")


def monthly_contributions(equity: pd.Series, monthly: float = 200.0) -> pd.DataFrame:
    """Applique un versement fixe au premier jour de bourse de chaque mois
    sur les rendements de `equity`. Renvoie investi cumulé et valeur."""
    r = equity.pct_change().fillna(0.0)
    value = invested = 0.0
    rows = {}
    prev = None
    for d in equity.index:
        value *= 1 + r[d]
        if prev is None or d.month != prev.month:
            value += monthly
            invested += monthly
        rows[d] = (invested, value)
        prev = d
    return pd.DataFrame.from_dict(rows, orient="index", columns=["investi", "valeur"])
