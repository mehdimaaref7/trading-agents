"""Indicateurs de performance."""
from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS = 252


def perf_stats(equity: pd.Series) -> dict[str, float]:
    rets = equity.pct_change().dropna()
    years = len(rets) / TRADING_DAYS if len(rets) else 0
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else 0.0
    vol = rets.std() * math.sqrt(TRADING_DAYS) if len(rets) > 1 else 0.0
    sharpe = (rets.mean() / rets.std() * math.sqrt(TRADING_DAYS)) if rets.std() > 0 else 0.0
    dd = (equity / equity.cummax() - 1).min()
    return {
        "rendement_total": total,
        "cagr": cagr,
        "volatilite": vol,
        "sharpe": sharpe,
        "drawdown_max": dd,
        "calmar": cagr / abs(dd) if dd < 0 else 0.0,
    }


def trade_stats(trades) -> dict[str, float]:
    if not trades:
        return {"nb_trades": 0, "taux_gain": 0.0, "gain_moyen": 0.0, "perte_moyenne": 0.0, "stops": 0}
    wins = [t.ret for t in trades if t.pnl > 0]
    losses = [t.ret for t in trades if t.pnl <= 0]
    return {
        "nb_trades": len(trades),
        "taux_gain": len(wins) / len(trades),
        "gain_moyen": sum(wins) / len(wins) if wins else 0.0,
        "perte_moyenne": sum(losses) / len(losses) if losses else 0.0,
        "stops": sum(1 for t in trades if t.reason == "stop"),
    }


def report_markdown(result, title: str = "Backtest momentum tendanciel") -> str:
    s, b = perf_stats(result.equity), perf_stats(result.benchmark)
    t = trade_stats(result.trades)
    pct = lambda x: f"{x:+.1%}"
    lines = [
        f"# {title}",
        "",
        f"Période : {result.equity.index[0].date()} au {result.equity.index[-1].date()}",
        "",
        "| Indicateur | Stratégie | SPY (achat-conservation) |",
        "|---|---|---|",
        f"| Rendement total | {pct(s['rendement_total'])} | {pct(b['rendement_total'])} |",
        f"| Rendement annualisé | {pct(s['cagr'])} | {pct(b['cagr'])} |",
        f"| Volatilité annualisée | {s['volatilite']:.1%} | {b['volatilite']:.1%} |",
        f"| Sharpe | {s['sharpe']:.2f} | {b['sharpe']:.2f} |",
        f"| Drawdown max | {pct(s['drawdown_max'])} | {pct(b['drawdown_max'])} |",
        f"| Calmar | {s['calmar']:.2f} | {b['calmar']:.2f} |",
        "",
        f"Trades : {t['nb_trades']} dont {t['stops']} sortis au stop, "
        f"{t['taux_gain']:.0%} gagnants, gain moyen {pct(t['gain_moyen'])}, perte moyenne {pct(t['perte_moyenne'])}.",
        f"Achats refusés par le gestionnaire de risque : {len(result.rejected)}.",
        "",
        "Limites : biais du survivant (univers actuel), pas de dividendes en cash, "
        "glissement de 5 points de base par exécution.",
    ]
    return "\n".join(lines)
