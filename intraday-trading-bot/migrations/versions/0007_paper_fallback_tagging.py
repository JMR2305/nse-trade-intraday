"""Tag paper-fallback orders so reconciliation can distinguish them.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-08

Adds:
  broker_order_correlations.paper_fallback_reason — non-null when the order
    was rerouted to the paper broker as a live-mode degradation fallback
    (e.g. "token_expired").
  broker_reconciliation_runs.paper_fallback_count — per-run count of orders
    bucketed as paper-fallback (excluded from discrepancy checks).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broker_order_correlations",
        sa.Column("paper_fallback_reason", sa.String(50), nullable=True),
    )
    op.add_column(
        "broker_reconciliation_runs",
        sa.Column(
            "paper_fallback_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("broker_reconciliation_runs", "paper_fallback_count")
    op.drop_column("broker_order_correlations", "paper_fallback_reason")
