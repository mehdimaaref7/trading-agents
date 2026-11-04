"""Gestionnaire de risque codé en dur.

Aucune décision d'agent ne contourne ce module : chaque ordre passe par
`RiskManager.check_order`. Les limites ne sont pas modifiables par un agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .universe import UNIVERSE


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.10      # 10 % du capital max par ligne
    max_risk_per_trade_pct: float = 0.005  # 0,5 % du capital perdu max si le stop est touché
    max_stop_distance_pct: float = 0.08   # stop au plus à 8 % sous le prix d'entrée
    max_open_positions: int = 10
    max_gross_exposure_pct: float = 1.0   # pas de levier
    min_price: float = 5.0                # pas de penny stocks
    max_daily_loss_pct: float = 0.03      # -3 % sur la journée : coupe-circuit
    max_drawdown_pct: float = 0.15        # -15 % depuis le plus haut : coupe-circuit
    allowed_symbols: frozenset[str] = field(default_factory=lambda: UNIVERSE)


@dataclass(frozen=True)
class Portfolio:
    equity: float                 # valeur totale du compte
    cash: float
    positions: dict[str, float]   # symbole -> valeur de marché (positive = long)
    equity_start_of_day: float
    equity_peak: float


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str          # "buy" ou "sell"
    qty: float
    price: float       # prix d'entrée estimé (limite ou dernier cours)
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str]

    def __bool__(self) -> bool:
        return self.approved


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    # Coupe-circuits au niveau du portefeuille
    def kill_switch_reasons(self, p: Portfolio) -> list[str]:
        L = self.limits
        reasons = []
        if p.equity_start_of_day > 0:
            daily = (p.equity - p.equity_start_of_day) / p.equity_start_of_day
            if daily <= -L.max_daily_loss_pct:
                reasons.append(
                    f"Perte du jour {daily:.1%} au-delà de -{L.max_daily_loss_pct:.0%} : plus d'achat aujourd'hui."
                )
        if p.equity_peak > 0:
            dd = (p.equity - p.equity_peak) / p.equity_peak
            if dd <= -L.max_drawdown_pct:
                reasons.append(
                    f"Drawdown {dd:.1%} au-delà de -{L.max_drawdown_pct:.0%} : trading suspendu, revue humaine requise."
                )
        return reasons

    def check_order(self, o: OrderRequest, p: Portfolio) -> RiskDecision:
        L = self.limits
        reasons: list[str] = []
        side = o.side.lower()
        held = p.positions.get(o.symbol, 0.0)

        if side not in ("buy", "sell"):
            return RiskDecision(False, [f"Sens d'ordre inconnu : {o.side}"])
        if o.qty <= 0 or o.price <= 0:
            return RiskDecision(False, ["Quantité et prix doivent être positifs."])

        # Les ventes qui réduisent une position existante sont toujours permises :
        # on ne bloque jamais une sortie de risque.
        if side == "sell":
            if held <= 0:
                return RiskDecision(False, ["Vente à découvert interdite."])
            if o.qty * o.price > held * 1.001:
                return RiskDecision(False, ["Vente supérieure à la position détenue (découvert interdit)."])
            return RiskDecision(True, [])

        # --- Achats ---
        reasons += self.kill_switch_reasons(p)
        if o.symbol not in L.allowed_symbols:
            reasons.append(f"{o.symbol} hors de l'univers autorisé.")
        if o.price < L.min_price:
            reasons.append(f"Prix {o.price} sous le minimum de {L.min_price}.")

        notional = o.qty * o.price
        if notional > p.cash:
            reasons.append(f"Cash insuffisant ({notional:.2f} demandé, {p.cash:.2f} disponible).")
        if held + notional > L.max_position_pct * p.equity:
            reasons.append(
                f"La ligne {o.symbol} dépasserait {L.max_position_pct:.0%} du capital."
            )
        gross = sum(abs(v) for v in p.positions.values()) + notional
        if gross > L.max_gross_exposure_pct * p.equity:
            reasons.append("Exposition totale au-delà du capital (levier interdit).")
        if held == 0 and sum(1 for v in p.positions.values() if v) >= L.max_open_positions:
            reasons.append(f"Déjà {L.max_open_positions} positions ouvertes.")

        if o.stop_loss is None:
            reasons.append("Stop-loss obligatoire sur tout achat.")
        else:
            if o.stop_loss >= o.price:
                reasons.append("Le stop-loss doit être sous le prix d'entrée.")
            else:
                dist = (o.price - o.stop_loss) / o.price
                if dist > L.max_stop_distance_pct:
                    reasons.append(
                        f"Stop à {dist:.1%} du prix, maximum {L.max_stop_distance_pct:.0%}."
                    )
                risk = (o.price - o.stop_loss) * o.qty
                if risk > L.max_risk_per_trade_pct * p.equity:
                    reasons.append(
                        f"Risque du trade {risk:.2f} au-delà de {L.max_risk_per_trade_pct:.1%} du capital."
                    )
        if o.take_profit is not None and o.take_profit <= o.price:
            reasons.append("Le take-profit doit être au-dessus du prix d'entrée.")

        return RiskDecision(not reasons, reasons)

    def max_qty(self, price: float, stop_loss: float, p: Portfolio) -> int:
        """Taille de position maximale (en actions entières) respectant les limites."""
        L = self.limits
        if stop_loss >= price or price <= 0:
            return 0
        by_risk = (L.max_risk_per_trade_pct * p.equity) / (price - stop_loss)
        by_size = (L.max_position_pct * p.equity) / price
        by_cash = p.cash / price
        return max(0, int(min(by_risk, by_size, by_cash)))
