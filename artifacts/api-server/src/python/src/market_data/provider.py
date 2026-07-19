"""Market-data provider abstraction.

Read-only.  No order-placement methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from src.market_data.contracts import CompletedBar, Tick


TickHandler = Callable[[Tick], Awaitable[None] | None]


class MarketDataProvider(ABC):
    """Abstract read-only market data provider.

    Implementations must be injectable with credentials and must not
    perform any network I/O at import time.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the provider's data feed."""
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully tear down the connection."""
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, tokens: list[int]) -> None:
        """Subscribe to live ticks for the given instrument tokens."""
        raise NotImplementedError

    @abstractmethod
    async def unsubscribe(self, tokens: list[int]) -> None:
        """Unsubscribe from live ticks for the given instrument tokens."""
        raise NotImplementedError

    @abstractmethod
    def set_tick_handler(self, callback: TickHandler) -> None:
        """Register the callback that receives every incoming Tick.

        The provider must invoke ``callback(tick)`` for each tick.
        If the callback is a coroutine function the provider should
        ``await`` it; otherwise it may call it directly.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_historical_bars(
        self,
        token: int,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "minute",
    ) -> list[CompletedBar]:
        """Fetch historical bars from the provider.

        Args:
            token: instrument_token
            from_dt: inclusive start (tz-aware)
            to_dt:   exclusive end (tz-aware)
            interval: bar interval string (default "minute")

        Returns:
            List of CompletedBar in ascending timestamp order.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_instruments(self, exchange: str = "NSE") -> list[dict[str, Any]]:
        """Fetch the full instrument master for an exchange.

        Returns:
            Raw instrument dictionaries.  The caller (instrument_sync)
            is responsible for validation and mapping to internal models.
        """
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return provider health status.

        Must not fake success.  If the provider is disconnected or
        unhealthy, the returned dict must reflect that fact.

        Returns:
            {"status": "healthy" | "degraded" | "unhealthy",
             "details": str | None,
             ...}
        """
        raise NotImplementedError
