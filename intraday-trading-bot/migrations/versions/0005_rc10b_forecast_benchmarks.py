"""RC-10B: Forecast benchmarks table

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24 09:08:00

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
        "forecast_benchmarks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("benchmark_id", sa.String(50), unique=True, nullable=False),
        sa.Column("instrument_token", sa.String(50), nullable=False),
        sa.Column("forecast_direction", sa.String(10), nullable=False),
        sa.Column("actual_direction", sa.String(10), nullable=False),
        sa.Column("correct", sa.Boolean, nullable=False),
        sa.Column("confidence", sa.Numeric(10, 4), nullable=False),
        sa.Column("forecast_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_forecast_benchmarks_instrument", "forecast_benchmarks", ["instrument_token"])
    op.create_index("ix_forecast_benchmarks_timestamp", "forecast_benchmarks", ["forecast_timestamp"])
    op.create_index("ix_forecast_benchmarks_correct", "forecast_benchmarks", ["correct"])


def downgrade() -> None:
    op.drop_index("ix_forecast_benchmarks_correct", table_name="forecast_benchmarks")
    op.drop_index("ix_forecast_benchmarks_timestamp", table_name="forecast_benchmarks")
    op.drop_index("ix_forecast_benchmarks_instrument", table_name="forecast_benchmarks")
    op.drop_table("forecast_benchmarks")
