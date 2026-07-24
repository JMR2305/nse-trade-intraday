"""RC-10D: Broker rate limiter.

BrokerRateLimiter enforces per-endpoint sliding-window rate limits using a
monotonic clock and asyncio.Lock.  Each endpoint category has its own bucket.

Limits (defaults from Zerodha API v3 documentation):
  - order_api:    10 req/s
  - quote_api:     1 req/s
  - account_api:   2 req/s
  - historical_api:3 req/s

Raises BrokerRateLimitError when a bucket is exhausted.
Cancellations and risk-critical operations use the order_api bucket.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from src.brokers.exceptions import BrokerRateLimitError
from src.core.logging import logger


@dataclass
class _Bucket:
    """Sliding-window token bucket for one API category."""
    name: str
    max_rps: int
    _timestamps: Deque[float] = field(default_factory=deque)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    throttled_count: int = 0

    async def acquire(self, *, timeout: float = 0.0) -> None:
        """Consume one token.  Raises BrokerRateLimitError if exhausted.

        Parameters
        ----------
        timeout:
            Seconds to wait for a slot before raising.  0 = immediate.
        """
        async with self._lock:
            now = time.monotonic()
            window_start = now - 1.0

            # Evict timestamps outside the 1-second window
            while self._timestamps and self._timestamps[0] < window_start:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.max_rps:
                # Compute how long until the oldest token expires
                wait = self._timestamps[0] - window_start
                if timeout >= wait:
                    await asyncio.sleep(wait)
                    # Evict again after sleep
                    now2 = time.monotonic()
                    ws2 = now2 - 1.0
                    while self._timestamps and self._timestamps[0] < ws2:
                        self._timestamps.popleft()
                else:
                    self.throttled_count += 1
                    logger.warning(
                        f"Rate limit exhausted for {self.name!r}",
                        extra={
                            "event_type": "BROKER_RATE_LIMIT",
                            "bucket": self.name,
                            "current_rps": len(self._timestamps),
                            "max_rps": self.max_rps,
                        },
                    )
                    raise BrokerRateLimitError(
                        f"Rate limit exceeded for {self.name!r} "
                        f"({len(self._timestamps)}/{self.max_rps} req/s)"
                    )

            self._timestamps.append(time.monotonic())

    def metrics(self) -> Dict[str, int]:
        return {
            "bucket": self.name,
            "current_rps": len(self._timestamps),
            "max_rps": self.max_rps,
            "throttled_total": self.throttled_count,
        }


class BrokerRateLimiter:
    """Rate limiter for all Zerodha API categories.

    Usage
    -----
        limiter = BrokerRateLimiter(order_rps=10, quote_rps=1)
        await limiter.acquire_order()
        await limiter.acquire_quote()
    """

    def __init__(
        self,
        *,
        order_rps: int = 10,
        quote_rps: int = 1,
        account_rps: int = 2,
        historical_rps: int = 3,
    ) -> None:
        self._buckets: Dict[str, _Bucket] = {
            "order": _Bucket("order", order_rps),
            "quote": _Bucket("quote", quote_rps),
            "account": _Bucket("account", account_rps),
            "historical": _Bucket("historical", historical_rps),
        }

    async def acquire_order(self, *, timeout: float = 0.0) -> None:
        """Consume one order-API token."""
        await self._buckets["order"].acquire(timeout=timeout)

    async def acquire_quote(self, *, timeout: float = 0.0) -> None:
        """Consume one quote-API token."""
        await self._buckets["quote"].acquire(timeout=timeout)

    async def acquire_account(self, *, timeout: float = 0.0) -> None:
        """Consume one account-API token."""
        await self._buckets["account"].acquire(timeout=timeout)

    async def acquire_historical(self, *, timeout: float = 0.0) -> None:
        """Consume one historical-API token."""
        await self._buckets["historical"].acquire(timeout=timeout)

    def get_metrics(self) -> Dict[str, Dict[str, int]]:
        """Return usage metrics for all buckets."""
        return {name: bucket.metrics() for name, bucket in self._buckets.items()}

    def is_rate_limited(self) -> bool:
        """Return True if any bucket has been throttled recently."""
        return any(b.throttled_count > 0 for b in self._buckets.values())
