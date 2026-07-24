"""RC-10B ForecastBenchmarkRepository — database-backed forecast accuracy tracking.

Public interface (plan-aligned, async + session-injected):

    repo = ForecastBenchmarkRepository()

    await repo.record_forecast(session, forecast)
    await repo.record_outcome(session, instrument_token, horizon,
                               actual_return, reference_timestamp)
    report = await repo.get_accuracy_report(session,
                                             instrument_token=None,
                                             last_n=100)

BenchmarkReport fields:
    directional_accuracy  correct / completed (Decimal, 4 dp)
    calibration_error     MAE(confidence, outcome) (Decimal, 4 dp)
    sample_count          number of completed records used

DB idempotency key: SHA-256 hash of "{instrument_token}:{horizon}:{computed_at}"
(stored in the `idempotency_key` column, UNIQUE constraint).

If persistence fails, all public methods are fail-safe:
  record_forecast / record_outcome log a warning and return.
  get_accuracy_report returns a zero-valued BenchmarkReport.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_forecast.kronos_adapter import ForecastResult

# Import the ORM model via whichever module path the runtime already loaded
# (avoids SQLAlchemy double-table-definition error in test environments where
# conftest imports src.database.models before our code imports database.models).
try:
    from src.database.models import ForecastBenchmarkRecord as _ForecastBenchmarkRecord
except ImportError:
    from database.models import ForecastBenchmarkRecord as _ForecastBenchmarkRecord  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_FOUR = Decimal("0.0001")
_D0   = Decimal("0")


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------

class BenchmarkReport(BaseModel, frozen=True):
    """Immutable accuracy report produced by get_accuracy_report()."""

    model_config = ConfigDict(frozen=True)

    directional_accuracy: Decimal = _D0
    calibration_error: Decimal = _D0
    sample_count: int = 0
    report_period: str = ""


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class ForecastBenchmarkRepository:
    """Async, database-backed forecast benchmark tracker.

    All methods are fail-safe: DB errors are logged and do not propagate.
    """

    @staticmethod
    def _idempotency_key(
        instrument_token: str, forecast_horizon: str, computed_at: str
    ) -> str:
        """Deterministic 32-char key from composite natural key."""
        raw = f"{instrument_token}:{forecast_horizon}:{computed_at}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # record_forecast
    # ------------------------------------------------------------------

    async def record_forecast(
        self,
        session: AsyncSession,
        forecast: ForecastResult,
    ) -> None:
        """Persist a forecast to DB.  Idempotent: duplicate computed_at is ignored."""
        ForecastBenchmarkRecord = _ForecastBenchmarkRecord

        ikey = self._idempotency_key(
            forecast.instrument_token,
            forecast.forecast_horizon,
            forecast.computed_at,
        )

        try:
            stmt = (
                pg_insert(ForecastBenchmarkRecord)
                .values(
                    idempotency_key=ikey,
                    instrument_token=forecast.instrument_token,
                    forecast_horizon=forecast.forecast_horizon,
                    direction=forecast.direction,
                    confidence=forecast.confidence,
                    model_version=forecast.model_version,
                    computed_at=(
                        datetime.fromisoformat(forecast.computed_at)
                        if forecast.computed_at
                        else datetime.now(timezone.utc)
                    ),
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
            )
            await session.execute(stmt)
        except Exception as exc:
            logger.warning(
                "ForecastBenchmark.record_forecast failed (non-fatal): %s", exc,
                extra={"instrument_token": forecast.instrument_token},
            )

    # ------------------------------------------------------------------
    # record_outcome
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        session: AsyncSession,
        instrument_token: str,
        horizon: str,
        actual_return: Decimal,
        reference_timestamp: datetime,
    ) -> None:
        """Update the most recent unresolved forecast row with the actual outcome.

        actual_return > 0 → UP, < 0 → DOWN, == 0 → NEUTRAL (per plan §8).
        Matches the latest forecast for (instrument_token, horizon) that has
        computed_at ≤ reference_timestamp and no outcome yet recorded.
        """
        ForecastBenchmarkRecord = _ForecastBenchmarkRecord

        # Derive actual direction from return
        if actual_return > _D0:
            actual_direction = "UP"
        elif actual_return < _D0:
            actual_direction = "DOWN"
        else:
            actual_direction = "NEUTRAL"

        try:
            # Find the most recent matching, unresolved row
            stmt = (
                select(ForecastBenchmarkRecord)
                .where(
                    and_(
                        ForecastBenchmarkRecord.instrument_token == instrument_token,
                        ForecastBenchmarkRecord.forecast_horizon == horizon,
                        ForecastBenchmarkRecord.computed_at <= reference_timestamp,
                        ForecastBenchmarkRecord.outcome_recorded_at.is_(None),
                    )
                )
                .order_by(ForecastBenchmarkRecord.computed_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row: Optional[ForecastBenchmarkRecord] = result.scalar_one_or_none()

            if row is None:
                logger.debug(
                    "No pending forecast found for outcome: %s %s",
                    instrument_token, horizon,
                )
                return

            row.actual_direction = actual_direction
            row.actual_return = actual_return
            row.outcome_recorded_at = datetime.now(timezone.utc)
            session.add(row)

        except Exception as exc:
            logger.warning(
                "ForecastBenchmark.record_outcome failed (non-fatal): %s", exc,
                extra={"instrument_token": instrument_token},
            )

    # ------------------------------------------------------------------
    # get_accuracy_report
    # ------------------------------------------------------------------

    async def get_accuracy_report(
        self,
        session: AsyncSession,
        instrument_token: Optional[str] = None,
        last_n: int = 100,
    ) -> BenchmarkReport:
        """Return an accuracy report from completed forecast records.

        Completed = outcome_recorded_at IS NOT NULL.
        Ordered by computed_at DESC (most recent first), limited to last_n rows.
        Returns a zero-valued BenchmarkReport on empty results or DB failure.
        """
        ForecastBenchmarkRecord = _ForecastBenchmarkRecord

        try:
            conditions = [ForecastBenchmarkRecord.outcome_recorded_at.is_not(None)]
            if instrument_token is not None:
                conditions.append(
                    ForecastBenchmarkRecord.instrument_token == instrument_token
                )

            stmt = (
                select(ForecastBenchmarkRecord)
                .where(and_(*conditions))
                .order_by(ForecastBenchmarkRecord.computed_at.desc())
                .limit(last_n)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                return BenchmarkReport()

            total = len(rows)
            correct = sum(
                1 for r in rows if r.direction == r.actual_direction
            )

            # directional accuracy
            directional_accuracy = (
                (Decimal(str(correct)) / Decimal(str(total))).quantize(_FOUR)
                if total > 0
                else _D0
            )

            # calibration error: MAE(predicted_confidence, binary_correctness)
            cal_sum = _D0
            for r in rows:
                outcome = Decimal("1") if r.direction == r.actual_direction else _D0
                cal_sum += abs(r.confidence - outcome)
            calibration_error = (cal_sum / Decimal(str(total))).quantize(_FOUR)

            return BenchmarkReport(
                directional_accuracy=directional_accuracy,
                calibration_error=calibration_error,
                sample_count=total,
            )

        except Exception as exc:
            logger.warning(
                "ForecastBenchmark.get_accuracy_report failed (non-fatal): %s", exc,
            )
            return BenchmarkReport()


# ---------------------------------------------------------------------------
# In-memory implementation — unit-testing and lightweight use only
# ---------------------------------------------------------------------------

@dataclass
class _BenchmarkEntry:
    instrument_token: str
    forecast_direction: str
    actual_direction: str
    confidence: Decimal
    correct: bool


class InMemoryForecastBenchmark:
    """In-memory benchmark tracker for unit tests and local development.

    Uses no DB. Not suitable for production deployments.
    """

    def __init__(self) -> None:
        self._entries: List[_BenchmarkEntry] = []
        self._pending: dict = {}  # composite key → pending record

    def record_forecast(
        self,
        instrument_token: str,
        forecast_direction: str,
        confidence: Decimal,
        timestamp: str,
        forecast_horizon: str = "15m",
    ) -> None:
        key = f"{instrument_token}:{forecast_horizon}:{timestamp}"
        self._pending[key] = {
            "instrument_token": instrument_token,
            "direction": forecast_direction,
            "confidence": str(confidence),
            "timestamp": timestamp,
            "forecast_horizon": forecast_horizon,
        }

    def evaluate(
        self,
        instrument_token: str,
        actual_direction: str,
        timestamp: str,
        forecast_horizon: str = "15m",
        forecast_timestamp: Optional[str] = None,
    ) -> None:
        if forecast_timestamp is not None:
            key = f"{instrument_token}:{forecast_horizon}:{forecast_timestamp}"
            pending = self._pending.pop(key, None)
        else:
            prefix = f"{instrument_token}:{forecast_horizon}:"
            key = next((k for k in list(self._pending) if k.startswith(prefix)), None)
            pending = self._pending.pop(key, None) if key else None

        if pending is None:
            return

        correct = pending["direction"] == actual_direction
        self._entries.append(
            _BenchmarkEntry(
                instrument_token=instrument_token,
                forecast_direction=pending["direction"],
                actual_direction=actual_direction,
                confidence=Decimal(pending["confidence"]),
                correct=correct,
            )
        )

    def generate_report(self, period: str = "daily") -> BenchmarkReport:
        if not self._entries:
            return BenchmarkReport(report_period=period)

        total = len(self._entries)
        correct = sum(1 for e in self._entries if e.correct)
        directional_accuracy = (
            (Decimal(str(correct)) / Decimal(str(total))).quantize(_FOUR)
        )
        cal_sum = sum(
            abs(e.confidence - (Decimal("1") if e.correct else _D0))
            for e in self._entries
        )
        calibration_error = (cal_sum / Decimal(str(total))).quantize(_FOUR)

        return BenchmarkReport(
            directional_accuracy=directional_accuracy,
            calibration_error=calibration_error,
            sample_count=total,
            report_period=period,
        )

    def clear(self) -> None:
        self._entries.clear()
        self._pending.clear()
