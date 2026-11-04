"""CLI : `status`, `check SYMBOL QTY PRIX STOP [TP]` et `backtest`."""
from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_settings
from .risk import OrderRequest, RiskManager


def _status() -> int:
    from .broker import AlpacaBroker
    broker = AlpacaBroker(load_settings())
    p = broker.portfolio()
    print(f"Capital : {p.equity:,.2f} $  |  Cash : {p.cash:,.2f} $")
    print(f"Début de journée : {p.equity_start_of_day:,.2f} $  |  Plus haut : {p.equity_peak:,.2f} $")
    for sym, val in sorted(p.positions.items()):
        print(f"  {sym:6s} {val:>12,.2f} $  ({val / p.equity:.1%})")
    ks = broker.risk.kill_switch_reasons(p)
    print("Coupe-circuit : " + ("; ".join(ks) if ks else "aucun"))
    return 0


def _check(a) -> int:
    from .broker import AlpacaBroker
    broker = AlpacaBroker(load_settings())
    p = broker.portfolio()
    o = OrderRequest(a.symbol.upper(), "buy", a.qty, a.price, a.stop, a.take_profit)
    d = RiskManager().check_order(o, p)
    print("APPROUVÉ" if d else "REFUSÉ")
    for r in d.reasons:
        print(" -", r)
    print(f"Taille max conseillée : {RiskManager().max_qty(a.price, a.stop, p)} actions")
    return 0 if d else 1


def _backtest(a) -> int:
    from pathlib import Path

    import pandas as pd

    from .backtest import run_backtest
    from .data import MarketData, to_panel
    from .metrics import report_markdown
    from .strategy import MomentumTrend
    from .universe import BENCHMARK, UNIVERSE

    cache = Path("data/bars.pkl")
    if cache.exists() and not a.refresh:
        bars = pd.read_pickle(cache)
    else:
        md = MarketData(load_settings())
        symbols = sorted(UNIVERSE | {BENCHMARK})
        bars = md.daily_bars(symbols, days=int(365 * (a.years + 1.2)))  # +1 an de chauffe
        cache.parent.mkdir(exist_ok=True)
        bars.to_pickle(cache)
    panel = to_panel(bars)
    universe = sorted(UNIVERSE)
    result = run_backtest(panel, universe, MomentumTrend(top_n=a.top_n),
                          initial_cash=a.capital)
    report = report_markdown(result)
    out = Path("reports/backtest.md")
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    result.equity.to_frame().join(result.benchmark).to_csv("reports/equity.csv")
    print(report)
    print(f"\nRapport : {out}  |  Courbe : reports/equity.csv")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trading-agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="État du compte paper et des coupe-circuits")
    c = sub.add_parser("check", help="Simule le contrôle de risque d'un achat (sans l'envoyer)")
    c.add_argument("symbol")
    c.add_argument("qty", type=float)
    c.add_argument("price", type=float)
    c.add_argument("stop", type=float)
    c.add_argument("take_profit", type=float, nargs="?")
    b = sub.add_parser("backtest", help="Backtest de la stratégie momentum vs SPY")
    b.add_argument("--years", type=float, default=5)
    b.add_argument("--capital", type=float, default=10_000)
    b.add_argument("--top-n", type=int, default=6)
    b.add_argument("--refresh", action="store_true", help="Retélécharger les données")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "backtest":
            return _backtest(a)
        return _status() if a.cmd == "status" else _check(a)
    except ConfigError as e:
        print(f"Configuration : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
