"""RC-8B: Add trade_count, order_count, emergency_halt_active, circuit_breaker_triggered to risk_state_snapshots

Revision ID: 0002_rc8b_risk_state_fields
Revises: 0001_initial_schema
Create Date: 2026-07-21 00:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_rc8b_risk_state_fields"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add RC-8B safety and counter columns to risk_state_snapshots.
    # All columns have server defaults so existing rows are filled immediately.
    op.add_column(
        "risk_state_snapshots",
        sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "risk_state_snapshots",
        sa.Column("order_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "risk_state_snapshots",
        sa.Column(
            "emergency_halt_active", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "risk_state_snapshots",
        sa.Column(
            "circuit_breaker_triggered", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("risk_state_snapshots", "circuit_breaker_triggered")
    op.drop_column("risk_state_snapshots", "emergency_halt_active")
    op.drop_column("risk_state_snapshots", "order_count")
    op.drop_column("risk_state_snapshots", "trade_count")
