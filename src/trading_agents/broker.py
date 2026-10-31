"""Accès au compte Alpaca. Tout ordre passe obligatoirement par le RiskManager."""
from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    GetPortfolioHistoryRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from .config import Settings
from .journal import log_event
from .risk import OrderRequest, Portfolio, RiskDecision, RiskManager


class OrderRejected(RuntimeError):
    def __init__(self, decision: RiskDecision):
        super().__init__("; ".join(decision.reasons))
        self.decision = decision


class AlpacaBroker:
    def __init__(self, settings: Settings, risk: RiskManager | None = None):
        if not settings.paper:
            raise RuntimeError("Ce broker n'accepte que le mode paper pour l'instant.")
        self.client = TradingClient(settings.api_key, settings.secret_key, paper=True)
        self.risk = risk or RiskManager()

    def portfolio(self) -> Portfolio:
        acct = self.client.get_account()
        positions = {
            p.symbol: float(p.market_value) for p in self.client.get_all_positions()
        }
        equity = float(acct.equity)
        peak = equity
        try:
            hist = self.client.get_portfolio_history(
                GetPortfolioHistoryRequest(period="1A", timeframe="1D")
            )
            values = [v for v in (hist.equity or []) if v]
            if values:
                peak = max(max(values), equity)
        except Exception:  # l'historique est un plus, pas un prérequis
            pass
        return Portfolio(
            equity=equity,
            cash=float(acct.cash),
            positions=positions,
            equity_start_of_day=float(acct.last_equity),
            equity_peak=peak,
        )

    def submit(self, order: OrderRequest, rationale: str = "") -> str:
        """Vérifie l'ordre puis l'envoie. Renvoie l'id Alpaca ou lève OrderRejected."""
        p = self.portfolio()
        decision = self.risk.check_order(order, p)
        log_event(
            "risk_check",
            order=order.__dict__,
            approved=decision.approved,
            reasons=decision.reasons,
            rationale=rationale,
            equity=p.equity,
        )
        if not decision:
            raise OrderRejected(decision)

        side = OrderSide.BUY if order.side.lower() == "buy" else OrderSide.SELL
        kwargs = dict(symbol=order.symbol, qty=order.qty, side=side,
                      time_in_force=TimeInForce.DAY)
        if side == OrderSide.BUY:
            # Achat toujours protégé : stop (OTO) ou stop + objectif (bracket).
            kwargs["stop_loss"] = StopLossRequest(stop_price=round(order.stop_loss, 2))
            if order.take_profit is not None:
                kwargs["order_class"] = OrderClass.BRACKET
                kwargs["take_profit"] = TakeProfitRequest(limit_price=round(order.take_profit, 2))
            else:
                kwargs["order_class"] = OrderClass.OTO
        result = self.client.submit_order(MarketOrderRequest(**kwargs))
        log_event("order_submitted", order_id=str(result.id), symbol=order.symbol,
                  side=order.side, qty=order.qty)
        return str(result.id)
