"""Historical backfill coordinator.

Queues missing intervals, merges broker historical bars deterministically,
detects conflicts, retries with bounded exponential backoff, and marks
unresolved gaps for the caller.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from src.market_data.contracts import CompletedBar, DataGap
from src.market_data.provider import MarketDataProvider
from src.database.repositories.minute_bars import MinuteBarRepository


ConflictPolicy = Literal["SKIP", "OVERWRITE", "MERGE_VOLUME"]


@dataclass(frozen=True)
class BackfillSettings:
    """Retry and conflict settings."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0
    conflict_policy: ConflictPolicy = "SKIP"
    price_tolerance: Decimal = Decimal("0.0001")  # for conflict detection


@dataclass(frozen=True)
class BackfillResult:
    """Summary of a backfill attempt."""
    gaps_processed: int = 0
    bars_inserted: int = 0
    bars_skipped: int = 0
    bars_overwritten: int = 0
    conflicts_detected: int = 0
    unresolved_gaps: list[DataGap] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BackfillCoordinator:
    """Coordinates backfill of missing minute bars.

    Usage:
        coordinator = BackfillCoordinator(provider, bar_repo, settings)
        coordinator.queue_gap(gap)
        result = await coordinator.process_queue()
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        bar_repo: MinuteBarRepository,
        settings: BackfillSettings | None = None,
    ) -> None:
        self._provider = provider
        self._bar_repo = bar_repo
        self._settings = settings or BackfillSettings()
        self._queue: deque[DataGap] = deque()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def queue_gap(self, gap: DataGap) -> None:
        """Add a gap to the backfill queue."""
        self._queue.append(gap)

    def queue_gaps(self, gaps: list[DataGap]) -> None:
        """Add multiple gaps to the backfill queue."""
        for gap in gaps:
            self._queue.append(gap)

    async def process_queue(self, session=None) -> BackfillResult:
        """Process every gap in the queue.

        Args:
            session: optional SQLAlchemy AsyncSession (service-level tx control)

        Returns:
            BackfillResult summarising the operation.
        """
        acc = _MutableResult()

        while self._queue:
            gap = self._queue.popleft()
            try:
                await self._process_single_gap(gap, acc, session)
            except Exception as exc:
                acc.unresolved_gaps.append(
                    DataGap(
                        instrument_token=gap.instrument_token,
                        start=gap.start,
                        end=gap.end,
                        gap_type="UNRESOLVED",
                        resolution_attempts=gap.resolution_attempts + self._settings.max_retries,
                    )
                )
                acc.errors.append(str(exc))

        return acc.to_frozen()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _process_single_gap(
        self,
        gap: DataGap,
        acc: _MutableResult,
        session,
    ) -> None:
        historical: list[CompletedBar] = []

        for attempt in range(1, self._settings.max_retries + 1):
            try:
                historical = await self._provider.get_historical_bars(
                    gap.instrument_token,
                    gap.start,
                    gap.end,
                    interval="minute",
                )
                break
            except Exception:
                if attempt < self._settings.max_retries:
                    delay = min(
                        self._settings.base_delay_seconds * (2 ** (attempt - 1)),
                        self._settings.max_delay_seconds,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(
                        f"Failed to fetch historical bars after {self._settings.max_retries} attempts"
                    )

        if not historical:
            raise RuntimeError(
                f"No historical bars returned for gap {gap.start}–{gap.end}"
            )

        acc.gaps_processed += 1

        for bar in historical:
            existing = await self._bar_repo.get_latest(
                bar.instrument_token,
                session=session,
                before=bar.timestamp + timedelta(minutes=1),
            )
            if existing and existing.timestamp == bar.timestamp:
                conflict = self._detect_conflict(existing, bar)
                if conflict:
                    acc.conflicts_detected += 1
                    if self._settings.conflict_policy == "OVERWRITE":
                        await self._bar_repo.upsert_backfilled_bar(
                            bar, policy="OVERWRITE", session=session
                        )
                        acc.bars_overwritten += 1
                    elif self._settings.conflict_policy == "MERGE_VOLUME":
                        merged = self._merge_volume(existing, bar)
                        await self._bar_repo.upsert_backfilled_bar(
                            merged, policy="OVERWRITE", session=session
                        )
                        acc.bars_overwritten += 1
                    else:
                        acc.bars_skipped += 1
                else:
                    acc.bars_skipped += 1
            else:
                await self._bar_repo.upsert_backfilled_bar(
                    bar, policy="INSERT_ONLY", session=session
                )
                acc.bars_inserted += 1

    def _detect_conflict(self, existing: CompletedBar, incoming: CompletedBar) -> bool:
        """Return True if existing and incoming bars differ beyond tolerance."""
        tol = self._settings.price_tolerance
        checks = [
            abs(existing.open - incoming.open) > tol,
            abs(existing.high - incoming.high) > tol,
            abs(existing.low - incoming.low) > tol,
            abs(existing.close - incoming.close) > tol,
            existing.volume != incoming.volume,
        ]
        return any(checks)

    def _merge_volume(self, existing: CompletedBar, incoming: CompletedBar) -> CompletedBar:
        """Return a new bar with volume = max(existing, incoming)."""
        return CompletedBar(
            instrument_token=existing.instrument_token,
            timestamp=existing.timestamp,
            open=existing.open,
            high=existing.high,
            low=existing.low,
            close=existing.close,
            volume=max(existing.volume, incoming.volume),
            oi=existing.oi,
            is_backfilled=True,
            source="backfill",
        )


class _MutableResult:
    """Internal mutable accumulator for backfill results."""

    def __init__(self) -> None:
        self.gaps_processed = 0
        self.bars_inserted = 0
        self.bars_skipped = 0
        self.bars_overwritten = 0
        self.conflicts_detected = 0
        self.unresolved_gaps: list[DataGap] = []
        self.errors: list[str] = []

    def to_frozen(self) -> BackfillResult:
        return BackfillResult(
            gaps_processed=self.gaps_processed,
            bars_inserted=self.bars_inserted,
            bars_skipped=self.bars_skipped,
            bars_overwritten=self.bars_overwritten,
            conflicts_detected=self.conflicts_detected,
            unresolved_gaps=list(self.unresolved_gaps),
            errors=list(self.errors),
        )
