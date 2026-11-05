"""Étape 3 : duel en paper trading.

- Portefeuille A : la stratégie momentum seule.
- Portefeuille B : la même stratégie, mais chaque nouvel achat passe d'abord
  par l'agent analyste, qui peut mettre un veto.

Les deux portefeuilles sont rejoués chaque jour avec le moteur de backtest,
sur les vraies données depuis le début du duel : mêmes règles d'exécution,
seuls les vetos diffèrent. C'est la comparaison qui compte.
Le portefeuille B est en plus répliqué sur le compte paper Alpaca, pour
tester la chaîne réelle (ordres, stops chez le broker).

La routine tourne une fois par jour de bourse, APRÈS la clôture de New York.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .core_satellite import buy_and_hold
from .metrics import perf_stats
from .risk import OrderRequest, RiskManager
from .strategy import MomentumTrend
from .universe import BENCHMARK, UNIVERSE

INITIAL_CAPITAL = 10_000.0


# ---------------------------------------------------------------- état

@dataclass
class DuelState:
    start: str                                   # premier jour du duel (AAAA-MM-JJ)
    vetoes: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path, today: date) -> "DuelState":
        if path.exists():
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        return cls(start=today.isoformat())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def veto_set(self) -> set[tuple[str, str]]:
        return {(v["date"], v["symbol"]) for v in self.vetoes}


def write_heartbeat(state_dir: Path, status: str, **extra) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    hb = {"last_run": datetime.now(timezone.utc).isoformat(), "status": status, **extra}
    (state_dir / "heartbeat.json").write_text(json.dumps(hb, ensure_ascii=False, indent=1),
                                              encoding="utf-8")


def heartbeat_age_hours(state_dir: Path) -> float | None:
    p = state_dir / "heartbeat.json"
    if not p.exists():
        return None
    last = datetime.fromisoformat(json.loads(p.read_text(encoding="utf-8"))["last_run"])
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600


# ---------------------------------------------------------------- calendrier

def is_decision_day(today: date, trading_days: list[date]) -> bool:
    """Dernier jour de bourse du mois : la décision se prend à la clôture."""
    if today not in trading_days:
        return False
    later = [d for d in trading_days if d > today]
    return bool(later) and later[0].month != today.month


# ---------------------------------------------------------------- portefeuilles

def replay_books(panel: dict, state: DuelState, strategy: MomentumTrend | None = None,
                 universe: list[str] | None = None) -> dict | None:
    """Rejoue A et B depuis le début du duel. None si pas encore de données."""
    strategy = strategy or MomentumTrend()
    universe = universe or sorted(UNIVERSE)
    kw = dict(start=state.start, initial_cash=INITIAL_CAPITAL, decide_on_first_day=True)
    try:
        a = run_backtest(panel, universe, strategy, **kw)
        b = run_backtest(panel, universe, strategy, vetoes=state.veto_set(), **kw)
    except ValueError:
        return None
    spy = buy_and_hold(panel["close"][BENCHMARK].loc[a.equity.index], INITIAL_CAPITAL)
    return {"A": a, "B": b, "SPY": spy}


def duel_table(books: dict) -> str:
    rows = ["| Portefeuille | Valeur | Depuis le début | Drawdown max | Trades |",
            "|---|---|---|---|---|"]
    for name, label in (("A", "A : stratégie seule"), ("B", "B : stratégie + analyste")):
        eq = books[name].equity
        s = perf_stats(eq) if len(eq) > 1 else {"rendement_total": 0.0, "drawdown_max": 0.0}
        rows.append(f"| {label} | {eq.iloc[-1]:,.0f} $ | {s['rendement_total']:+.2%} | "
                    f"{s['drawdown_max']:+.2%} | {len(books[name].trades)} |")
    spy = books["SPY"]
    s = perf_stats(spy) if len(spy) > 1 else {"rendement_total": 0.0, "drawdown_max": 0.0}
    rows.append(f"| SPY (référence) | {spy.iloc[-1]:,.0f} $ | {s['rendement_total']:+.2%} | "
                f"{s['drawdown_max']:+.2%} | |")
    return "\n".join(rows)


# ---------------------------------------------------------------- routine

@dataclass
class Env:
    """Dépendances de la routine (injectées pour pouvoir tester sans réseau)."""
    trading: object             # alpaca TradingClient (get_clock, get_calendar, get_orders...)
    broker: object              # AlpacaBroker (portfolio, submit, risk)
    load_panel: object          # callable(days) -> panel
    analyst: object             # NewsAnalyst (review)
    state_dir: Path = Path("state")
    journal_dir: Path = Path("journal")
    dry_run: bool = False


def _trading_days(trading, today: date) -> list[date]:
    from alpaca.trading.requests import GetCalendarRequest
    cal = trading.get_calendar(GetCalendarRequest(start=today - timedelta(days=7),
                                                  end=today + timedelta(days=14)))
    return [c.date if isinstance(c.date, date) else date.fromisoformat(str(c.date)) for c in cal]


def _cancel_open_orders(trading, symbol: str) -> None:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    for o in trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])):
        trading.cancel_order_by_id(o.id)


def run_daily(env: Env, today: date | None = None) -> dict:
    """Une exécution de la routine. Renvoie un résumé (aussi écrit dans le journal)."""
    state_path = env.state_dir / "duel.json"
    clock = env.trading.get_clock()
    now_ny = pd.Timestamp(clock.timestamp).tz_convert("America/New_York")
    today = today or now_ny.date()
    log: list[str] = []
    summary = {"date": today.isoformat(), "decision": False, "orders": [], "reviews": []}

    if clock.is_open:
        write_heartbeat(env.state_dir, "marché ouvert : relancer après la clôture",
                        date=today.isoformat())
        summary["status"] = "market_open"
        return summary

    days = _trading_days(env.trading, today)
    if today not in days:
        write_heartbeat(env.state_dir, "jour sans bourse", date=today.isoformat())
        summary["status"] = "market_closed_today"
        return summary

    state = DuelState.load(state_path, today)
    first_run = not state_path.exists()
    decision_today = first_run or is_decision_day(today, days)
    if today.isoformat() in state.decisions:
        decision_today = False                     # déjà décidé aujourd'hui (relance)

    span = (today - date.fromisoformat(state.start)).days + 420   # +chauffe 200 séances
    panel = env.load_panel(span)
    last_bar = panel["close"].index[-1].date()
    if last_bar != today:
        log.append(f"Attention : dernière barre au {last_bar}, pas au {today} (données en retard).")
        decision_today = False

    strategy = MomentumTrend()
    if decision_today:
        summary["decision"] = True
        state.decisions.append(today.isoformat())
        c, h, l = panel["close"], panel["high"], panel["low"]
        picks = strategy.picks(c, h, l, sorted(UNIVERSE))
        wanted = {p.symbol for p in picks}
        pf = env.broker.portfolio()
        held = {s for s in pf.positions if s in UNIVERSE}
        log.append(f"Décision du mois : {', '.join(sorted(wanted)) or 'aucun titre (cash)'}")

        # Ventes : titres détenus qui ne sont plus retenus (jamais soumises à veto)
        for s in sorted(held - wanted):
            summary["orders"].append({"symbol": s, "side": "sell", "status": "dry_run" if env.dry_run else "sent"})
            if not env.dry_run:
                _cancel_open_orders(env.trading, s)
                env.trading.close_position(s)

        # Achats : chaque nouvel achat passe par l'analyste
        for p in picks:
            if p.symbol in held:
                continue
            v = env.analyst.review(p, today.isoformat())
            rec = {"date": today.isoformat(), **v.to_dict()}
            state.reviews.append(rec)
            summary["reviews"].append(rec)
            if v.veto:
                state.vetoes.append({"date": today.isoformat(), "symbol": p.symbol,
                                     "reason": v.reason, "confidence": v.confidence})
                continue
            price = float(c[p.symbol].iloc[-1])
            stop = price * (1 - p.stop_pct)
            qty = env.broker.risk.max_qty(price, stop, pf)
            order = {"symbol": p.symbol, "side": "buy", "qty": qty, "price": round(price, 2),
                     "stop": round(stop, 2)}
            if qty < 1:
                order["status"] = "taille nulle"
            elif env.dry_run:
                order["status"] = "dry_run"
            else:
                try:
                    order["id"] = env.broker.submit(OrderRequest(p.symbol, "buy", qty, price, stop),
                                                    rationale=p.rationale)
                    order["status"] = "sent"
                except Exception as e:     # refus du RiskManager ou du broker : on journalise
                    order["status"] = f"refusé : {e}"
            summary["orders"].append(order)
            state.orders.append({"date": today.isoformat(), **order})

    state.save(state_path)
    books = replay_books(panel, state, strategy)
    summary["status"] = "ok"
    _write_journal(env, today, summary, books, log)
    write_heartbeat(env.state_dir, "ok", date=today.isoformat(), decision=summary["decision"])
    return summary


def _write_journal(env: Env, today: date, summary: dict, books: dict | None, log: list[str]) -> Path:
    lines = [f"# Journal du {today.isoformat()}", ""]
    lines += [f"- {x}" for x in log]
    if summary["decision"]:
        lines += ["", "## Revue de l'analyste", ""]
        if not summary["reviews"]:
            lines.append("Aucun nouvel achat à examiner.")
        for r in summary["reviews"]:
            verdict = "VETO" if r["veto"] else ("OK" if r["available"] else "OK (analyste indisponible)")
            lines.append(f"- **{r['symbol']}** : {verdict} ({r['confidence']:.0%}, "
                         f"{r['headlines']} articles). {r['reason']}")
        lines += ["", "## Ordres (portefeuille B sur le compte paper)", ""]
        if not summary["orders"]:
            lines.append("Aucun ordre.")
        for o in summary["orders"]:
            extra = f" x{o['qty']} vers {o['price']} $, stop {o['stop']} $" if o["side"] == "buy" else ""
            lines.append(f"- {o['side']} {o['symbol']}{extra} : {o['status']}")
    lines += ["", "## Duel depuis le début", ""]
    lines.append(duel_table(books) if books else "Pas encore de séance complète à comparer.")
    if not summary["decision"]:
        lines += ["", "Pas de décision aujourd'hui (rééquilibrage le dernier jour de bourse du mois)."]
    env.journal_dir.mkdir(parents=True, exist_ok=True)
    out = env.journal_dir / f"{today.isoformat()}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
