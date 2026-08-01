"""Basic metrics collection interfaces."""
from dataclasses import dataclass, field
from typing import Any

from app.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FetchMetrics:
    """Metrics for a single fetch operation."""

    success: bool = False
    latency_ms: int = 0
    retry_count: int = 0
    rate_limited: bool = False
    error_type: str | None = None


@dataclass
class CollectionMetrics:
    """Aggregated metrics for a collection run."""

    fetch_success_count: int = 0
    fetch_failure_count: int = 0
    total_latency_ms: int = 0
    parser_failure_count: int = 0
    duplicates_ignored: int = 0
    records_created: int = 0
    records_updated: int = 0
    source_cooldowns: int = 0
    rate_limit_events: int = 0

    @property
    def fetch_success_rate(self) -> float:
        total = self.fetch_success_count + self.fetch_failure_count
        if total == 0:
            return 0.0
        return self.fetch_success_count / total

    @property
    def average_latency_ms(self) -> float:
        total = self.fetch_success_count + self.fetch_failure_count
        if total == 0:
            return 0.0
        return self.total_latency_ms / total

    def log_summary(self, run_id: str, source_id: str) -> None:
        logger.info(
            "collection_metrics_summary",
            run_id=run_id,
            source_id=source_id,
            success_rate=round(self.fetch_success_rate, 4),
            avg_latency_ms=round(self.average_latency_ms, 2),
            parser_failures=self.parser_failure_count,
            duplicates_ignored=self.duplicates_ignored,
            records_created=self.records_created,
            records_updated=self.records_updated,
            rate_limit_events=self.rate_limit_events,
        )


class MetricsCollector:
    """Simple in-memory metrics collector."""

    def __init__(self) -> None:
        self._metrics: dict[str, Any] = {}

    def record_fetch(self, source_id: str, metrics: FetchMetrics) -> None:
        key = f"fetch:{source_id}"
        if key not in self._metrics:
            self._metrics[key] = []
        self._metrics[key].append(metrics)
        logger.debug(
            "fetch_metric_recorded",
            source_id=source_id,
            success=metrics.success,
            latency_ms=metrics.latency_ms,
        )

    def record_rate_limit(self, source_id: str) -> None:
        key = f"rate_limit:{source_id}"
        self._metrics[key] = self._metrics.get(key, 0) + 1
        logger.warning("rate_limit_event", source_id=source_id)

    def get_summary(self, source_id: str | None = None) -> dict[str, Any]:
        if source_id:
            return {
                k: v for k, v in self._metrics.items() if f":{source_id}" in k
            }
        return dict(self._metrics)

    def reset(self) -> None:
        self._metrics.clear()
