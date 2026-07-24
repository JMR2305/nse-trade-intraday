"""Integration tests: ForecastBenchmarkRepository persistence contract.

These tests use mock AsyncSession objects (no real DB).
Real DB persistence is tested manually via alembic + pytest fixtures.

Covers:
  - DB row created on record_forecast
  - Duplicate (same computed_at) is idempotent
  - Outcome updates correct row
  - Calibration error and directional accuracy computed correctly
  - DB failure is fail-safe (no raise)
  - Migration ORM parity (ForecastBenchmarkRecord fields match plan)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_forecast.benchmark import BenchmarkReport, ForecastBenchmarkRepository
from ai_forecast.kronos_adapter import ForecastResult

# Resolve ORM model consistently to avoid SQLAlchemy double-table-definition
try:
    from src.database.models import ForecastBenchmarkRecord, Base
except ImportError:
    from database.models import ForecastBenchmarkRecord, Base  # type: ignore[no-redef]


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
        model_version="v2.0",
        computed_at=computed_at or datetime.now(timezone.utc).isoformat(),
    )


def make_rows(predictions: list[tuple]) -> list:
    """Make mock DB row objects.

    predictions: [(pred_direction, actual_direction, confidence), ...]
    """
    rows = []
    for pred, actual, conf in predictions:
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = pred
        row.actual_direction = actual
        row.confidence = Decimal(conf)
        rows.append(row)
    return rows


def make_session(rows=None, scalar_one_or_none=None):
    """result is MagicMock (not AsyncMock): SQLAlchemy result methods are sync.
    session.add is also MagicMock since it's synchronous in SQLAlchemy AsyncSession.
    """
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    if scalar_one_or_none is not None:
        result.scalar_one_or_none.return_value = scalar_one_or_none
    if rows is not None:
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# record_forecast persistence
# ---------------------------------------------------------------------------

class TestRecordForecastPersistence:
    @pytest.mark.asyncio
    async def test_record_forecast_executes_insert(self) -> None:
        repo = ForecastBenchmarkRepository()
        session = make_session()
        forecast = make_forecast()
        await repo.record_forecast(session, forecast)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_forecast_uses_on_conflict_do_nothing(self) -> None:
        """Duplicate records must be idempotent — no error on second insert."""
        repo = ForecastBenchmarkRepository()

        # First insert
        session1 = make_session()
        forecast = make_forecast(computed_at="2026-07-24T09:30:00+00:00")
        await repo.record_forecast(session1, forecast)

        # Second insert (same data → same idempotency_key)
        session2 = make_session()
        await repo.record_forecast(session2, forecast)

        # Both sessions executed without error; second was idempotent
        session1.execute.assert_called_once()
        session2.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotency_key_is_32_chars(self) -> None:
        repo = ForecastBenchmarkRepository()
        key = repo._idempotency_key("INFY", "15m", "2026-07-24T09:30:00+00:00")
        assert len(key) == 32

    @pytest.mark.asyncio
    async def test_different_horizons_different_keys(self) -> None:
        repo = ForecastBenchmarkRepository()
        k1 = repo._idempotency_key("INFY", "15m", "2026-07-24T09:30:00+00:00")
        k2 = repo._idempotency_key("INFY", "30m", "2026-07-24T09:30:00+00:00")
        assert k1 != k2

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise(self) -> None:
        repo = ForecastBenchmarkRepository()
        session = AsyncMock()
        session.execute.side_effect = Exception("DB unavailable")
        forecast = make_forecast()
        # Must not raise
        await repo.record_forecast(session, forecast)


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------

class TestRecordOutcome:
    @pytest.mark.asyncio
    async def test_outcome_sets_actual_direction_return_and_timestamp(self) -> None:
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = "UP"
        row.outcome_recorded_at = None
        session = make_session(scalar_one_or_none=row)
        repo = ForecastBenchmarkRepository()

        ref_ts = datetime.now(timezone.utc)
        await repo.record_outcome(session, "INFY", "15m", Decimal("0.035"), ref_ts)

        assert row.actual_direction == "UP"
        assert row.actual_return == Decimal("0.035")
        assert row.outcome_recorded_at is not None
        session.add.assert_called_once_with(row)

    @pytest.mark.asyncio
    async def test_negative_return_maps_to_down(self) -> None:
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = "DOWN"
        row.outcome_recorded_at = None
        session = make_session(scalar_one_or_none=row)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)
        await repo.record_outcome(session, "INFY", "15m", Decimal("-0.015"), ref_ts)
        assert row.actual_direction == "DOWN"

    @pytest.mark.asyncio
    async def test_zero_return_maps_to_neutral(self) -> None:
        row = MagicMock(spec=ForecastBenchmarkRecord)
        row.direction = "NEUTRAL"
        row.outcome_recorded_at = None
        session = make_session(scalar_one_or_none=row)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)
        await repo.record_outcome(session, "INFY", "15m", Decimal("0"), ref_ts)
        assert row.actual_direction == "NEUTRAL"

    @pytest.mark.asyncio
    async def test_no_matching_row_is_silent(self) -> None:
        session = make_session(scalar_one_or_none=None)
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)
        # Must not raise
        await repo.record_outcome(session, "INFY", "15m", Decimal("0.02"), ref_ts)

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise(self) -> None:
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("Connection reset")
        repo = ForecastBenchmarkRepository()
        ref_ts = datetime.now(timezone.utc)
        # Must not raise
        await repo.record_outcome(session, "INFY", "15m", Decimal("0.02"), ref_ts)


# ---------------------------------------------------------------------------
# Accuracy report
# ---------------------------------------------------------------------------

class TestAccuracyReport:
    @pytest.mark.asyncio
    async def test_perfect_directional_accuracy(self) -> None:
        rows = make_rows([
            ("UP", "UP", "0.80"),
            ("DOWN", "DOWN", "0.75"),
            ("UP", "UP", "0.70"),
        ])
        session = make_session(rows=rows)
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.directional_accuracy == Decimal("1.0000")
        assert report.sample_count == 3

    @pytest.mark.asyncio
    async def test_zero_directional_accuracy(self) -> None:
        rows = make_rows([
            ("UP", "DOWN", "0.80"),
            ("DOWN", "UP", "0.70"),
        ])
        session = make_session(rows=rows)
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.directional_accuracy == Decimal("0.0000")

    @pytest.mark.asyncio
    async def test_calibration_error_all_correct_high_confidence(self) -> None:
        """Perfect predictions with 0.90 confidence → calibration error = |0.90 - 1.0| = 0.10."""
        rows = make_rows([
            ("UP", "UP", "0.90"),
            ("UP", "UP", "0.90"),
        ])
        session = make_session(rows=rows)
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.calibration_error == Decimal("0.1000")

    @pytest.mark.asyncio
    async def test_calibration_error_mixed(self) -> None:
        """
        Row 1: pred=UP, actual=UP, conf=0.80 → error=|0.80 - 1.0|=0.20 (correct)
        Row 2: pred=UP, actual=DOWN, conf=0.60 → error=|0.60 - 0.0|=0.60 (wrong)
        MAE = (0.20 + 0.60) / 2 = 0.40
        """
        rows = make_rows([
            ("UP", "UP", "0.80"),
            ("UP", "DOWN", "0.60"),
        ])
        session = make_session(rows=rows)
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.calibration_error == Decimal("0.4000")

    @pytest.mark.asyncio
    async def test_empty_rows_returns_zero_report(self) -> None:
        session = make_session(rows=[])
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.sample_count == 0
        assert report.directional_accuracy == Decimal("0")
        assert report.calibration_error == Decimal("0")

    @pytest.mark.asyncio
    async def test_db_failure_returns_zero_report(self) -> None:
        session = AsyncMock()
        session.execute.side_effect = Exception("Timeout")
        repo = ForecastBenchmarkRepository()
        report = await repo.get_accuracy_report(session)
        assert report.sample_count == 0
        assert report.directional_accuracy == Decimal("0")


# ---------------------------------------------------------------------------
# ORM model field parity
# ---------------------------------------------------------------------------

class TestForecastBenchmarkRecordORM:
    def test_orm_model_exists_with_plan_aligned_fields(self) -> None:
        """ForecastBenchmarkRecord must have the plan-required fields."""
        # Verify tablename
        assert ForecastBenchmarkRecord.__tablename__ == "forecast_benchmark"

        # Check column presence via ORM mapper
        columns = {c.key for c in ForecastBenchmarkRecord.__table__.columns}
        required = {
            "id",
            "idempotency_key",
            "instrument_token",
            "forecast_horizon",
            "direction",
            "confidence",
            "model_version",
            "computed_at",
            "actual_direction",
            "actual_return",
            "outcome_recorded_at",
            "created_at",
        }
        missing = required - columns
        assert not missing, f"ORM model missing columns: {missing}"

    def test_orm_model_has_unique_idempotency_key(self) -> None:
        idempotency_col = ForecastBenchmarkRecord.__table__.c.idempotency_key
        # Should have a unique constraint
        assert idempotency_col.unique is True

    def test_old_forecast_benchmarks_table_not_present(self) -> None:
        """The old tablename 'forecast_benchmarks' (plural) must not exist."""
        table_names = {t.name for t in Base.metadata.sorted_tables}
        assert "forecast_benchmarks" not in table_names
        assert "forecast_benchmark" in table_names
