"""CLI : `trading-agents status` et `trading-agents check SYMBOL QTY PRIX STOP [TP]`."""
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
    a = ap.parse_args(argv)
    try:
        return _status() if a.cmd == "status" else _check(a)
    except ConfigError as e:
        print(f"Configuration : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
