"""Per-instrument data quality tracker.

Tracks state transitions and emits structured events.
All thresholds are configurable via ``DataQualitySettings``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable

from src.market_data.contracts import (
    DataQualityEvent,
    DataQualityState,
    DataQualityStatus,
)


@dataclass(frozen=True)
class DataQualitySettings:
    """Thresholds for quality-state transitions."""
    delayed_threshold_ms: int = 5_000      # >5s  → DELAYED
    stale_threshold_ms: int = 30_000       # >30s → STALE
    disconnected_threshold_ms: int = 60_000  # >60s → DISCONNECTED
    backfill_timeout_ms: int = 120_000     # backfill >2min → STALE


EventCallback = Callable[[DataQualityEvent], Awaitable[None] | None]


class DataQualityTracker:
    """Thread/async-safe tracker of data quality per instrument.

    Usage:
        tracker = DataQualityTracker(settings)
        tracker.on_event(my_async_callback)
        tracker.record_tick(token, tick_time, received_time)
        tracker.record_gap(token, gap_time)
        tracker.record_backfill_start(token)
        tracker.record_backfill_end(token)
    """

    def __init__(self, settings: DataQualitySettings | None = None) -> None:
        self._settings = settings or DataQualitySettings()
        self._states: dict[int, _InstrumentQuality] = {}
        self._lock = asyncio.Lock()
        self._callbacks: list[EventCallback] = []

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------
    def on_event(self, callback: EventCallback) -> None:
        """Register a callback that receives every state-change event."""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def record_tick(
        self,
        instrument_token: int,
        exchange_timestamp: datetime,
        received_at: datetime,
    ) -> None:
        """Process an incoming tick and update quality state."""
        latency_ms = int((received_at - exchange_timestamp).total_seconds() * 1000)
        now = datetime.now(timezone.utc)
        new_state = self._classify_latency(latency_ms, now, exchange_timestamp)
        await self._transition(instrument_token, new_state, f"tick latency={latency_ms}ms")

    async def record_gap(self, instrument_token: int, gap_time: datetime) -> None:
        """Mark that a gap was detected for this instrument."""
        await self._transition(
            instrument_token,
            DataQualityState.GAP_DETECTED,
            f"gap detected at {gap_time.isoformat()}",
        )

    async def record_out_of_order(self, instrument_token: int, tick_time: datetime) -> None:
        """Mark that an out-of-order tick was received."""
        await self._transition(
            instrument_token,
            DataQualityState.OUT_OF_ORDER,
            f"out-of-order tick at {tick_time.isoformat()}",
        )

    async def record_backfill_start(self, instrument_token: int) -> None:
        """Mark that backfill has started for this instrument."""
        await self._transition(
            instrument_token,
            DataQualityState.BACKFILLING,
            "backfill started",
        )

    async def record_backfill_end(self, instrument_token: int) -> None:
        """Restore LIVE after backfill completes."""
        await self._transition(
            instrument_token,
            DataQualityState.LIVE,
            "backfill completed",
        )

    async def record_disconnect(self, instrument_token: int) -> None:
        """Mark instrument as disconnected."""
        await self._transition(
            instrument_token,
            DataQualityState.DISCONNECTED,
            "provider disconnected",
        )

    async def record_reconnect(self, instrument_token: int) -> None:
        """Restore LIVE after reconnect."""
        await self._transition(
            instrument_token,
            DataQualityState.LIVE,
            "provider reconnected",
        )

    async def get_status(self, instrument_token: int) -> DataQualityStatus | None:
        """Return the current quality status for an instrument."""
        async with self._lock:
            inst = self._states.get(instrument_token)
            if inst is None:
                return None
            return DataQualityStatus(
                instrument_token=instrument_token,
                state=inst.state,
                last_tick_at=inst.last_tick_at,
                last_bar_at=inst.last_bar_at,
                latency_ms=inst.last_latency_ms,
                details=inst.last_reason,
                updated_at=inst.updated_at,
            )

    async def get_all_statuses(self) -> list[DataQualityStatus]:
        """Return quality status for every tracked instrument."""
        async with self._lock:
            return [
                DataQualityStatus(
                    instrument_token=tok,
                    state=inst.state,
                    last_tick_at=inst.last_tick_at,
                    last_bar_at=inst.last_bar_at,
                    latency_ms=inst.last_latency_ms,
                    details=inst.last_reason,
                    updated_at=inst.updated_at,
                )
                for tok, inst in self._states.items()
            ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _classify_latency(
        self,
        latency_ms: int,
        received_at: datetime,
        exchange_timestamp: datetime,
    ) -> DataQualityState:
        """Map latency to quality state."""
        if latency_ms > self._settings.disconnected_threshold_ms:
            return DataQualityState.DISCONNECTED
        if latency_ms > self._settings.stale_threshold_ms:
            return DataQualityState.STALE
        if latency_ms > self._settings.delayed_threshold_ms:
            return DataQualityState.DELAYED
        return DataQualityState.LIVE

    async def _transition(
        self,
        instrument_token: int,
        new_state: DataQualityState,
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            inst = self._states.get(instrument_token)
            if inst is None:
                # First time we see this instrument: initialise silently, no event.
                inst = _InstrumentQuality()
                inst.state = new_state
                inst.updated_at = now
                inst.last_reason = reason
                self._states[instrument_token] = inst
                return
            if inst.state == new_state:
                # No transition, just update metadata
                inst.updated_at = now
                inst.last_reason = reason
                return
            previous = inst.state
            inst.state = new_state
            inst.updated_at = now
            inst.last_reason = reason
            event = DataQualityEvent(
                instrument_token=instrument_token,
                previous_state=previous,
                new_state=new_state,
                reason=reason,
                occurred_at=now,
            )
        # Emit outside the lock to avoid re-entrancy deadlocks
        await self._emit(event)

    async def _emit(self, event: DataQualityEvent) -> None:
        for cb in self._callbacks:
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Callback errors must not crash the tracker
                pass


@dataclass
class _InstrumentQuality:
    """Mutable internal state for a single instrument."""
    state: DataQualityState = DataQualityState.DISCONNECTED
    last_tick_at: datetime | None = None
    last_bar_at: datetime | None = None
    last_latency_ms: int | None = None
    last_reason: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
