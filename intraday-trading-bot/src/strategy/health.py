"""StrategyHealthMonitor — derives live health from runtime metrics.

Health is computed on demand from the MetricsCollector; no additional
state is maintained here.  Callers can poll compute_health() at any
frequency; it is a pure function over the current metrics snapshot.

Health thresholds
-----------------
Consecutive errors  >= UNHEALTHY_CONSECUTIVE_ERRORS  → UNHEALTHY
Consecutive errors  >= DEGRADED_CONSECUTIVE_ERRORS   → DEGRADED
Last bar latency_ms >= UNHEALTHY_LATENCY_MS          → UNHEALTHY
Last bar latency_ms >= DEGRADED_LATENCY_MS           → DEGRADED
No metrics recorded                                  → UNKNOWN
Otherwise                                            → HEALTHY

Thresholds can be overridden at construction time for different
deployment environments (e.g. tighter in production).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from strategy.metrics import MetricsCollector

logger = logging.getLogger(__name__)


class StrategyHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HealthReport:
    """Immutable health snapshot for one strategy at one point in time."""

    strategy_id: str
    status: StrategyHealthStatus
    reason: str = ""
    consecutive_errors: int = 0
    last_bar_latency_ms: float = 0.0
    bars_processed: int = 0
    signals_emitted: int = 0
    error_count: int = 0
    last_checked: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class StrategyHealthMonitor:
    """Computes health reports from live MetricsCollector data.

    Parameters
    ----------
    metrics:
        Shared MetricsCollector instance (injected by coordinator).
    degraded_consecutive_errors:
        Consecutive-error count that triggers DEGRADED status.
    unhealthy_consecutive_errors:
        Consecutive-error count that triggers UNHEALTHY status.
    degraded_latency_ms:
        Last-bar latency (ms) that triggers DEGRADED status.
    unhealthy_latency_ms:
        Last-bar latency (ms) that triggers UNHEALTHY status.
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        degraded_consecutive_errors: int = 3,
        unhealthy_consecutive_errors: int = 5,
        degraded_latency_ms: float = 500.0,
        unhealthy_latency_ms: float = 2000.0,
    ) -> None:
        self._metrics = metrics
        self._degraded_consecutive = degraded_consecutive_errors
        self._unhealthy_consecutive = unhealthy_consecutive_errors
        self._degraded_latency = degraded_latency_ms
        self._unhealthy_latency = unhealthy_latency_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_health(self, strategy_id: str) -> HealthReport:
        """Derive a HealthReport from the current metrics snapshot.

        This is a pure read — no side effects, no locks.
        """
        m = self._metrics.get_metrics(strategy_id)
        if m is None:
            return HealthReport(
                strategy_id=strategy_id,
                status=StrategyHealthStatus.UNKNOWN,
                reason="No metrics recorded",
            )

        # --- consecutive-error thresholds (checked first — most critical) ---
        if m.consecutive_errors >= self._unhealthy_consecutive:
            return HealthReport(
                strategy_id=strategy_id,
                status=StrategyHealthStatus.UNHEALTHY,
                reason=(
                    f"{m.consecutive_errors} consecutive errors "
                    f"(threshold={self._unhealthy_consecutive})"
                ),
                consecutive_errors=m.consecutive_errors,
                last_bar_latency_ms=m.last_bar_latency_ms,
                bars_processed=m.bars_processed,
                signals_emitted=m.signals_emitted,
                error_count=m.error_count,
            )

        if m.consecutive_errors >= self._degraded_consecutive:
            return HealthReport(
                strategy_id=strategy_id,
                status=StrategyHealthStatus.DEGRADED,
                reason=(
                    f"{m.consecutive_errors} consecutive errors "
                    f"(threshold={self._degraded_consecutive})"
                ),
                consecutive_errors=m.consecutive_errors,
                last_bar_latency_ms=m.last_bar_latency_ms,
                bars_processed=m.bars_processed,
                signals_emitted=m.signals_emitted,
                error_count=m.error_count,
            )

        # --- latency thresholds ---
        if m.bars_processed > 0 and m.last_bar_latency_ms >= self._unhealthy_latency:
            return HealthReport(
                strategy_id=strategy_id,
                status=StrategyHealthStatus.UNHEALTHY,
                reason=(
                    f"Bar latency {m.last_bar_latency_ms:.1f} ms "
                    f"exceeds {self._unhealthy_latency:.0f} ms threshold"
                ),
                consecutive_errors=m.consecutive_errors,
                last_bar_latency_ms=m.last_bar_latency_ms,
                bars_processed=m.bars_processed,
                signals_emitted=m.signals_emitted,
                error_count=m.error_count,
            )

        if m.bars_processed > 0 and m.last_bar_latency_ms >= self._degraded_latency:
            return HealthReport(
                strategy_id=strategy_id,
                status=StrategyHealthStatus.DEGRADED,
                reason=(
                    f"Bar latency {m.last_bar_latency_ms:.1f} ms "
                    f"exceeds {self._degraded_latency:.0f} ms threshold"
                ),
                consecutive_errors=m.consecutive_errors,
                last_bar_latency_ms=m.last_bar_latency_ms,
                bars_processed=m.bars_processed,
                signals_emitted=m.signals_emitted,
                error_count=m.error_count,
            )

        return HealthReport(
            strategy_id=strategy_id,
            status=StrategyHealthStatus.HEALTHY,
            consecutive_errors=m.consecutive_errors,
            last_bar_latency_ms=m.last_bar_latency_ms,
            bars_processed=m.bars_processed,
            signals_emitted=m.signals_emitted,
            error_count=m.error_count,
        )

    def get_all_health(self, strategy_ids: List[str]) -> Dict[str, HealthReport]:
        """Compute health for every strategy_id in the given list."""
        return {sid: self.compute_health(sid) for sid in strategy_ids}

    def is_healthy(self, strategy_id: str) -> bool:
        """Convenience check: True iff status == HEALTHY."""
        return self.compute_health(strategy_id).status == StrategyHealthStatus.HEALTHY

    def any_unhealthy(self, strategy_ids: List[str]) -> bool:
        """True iff any strategy in the list is UNHEALTHY."""
        return any(
            self.compute_health(sid).status == StrategyHealthStatus.UNHEALTHY
            for sid in strategy_ids
        )
