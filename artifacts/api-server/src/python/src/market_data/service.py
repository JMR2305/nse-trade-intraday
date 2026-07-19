"""Market-data service orchestrator.

DI hub that wires provider → subscription manager → bar builder →
quality tracker → backfill coordinator.  Not wired into src/main.py yet.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from src.market_data.backfill import BackfillCoordinator
from src.market_data.bar_builder import BarBuilder
from src.market_data.contracts import CompletedBar, DataGap, SubscriptionRequest, Tick
from src.market_data.instrument_sync import InstrumentSync
from src.market_data.provider import MarketDataProvider
from src.market_data.quality import DataQualityTracker
from src.market_data.subscription_manager import SubscriptionManager
from src.database.repositories.minute_bars import MinuteBarRepository


class MarketDataService:
    """Orchestrates the market-data pipeline.

    Usage (typical lifecycle):
        service = MarketDataService(provider, bar_repo, instrument_repo)
        await service.start()
        await service.subscribe(SubscriptionRequest(token=123, consumer_id="strategy"))
        ...
        await service.stop()
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        bar_repo: MinuteBarRepository,
        instrument_repo: Any,
        session_factory: Any | None = None,
        backfill_settings: Any | None = None,
        max_subscriptions: int = 3_000,
        subscription_batch_size: int = 100,
    ) -> None:
        self._provider = provider
        self._bar_repo = bar_repo
        self._instrument_repo = instrument_repo
        self._session_factory = session_factory

        self._subscription_manager = SubscriptionManager(
            provider=provider,
            max_subscriptions=max_subscriptions,
            batch_size=subscription_batch_size,
        )
        self._bar_builder = BarBuilder()
        self._quality_tracker = DataQualityTracker()
        self._backfill = BackfillCoordinator(
            provider=provider,
            bar_repo=bar_repo,
            settings=backfill_settings,
        )
        self._instrument_sync = InstrumentSync(
            provider=provider,
            instrument_repo=instrument_repo,
        )

        # Wire internal callbacks
        self._bar_builder.on_bar(self._on_bar)
        self._bar_builder.on_gap(self._on_gap)
        self._bar_builder.on_out_of_order(self._on_out_of_order)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Connect provider and set up tick handler."""
        self._provider.set_tick_handler(self._on_tick)
        await self._provider.connect()

    async def stop(self) -> None:
        """Flush open bars and disconnect provider."""
        self._bar_builder.flush_session_close()
        await self._provider.disconnect()

    # ------------------------------------------------------------------
    # Subscription API
    # ------------------------------------------------------------------
    async def subscribe(self, request: SubscriptionRequest) -> None:
        """Subscribe a consumer to an instrument."""
        await self._subscription_manager.subscribe(request)

    async def unsubscribe(self, instrument_token: int, consumer_id: str) -> None:
        """Unsubscribe a consumer from an instrument."""
        await self._subscription_manager.unsubscribe(instrument_token, consumer_id)

    async def resubscribe_all(self) -> None:
        """Re-subscribe all active tokens (call after reconnect)."""
        await self._subscription_manager.resubscribe_all()

    def set_known_tokens(self, tokens: set[int]) -> None:
        """Update the valid token registry used for subscription validation."""
        self._subscription_manager.set_known_tokens(tokens)

    # ------------------------------------------------------------------
    # Instrument sync
    # ------------------------------------------------------------------
    async def sync_instruments(self, exchange: str = "NSE") -> Any:
        """Run instrument synchronisation for an exchange."""
        return await self._instrument_sync.sync(exchange)

    # ------------------------------------------------------------------
    # Quality API
    # ------------------------------------------------------------------
    def on_quality_event(self, callback: Callable[[Any], Any]) -> None:
        """Register a callback for data-quality state changes."""
        self._quality_tracker.on_event(callback)

    async def get_quality_status(self, instrument_token: int) -> Any | None:
        """Return current quality status for a token."""
        return await self._quality_tracker.get_status(instrument_token)

    # ------------------------------------------------------------------
    # Internal tick pipeline
    # ------------------------------------------------------------------
    def _on_tick(self, tick: Tick) -> None:
        """Called by the provider for every incoming tick."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(
            self._quality_tracker.record_tick(
                tick.instrument_token,
                tick.exchange_timestamp,
                tick.received_at,
            )
        )
        self._bar_builder.process(tick)

    def _on_bar(self, bar: CompletedBar) -> None:
        """Called by BarBuilder when a bar is finalised."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._persist_bar(bar))

    async def _persist_bar(self, bar: CompletedBar) -> None:
        """Persist a completed bar to the repository.

        If session_factory was provided at construction, creates a session,
        inserts the bar, and commits.  If no factory is available, the bar
        is silently dropped (service not yet wired into main.py).
        """
        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                await self._bar_repo.insert_completed_bar(bar, session)
                await session.commit()
        except Exception:
            # Persistence failures must not crash the tick pipeline
            pass

    def _on_gap(self, gap: DataGap) -> None:
        """Called by BarBuilder when a gap is detected."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(
            self._quality_tracker.record_gap(gap.instrument_token, gap.start)
        )
        self._backfill.queue_gap(gap)

    def _on_out_of_order(self, tick: Tick) -> None:
        """Called by BarBuilder for out-of-order ticks."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(
            self._quality_tracker.record_out_of_order(
                tick.instrument_token, tick.exchange_timestamp
            )
        )
