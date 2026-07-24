"""Migration / ORM parity tests for RC-10B forecast_benchmark table (0005).

Verifies that:
1. The ORM model ForecastBenchmarkRecord has every column defined in migration 0005.
2. Column types and constraints match the migration definition.
3. The unique constraint on idempotency_key is present.
4. The composite unique index columns are defined.
5. The partial index marker column (outcome_recorded_at) is nullable.

These tests are pure Python — they do NOT require a live database.
They introspect SQLAlchemy's Table metadata to verify structural parity.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from datetime import datetime, timezone

# Use the double-import guard: conftest may already have loaded src.database.models.
try:
    from src.database.models import ForecastBenchmarkRecord
except ImportError:
    from database.models import ForecastBenchmarkRecord  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table():
    return ForecastBenchmarkRecord.__table__


def _col(name: str):
    return _table().c[name]


def _col_exists(name: str) -> bool:
    return name in _table().c


# ---------------------------------------------------------------------------
# Column presence
# ---------------------------------------------------------------------------

class TestMigration0005ColumnPresence:
    """Every column in the migration upgrade() must exist in the ORM model."""

    REQUIRED_COLUMNS = [
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
    ]

    def test_all_columns_present(self) -> None:
        for col in self.REQUIRED_COLUMNS:
            assert _col_exists(col), (
                f"Column '{col}' is in migration 0005 but missing from "
                f"ForecastBenchmarkRecord ORM model."
            )

    def test_no_extra_required_columns(self) -> None:
        """Sanity-check: model should have at least the 12 migration columns."""
        actual = set(_table().c.keys())
        required = set(self.REQUIRED_COLUMNS)
        assert required.issubset(actual), (
            f"Missing: {required - actual}"
        )


# ---------------------------------------------------------------------------
# Column types and nullability
# ---------------------------------------------------------------------------

class TestMigration0005ColumnAttributes:
    def test_id_is_primary_key(self) -> None:
        assert _col("id").primary_key is True

    def test_idempotency_key_not_nullable(self) -> None:
        assert _col("idempotency_key").nullable is False

    def test_idempotency_key_unique(self) -> None:
        """idempotency_key must have a UNIQUE constraint."""
        col = _col("idempotency_key")
        assert col.unique is True, (
            "idempotency_key must be unique (migration 0005 line: unique=True)"
        )

    def test_idempotency_key_max_length(self) -> None:
        from sqlalchemy import String
        col_type = _col("idempotency_key").type
        assert isinstance(col_type, String)
        # SHA-256 truncated to 32 chars
        assert col_type.length == 32

    def test_instrument_token_not_nullable(self) -> None:
        assert _col("instrument_token").nullable is False

    def test_forecast_horizon_not_nullable(self) -> None:
        assert _col("forecast_horizon").nullable is False

    def test_direction_not_nullable(self) -> None:
        assert _col("direction").nullable is False

    def test_confidence_not_nullable(self) -> None:
        assert _col("confidence").nullable is False

    def test_model_version_not_nullable(self) -> None:
        assert _col("model_version").nullable is False

    def test_computed_at_not_nullable(self) -> None:
        assert _col("computed_at").nullable is False

    def test_actual_direction_nullable(self) -> None:
        """Outcome columns must be nullable — populated by outcome scheduler."""
        assert _col("actual_direction").nullable is True

    def test_actual_return_nullable(self) -> None:
        assert _col("actual_return").nullable is True

    def test_outcome_recorded_at_nullable(self) -> None:
        """Partial index condition: NULL until outcome is recorded."""
        assert _col("outcome_recorded_at").nullable is True

    def test_confidence_numeric_precision(self) -> None:
        from sqlalchemy import Numeric
        col_type = _col("confidence").type
        assert isinstance(col_type, Numeric)
        # Migration: NUMERIC(6, 4)
        assert col_type.precision == 6, f"Expected precision 6, got {col_type.precision}"
        assert col_type.scale == 4, f"Expected scale 4, got {col_type.scale}"

    def test_actual_return_numeric_precision(self) -> None:
        from sqlalchemy import Numeric
        col_type = _col("actual_return").type
        assert isinstance(col_type, Numeric)
        # Migration: NUMERIC(12, 6)
        assert col_type.precision == 12
        assert col_type.scale == 6


# ---------------------------------------------------------------------------
# Table name
# ---------------------------------------------------------------------------

class TestMigration0005TableName:
    def test_table_name(self) -> None:
        """Must be forecast_benchmark (singular) per migration 0005 correction."""
        assert ForecastBenchmarkRecord.__tablename__ == "forecast_benchmark", (
            "Table name must be 'forecast_benchmark' (singular). "
            "Migration 0005 corrected this from 'forecast_benchmarks' (plural)."
        )


# ---------------------------------------------------------------------------
# Composite index columns
# ---------------------------------------------------------------------------

class TestMigration0005Indexes:
    def test_natural_key_columns_exist(self) -> None:
        """All 3 columns in the unique composite index must be present."""
        for col_name in ("instrument_token", "forecast_horizon", "computed_at"):
            assert _col_exists(col_name), (
                f"Composite index column '{col_name}' not found in ORM"
            )

    def test_model_version_index_column_exists(self) -> None:
        assert _col_exists("model_version")
        assert _col_exists("computed_at")

    def test_partial_index_condition_column_exists(self) -> None:
        """outcome_recorded_at is the WHERE condition for the partial index."""
        assert _col_exists("outcome_recorded_at")


# ---------------------------------------------------------------------------
# ORM class attributes
# ---------------------------------------------------------------------------

class TestForecastBenchmarkRecordORM:
    def test_class_name(self) -> None:
        assert ForecastBenchmarkRecord.__name__ == "ForecastBenchmarkRecord"

    def test_orm_model_has_unique_idempotency_key(self) -> None:
        idempotency_col = ForecastBenchmarkRecord.__table__.c.idempotency_key
        assert idempotency_col.unique is True

    def test_can_instantiate_with_required_fields(self) -> None:
        """ORM model must accept all required column values without error."""
        now = datetime.now(timezone.utc)
        row = ForecastBenchmarkRecord(
            idempotency_key="a" * 32,
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.75"),
            model_version="v1",
            computed_at=now,
            created_at=now,
        )
        assert row.instrument_token == "INFY"
        assert row.direction == "UP"
        assert row.actual_direction is None
        assert row.actual_return is None
        assert row.outcome_recorded_at is None
