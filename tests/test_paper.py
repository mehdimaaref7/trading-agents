import json
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from trading_agents.analyst import NewsAnalyst, Verdict
from trading_agents.paper import (DuelState, Env, heartbeat_age_hours, is_decision_day,
                                  replay_books, run_daily)
from trading_agents.risk import Portfolio, RiskManager
from trading_agents.strategy import Pick

from test_backtest import make_panel


# ------------------------------------------------------------ faux objets

class FakeTrading:
    def __init__(self, days, today, is_open=False):
        self.days, self.is_open = days, is_open
        self.ts = pd.Timestamp(today).tz_localize("America/New_York") + pd.Timedelta(hours=17)
        self.closed, self.cancelled = [], []

    def get_clock(self):
        return SimpleNamespace(timestamp=self.ts.to_pydatetime(), is_open=self.is_open)

    def get_calendar(self, req):
        return [SimpleNamespace(date=d) for d in self.days]

    def get_orders(self, req):
        return []

    def cancel_order_by_id(self, oid):
        self.cancelled.append(oid)

    def close_position(self, s):
        self.closed.append(s)


class FakeBroker:
    def __init__(self, positions=None):
        self.risk = RiskManager()
        self.positions = positions or {}
        self.sent = []

    def portfolio(self):
        return Portfolio(100_000, 100_000 - sum(self.positions.values()), dict(self.positions),
                         100_000, 100_000)

    def submit(self, order, rationale=""):
        self.sent.append(order)
        return f"id-{order.symbol}"


class FakeAnalyst:
    def __init__(self, veto_symbols=()):
        self.veto_symbols, self.seen = set(veto_symbols), []

    def review(self, pick, as_of):
        self.seen.append(pick.symbol)
        v = pick.symbol in self.veto_symbols
        return Verdict(pick.symbol, v, "enquête de la SEC" if v else "rien de notable", 0.8, headlines=3)


def setup(tmp_path, veto=(), is_open=False, positions=None):
    panel = make_panel(n=600, seed=3, drift={"NVDA": 0.003, "AAPL": 0.002})
    today = panel["close"].index[-1].date()
    days = [d.date() for d in panel["close"].index[-10:]] + \
           [d.date() for d in pd.bdate_range(today + timedelta(days=1), periods=10)]
    env = Env(trading=FakeTrading(days, today, is_open), broker=FakeBroker(positions),
              load_panel=lambda n: panel, analyst=FakeAnalyst(veto),
              state_dir=tmp_path / "state", journal_dir=tmp_path / "journal")
    return env, panel, today


# ------------------------------------------------------------ analyste

def _client_returning(text=None, stop_reason="end_turn", exc=None):
    def create(**kw):
        if exc:
            raise exc
        return SimpleNamespace(stop_reason=stop_reason,
                               content=[SimpleNamespace(type="text", text=text)])
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


PICK = Pick("AAPL", 0.06, "AAPL : momentum +20 %")


def test_analyst_parses_veto():
    a = NewsAnalyst(lambda s: [{"titre": "x"}],
                    client=_client_returning(json.dumps({"veto": True, "reason": "fraude", "confidence": 1.4})))
    v = a.review(PICK, "2026-11-30")
    assert v.veto and v.available and v.confidence == 1.0 and v.headlines == 1


def test_analyst_refusal_means_no_veto():
    a = NewsAnalyst(lambda s: [{"titre": "x"}], client=_client_returning(stop_reason="refusal"))
    v = a.review(PICK, "2026-11-30")
    assert not v.veto and not v.available


def test_analyst_api_error_means_no_veto():
    import anthropic
    import httpx2
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    a = NewsAnalyst(lambda s: [{"titre": "x"}], client=_client_returning(exc=err))
    v = a.review(PICK, "2026-11-30")
    assert not v.veto and not v.available


def test_analyst_without_news_does_not_call_model():
    def boom(**kw):
        raise AssertionError("ne doit pas appeler le modèle")
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=boom)))
    v = NewsAnalyst(lambda s: [], client=client).review(PICK, "2026-11-30")
    assert not v.veto and v.available


# ------------------------------------------------------------ calendrier et duel

def test_is_decision_day():
    days = [date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 30), date(2026, 12, 1)]
    assert is_decision_day(date(2026, 11, 30), days)
    assert not is_decision_day(date(2026, 11, 27), days)
    assert not is_decision_day(date(2026, 11, 28), days)   # samedi


def test_replay_vetoes_only_change_book_b():
    panel = make_panel(n=700, seed=3, drift={"NVDA": 0.003})
    start = panel["close"].index[400].date().isoformat()
    a_only = replay_books(panel, DuelState(start=start))
    first_buys = {t.symbol for t in a_only["A"].trades if t.entry_date == a_only["A"].trades[0].entry_date}
    vetoed = sorted(first_buys)[0]
    state = DuelState(start=start, vetoes=[{"date": start, "symbol": vetoed}])
    books = replay_books(panel, state)
    pd.testing.assert_series_equal(books["A"].equity, a_only["A"].equity)
    b_first = [t for t in books["B"].trades if t.entry_date == books["A"].trades[0].entry_date]
    assert vetoed not in {t.symbol for t in b_first}


# ------------------------------------------------------------ routine

def test_run_daily_first_run_decides_reviews_and_orders(tmp_path):
    env, panel, today = setup(tmp_path, veto={"NVDA"})
    s = run_daily(env)
    assert s["status"] == "ok" and s["decision"]
    assert "NVDA" in env.analyst.seen
    sent = {o.symbol for o in env.broker.sent}
    assert "NVDA" not in sent and sent, "le titre sous veto ne doit pas être acheté"
    for o in env.broker.sent:
        assert o.stop_loss < o.price
    state = json.loads((tmp_path / "state" / "duel.json").read_text(encoding="utf-8"))
    assert state["vetoes"][0]["symbol"] == "NVDA"
    journal = (tmp_path / "journal" / f"{today}.md").read_text(encoding="utf-8")
    assert "VETO" in journal and "enquête de la SEC" in journal
    assert heartbeat_age_hours(tmp_path / "state") < 0.1


def test_run_daily_is_idempotent_same_day(tmp_path):
    env, panel, today = setup(tmp_path)
    run_daily(env)
    n = len(env.broker.sent)
    s = run_daily(env)
    assert not s["decision"] and len(env.broker.sent) == n


def test_run_daily_sells_positions_no_longer_wanted_without_review(tmp_path):
    # HD est dans l'univers mais absent des choix ; TSLA est hors univers (jamais touché)
    env, panel, today = setup(tmp_path, positions={"HD": 5_000.0, "TSLA": 1_000.0})
    run_daily(env)
    assert env.trading.closed == ["HD"]
    assert "HD" not in env.analyst.seen


def test_run_daily_skips_when_market_open(tmp_path):
    env, panel, today = setup(tmp_path, is_open=True)
    s = run_daily(env)
    assert s["status"] == "market_open" and not env.broker.sent
    assert not (tmp_path / "state" / "duel.json").exists()


def test_run_daily_dry_run_sends_nothing(tmp_path):
    env, panel, today = setup(tmp_path)
    env.dry_run = True
    s = run_daily(env)
    assert s["decision"] and not env.broker.sent
    assert all(o["status"] == "dry_run" for o in s["orders"])
