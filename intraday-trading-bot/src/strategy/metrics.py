"""StrategyMetrics — per-strategy runtime performance counters.

Collects latency, signal, error, and fill counters for every strategy
running under a StrategyCoordinator.  All mutations are async-safe via
an internal asyncio.Lock.  Reads (get_metrics / get_all_metrics) are
lock-free snapshots — safe to call from any coroutine.

Design principles
-----------------
- MetricsCollector is a singleton injected into coordinator and runtime.
- StrategyMetrics instances are immutable (replaced on each update via
  dataclasses.replace so callers always get a stable snapshot).
- No I/O, no DB calls — this module is pure in-process state.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyMetrics:
    """Immutable point-in-time metrics snapshot for one strategy."""

    strategy_id: str

    # Bar / tick throughput
    bars_processed: int = 0
    ticks_processed: int = 0

    # Signal accounting
    signals_emitted: int = 0
    signals_rejected: int = 0

    # Fill accounting
    fill_count: int = 0

    # Error accounting
    error_count: int = 0
    consecutive_errors: int = 0

    # Latency (milliseconds)
    last_bar_latency_ms: float = 0.0
    avg_bar_latency_ms: float = 0.0
    # Internal accumulator — not exposed directly but needed for avg
    _total_bar_latency_ms: float = field(default=0.0, compare=False, repr=False)

    # Timestamps
    started_at: Optional[datetime] = None
    last_bar_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None


class MetricsCollector:
    """Thread/coroutine-safe store of per-strategy runtime metrics.

    All write methods are async and acquire a lock.
    Read methods (get_metrics, get_all_metrics) are synchronous and
    return frozen snapshots — safe to call from any context.
    """

    def __init__(self) -> None:
        self._metrics: Dict[str, StrategyMetrics] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle helpers (called by coordinator)
    # ------------------------------------------------------------------

    def initialize(self, strategy_id: str) -> None:
        """Register a strategy's metrics slot.  No-op if already present."""
        if strategy_id not in self._metrics:
            self._metrics[strategy_id] = StrategyMetrics(
                strategy_id=strategy_id,
                started_at=datetime.now(timezone.utc),
            )

    def remove(self, strategy_id: str) -> None:
        """Drop a strategy's metrics slot (called on deregister)."""
        self._metrics.pop(strategy_id, None)

    # ------------------------------------------------------------------
    # Write methods (async, lock-protected)
    # ------------------------------------------------------------------

    async def record_bar(self, strategy_id: str, latency_ms: float) -> None:
        """Record a completed bar with its processing latency."""
        async with self._lock:
            m = self._ensure(strategy_id)
            new_bars = m.bars_processed + 1
            new_total = m._total_bar_latency_ms + latency_ms
            self._metrics[strategy_id] = dataclasses.replace(
                m,
                bars_processed=new_bars,
                last_bar_latency_ms=latency_ms,
                avg_bar_latency_ms=new_total / new_bars,
                _total_bar_latency_ms=new_total,
                last_bar_at=datetime.now(timezone.utc),
                consecutive_errors=0,  # successful bar resets streak
            )

    async def record_tick(self, strategy_id: str) -> None:
        """Record a completed tick."""
        async with self._lock:
            m = self._ensure(strategy_id)
            self._metrics[strategy_id] = dataclasses.replace(
                m, ticks_processed=m.ticks_processed + 1
            )

    async def record_signal(self, strategy_id: str) -> None:
        """Increment emitted signal counter."""
        async with self._lock:
            m = self._ensure(strategy_id)
            self._metrics[strategy_id] = dataclasses.replace(
                m, signals_emitted=m.signals_emitted + 1
            )

    async def record_signal_rejected(self, strategy_id: str) -> None:
        """Increment rejected signal counter."""
        async with self._lock:
            m = self._ensure(strategy_id)
            self._metrics[strategy_id] = dataclasses.replace(
                m, signals_rejected=m.signals_rejected + 1
            )

    async def record_fill(self, strategy_id: str) -> None:
        """Increment fill counter."""
        async with self._lock:
            m = self._ensure(strategy_id)
            self._metrics[strategy_id] = dataclasses.replace(
                m, fill_count=m.fill_count + 1
            )

    async def record_error(self, strategy_id: str) -> None:
        """Increment error counters and consecutive-error streak."""
        async with self._lock:
            m = self._ensure(strategy_id)
            self._metrics[strategy_id] = dataclasses.replace(
                m,
                error_count=m.error_count + 1,
                consecutive_errors=m.consecutive_errors + 1,
                last_error_at=datetime.now(timezone.utc),
            )

    async def record_success(self, strategy_id: str) -> None:
        """Reset consecutive-error streak after a clean bar/tick."""
        async with self._lock:
            m = self._ensure(strategy_id)
            if m.consecutive_errors > 0:
                self._metrics[strategy_id] = dataclasses.replace(
                    m, consecutive_errors=0
                )

    # ------------------------------------------------------------------
    # Read methods (synchronous, lock-free)
    # ------------------------------------------------------------------

    def get_metrics(self, strategy_id: str) -> Optional[StrategyMetrics]:
        """Return a frozen snapshot, or None if not yet initialised."""
        return self._metrics.get(strategy_id)

    def get_all_metrics(self) -> Dict[str, StrategyMetrics]:
        """Return a shallow copy of all metric snapshots."""
        return dict(self._metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure(self, strategy_id: str) -> StrategyMetrics:
        """Return existing metrics or create a default entry."""
        if strategy_id not in self._metrics:
            self._metrics[strategy_id] = StrategyMetrics(
                strategy_id=strategy_id,
                started_at=datetime.now(timezone.utc),
            )
        return self._metrics[strategy_id]
