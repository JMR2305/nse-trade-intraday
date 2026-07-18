"""Initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-07-18 23:59:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    order_status = sa.Enum("PENDING", "OPEN", "PARTIAL_FILL", "COMPLETE", "CANCELLED", "REJECTED", "EXPIRED", name="order_status")
    order_status.create(op.get_bind(), checkfirst=True)
    order_side = sa.Enum("BUY", "SELL", name="order_side")
    order_side.create(op.get_bind(), checkfirst=True)
    order_type = sa.Enum("MARKET", "LIMIT", "SL", "SL-M", name="order_type")
    order_type.create(op.get_bind(), checkfirst=True)
    product_type = sa.Enum("MIS", "CNC", "NRML", name="product_type")
    product_type.create(op.get_bind(), checkfirst=True)
    session_status = sa.Enum("INITIALIZING", "ACTIVE", "PAUSED", "RECOVERING", "SHUTTING_DOWN", "CLOSED", name="session_status")
    session_status.create(op.get_bind(), checkfirst=True)
    trading_mode = sa.Enum("PAPER", "REPLAY", "SHADOW", "SIMULATION", "LIVE", name="trading_mode")
    trading_mode.create(op.get_bind(), checkfirst=True)
    signal_quality = sa.Enum("LOW", "MEDIUM", "HIGH", name="signal_quality")
    signal_quality.create(op.get_bind(), checkfirst=True)
    market_regime = sa.Enum("UNKNOWN", "RANGING", "UPTREND", "DOWNTREND", "STRONG_UPTREND", "STRONG_DOWNTREND", "EXPANDING_RANGE", name="market_regime")
    market_regime.create(op.get_bind(), checkfirst=True)
    data_quality_state = sa.Enum("LIVE", "DELAYED", "STALE", "BACKFILLING", "DISCONNECTED", name="data_quality_state")
    data_quality_state.create(op.get_bind(), checkfirst=True)
    kill_switch_level = sa.Enum("NORMAL", "PAUSE", "CANCEL_PENDING", "FLATTEN_ALL", name="kill_switch_level")
    kill_switch_level.create(op.get_bind(), checkfirst=True)
    severity = sa.Enum("INFO", "WARNING", "CRITICAL", name="severity")
    severity.create(op.get_bind(), checkfirst=True)
    incident_status = sa.Enum("OPEN", "INVESTIGATING", "RESOLVED", "CLOSED", name="incident_status")
    incident_status.create(op.get_bind(), checkfirst=True)
    audit_action = sa.Enum("INSERT", "UPDATE", "DELETE", name="audit_action")
    audit_action.create(op.get_bind(), checkfirst=True)
    heartbeat_status = sa.Enum("HEALTHY", "UNHEALTHY", "UNKNOWN", name="heartbeat_status")
    heartbeat_status.create(op.get_bind(), checkfirst=True)
    ledger_transaction = sa.Enum("DEPOSIT", "WITHDRAWAL", "TRADE_PROFIT", "TRADE_LOSS", "COSTS", "ADJUSTMENT", name="ledger_transaction")
    ledger_transaction.create(op.get_bind(), checkfirst=True)

    # Tables
    op.create_table("instrument_master",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_token", sa.BigInteger(), nullable=False),
        sa.Column("exchange", sa.String(length=10), nullable=False),
        sa.Column("tradingsymbol", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("instrument_type", sa.String(length=10), nullable=True),
        sa.Column("segment", sa.String(length=10), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("strike", sa.Numeric(12, 2), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tick_size", sa.Numeric(10, 4), nullable=False, server_default="0.05"),
        sa.Column("is_tradable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_token"),
        sa.UniqueConstraint("exchange", "tradingsymbol", "expiry", "strike", name="uq_instrument"),
    )
    op.create_index("idx_instrument_token", "instrument_master", ["instrument_token"])
    op.create_index("idx_instrument_symbol", "instrument_master", ["tradingsymbol"])
    op.create_index("idx_instrument_tradable", "instrument_master", ["is_tradable"])

    op.create_table("trading_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("INITIALIZING", "ACTIVE", "PAUSED", "RECOVERING", "SHUTTING_DOWN", "CLOSED", name="session_status"), nullable=False, server_default="INITIALIZING"),
        sa.Column("trading_mode", sa.Enum("PAPER", "REPLAY", "SHADOW", "SIMULATION", "LIVE", name="trading_mode"), nullable=False, server_default="PAPER"),
        sa.Column("previous_session_id", sa.String(length=50), nullable=True),
        sa.Column("recovery_reason", sa.String(length=100), nullable=True),
        sa.Column("recovery_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("idx_session_status", "trading_sessions", ["status"])
    op.create_index("idx_session_active", "trading_sessions", ["ended_at"])

    op.create_table("orders",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.String(length=50), nullable=True),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("instrument_token", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.Enum("BUY", "SELL", name="order_side"), nullable=False),
        sa.Column("order_type", sa.Enum("MARKET", "LIMIT", "SL", "SL-M", name="order_type"), nullable=False),
        sa.Column("product", sa.Enum("MIS", "CNC", "NRML", name="product_type"), nullable=False, server_default="MIS"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=True),
        sa.Column("trigger_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("stop_loss", sa.Numeric(12, 4), nullable=True),
        sa.Column("target", sa.Numeric(12, 4), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "OPEN", "PARTIAL_FILL", "COMPLETE", "CANCELLED", "REJECTED", "EXPIRED", name="order_status"), nullable=False, server_default="PENDING"),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["trading_sessions.session_id"]),
        sa.ForeignKeyConstraint(["instrument_token"], ["instrument_master.instrument_token"]),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint("quantity > 0", name="ck_order_quantity_positive"),
        sa.CheckConstraint("price IS NULL OR price > 0", name="ck_order_price_positive"),
        sa.CheckConstraint("trigger_price IS NULL OR trigger_price > 0", name="ck_order_trigger_positive"),
        sa.CheckConstraint("stop_loss IS NULL OR stop_loss > 0", name="ck_order_sl_positive"),
        sa.CheckConstraint("target IS NULL OR target > 0", name="ck_order_target_positive"),
    )
    op.create_index("idx_orders_session", "orders", ["session_id"])
    op.create_index("idx_orders_status", "orders", ["status"])
    op.create_index("idx_orders_instrument", "orders", ["instrument_token"])
    op.create_index("idx_orders_idempotency", "orders", ["idempotency_key"])

    op.create_table("order_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
    )
    op.create_index("idx_order_events_order", "order_events", ["order_id"])

    op.create_table("fills",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("fill_id", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("brokerage", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("stt", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("exchange_charge", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("gst", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("sebi_charge", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("stamp_duty", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.CheckConstraint("quantity > 0", name="ck_fill_quantity_positive"),
        sa.CheckConstraint("price > 0", name="ck_fill_price_positive"),
    )
    op.create_index("idx_fills_order", "fills", ["order_id"])

    op.create_table("positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("instrument_token", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.Enum("BUY", "SELL", name="order_side"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("last_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["trading_sessions.session_id"]),
        sa.ForeignKeyConstraint(["instrument_token"], ["instrument_master.instrument_token"]),
        sa.CheckConstraint("quantity > 0", name="ck_position_quantity_positive"),
        sa.CheckConstraint("average_price > 0", name="ck_position_avg_price_positive"),
    )
    op.create_index("idx_positions_session", "positions", ["session_id"])
    op.create_index("idx_positions_instrument", "positions", ["instrument_token"])
    op.create_index("idx_positions_open", "positions", ["is_open"])

    op.create_table("paper_account_ledger",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("transaction_type", sa.Enum("DEPOSIT", "WITHDRAWAL", "TRADE_PROFIT", "TRADE_LOSS", "COSTS", "ADJUSTMENT", name="ledger_transaction"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 4), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("related_order_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["trading_sessions.session_id"]),
        sa.ForeignKeyConstraint(["related_order_id"], ["orders.id"]),
    )
    op.create_index("idx_ledger_session", "paper_account_ledger", ["session_id"])
    op.create_index("idx_ledger_order", "paper_account_ledger", ["related_order_id"])

    op.create_table("minute_bars",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_token", sa.BigInteger(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=False),
        sa.Column("high", sa.Numeric(12, 4), nullable=False),
        sa.Column("low", sa.Numeric(12, 4), nullable=False),
        sa.Column("close", sa.Numeric(12, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("oi", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["instrument_token"], ["instrument_master.instrument_token"]),
        sa.CheckConstraint("open > 0", name="ck_bar_open_positive"),
        sa.CheckConstraint("high > 0", name="ck_bar_high_positive"),
        sa.CheckConstraint("low > 0", name="ck_bar_low_positive"),
        sa.CheckConstraint("close > 0", name="ck_bar_close_positive"),
        sa.CheckConstraint("high >= low", name="ck_bar_high_ge_low"),
    )
    op.create_index("idx_bars_instrument", "minute_bars", ["instrument_token"])
    op.create_index("idx_bars_timestamp", "minute_bars", ["timestamp"])
    op.create_index("idx_bars_instrument_timestamp", "minute_bars", ["instrument_token", "timestamp"])

    op.create_table("incidents",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.Enum("INFO", "WARNING", "CRITICAL", name="severity"), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("OPEN", "INVESTIGATING", "RESOLVED", "CLOSED", name="incident_status"), nullable=False, server_default="OPEN"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=100), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["trading_sessions.session_id"]),
    )
    op.create_index("idx_incidents_session", "incidents", ["session_id"])
    op.create_index("idx_incidents_status", "incidents", ["status"])
    op.create_index("idx_incidents_severity", "incidents", ["severity"])

    op.create_table("reconciliation_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=50), nullable=False),
        sa.Column("internal_value", postgresql.JSONB(), nullable=True),
        sa.Column("external_value", postgresql.JSONB(), nullable=True),
        sa.Column("discrepancy", postgresql.JSONB(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["trading_sessions.session_id"]),
    )
    op.create_index("idx_recon_session", "reconciliation_log", ["session_id"])
    op.create_index("idx_recon_unresolved", "reconciliation_log", ["is_resolved"])

    op.create_table("audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("table_name", sa.String(length=50), nullable=False),
        sa.Column("record_id", sa.String(length=50), nullable=False),
        sa.Column("action", sa.Enum("INSERT", "UPDATE", "DELETE", name="audit_action"), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_table", "audit_logs", ["table_name"])
    op.create_index("idx_audit_record", "audit_logs", ["record_id"])
    op.create_index("idx_audit_actor", "audit_logs", ["actor"])

    op.create_table("system_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(length=50), nullable=False),
        sa.Column("last_beat", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.Enum("HEALTHY", "UNHEALTHY", "UNKNOWN", name="heartbeat_status"), nullable=False, server_default="UNKNOWN"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_name"),
    )
    op.create_index("idx_heartbeat_service", "system_heartbeats", ["service_name"])

    op.create_table("idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("idx_idempotency_key", "idempotency_records", ["key"])
    op.create_index("idx_idempotency_expires", "idempotency_records", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_idempotency_expires", table_name="idempotency_records")
    op.drop_index("idx_idempotency_key", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("idx_heartbeat_service", table_name="system_heartbeats")
    op.drop_table("system_heartbeats")
    op.drop_index("idx_audit_actor", table_name="audit_logs")
    op.drop_index("idx_audit_record", table_name="audit_logs")
    op.drop_index("idx_audit_table", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("idx_recon_unresolved", table_name="reconciliation_log")
    op.drop_index("idx_recon_session", table_name="reconciliation_log")
    op.drop_table("reconciliation_log")
    op.drop_index("idx_incidents_severity", table_name="incidents")
    op.drop_index("idx_incidents_status", table_name="incidents")
    op.drop_index("idx_incidents_session", table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("idx_bars_instrument_timestamp", table_name="minute_bars")
    op.drop_index("idx_bars_timestamp", table_name="minute_bars")
    op.drop_index("idx_bars_instrument", table_name="minute_bars")
    op.drop_table("minute_bars")
    op.drop_index("idx_ledger_order", table_name="paper_account_ledger")
    op.drop_index("idx_ledger_session", table_name="paper_account_ledger")
    op.drop_table("paper_account_ledger")
    op.drop_index("idx_positions_open", table_name="positions")
    op.drop_index("idx_positions_instrument", table_name="positions")
    op.drop_index("idx_positions_session", table_name="positions")
    op.drop_table("positions")
    op.drop_index("idx_fills_order", table_name="fills")
    op.drop_table("fills")
    op.drop_index("idx_order_events_order", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("idx_orders_idempotency", table_name="orders")
    op.drop_index("idx_orders_instrument", table_name="orders")
    op.drop_index("idx_orders_status", table_name="orders")
    op.drop_index("idx_orders_session", table_name="orders")
    op.drop_table("orders")
    op.drop_index("idx_session_active", table_name="trading_sessions")
    op.drop_index("idx_session_status", table_name="trading_sessions")
    op.drop_table("trading_sessions")
    op.drop_index("idx_instrument_tradable", table_name="instrument_master")
    op.drop_index("idx_instrument_symbol", table_name="instrument_master")
    op.drop_index("idx_instrument_token", table_name="instrument_master")
    op.drop_table("instrument_master")
    op.execute("DROP TYPE IF EXISTS ledger_transaction")
    op.execute("DROP TYPE IF EXISTS heartbeat_status")
    op.execute("DROP TYPE IF EXISTS audit_action")
    op.execute("DROP TYPE IF EXISTS incident_status")
    op.execute("DROP TYPE IF EXISTS severity")
    op.execute("DROP TYPE IF EXISTS kill_switch_level")
    op.execute("DROP TYPE IF EXISTS data_quality_state")
    op.execute("DROP TYPE IF EXISTS market_regime")
    op.execute("DROP TYPE IF EXISTS signal_quality")
    op.execute("DROP TYPE IF EXISTS trading_mode")
    op.execute("DROP TYPE IF EXISTS session_status")
    op.execute("DROP TYPE IF EXISTS product_type")
    op.execute("DROP TYPE IF EXISTS order_type")
    op.execute("DROP TYPE IF EXISTS order_side")
    op.execute("DROP TYPE IF EXISTS order_status")
