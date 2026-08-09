"""SQLAlchemy ORM models for RC-10C1 Portfolio Core persistence.

Tables:
  - portfolio_snapshots
  - portfolio_events
  - capital_allocations
  - exposure_snapshots
  - reconciliation_runs
  - reconciliation_discrepancies
  - portfolio_health_events
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from src.database.models.base import Base

_MONEY = dict(precision=20, scale=6)


class PortfolioSnapshotModel(Base):
    """Persistent representation of a PortfolioSnapshot."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Text, nullable=False, unique=True)
    portfolio_id = Column(Text, nullable=False, index=True)
    status = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    paper_mode = Column(Boolean, nullable=False, default=True)
    cash_available = Column(Numeric(**_MONEY), nullable=False)
    cash_blocked = Column(Numeric(**_MONEY), nullable=False)
    cash_total = Column(Numeric(**_MONEY), nullable=False)
    buying_power_net = Column(Numeric(**_MONEY), nullable=False)
    equity = Column(Numeric(**_MONEY), nullable=False)
    open_position_count = Column(Integer, nullable=False, default=0)
    pending_order_count = Column(Integer, nullable=False, default=0)
    realised_pnl = Column(Numeric(**_MONEY), nullable=False, default=0)
    unrealised_pnl = Column(Numeric(**_MONEY), nullable=False, default=0)
    daily_pnl = Column(Numeric(**_MONEY), nullable=False, default=0)
    drawdown = Column(Numeric(**_MONEY), nullable=False, default=0)
    snapshot_payload = Column(JSONB, nullable=True)
    checksum = Column(Text, nullable=True)
    # Durable replay cursor: highest contiguous portfolio_events serial id
    # incorporated in this snapshot (nullable for legacy rows).
    event_cursor = Column(BigInteger, nullable=True)
    snapshotted_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<PortfolioSnapshotModel(snapshot_id={self.snapshot_id!r}, "
            f"portfolio_id={self.portfolio_id!r}, version={self.version})>"
        )


class PortfolioEventModel(Base):
    """Persistent representation of a PortfolioEvent ledger entry."""

    __tablename__ = "portfolio_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Text, nullable=False, unique=True)
    idempotency_key = Column(Text, nullable=False, unique=True, index=True)
    event_type = Column(Text, nullable=False, index=True)
    portfolio_id = Column(Text, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    instrument_token = Column(Integer, nullable=True)
    internal_order_id = Column(Text, nullable=True)
    broker_order_id = Column(Text, nullable=True)
    strategy_id = Column(Text, nullable=True)
    correlation_id = Column(Text, nullable=True, index=True)
    payload = Column(JSONB, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "sequence", name="uq_portfolio_event_sequence"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PortfolioEventModel(event_id={self.event_id!r}, "
            f"event_type={self.event_type!r}, sequence={self.sequence})>"
        )


class CapitalAllocationModel(Base):
    """Persistent representation of an AllocationDecision."""

    __tablename__ = "capital_allocations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(Text, nullable=False, unique=True)
    strategy_id = Column(Text, nullable=False, index=True)
    instrument_token = Column(Integer, nullable=True)
    requested_capital = Column(Numeric(**_MONEY), nullable=False)
    approved_capital = Column(Numeric(**_MONEY), nullable=False)
    rejected_capital = Column(Numeric(**_MONEY), nullable=False, default=0)
    status = Column(Text, nullable=False)
    reason_codes = Column(JSONB, nullable=True)
    binding_limit = Column(Text, nullable=True)
    portfolio_state_version = Column(Integer, nullable=False, default=0)
    decided_at = Column(DateTime(timezone=True), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    correlation_id = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CapitalAllocationModel(decision_id={self.decision_id!r}, "
            f"strategy_id={self.strategy_id!r}, status={self.status!r})>"
        )


class ExposureSnapshotModel(Base):
    """Persistent representation of an ExposureSnapshot."""

    __tablename__ = "exposure_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Text, nullable=False, index=True)
    gross_exposure = Column(Numeric(**_MONEY), nullable=False)
    net_exposure = Column(Numeric(**_MONEY), nullable=False)
    long_exposure = Column(Numeric(**_MONEY), nullable=False, default=0)
    short_exposure = Column(Numeric(**_MONEY), nullable=False, default=0)
    pending_order_exposure = Column(Numeric(**_MONEY), nullable=False, default=0)
    portfolio_equity = Column(Numeric(**_MONEY), nullable=False)
    stale_prices = Column(Boolean, nullable=False, default=False)
    instrument_exposures = Column(JSONB, nullable=True)
    sector_exposures = Column(JSONB, nullable=True)
    strategy_exposures = Column(JSONB, nullable=True)
    state_version = Column(Integer, nullable=False, default=0)
    snapshotted_at = Column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<ExposureSnapshotModel(portfolio_id={self.portfolio_id!r}, "
            f"snapshotted_at={self.snapshotted_at})>"
        )


class ReconciliationRunModel(Base):
    """Persistent representation of a PortfolioReconciliationReport."""

    __tablename__ = "reconciliation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Text, nullable=False, unique=True)
    portfolio_id = Column(Text, nullable=False, index=True)
    dry_run = Column(Boolean, nullable=False)
    critical_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    portfolio_ready = Column(Boolean, nullable=False)
    notes = Column(Text, nullable=True)
    state_version = Column(Integer, nullable=False, default=0)
    broker_snapshot_age_s = Column(Numeric(**_MONEY), nullable=True)
    # Full serialized PortfolioReconciliationReport for exact round-trip
    # by the reconciliation repository (nullable for legacy rows).
    report_payload = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ReconciliationRunModel(run_id={self.run_id!r}, "
            f"portfolio_id={self.portfolio_id!r}, portfolio_ready={self.portfolio_ready})>"
        )


class ReconciliationDiscrepancyModel(Base):
    """Persistent representation of a PortfolioDiscrepancy."""

    __tablename__ = "reconciliation_discrepancies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    discrepancy_id = Column(Text, nullable=False, unique=True)
    run_id = Column(Text, nullable=False, index=True)
    portfolio_id = Column(Text, nullable=False, index=True)
    discrepancy_type = Column(Text, nullable=False)
    instrument_token = Column(Integer, nullable=True)
    instrument_symbol = Column(Text, nullable=True)
    local_value = Column(Text, nullable=True)
    broker_value = Column(Text, nullable=True)
    severity = Column(Text, nullable=False)
    resolved = Column(Boolean, nullable=False, default=False)
    resolution_note = Column(Text, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<ReconciliationDiscrepancyModel(discrepancy_id={self.discrepancy_id!r}, "
            f"discrepancy_type={self.discrepancy_type!r}, severity={self.severity!r})>"
        )


class PortfolioHealthEventModel(Base):
    """Persistent representation of a PortfolioHealth check event."""

    __tablename__ = "portfolio_health_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Text, nullable=False, index=True)
    status = Column(Text, nullable=False)
    readiness = Column(Boolean, nullable=False)
    liveness = Column(Boolean, nullable=False)
    degraded = Column(Boolean, nullable=False)
    failure_reason = Column(Text, nullable=True)
    unresolved_discrepancies = Column(Integer, nullable=False, default=0)
    critical_limit_breaches = Column(Integer, nullable=False, default=0)
    state_freshness_s = Column(Numeric(**_MONEY), nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<PortfolioHealthEventModel(portfolio_id={self.portfolio_id!r}, "
            f"status={self.status!r}, readiness={self.readiness})>"
        )
