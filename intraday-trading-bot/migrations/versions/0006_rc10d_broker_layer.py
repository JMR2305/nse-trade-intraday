"""RC-10D: Broker Integration Layer — new tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24

Creates six broker-specific tables:
  broker_sessions                     — session metadata (no tokens)
  broker_order_correlations           — idempotent submission tracking
  broker_event_inbox                  — unresolvable broker events
  broker_reconciliation_runs          — reconciliation run records
  broker_reconciliation_discrepancies — per-discrepancy records
  instrument_sync_runs                — instrument master download log
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── broker_sessions ───────────────────────────────────────────────────
    op.create_table(
        "broker_sessions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("session_uuid", sa.String(64), nullable=False, unique=True),
        sa.Column("broker_name", sa.String(32), nullable=False, server_default="zerodha"),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("paper_mode", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_valid", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(200), nullable=True),
    )
    op.create_index("idx_broker_sessions_uuid", "broker_sessions", ["session_uuid"])
    op.create_index("idx_broker_sessions_valid", "broker_sessions", ["is_valid"])
    op.create_index("idx_broker_sessions_broker", "broker_sessions", ["broker_name"])

    # ── broker_order_correlations ─────────────────────────────────────────
    op.create_table(
        "broker_order_correlations",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("internal_order_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("broker_order_id", sa.String(64), nullable=True),
        sa.Column("exchange_order_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("paper_mode", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("trading_symbol", sa.String(50), nullable=True),
        sa.Column("exchange", sa.String(10), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_correlations_internal", "broker_order_correlations", ["internal_order_id"]
    )
    op.create_index(
        "idx_correlations_broker", "broker_order_correlations", ["broker_order_id"]
    )
    op.create_index(
        "idx_correlations_status", "broker_order_correlations", ["status"]
    )
    op.create_index(
        "idx_correlations_idempotency", "broker_order_correlations", ["idempotency_key"]
    )

    # ── broker_event_inbox ────────────────────────────────────────────────
    op.create_table(
        "broker_event_inbox",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("broker_order_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("raw_payload", JSONB, nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="websocket"),
        sa.Column("processed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("requires_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("review_notes", sa.Text, nullable=True),
        sa.Column("paper_mode", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_event_inbox_processed", "broker_event_inbox", ["processed"])
    op.create_index(
        "idx_event_inbox_review", "broker_event_inbox", ["requires_review"]
    )

    # ── broker_reconciliation_runs ────────────────────────────────────────
    op.create_table(
        "broker_reconciliation_runs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False, unique=True),
        sa.Column("trigger", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orders_checked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("clean", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("discrepancy_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paper_mode", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_recon_runs_run_id", "broker_reconciliation_runs", ["run_id"]
    )
    op.create_index(
        "idx_recon_runs_trigger", "broker_reconciliation_runs", ["trigger"]
    )
    op.create_index("idx_recon_runs_clean", "broker_reconciliation_runs", ["clean"])

    # ── broker_reconciliation_discrepancies ───────────────────────────────
    op.create_table(
        "broker_reconciliation_discrepancies",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("discrepancy_type", sa.String(50), nullable=False),
        sa.Column("internal_order_id", sa.String(64), nullable=True),
        sa.Column("broker_order_id", sa.String(64), nullable=True),
        sa.Column("trading_symbol", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("local_value", sa.Text, nullable=True),
        sa.Column("broker_value", sa.Text, nullable=True),
        sa.Column(
            "requires_manual_review", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_recon_disc_run_id", "broker_reconciliation_discrepancies", ["run_id"]
    )
    op.create_index(
        "idx_recon_disc_type", "broker_reconciliation_discrepancies", ["discrepancy_type"]
    )
    op.create_index(
        "idx_recon_disc_review",
        "broker_reconciliation_discrepancies",
        ["requires_manual_review"],
    )
    op.create_index(
        "idx_recon_disc_resolved", "broker_reconciliation_discrepancies", ["resolved"]
    )

    # ── instrument_sync_runs ──────────────────────────────────────────────
    op.create_table(
        "instrument_sync_runs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("upserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("idx_sync_runs_exchange", "instrument_sync_runs", ["exchange"])
    op.create_index("idx_sync_runs_success", "instrument_sync_runs", ["success"])


def downgrade() -> None:
    op.drop_table("instrument_sync_runs")
    op.drop_table("broker_reconciliation_discrepancies")
    op.drop_table("broker_reconciliation_runs")
    op.drop_table("broker_event_inbox")
    op.drop_table("broker_order_correlations")
    op.drop_table("broker_sessions")
