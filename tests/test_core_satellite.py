import pandas as pd
import pytest

from trading_agents.core_satellite import blend, buy_and_hold, monthly_contributions
from trading_agents.optimize import Variant, walk_forward

from test_backtest import UNI, make_panel


def series(vals):
    return pd.Series(vals, index=pd.bdate_range("2024-01-29", periods=len(vals)), dtype=float)


def test_blend_full_core_equals_core():
    core = series([100, 110, 121, 100, 130])
    sat = series([100, 90, 95, 99, 80])
    pd.testing.assert_series_equal(blend(core, sat, 1.0), core, check_names=False, check_freq=False)


def test_blend_is_between_sleeves():
    core = buy_and_hold(series([100 + i for i in range(60)]))
    sat = buy_and_hold(series([100 - 0.2 * i for i in range(60)]))
    mix = blend(core, sat, 0.75)
    assert sat.iloc[-1] < mix.iloc[-1] < core.iloc[-1]


def test_monthly_contributions_flat_market():
    eq = series([100.0] * 45)  # 45 jours ouvrés à partir de fin janvier = 3 mois
    d = monthly_contributions(eq, 200).iloc[-1]
    assert d["investi"] == pytest.approx(d["valeur"])
    assert d["investi"] == 200 * eq.index.to_period("M").nunique()


def test_risk_limits_follow_variant():
    v = Variant(top_n=6, atr_mult=3, max_stop=0.15, trailing=True, risk_per_trade=0.01)
    assert v.risk().limits.max_stop_distance_pct == 0.15
    assert v.strategy().trailing


def test_walk_forward_picks_on_train_only():
    panel = make_panel(n=900, seed=11)
    split = panel["close"].index[700]
    grid = {"top_n": [3, 5], "atr_mult": [3.0], "max_stop": [0.08], "trailing": [False, True],
            "risk_per_trade": [0.005]}
    table, best, oos = walk_forward(panel, UNI, split=str(split.date()), min_trades=1, grid=grid)
    assert len(table) <= 4
    assert oos["result"].equity.index[0] >= split
    # changer les données de validation ne doit pas changer le choix
    p2 = {k: v.copy() for k, v in panel.items()}
    for k in p2:
        p2[k].loc[p2[k].index >= split] *= 0.5
    _, best2, _ = walk_forward(p2, UNI, split=str(split.date()), min_trades=1, grid=grid)
    assert best2 == best
