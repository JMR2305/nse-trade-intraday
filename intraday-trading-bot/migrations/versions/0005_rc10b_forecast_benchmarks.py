"""RC-10B: Forecast benchmark table (corrected schema)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24 09:08:00
Corrected: 2026-07-24 (pre-freeze patch — no production DB applied yet)

Migration strategy: 0005 corrected in-place.
Reason: RC-10B was NOT frozen when the correction was made; no persistent
production database had the previous 0005 schema applied.  A corrective 0006
migration was therefore unnecessary.

Changes from original 0005:
  - Table renamed from forecast_benchmarks → forecast_benchmark (matches plan)
  - Added: idempotency_key (UNIQUE), forecast_horizon, actual_return,
            outcome_recorded_at
  - Renamed: forecast_direction → direction, actual_timestamp → outcome_recorded_at
  - Removed: benchmark_id, correct (derived at query time)
  - Updated confidence precision: NUMERIC(10,4) → NUMERIC(6,4)
  - Unique composite index: (instrument_token, forecast_horizon, computed_at)
  - Additional indexes: (model_version, computed_at), partial on outcome_recorded_at
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_benchmark",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("idempotency_key", sa.String(32), unique=True, nullable=False),
        sa.Column("instrument_token", sa.String(50), nullable=False),
        sa.Column("forecast_horizon", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 4), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_direction", sa.String(10), nullable=True),
        sa.Column("actual_return", sa.Numeric(12, 6), nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Unique composite index — idempotency key for record_forecast()
    op.create_index(
        "uq_forecast_benchmark_natural_key",
        "forecast_benchmark",
        ["instrument_token", "forecast_horizon", "computed_at"],
        unique=True,
    )
    # For model monitoring queries
    op.create_index(
        "ix_forecast_benchmark_model_version",
        "forecast_benchmark",
        ["model_version", "computed_at"],
    )
    # Partial index on completed outcomes (outcome_recorded_at IS NOT NULL)
    op.create_index(
        "ix_forecast_benchmark_completed",
        "forecast_benchmark",
        ["outcome_recorded_at"],
        postgresql_where=sa.text("outcome_recorded_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_benchmark_completed", table_name="forecast_benchmark")
    op.drop_index("ix_forecast_benchmark_model_version", table_name="forecast_benchmark")
    op.drop_index("uq_forecast_benchmark_natural_key", table_name="forecast_benchmark")
    op.drop_table("forecast_benchmark")
