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


def _load_panel(a):
    from pathlib import Path

    import pandas as pd

    from .data import MarketData, to_panel
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
    return to_panel(bars), sorted(UNIVERSE)


def _variant(a):
    from .optimize import Variant
    return Variant(a.top_n, a.atr_mult, a.max_stop, a.trailing, a.risk)


def _write(name: str, text: str):
    from pathlib import Path
    out = Path("reports") / name
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def _backtest(a) -> int:
    import pandas as pd

    from .backtest import run_backtest
    from .metrics import report_markdown

    panel, universe = _load_panel(a)
    v = _variant(a)
    result = run_backtest(panel, universe, v.strategy(), v.risk(), initial_cash=a.capital,
                          cash_sweep=a.sweep)
    report = report_markdown(result, title=f"Backtest momentum ({v.label()}"
                             + (f", cash en {a.sweep}" if a.sweep else "") + ")")
    out = _write("backtest.md", report)
    result.equity.to_frame().join(result.benchmark).to_csv("reports/equity.csv")
    pd.DataFrame([{**t.__dict__, "pnl": t.pnl, "ret": t.ret} for t in result.trades]).to_csv(
        "reports/trades.csv", index=False)
    print(report)
    print(f"\nRapport : {out}  |  Courbe : reports/equity.csv  |  Trades : reports/trades.csv")
    return 0


def _fmt_stats(name, s, extra=""):
    return (f"| {name} | {s['cagr']:+.1%} | {s['sharpe']:.2f} | {s['drawdown_max']:+.1%} | {extra} |")


def _optimize(a) -> int:
    import pandas as pd

    from .core_satellite import buy_and_hold
    from .metrics import perf_stats
    from .optimize import evaluate, walk_forward

    panel, universe = _load_panel(a)
    split = pd.Timestamp(a.split)
    prog = lambda k, n: print(f"\r  variante {k}/{n}", end="", flush=True)
    table, best, oos = walk_forward(panel, universe, split=a.split, progress=prog,
                                    cash_sweep=a.sweep)
    print()
    ref = _variant(a)
    ref_in = evaluate(ref, panel, universe, end=split - pd.Timedelta(days=1), cash_sweep=a.sweep)
    ref_oos = evaluate(ref, panel, universe, start=split, cash_sweep=a.sweep)
    spy = panel["close"]["SPY"]
    spy_in = perf_stats(buy_and_hold(spy.loc[ref_in["result"].equity.index]))
    spy_oos = perf_stats(buy_and_hold(spy.loc[oos["result"].equity.index]))

    lines = [f"# Optimisation avec validation hors échantillon (coupure au {split.date()})", "",
             "## Apprentissage : les 5 meilleures variantes (rendement annuel, drawdown limité à 20 %)", "",
             "| Variante | Rendement annuel | Sharpe | Drawdown max | Trades |", "|---|---|---|---|---|"]
    for _, r in table.head(5).iterrows():
        lines.append(_fmt_stats(r["variante"].label(), r, int(r["nb_trades"])))
    lines.append(_fmt_stats("Stratégie actuelle", ref_in, ref_in["nb_trades"]))
    lines.append(_fmt_stats("SPY", spy_in))
    lines += ["", f"## Validation : la n°1 sur des données jamais vues ({split.date()} et après)", "",
              "| Variante | Rendement annuel | Sharpe | Drawdown max | Trades |", "|---|---|---|---|---|",
              _fmt_stats(f"N°1 : {best.label()}", oos, oos["nb_trades"]),
              _fmt_stats("Stratégie actuelle", ref_oos, ref_oos["nb_trades"]),
              _fmt_stats("SPY", spy_oos), "",
              f"{len(table)} variantes testées. Si la n°1 s'effondre en validation, "
              "c'est du surapprentissage : on ne la retient pas."]
    report = "\n".join(lines)
    out = _write("optimisation.md", report)
    print(report)
    print(f"\nRapport : {out}")
    return 0


def _coresat(a) -> int:
    from .backtest import run_backtest
    from .core_satellite import blend, buy_and_hold, monthly_contributions
    from .metrics import perf_stats

    panel, universe = _load_panel(a)
    v = _variant(a)
    sat = run_backtest(panel, universe, v.strategy(), v.risk(), cash_sweep=a.sweep).equity
    core = buy_and_hold(panel["close"][a.core].loc[sat.index])
    mix = blend(core, sat, a.weight)
    lines = [f"# Cœur-satellite : {a.weight:.0%} {a.core} + {1 - a.weight:.0%} stratégie", "",
             f"Satellite : {v.label()}" + (f", cash en {a.sweep}" if a.sweep else ""), "",
             "| Portefeuille | Rendement annuel | Sharpe | Drawdown max | Avec 200 €/mois : investi -> valeur |",
             "|---|---|---|---|---|"]
    for name, eq in ((f"100 % {a.core}", core), ("Cœur-satellite", mix), ("100 % stratégie", sat)):
        d = monthly_contributions(eq, a.monthly).iloc[-1]
        lines.append(_fmt_stats(name, perf_stats(eq),
                                f"{d['investi']:,.0f} -> {d['valeur']:,.0f}".replace(",", " ")))
    lines += ["", f"Versement de {a.monthly:.0f} par mois le premier jour de bourse du mois, "
              "rééquilibrage mensuel des deux poches, sans frais de change ni fiscalité."]
    report = "\n".join(lines)
    out = _write("coeur_satellite.md", report)
    print(report)
    print(f"\nRapport : {out}")
    return 0


def _add_strategy_args(p):
    p.add_argument("--years", type=float, default=5)
    p.add_argument("--refresh", action="store_true", help="Retélécharger les données")
    p.add_argument("--top-n", type=int, default=6)
    p.add_argument("--atr-mult", type=float, default=3.0)
    p.add_argument("--max-stop", type=float, default=0.08, help="Distance max du stop (0.08 = 8 %%)")
    p.add_argument("--trailing", action="store_true", help="Stop suiveur")
    p.add_argument("--risk", type=float, default=0.005, help="Risque max par trade (0.005 = 0,5 %%)")
    p.add_argument("--sweep", default=None, metavar="ETF",
                   help="Placer le cash dormant dans cet ETF (ex. SPY), sauf en marché baissier")


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
    _add_strategy_args(b)
    b.add_argument("--capital", type=float, default=10_000)
    o = sub.add_parser("optimize", help="Teste 72 variantes, choisit sur l'apprentissage, valide hors échantillon")
    _add_strategy_args(o)
    o.add_argument("--split", default="2025-01-01", help="Début de la période de validation")
    cs = sub.add_parser("coresat", help="Cœur ETF + satellite stratégie, avec versements mensuels")
    _add_strategy_args(cs)
    cs.add_argument("--weight", type=float, default=0.75, help="Poids du cœur (0.75 = 75 %%)")
    cs.add_argument("--core", default="SPY")
    cs.add_argument("--monthly", type=float, default=200)
    a = ap.parse_args(argv)
    try:
        handlers = {"backtest": _backtest, "optimize": _optimize, "coresat": _coresat,
                    "check": _check}
        if a.cmd == "status":
            return _status()
        return handlers[a.cmd](a)
    except ConfigError as e:
        print(f"Configuration : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
