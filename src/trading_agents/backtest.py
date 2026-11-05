"""Moteur de backtest journalier.

Hypothèses (volontairement prudentes) :
- La décision est prise à la clôture du jour t, exécutée à l'ouverture de t+1.
- Glissement (slippage) appliqué à chaque exécution, défavorable.
- Stops vérifiés chaque jour sur le plus bas ; si l'ouverture passe sous le
  stop (gap), on sort à l'ouverture, pas au stop.
- Chaque achat passe par le même RiskManager que le trading paper.
- Pas de fractions d'action, pas de levier, pas de vente à découvert.

Limite connue : l'univers est la liste actuelle des grandes capitalisations,
donc biais du survivant (les perdants d'il y a 5 ans en sont absents).
Les résultats sont donc optimistes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .risk import OrderRequest, Portfolio, RiskManager
from .strategy import MomentumTrend


@dataclass
class Position:
    qty: int
    entry: float
    stop: float
    entry_date: pd.Timestamp
    stop_pct: float = 0.0


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    qty: int
    entry: float
    exit: float
    reason: str

    @property
    def pnl(self) -> float:
        return (self.exit - self.entry) * self.qty

    @property
    def ret(self) -> float:
        return self.exit / self.entry - 1


@dataclass
class BacktestResult:
    equity: pd.Series
    benchmark: pd.Series
    trades: list[Trade]
    rejected: list[tuple[pd.Timestamp, str, list[str]]] = field(default_factory=list)


def _is_rebalance_day(dates: pd.DatetimeIndex, i: int) -> bool:
    """Dernier jour de bourse du mois (décision), exécution le premier jour du mois suivant."""
    return i + 1 < len(dates) and dates[i + 1].month != dates[i].month


def run_backtest(panel: dict[str, pd.DataFrame], universe: list[str],
                 strategy: MomentumTrend | None = None,
                 risk: RiskManager | None = None,
                 initial_cash: float = 10_000.0,
                 slippage: float = 0.0005,
                 benchmark: str = "SPY",
                 start: str | pd.Timestamp | None = None,
                 end: str | pd.Timestamp | None = None,
                 cash_sweep: str | None = None) -> BacktestResult:
    """`start`/`end` limitent la période évaluée ; l'historique antérieur sert
    quand même au calcul des indicateurs (pas de démarrage à froid).

    `cash_sweep` (ex. "SPY") : le cash non utilisé par la stratégie est placé
    dans cet ETF à chaque rééquilibrage mensuel au lieu de dormir à 0 %,
    sauf en marché baissier (filtre de la stratégie), où il reste en cash.
    Cette poche n'est pas une position de la stratégie (pas de stop, hors
    limites par ligne) ; elle est revendue avant chaque rééquilibrage."""
    strategy = strategy or MomentumTrend(benchmark=benchmark)
    risk = risk or RiskManager()
    o, h, l, c = (panel[k] for k in ("open", "high", "low", "close"))
    dates = c.index

    cash = initial_cash
    pos: dict[str, Position] = {}
    trades: list[Trade] = []
    rejected = []
    sweep_qty = 0.0
    execute_month = True
    sweep_allowed = True
    eq_hist = {}
    pending_sells: list[str] = []
    pending_buys: list = []
    prev_eq = peak = initial_cash

    def portfolio(prices: pd.Series, start_eq: float) -> Portfolio:
        values = {s: p.qty * float(prices[s]) for s, p in pos.items()}
        eq = cash + sum(values.values())
        return Portfolio(eq, cash, values, start_eq, max(peak, eq))

    def close_pos(sym, price, date, reason):
        nonlocal cash
        p = pos.pop(sym)
        fill = price * (1 - slippage)
        cash += p.qty * fill
        trades.append(Trade(sym, p.entry_date, date, p.qty, p.entry, fill, reason))

    first = strategy.warmup
    if start is not None:
        first = max(first, int(dates.searchsorted(pd.Timestamp(start))))
    stop_i = len(dates) if end is None else int(dates.searchsorted(pd.Timestamp(end), side="right"))
    if first >= stop_i:
        raise ValueError("Période vide : pas assez d'historique avant la date de début.")
    sweep_allowed = strategy.risk_on(c.iloc[:first])  # décision prise la veille du premier jour
    for i in range(first, stop_i):
        d = dates[i]
        op, hi, lo, cl = o.iloc[i], h.iloc[i], l.iloc[i], c.iloc[i]

        # 1. Ordres décidés la veille, exécutés à l'ouverture
        if cash_sweep and execute_month and sweep_qty and pd.notna(op[cash_sweep]):
            cash += sweep_qty * float(op[cash_sweep]) * (1 - slippage)
            sweep_qty = 0.0
        for s in pending_sells:
            if s in pos and pd.notna(op[s]):
                close_pos(s, float(op[s]), d, "rééquilibrage")
        for pick in pending_buys:
            s = pick.symbol
            if s in pos or pd.isna(op[s]):
                continue
            fill = float(op[s]) * (1 + slippage)
            stop = fill * (1 - pick.stop_pct)
            pf = portfolio(op.fillna(c.iloc[i - 1]), prev_eq)
            qty = risk.max_qty(fill, stop, pf)
            if qty < 1:
                continue
            dec = risk.check_order(OrderRequest(s, "buy", qty, fill, stop), pf)
            if not dec:
                rejected.append((d, s, dec.reasons))
                continue
            cash -= qty * fill
            pos[s] = Position(qty, fill, stop, d, pick.stop_pct)
        pending_sells, pending_buys = [], []
        if cash_sweep and execute_month and sweep_allowed and pd.notna(op[cash_sweep]) and cash > 0:
            px = float(op[cash_sweep]) * (1 + slippage)
            sweep_qty = cash * 0.98 / px   # 2 % gardés en cash
            cash -= sweep_qty * px
        execute_month = False

        # 2. Stops intrajournaliers
        for s in list(pos):
            p = pos[s]
            if pd.notna(lo[s]) and lo[s] <= p.stop:
                exit_px = min(float(op[s]), p.stop)
                close_pos(s, exit_px, d, "stop")

        # 3. Valorisation à la clôture
        values = sum(p.qty * float(cl[s]) for s, p in pos.items())
        if sweep_qty and pd.notna(cl[cash_sweep]):
            values += sweep_qty * float(cl[cash_sweep])
        eq = cash + values
        eq_hist[d] = eq
        peak = max(peak, eq)

        # Stop suiveur : remonte le stop sous le cours de clôture, jamais l'inverse
        if strategy.trailing:
            for s, p in pos.items():
                if pd.notna(cl[s]):
                    p.stop = max(p.stop, float(cl[s]) * (1 - p.stop_pct))

        # 4. Décision du mois
        if i + 1 < stop_i and _is_rebalance_day(dates, i):
            picks = strategy.picks(c.iloc[: i + 1], h.iloc[: i + 1], l.iloc[: i + 1], universe)
            wanted = {p.symbol for p in picks}
            pending_sells = [s for s in pos if s not in wanted]
            pending_buys = [p for p in picks if p.symbol not in pos]
            execute_month = True
            # En marché baissier, le cash reste en cash (on respecte le filtre)
            sweep_allowed = strategy.risk_on(c.iloc[: i + 1])
            # Coupe-circuit drawdown : on n'achète plus, on garde les sorties
            if risk.kill_switch_reasons(Portfolio(eq, cash, {}, prev_eq, peak)):
                pending_buys = []
        prev_eq = eq

    # Clôture des positions restantes pour le décompte des trades
    last = dates[stop_i - 1]
    if sweep_qty:
        cash += sweep_qty * float(c.iloc[stop_i - 1][cash_sweep]) * (1 - slippage)
        sweep_qty = 0.0
    for s in list(pos):
        close_pos(s, float(c.iloc[stop_i - 1][s]), last, "fin du test")

    equity = pd.Series(eq_hist, name="strategie")
    bench_px = c[benchmark].loc[equity.index]
    bench = initial_cash * bench_px / bench_px.iloc[0]
    bench.name = benchmark
    return BacktestResult(equity, bench, trades, rejected)
