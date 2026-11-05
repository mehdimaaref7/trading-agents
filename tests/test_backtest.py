import numpy as np
import pandas as pd

from trading_agents.backtest import run_backtest
from trading_agents.metrics import perf_stats, report_markdown, trade_stats
from trading_agents.strategy import MomentumTrend

SYMS = ["AAPL", "MSFT", "NVDA", "JPM", "KO", "XOM", "SPY"]


def make_panel(n=700, seed=0, drift=None, crash=None):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    drift = drift or {}
    closes = {}
    for k, s in enumerate(SYMS):
        mu = drift.get(s, 0.0003 * (k + 1))
        r = rng.normal(mu, 0.012, n)
        closes[s] = 100 * np.exp(np.cumsum(r))
    c = pd.DataFrame(closes, index=dates)
    if crash:
        sym, day, factor = crash
        c.loc[c.index[day]:, sym] *= factor
    o = c.shift(1).fillna(c.iloc[0]) * (1 + rng.normal(0, 0.002, c.shape))
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    return {"open": o, "high": h, "low": l, "close": c}


UNI = [s for s in SYMS if s != "SPY"]


def test_runs_and_respects_basic_invariants():
    res = run_backtest(make_panel(), UNI)
    assert len(res.equity) > 400
    assert (res.equity > 0).all()
    assert res.trades, "la stratégie devrait trader sur un marché haussier"
    for t in res.trades:
        assert t.qty >= 1 and t.entry > 0


def test_no_lookahead():
    """Changer les données APRÈS une date ne doit rien changer AVANT."""
    p1 = make_panel(seed=1)
    p2 = {k: v.copy() for k, v in p1.items()}
    cut = p1["close"].index[500]
    for k in p2:
        p2[k].loc[p2[k].index > cut] *= 0.5
    e1 = run_backtest(p1, UNI).equity.loc[:cut]
    e2 = run_backtest(p2, UNI).equity.loc[:cut]
    pd.testing.assert_series_equal(e1, e2)


def test_bear_market_filter_keeps_cash():
    drift = {s: -0.004 for s in SYMS}
    res = run_backtest(make_panel(drift=drift, seed=2), UNI)
    assert not res.trades
    assert res.equity.iloc[-1] == res.equity.iloc[0]


def test_stop_exits_at_or_below_stop_on_crash():
    drift = {"NVDA": 0.004}
    res = run_backtest(make_panel(drift=drift, crash=("NVDA", 450, 0.25), seed=3), UNI)
    nv = [t for t in res.trades if t.symbol == "NVDA" and t.reason == "stop"]
    assert nv, "le crash de NVDA doit déclencher un stop"
    for t in nv:
        assert t.exit < t.entry
        assert -0.085 <= t.ret <= -0.029  # sortie au stop (3 à 8 % sous l'entrée), pas au plus bas du krach


def test_position_sizes_respect_risk_limits():
    res = run_backtest(make_panel(seed=4), UNI, initial_cash=10_000)
    eq = res.equity
    for t in res.trades:
        equity_then = eq.loc[:t.entry_date].iloc[-2] if len(eq.loc[:t.entry_date]) > 1 else eq.iloc[0]
        assert t.qty * t.entry <= 0.10 * equity_then * 1.05


def test_strategy_warmup_returns_nothing():
    p = make_panel(n=100)
    assert MomentumTrend().picks(p["close"], p["high"], p["low"], UNI) == []


def test_metrics_and_report():
    res = run_backtest(make_panel(seed=5), UNI)
    s = perf_stats(res.equity)
    assert -1 < s["drawdown_max"] <= 0
    assert trade_stats(res.trades)["nb_trades"] == len(res.trades)
    md = report_markdown(res)
    assert "Sharpe" in md and "SPY" in md


def test_cash_sweep_invests_idle_cash_in_bull_market():
    p = make_panel(seed=4)
    base = run_backtest(p, UNI)
    swept = run_backtest(p, UNI, cash_sweep="SPY")
    # marché haussier synthétique : le cash placé en SPY doit rapporter plus
    assert swept.equity.iloc[-1] > base.equity.iloc[-1]
    # les trades de la stratégie ne changent pas de nature (pas de trade SPY de balayage)
    assert all(t.symbol != "SPY" or t.reason != "balayage" for t in swept.trades)


def test_cash_sweep_respects_bear_filter():
    drift = {s: -0.004 for s in SYMS}
    p = make_panel(drift=drift, seed=2)
    swept = run_backtest(p, UNI, cash_sweep="SPY")
    # en marché baissier, ni la stratégie ni le balayage n'investissent
    assert swept.equity.iloc[-1] >= swept.equity.iloc[0] * 0.98


def test_cash_sweep_has_no_lookahead():
    p1 = make_panel(seed=1)
    p2 = {k: v.copy() for k, v in p1.items()}
    cut = p1["close"].index[500]
    for k in p2:
        p2[k].loc[p2[k].index > cut] *= 0.5
    e1 = run_backtest(p1, UNI, cash_sweep="SPY").equity.loc[:cut]
    e2 = run_backtest(p2, UNI, cash_sweep="SPY").equity.loc[:cut]
    pd.testing.assert_series_equal(e1, e2)
