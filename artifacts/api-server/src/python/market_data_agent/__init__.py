"""
market_data_agent — Phase 10A
Collects and normalises NSE/Zerodha market data; publishes MarketSnapshot.

READ-ONLY · ADVISORY-ONLY
No analysis. No recommendations. No order placement.
"""
from .shared_services import (
    get_market_data_snapshot,
    get_market_data_metrics,
    get_market_data_status,
)

__all__ = [
    "get_market_data_snapshot",
    "get_market_data_metrics",
    "get_market_data_status",
]
