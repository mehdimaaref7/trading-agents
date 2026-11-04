import pytest

from trading_agents.config import ConfigError, load_settings
from trading_agents.risk import OrderRequest, Portfolio, RiskManager


def pf(**kw):
    base = dict(equity=10_000, cash=10_000, positions={},
                equity_start_of_day=10_000, equity_peak=10_000)
    base.update(kw)
    return Portfolio(**base)


rm = RiskManager()


def buy(sym="AAPL", qty=4, price=200, stop=190, tp=None):
    return OrderRequest(sym, "buy", qty, price, stop, tp)


def test_valid_buy_is_approved():
    d = rm.check_order(buy(), pf())
    assert d.approved, d.reasons


def test_stop_loss_is_mandatory():
    d = rm.check_order(buy(stop=None), pf())
    assert not d and any("Stop-loss obligatoire" in r for r in d.reasons)


def test_stop_too_far():
    assert not rm.check_order(buy(stop=150), pf())


def test_stop_above_price():
    assert not rm.check_order(buy(stop=210), pf())


def test_position_size_cap():
    # 6 x 200 = 1200 > 10 % de 10 000
    assert not rm.check_order(buy(qty=6, stop=198), pf())



def test_risk_per_trade_rejects():
    # limite 0,5 % de 10 000 = 50
    assert rm.check_order(buy(qty=5, price=200, stop=190), pf()).approved  # risque 50
    d = rm.check_order(buy(qty=5, price=200, stop=188), pf())               # risque 60
    assert not d and any("Risque du trade" in r for r in d.reasons)


def test_symbol_outside_universe():
    assert not rm.check_order(buy(sym="GME"), pf())


def test_penny_stock():
    from trading_agents.risk import RiskLimits
    r = RiskManager(RiskLimits(allowed_symbols=frozenset({"XYZ"})))
    assert not r.check_order(OrderRequest("XYZ", "buy", 10, 3, 2.9), pf())


def test_insufficient_cash():
    assert not rm.check_order(buy(), pf(cash=500))


def test_no_leverage():
    positions = {s: 1000 for s in ["MSFT", "NVDA", "AMZN", "META", "JPM", "V", "MA", "KO", "PG", "HD"]}
    assert not rm.check_order(buy(qty=1), pf(cash=10_000, positions=positions))


def test_max_open_positions():
    positions = {s: 500 for s in ["MSFT", "NVDA", "AMZN", "META", "JPM", "V", "MA", "KO", "PG", "HD"]}
    d = rm.check_order(buy(qty=1), pf(cash=5_000, positions=positions))
    assert any("positions ouvertes" in r for r in d.reasons)


def test_daily_loss_kill_switch():
    d = rm.check_order(buy(), pf(equity=9_650, cash=9_650))
    assert not d and any("Perte du jour" in r for r in d.reasons)


def test_drawdown_kill_switch():
    d = rm.check_order(buy(), pf(equity=8_400, cash=8_400, equity_start_of_day=8_400))
    assert not d and any("Drawdown" in r for r in d.reasons)


def test_sell_allowed_even_during_kill_switch():
    d = rm.check_order(OrderRequest("AAPL", "sell", 2, 200), pf(
        equity=8_000, positions={"AAPL": 400}, equity_start_of_day=9_000))
    assert d.approved


def test_short_selling_forbidden():
    assert not rm.check_order(OrderRequest("AAPL", "sell", 1, 200), pf())


def test_take_profit_below_price():
    assert not rm.check_order(buy(tp=195), pf())


def test_max_qty():
    # risque: 50/10 = 5 ; taille: 1000/200 = 5 ; cash: 50 -> 5
    assert rm.max_qty(200, 190, pf()) == 5


def test_live_mode_refused(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setenv("ALPACA_PAPER_TRADE", "false")
    with pytest.raises(ConfigError):
        load_settings()


def test_missing_keys(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(ConfigError):
        load_settings()
