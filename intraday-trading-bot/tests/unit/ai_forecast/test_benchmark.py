"""Tests for RC-10B ForecastBenchmarkRepository and InMemoryForecastBenchmark."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from ai_forecast.benchmark import (
    BenchmarkReport,
    ForecastBenchmarkRepository,
    InMemoryForecastBenchmark,
)
from ai_forecast.kronos_adapter import ForecastResult

# Resolve ORM model via the same import path that will be available at runtime
try:
    from src.database.models import ForecastBenchmarkRecord
except ImportError:
    from database.models import ForecastBenchmarkRecord  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_forecast(
    token: str = "INFY",
    direction: str = "UP",
    confidence: str = "0.75",
    horizon: str = "15m",
    computed_at: str | None = None,
) -> ForecastResult:
    return ForecastResult(
        instrument_token=token,
        forecast_horizon=horizon,
        direction=direction,
        confidence=Decimal(confidence),
        model_version="v1",
        computed_at=computed_at or datetime.now(timezone.utc).isoformat(),
    )


def make_session(rows=None, scalar_one_or_none=None):
    """Mock AsyncSession for unit tests.

    result is a MagicMock (not AsyncMock) because SQLAlchemy result methods
    (scalar_one_or_none, scalars) are synchronous — they must NOT return coroutines.
    session.add is also a MagicMock because it is synchronous in AsyncSession.
    """
    session = AsyncMock()
    session.add = MagicMock()   # synchronous in SQLAlchemy AsyncSession
    result = MagicMock()        # synchronous result object
    if scalar_one_or_none is not None:
        result.scalar_one_or_none.return_value = scalar_one_or_none
    if rows is not None:
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# ForecastBenchmarkRepository
# ---------------------------------------------------------------------------

class TestForecastBenchmarkRepository:
    @pytest.mark.asyncio
    async def test_record_forecast_calls_execute(self) -> None:
        """record_forecast() should execute an insert statement."""
        repo = ForecastBenchmarkRepository()
        forecast = make_forecast()
        session = make_session()
        await repo.record_forecast(session, forecast)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_forecast_idempotency_key_stable(self) -> None:
        """Same forecast → same idempotency key (deterministic SHA-256 hash)."""
        repo = ForecastBenchmarkRepository()
        computed_at = "2026-07-24T09:30:00+00:00"
        key1 = repo._idempotency_key("INFY", "15m", computed_at)
        key2 = repo._idempotency_key("INFY", "15m", computed_at)
        assert key1 == key2
        assert len(key1) == 32

    @pytest.mark.asyncio
    async def test_record_forecast_different_tokens_different_keys(self) -> None:
        repo = ForecastBenchmarkRepository()
        computed_at = "2026-07-24T09:30:00+00:00"
        key_infy = repo._idempotency_key("INFY", "15m", computed_at)
        key_reli = repo._idempotency_key("RELI", "15m", computed_at)
        assert key_infy != key_reli

    @pytest.mark.asyncio
    async def test_record_forecast_db_failure_is_silent(self) -> None:
        """DB errors must not propagate — fail-safe."""
        repo = ForecastBenchmarkRepository()
        forecast = make_forecast()
        session = AsyncMock()
        session.execute.side_effect = Exception("DB connection lost")
        # Must not raise
        await repo.record_forecast(session, forecast)

    @pytest.mark.asyncio
    async def test_record_outcome_updates_matching_row(self) -> None:
        """record_outcome() should update actual_direction / actual_return."""
        # Mock the DB row returned by the query
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = "UP"
        row.outcome_recorded_at = None

        session = make_session(scalar_one_or_none=row)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)

        await repo.record_outcome(session, "INFY", "15m", Decimal("0.025"), ref_ts)

        assert row.actual_direction == "UP"
        assert row.actual_return == Decimal("0.025")
        assert row.outcome_recorded_at is not None
        session.add.assert_called_once_with(row)

    @pytest.mark.asyncio
    async def test_record_outcome_negative_return_is_down(self) -> None:
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = "DOWN"
        row.outcome_recorded_at = None
        session = make_session(scalar_one_or_none=row)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)

        await repo.record_outcome(session, "INFY", "15m", Decimal("-0.01"), ref_ts)
        assert row.actual_direction == "DOWN"

    @pytest.mark.asyncio
    async def test_record_outcome_zero_return_is_neutral(self) -> None:
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = "NEUTRAL"
        row.outcome_recorded_at = None
        session = make_session(scalar_one_or_none=row)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)

        await repo.record_outcome(session, "INFY", "15m", Decimal("0"), ref_ts)
        assert row.actual_direction == "NEUTRAL"

    @pytest.mark.asyncio
    async def test_record_outcome_no_matching_row_is_silent(self) -> None:
        session = make_session(scalar_one_or_none=None)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)
        # Must not raise
        await repo.record_outcome(session, "INFY", "15m", Decimal("0.01"), ref_ts)

    @pytest.mark.asyncio
    async def test_get_accuracy_report_empty(self) -> None:
        session = make_session(rows=[])
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.sample_count == 0
        assert report.directional_accuracy == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_accuracy_report_all_correct(self) -> None:
        rows = []
        for _ in range(4):
            row = MagicMock(spec=ForecastBenchmarkRecord)
            row.direction = "UP"
            row.actual_direction = "UP"
            row.confidence = Decimal("0.80")
            rows.append(row)

        session = make_session(rows=rows)
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.sample_count == 4
        assert report.directional_accuracy == Decimal("1.0000")
        # Calibration error: MAE(0.80, 1.0) for all = 0.20
        assert report.calibration_error == Decimal("0.2000")

    @pytest.mark.asyncio
    async def test_get_accuracy_report_mixed(self) -> None:
        rows = []
        for i, (pred, actual, conf) in enumerate([
            ("UP", "UP", "0.80"),    # correct
            ("UP", "DOWN", "0.70"),  # wrong
            ("DOWN", "DOWN", "0.65"), # correct
            ("DOWN", "UP", "0.60"),   # wrong
        ]):
            row = MagicMock(spec=ForecastBenchmarkRecord)
            row.direction = pred
            row.actual_direction = actual
            row.confidence = Decimal(conf)
            rows.append(row)

        session = make_session(rows=rows)
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.sample_count == 4
        assert report.directional_accuracy == Decimal("0.5000")

    @pytest.mark.asyncio
    async def test_get_accuracy_report_db_failure_returns_zero(self) -> None:
        session = AsyncMock()
        session.execute.side_effect = Exception("Connection timeout")
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.sample_count == 0
        assert report.directional_accuracy == Decimal("0")


# ---------------------------------------------------------------------------
# InMemoryForecastBenchmark (unit test / dev only)
# ---------------------------------------------------------------------------

class TestInMemoryForecastBenchmark:
    def test_record_and_evaluate_correct(self) -> None:
        bench = InMemoryForecastBenchmark()
        ts = datetime.now(timezone.utc).isoformat()
        bench.record_forecast("INFY", "UP", Decimal("0.80"), ts)
        bench.evaluate("INFY", "UP", ts)
        report = bench.generate_report()
        assert report.sample_count == 1
        assert report.directional_accuracy == Decimal("1.0000")

    def test_evaluate_mismatch(self) -> None:
        bench = InMemoryForecastBenchmark()
        ts = datetime.now(timezone.utc).isoformat()
        bench.record_forecast("INFY", "UP", Decimal("0.75"), ts)
        bench.evaluate("INFY", "DOWN", ts)
        report = bench.generate_report()
        assert report.directional_accuracy == Decimal("0.0000")

    def test_empty_report(self) -> None:
        bench = InMemoryForecastBenchmark()
        report = bench.generate_report()
        assert report.sample_count == 0

    def test_clear_resets(self) -> None:
        bench = InMemoryForecastBenchmark()
        ts = datetime.now(timezone.utc).isoformat()
        bench.record_forecast("INFY", "UP", Decimal("0.75"), ts)
        bench.evaluate("INFY", "UP", ts)
        bench.clear()
        report = bench.generate_report()
        assert report.sample_count == 0
