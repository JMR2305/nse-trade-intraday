"""Reference-counted, deduplicated subscription manager.

Thread/async safe.  Batches subscribe/unsubscribe calls to the upstream
provider.  Supports resubscription after reconnect.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.market_data.contracts import SubscriptionRequest
from src.market_data.provider import MarketDataProvider


class SubscriptionManager:
    """Manages deduplicated subscriptions with reference counting.

    Args:
        provider: the upstream MarketDataProvider
        max_subscriptions: hard ceiling on total unique tokens
        batch_size: max tokens per single subscribe/unsubscribe call
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        max_subscriptions: int = 3_000,
        batch_size: int = 100,
    ) -> None:
        self._provider = provider
        self._max_subscriptions = max_subscriptions
        self._batch_size = batch_size
        self._lock = asyncio.Lock()
        # token -> set of consumer_ids
        self._refs: dict[int, set[str]] = defaultdict(set)
        # token -> metadata
        self._meta: dict[int, _TokenMeta] = {}
        # known valid tokens (injected by caller, e.g. instrument master)
        self._known_tokens: set[int] = set()

    # ------------------------------------------------------------------
    # Token registry (used for validation)
    # ------------------------------------------------------------------
    def set_known_tokens(self, tokens: set[int]) -> None:
        """Update the set of instrument tokens considered valid."""
        self._known_tokens = set(tokens)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def subscribe(self, request: SubscriptionRequest) -> None:
        """Add a consumer reference for a token.

        If the token is new (refcount goes from 0→1) a batched upstream
        subscribe is issued.
        """
        token = request.instrument_token
        consumer = request.consumer_id

        if token not in self._known_tokens:
            raise ValueError(
                f"instrument_token {token} is not in the known instrument master"
            )

        async with self._lock:
            current_count = len(self._refs)
            is_new = token not in self._refs or len(self._refs[token]) == 0

            if is_new and current_count >= self._max_subscriptions:
                raise RuntimeError(
                    f"subscription limit ({self._max_subscriptions}) reached"
                )

            self._refs[token].add(consumer)
            if is_new:
                self._meta[token] = _TokenMeta(subscribed_at=datetime.now(timezone.utc))
                await self._batch_subscribe([token])

    async def unsubscribe(self, instrument_token: int, consumer_id: str) -> None:
        """Remove a consumer reference for a token.

        If the refcount drops to 0 a batched upstream unsubscribe is issued.
        """
        async with self._lock:
            consumers = self._refs.get(instrument_token)
            if consumers is None:
                return
            consumers.discard(consumer_id)
            if not consumers:
                del self._refs[instrument_token]
                self._meta.pop(instrument_token, None)
                await self._batch_unsubscribe([instrument_token])

    async def resubscribe_all(self) -> None:
        """Re-issue subscriptions for all tokens with active references.

        Call this after a provider reconnect to restore the subscription
        state on the new connection.
        """
        async with self._lock:
            tokens = list(self._refs.keys())
        if not tokens:
            return
        for i in range(0, len(tokens), self._batch_size):
            batch = tokens[i : i + self._batch_size]
            await self._provider.subscribe(batch)

    def snapshot(self) -> dict[int, set[str]]:
        """Return a shallow copy of the current subscription map."""
        return {tok: set(consumers) for tok, consumers in self._refs.items()}

    def is_subscribed(self, instrument_token: int) -> bool:
        """Return True if the token has at least one active consumer."""
        return instrument_token in self._refs and len(self._refs[instrument_token]) > 0

    def consumer_count(self, instrument_token: int) -> int:
        """Return the number of consumers for a token."""
        return len(self._refs.get(instrument_token, set()))

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------
    async def _batch_subscribe(self, tokens: list[int]) -> None:
        for i in range(0, len(tokens), self._batch_size):
            batch = tokens[i : i + self._batch_size]
            await self._provider.subscribe(batch)

    async def _batch_unsubscribe(self, tokens: list[int]) -> None:
        for i in range(0, len(tokens), self._batch_size):
            batch = tokens[i : i + self._batch_size]
            await self._provider.unsubscribe(batch)


@dataclass
class _TokenMeta:
    """Per-token metadata."""
    subscribed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_error: str | None = None
