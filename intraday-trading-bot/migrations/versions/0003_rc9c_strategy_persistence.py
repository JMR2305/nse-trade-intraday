"""Create strategy persistence tables.

Revision ID: 0003_rc9c_strategy_persistence
Revises: 0002_rc8b_risk_state_fields
Create Date: 2026-07-22 02:54:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_rc9c_strategy_persistence"
down_revision: Union[str, None] = "0002_rc8b_risk_state_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # strategies
    # ------------------------------------------------------------------
    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("instrument_tokens", sa.JSON(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", name="uq_strategies_strategy_id"),
    )
    op.create_index("ix_strategies_strategy_id", "strategies", ["strategy_id"], unique=False)
    op.create_index("ix_strategies_account_id", "strategies", ["account_id"], unique=False)
    op.create_index(
        "ix_strategies_account_lifecycle",
        "strategies",
        ["account_id", "lifecycle_state"],
        unique=False,
    )
    op.create_index(
        "ix_strategies_type_state",
        "strategies",
        ["strategy_type", "lifecycle_state"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # strategy_signals
    # ------------------------------------------------------------------
    op.create_table(
        "strategy_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("instrument_token", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("trigger_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "routing_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("routed_client_order_id", sa.String(length=64), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", name="uq_strategy_signals_signal_id"),
    )
    op.create_index(
        "ix_strategy_signals_signal_id", "strategy_signals", ["signal_id"], unique=False
    )
    op.create_index(
        "ix_strategy_signals_strategy_id", "strategy_signals", ["strategy_id"], unique=False
    )
    op.create_index(
        "ix_strategy_signals_account_id", "strategy_signals", ["account_id"], unique=False
    )
    op.create_index(
        "ix_strategy_signals_instrument_token",
        "strategy_signals",
        ["instrument_token"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_signals_routed_coid",
        "strategy_signals",
        ["routed_client_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_signals_strategy_status",
        "strategy_signals",
        ["strategy_id", "routing_status"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_signals_pending",
        "strategy_signals",
        ["routing_status", "timestamp"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # strategy_state_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "strategy_state_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False),
        sa.Column("pending_order_ids", sa.JSON(), nullable=False),
        sa.Column("latest_signal_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "emitted_signal_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "routed_signal_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rejected_signal_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fill_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("extra_data", sa.JSON(), nullable=False),
        sa.Column(
            "snapshot_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "strategy_id",
            "snapshot_timestamp",
            name="uq_strategy_state_snapshots_strategy_timestamp",
        ),
    )
    op.create_index(
        "ix_strategy_state_snapshots_strategy_id",
        "strategy_state_snapshots",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_state_snapshots_strategy_latest",
        "strategy_state_snapshots",
        ["strategy_id", "snapshot_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_state_snapshots_strategy_latest", table_name="strategy_state_snapshots")
    op.drop_index("ix_strategy_state_snapshots_strategy_id", table_name="strategy_state_snapshots")
    op.drop_table("strategy_state_snapshots")

    op.drop_index("ix_strategy_signals_pending", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_strategy_status", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_routed_coid", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_instrument_token", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_account_id", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_strategy_id", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_signal_id", table_name="strategy_signals")
    op.drop_table("strategy_signals")

    op.drop_index("ix_strategies_type_state", table_name="strategies")
    op.drop_index("ix_strategies_account_lifecycle", table_name="strategies")
    op.drop_index("ix_strategies_account_id", table_name="strategies")
    op.drop_index("ix_strategies_strategy_id", table_name="strategies")
    op.drop_table("strategies")
