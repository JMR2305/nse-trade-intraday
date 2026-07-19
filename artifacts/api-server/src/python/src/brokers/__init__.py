"""Broker adapters package."""
# Preserve existing exports — append new ones only.
# If PaperBroker or other adapters are added by the main project,
# they should remain above this line.

try:
    from src.brokers.zerodha_market_data import ZerodhaMarketDataProvider
    __all__ = ["ZerodhaMarketDataProvider"]
except ImportError:
    __all__ = []
