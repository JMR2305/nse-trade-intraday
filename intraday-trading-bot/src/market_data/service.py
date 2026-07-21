"""Stub for market_data/service.py - RC-6 frozen module."""
from typing import Callable, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime

from market_data.contracts import Tick, CompletedBar, Quote


class MarketDataService:
    """Minimal stub for MarketDataService."""

    def __init__(self):
        self._subscribers: Dict[str, list] = {}
        self._snapshots: Dict[str, dict] = {}

    async def subscribe(self, instrument_token: str, callback: Callable) -> None:
        if instrument_token not in self._subscribers:
            self._subscribers[instrument_token] = []
        self._subscribers[instrument_token].append(callback)

    async def unsubscribe(self, instrument_token: str, callback: Callable) -> None:
        if instrument_token in self._subscribers:
            if callback in self._subscribers[instrument_token]:
                self._subscribers[instrument_token].remove(callback)

    def get_snapshot(self, instrument_token: str) -> Optional[dict]:
        return self._snapshots.get(instrument_token)

    def set_snapshot(self, instrument_token: str, snapshot: dict) -> None:
        self._snapshots[instrument_token] = snapshot

    async def publish_bar(self, instrument_token: str, bar) -> None:
        """Deliver a bar directly to all subscribers for the given token.

        Calls each subscriber synchronously (subscribers are sync callbacks
        like StrategyRuntime._on_market_data which schedule async tasks
        internally). Use this in tests instead of accessing _subscribers.
        """
        for callback in list(self._subscribers.get(instrument_token, [])):
            callback(bar)
