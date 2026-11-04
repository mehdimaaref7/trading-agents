"""Univers de départ : grandes capitalisations US liquides + ETF de référence.

Volontairement restreint. Toute extension doit passer par une revue.
"""

LARGE_CAPS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "AVGO",
    "JPM", "V", "MA", "UNH", "LLY", "JNJ", "XOM", "PG", "HD", "COST",
    "KO", "PEP", "WMT", "ADBE", "CRM", "NFLX",
]

ETFS = ["SPY", "QQQ", "IWM", "GLD", "TLT", "XLE"]

# Référence de performance : la stratégie doit faire mieux que ça.
BENCHMARK = "SPY"

UNIVERSE = frozenset(LARGE_CAPS + ETFS)
