"""RC-10D: ORM models for broker integration tables.

Defines:
  BrokerSessionModel          → broker_sessions
  BrokerOrderCorrelation      → broker_order_correlations
  BrokerEventInbox            → broker_event_inbox
  BrokerReconciliationRun     → broker_reconciliation_runs
  BrokerReconciliationDiscrepancy → broker_reconciliation_discrepancies
  InstrumentSyncRun           → instrument_sync_runs
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.database.connection import Base


# ---------------------------------------------------------------------------
# broker_sessions
# ---------------------------------------------------------------------------

class BrokerSessionModel(Base):
    """Persisted broker session metadata.

    The access_token itself is NOT stored here — only metadata.
    Token is read from env vars at runtime.
    """
    __tablename__ = "broker_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_uuid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    broker_name: Mapped[str] = mapped_column(String(32), nullable=False, default="zerodha")
    user_id: Mapped[Optional[str]] = mapped_column(String(64))
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    invalidation_reason: Mapped[Optional[str]] = mapped_column(String(200))

    __table_args__ = (
        Index("idx_broker_sessions_uuid", "session_uuid"),
        Index("idx_broker_sessions_valid", "is_valid"),
        Index("idx_broker_sessions_broker", "broker_name"),
    )


# ---------------------------------------------------------------------------
# broker_order_correlations
# ---------------------------------------------------------------------------

CORRELATION_STATUS = [
    "PENDING", "SUBMITTED", "CONFIRMED", "UNCERTAIN", "RECONCILED", "FAILED"
]


class BrokerOrderCorrelation(Base):
    """Idempotent order submission tracking.

    Links internal_order_id → broker_order_id.
    UNCERTAIN means placement timed out — reconciliation will resolve.
    """
    __tablename__ = "broker_order_correlations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    internal_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trading_symbol: Mapped[Optional[str]] = mapped_column(String(50))
    exchange: Mapped[Optional[str]] = mapped_column(String(10))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_correlations_internal", "internal_order_id"),
        Index("idx_correlations_broker", "broker_order_id"),
        Index("idx_correlations_status", "status"),
        Index("idx_correlations_idempotency", "idempotency_key"),
    )


# ---------------------------------------------------------------------------
# broker_event_inbox
# ---------------------------------------------------------------------------

class BrokerEventInbox(Base):
    """Persisted broker events awaiting processing.

    Used for unknown statuses and events that cannot be immediately resolved.
    """
    __tablename__ = "broker_event_inbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="websocket")
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_notes: Mapped[Optional[str]] = mapped_column(Text)
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_event_inbox_processed", "processed"),
        Index("idx_event_inbox_review", "requires_review"),
    )


# ---------------------------------------------------------------------------
# broker_reconciliation_runs
# ---------------------------------------------------------------------------

class BrokerReconciliationRun(Base):
    """One reconciliation run record."""
    __tablename__ = "broker_reconciliation_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    orders_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clean: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_recon_runs_run_id", "run_id"),
        Index("idx_recon_runs_trigger", "trigger"),
        Index("idx_recon_runs_clean", "clean"),
    )


# ---------------------------------------------------------------------------
# broker_reconciliation_discrepancies
# ---------------------------------------------------------------------------

class BrokerReconciliationDiscrepancy(Base):
    """A single discrepancy found during a reconciliation run."""
    __tablename__ = "broker_reconciliation_discrepancies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    discrepancy_type: Mapped[str] = mapped_column(String(50), nullable=False)
    internal_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    trading_symbol: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    local_value: Mapped[Optional[str]] = mapped_column(Text)
    broker_value: Mapped[Optional[str]] = mapped_column(Text)
    requires_manual_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_recon_disc_run_id", "run_id"),
        Index("idx_recon_disc_type", "discrepancy_type"),
        Index("idx_recon_disc_review", "requires_manual_review"),
        Index("idx_recon_disc_resolved", "resolved"),
    )


# ---------------------------------------------------------------------------
# instrument_sync_runs
# ---------------------------------------------------------------------------

class InstrumentSyncRun(Base):
    """Record of each instrument master download/sync run."""
    __tablename__ = "instrument_sync_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    downloaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[Optional[str]] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_sync_runs_exchange", "exchange"),
        Index("idx_sync_runs_success", "success"),
    )
