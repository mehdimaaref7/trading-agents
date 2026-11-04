"""Données de marché historiques via Alpaca (flux IEX gratuit)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from .config import Settings


class MarketData:
    def __init__(self, settings: Settings):
        self.client = StockHistoricalDataClient(settings.api_key, settings.secret_key)

    def daily_bars(self, symbols: list[str], days: int = 365 * 5):
        """Barres journalières ajustées (splits et dividendes), en DataFrame pandas."""
        end = datetime.now(timezone.utc) - timedelta(minutes=20)  # le flux gratuit a 15 min de retard
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=end - timedelta(days=days),
            end=end,
            adjustment="all",
            feed=DataFeed.IEX,
        )
        return self.client.get_stock_bars(req).df


def to_panel(bars) -> dict:
    """Transforme le DataFrame Alpaca (index symbole, date) en
    {"open"|"high"|"low"|"close": DataFrame dates x symboles}."""
    df = bars.reset_index()
    df["date"] = df["timestamp"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    panel = {}
    for field in ("open", "high", "low", "close"):
        panel[field] = df.pivot_table(index="date", columns="symbol", values=field).sort_index()
    # Jours où le benchmark n'a pas coté = jours fériés ou trous de données : on les retire
    return panel
