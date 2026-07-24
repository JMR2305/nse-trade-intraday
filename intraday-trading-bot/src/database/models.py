"""SQLAlchemy ORM models for the trading platform."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime, Date,
    Numeric, Text, ForeignKey, CheckConstraint, Index, UniqueConstraint,
    Enum as SQLEnum, JSON,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from src.database.connection import Base


# ============================================================================
# ENUMS (as Python strings for SQLAlchemy)
# ============================================================================

ORDER_STATUS = ["PENDING", "OPEN", "PARTIAL_FILL", "COMPLETE", "CANCELLED", "REJECTED", "EXPIRED"]
ORDER_SIDE = ["BUY", "SELL"]
ORDER_TYPE = ["MARKET", "LIMIT", "SL", "SL-M"]
PRODUCT_TYPE = ["MIS", "CNC", "NRML"]
SESSION_STATUS = ["INITIALIZING", "ACTIVE", "PAUSED", "RECOVERING", "SHUTTING_DOWN", "CLOSED"]
TRADING_MODE = ["PAPER", "REPLAY", "SHADOW", "SIMULATION", "LIVE"]
SIGNAL_QUALITY = ["LOW", "MEDIUM", "HIGH"]
MARKET_REGIME = ["UNKNOWN", "RANGING", "UPTREND", "DOWNTREND", "STRONG_UPTREND", "STRONG_DOWNTREND", "EXPANDING_RANGE"]
DATA_QUALITY_STATE = ["LIVE", "DELAYED", "STALE", "BACKFILLING", "DISCONNECTED"]
KILL_SWITCH_LEVEL = ["NORMAL", "PAUSE", "CANCEL_PENDING", "FLATTEN_ALL"]
SEVERITY = ["INFO", "WARNING", "CRITICAL"]
INCIDENT_STATUS = ["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"]
AUDIT_ACTION = ["INSERT", "UPDATE", "DELETE"]
HEARTBEAT_STATUS = ["HEALTHY", "UNHEALTHY", "UNKNOWN"]
LEDGER_TRANSACTION = ["DEPOSIT", "WITHDRAWAL", "TRADE_PROFIT", "TRADE_LOSS", "COSTS", "ADJUSTMENT"]


# ============================================================================
# INSTRUMENT MASTER
# ============================================================================

class InstrumentMaster(Base):
    __tablename__ = "instrument_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_token: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    instrument_type: Mapped[Optional[str]] = mapped_column(String(10))  # EQ, FUT, CE, PE
    segment: Mapped[Optional[str]] = mapped_column(String(10))  # NSE, BSE, NFO, etc.
    expiry: Mapped[Optional[Date]] = mapped_column(Date)
    strike: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=Decimal("0.05"))
    is_tradable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("exchange", "tradingsymbol", "expiry", "strike", name="uq_instrument"),
        Index("idx_instrument_token", "instrument_token"),
        Index("idx_instrument_symbol", "tradingsymbol"),
        Index("idx_instrument_tradable", "is_tradable"),
    )


# ============================================================================
# TRADING SESSIONS
# ============================================================================

class TradingSession(Base):
    __tablename__ = "trading_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(SQLEnum(*SESSION_STATUS, name="session_status"), nullable=False, default="INITIALIZING")
    trading_mode: Mapped[str] = mapped_column(SQLEnum(*TRADING_MODE, name="trading_mode"), nullable=False, default="PAPER")

    previous_session_id: Mapped[Optional[str]] = mapped_column(String(50))
    recovery_reason: Mapped[Optional[str]] = mapped_column(String(100))
    recovery_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="session")
    positions: Mapped[list["Position"]] = relationship("Position", back_populates="session")
    ledger_entries: Mapped[list["PaperAccountLedger"]] = relationship("PaperAccountLedger", back_populates="session")
    incidents: Mapped[list["Incident"]] = relationship("Incident", back_populates="session")

    __table_args__ = (
        Index("idx_session_status", "status"),
        Index("idx_session_active", "ended_at"),
    )


# ============================================================================
# ORDERS
# ============================================================================

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(50))  # Broker/paper order ID
    session_id: Mapped[str] = mapped_column(String(50), ForeignKey("trading_sessions.session_id"), nullable=False)
    instrument_token: Mapped[int] = mapped_column(BigInteger, ForeignKey("instrument_master.instrument_token"), nullable=False)

    side: Mapped[str] = mapped_column(SQLEnum(*ORDER_SIDE, name="order_side"), nullable=False)
    order_type: Mapped[str] = mapped_column(SQLEnum(*ORDER_TYPE, name="order_type"), nullable=False)
    product: Mapped[str] = mapped_column(SQLEnum(*PRODUCT_TYPE, name="product_type"), nullable=False, default="MIS")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    trigger_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    target: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))

    status: Mapped[str] = mapped_column(SQLEnum(*ORDER_STATUS, name="order_status"), nullable=False, default="PENDING")
    status_message: Mapped[Optional[str]] = mapped_column(Text)

    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="system")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    session: Mapped["TradingSession"] = relationship("TradingSession", back_populates="orders")
    events: Mapped[list["OrderEvent"]] = relationship("OrderEvent", back_populates="order")
    fills: Mapped[list["Fill"]] = relationship("Fill", back_populates="order")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_quantity_positive"),
        CheckConstraint("price IS NULL OR price > 0", name="ck_order_price_positive"),
        CheckConstraint("trigger_price IS NULL OR trigger_price > 0", name="ck_order_trigger_positive"),
        CheckConstraint("stop_loss IS NULL OR stop_loss > 0", name="ck_order_sl_positive"),
        CheckConstraint("target IS NULL OR target > 0", name="ck_order_target_positive"),
        Index("idx_orders_session", "session_id"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_instrument", "instrument_token"),
        Index("idx_orders_idempotency", "idempotency_key"),
    )


# ============================================================================
# ORDER EVENTS
# ============================================================================

class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="events")

    __table_args__ = (
        Index("idx_order_events_order", "order_id"),
    )


# ============================================================================
# FILLS
# ============================================================================

class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False)
    fill_id: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    # Cost tracking (versioned schedule)
    brokerage: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    stt: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    exchange_charge: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    gst: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    sebi_charge: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    stamp_duty: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="fills")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_fill_quantity_positive"),
        CheckConstraint("price > 0", name="ck_fill_price_positive"),
        Index("idx_fills_order", "order_id"),
    )


# ============================================================================
# POSITIONS
# ============================================================================

class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), ForeignKey("trading_sessions.session_id"), nullable=False)
    instrument_token: Mapped[int] = mapped_column(BigInteger, ForeignKey("instrument_master.instrument_token"), nullable=False)

    side: Mapped[str] = mapped_column(SQLEnum(*ORDER_SIDE, name="order_side"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    last_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    session: Mapped["TradingSession"] = relationship("TradingSession", back_populates="positions")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_position_quantity_positive"),
        CheckConstraint("average_price > 0", name="ck_position_avg_price_positive"),
        Index("idx_positions_session", "session_id"),
        Index("idx_positions_instrument", "instrument_token"),
        Index("idx_positions_open", "is_open"),
    )


# ============================================================================
# PAPER ACCOUNT LEDGER
# ============================================================================

class PaperAccountLedger(Base):
    __tablename__ = "paper_account_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), ForeignKey("trading_sessions.session_id"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(SQLEnum(*LEDGER_TRANSACTION, name="ledger_transaction"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    related_order_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("orders.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    session: Mapped["TradingSession"] = relationship("TradingSession", back_populates="ledger_entries")

    __table_args__ = (
        Index("idx_ledger_session", "session_id"),
        Index("idx_ledger_order", "related_order_id"),
    )


# ============================================================================
# MINUTE BARS (partition-ready, not partitioned yet)
# ============================================================================

class MinuteBar(Base):
    __tablename__ = "minute_bars"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_token: Mapped[int] = mapped_column(BigInteger, ForeignKey("instrument_master.instrument_token"), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    oi: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("open > 0", name="ck_bar_open_positive"),
        CheckConstraint("high > 0", name="ck_bar_high_positive"),
        CheckConstraint("low > 0", name="ck_bar_low_positive"),
        CheckConstraint("close > 0", name="ck_bar_close_positive"),
        CheckConstraint("high >= low", name="ck_bar_high_ge_low"),
        Index("idx_bars_instrument", "instrument_token"),
        Index("idx_bars_timestamp", "timestamp"),
        Index("idx_bars_instrument_timestamp", "instrument_token", "timestamp"),
    )


# ============================================================================
# INCIDENTS
# ============================================================================

class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), ForeignKey("trading_sessions.session_id"), nullable=False)
    severity: Mapped[str] = mapped_column(SQLEnum(*SEVERITY, name="severity"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(SQLEnum(*INCIDENT_STATUS, name="incident_status"), nullable=False, default="OPEN")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    session: Mapped["TradingSession"] = relationship("TradingSession", back_populates="incidents")

    __table_args__ = (
        Index("idx_incidents_session", "session_id"),
        Index("idx_incidents_status", "status"),
        Index("idx_incidents_severity", "severity"),
    )


# ============================================================================
# RECONCILIATION LOG
# ============================================================================

class ReconciliationLog(Base):
    __tablename__ = "reconciliation_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), ForeignKey("trading_sessions.session_id"), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    internal_value: Mapped[Optional[dict]] = mapped_column(JSON)
    external_value: Mapped[Optional[dict]] = mapped_column(JSON)
    discrepancy: Mapped[Optional[dict]] = mapped_column(JSON)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_recon_session", "session_id"),
        Index("idx_recon_unresolved", "is_resolved"),
    )


# ============================================================================
# AUDIT LOGS
# ============================================================================

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(50), nullable=False)
    record_id: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(SQLEnum(*AUDIT_ACTION, name="audit_action"), nullable=False)
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_audit_table", "table_name"),
        Index("idx_audit_record", "record_id"),
        Index("idx_audit_actor", "actor"),
    )


# ============================================================================
# SYSTEM HEARTBEATS
# ============================================================================

class SystemHeartbeat(Base):
    __tablename__ = "system_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    last_beat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(SQLEnum(*HEARTBEAT_STATUS, name="heartbeat_status"), nullable=False, default="UNKNOWN")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_heartbeat_service", "service_name"),
    )


# ============================================================================
# IDEMPOTENCY RECORDS
# ============================================================================

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_idempotency_key", "key"),
        Index("idx_idempotency_expires", "expires_at"),
    )


# ===========================================================================
# RISK ENGINE
# ===========================================================================

class RiskStateModel(Base):
    """ORM model for risk_state_snapshots table.

    Stores point-in-time snapshots of RiskState for crash recovery.
    Each row represents one snapshot for one account.
    """

    __tablename__ = "risk_state_snapshots"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=__import__("uuid").uuid4)
    account_id = Column(String(64), nullable=False, index=True)
    snapshot_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Monetary fields — Decimal precision
    daily_realized_pnl = Column(Numeric(20, 8), nullable=False, default=0)
    daily_turnover = Column(Numeric(20, 8), nullable=False, default=0)
    peak_equity = Column(Numeric(20, 8), nullable=False, default=0)

    # Kill switch state
    kill_switch_active = Column(Boolean, nullable=False, default=False)
    kill_switch_reason = Column(Text, nullable=True)

    # RC-8B: Extended safety and counter fields
    trade_count = Column(Integer, nullable=False, default=0)
    order_count = Column(Integer, nullable=False, default=0)
    emergency_halt_active = Column(Boolean, nullable=False, default=False)
    circuit_breaker_triggered = Column(Boolean, nullable=False, default=False)

    # Message counts stored as JSONB
    message_counts = Column(JSONB, nullable=False, default=dict)

    # Extra metadata for extensibility
    extra_data = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_risk_state_account_timestamp", "account_id", "snapshot_timestamp"),
    )


# ===========================================================================
# STRATEGY PERSISTENCE (Batch 9C)
# ===========================================================================

class StrategyModel(Base):
    """ORM model for the strategies table.

    Stores strategy registration, type, configuration, instrument tokens,
    lifecycle state, and timestamps. strategy_id is the natural key.
    """

    __tablename__ = "strategies"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=__import__("uuid").uuid4)
    strategy_id = Column(String(64), nullable=False, index=True)
    strategy_type = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    account_id = Column(String(64), nullable=True, index=True)
    configuration = Column(JSON(), nullable=False, default=dict)
    instrument_tokens = Column(JSON(), nullable=False, default=list)
    lifecycle_state = Column(String(32), nullable=False, index=True)
    enabled = Column(Boolean(), nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_strategies_strategy_id"),
        Index("ix_strategies_account_lifecycle", "account_id", "lifecycle_state"),
        Index("ix_strategies_type_state", "strategy_type", "lifecycle_state"),
    )


class StrategySignalModel(Base):
    """ORM model for the strategy_signals table.

    Stores every signal emitted by a strategy, including routing status,
    the client_order_id assigned on successful routing, and any rejection reason.
    """

    __tablename__ = "strategy_signals"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=__import__("uuid").uuid4)
    signal_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    strategy_id = Column(String(64), nullable=False, index=True)
    account_id = Column(String(64), nullable=True, index=True)
    instrument_token = Column(String(64), nullable=False, index=True)
    action = Column(String(16), nullable=False)
    side = Column(String(8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    order_type = Column(String(16), nullable=False)
    limit_price = Column(Numeric(20, 8), nullable=True)
    trigger_price = Column(Numeric(20, 8), nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    routing_status = Column(String(16), nullable=False, default="PENDING")
    routed_client_order_id = Column(String(64), nullable=True)
    rejection_reason = Column(Text(), nullable=True)
    extra_data = Column(JSON(), nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_strategy_signals_signal_id"),
        Index("ix_strategy_signals_strategy_status", "strategy_id", "routing_status"),
        Index("ix_strategy_signals_pending", "routing_status", "timestamp"),
        Index("ix_strategy_signals_routed_coid", "routed_client_order_id"),
    )


class StrategyStateModel(Base):
    """ORM model for the strategy_state_snapshots table.

    Stores a point-in-time snapshot of a strategy's runtime counters,
    pending order IDs, and latest signal timestamp.
    """

    __tablename__ = "strategy_state_snapshots"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=__import__("uuid").uuid4)
    strategy_id = Column(String(64), nullable=False, index=True)
    lifecycle_state = Column(String(32), nullable=False)
    pending_order_ids = Column(JSON(), nullable=False, default=list)
    latest_signal_timestamp = Column(DateTime(timezone=True), nullable=True)
    emitted_signal_count = Column(Integer(), nullable=False, default=0)
    routed_signal_count = Column(Integer(), nullable=False, default=0)
    rejected_signal_count = Column(Integer(), nullable=False, default=0)
    fill_count = Column(Integer(), nullable=False, default=0)
    extra_data = Column(JSON(), nullable=False, default=dict)
    snapshot_timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "snapshot_timestamp",
            name="uq_strategy_state_snapshots_strategy_timestamp",
        ),
        Index(
            "ix_strategy_state_snapshots_strategy_latest",
            "strategy_id",
            "snapshot_timestamp",
        ),
    )


# ===========================================================================
# ANNOUNCEMENTS (RC-10A)
# ===========================================================================

class Announcement(Base):
    """Corporate announcement record (BSE/NSE feed)."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    announcement_id: Mapped[str] = mapped_column(String(100), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    instrument_token: Mapped[str] = mapped_column(String(50), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("exchange", "announcement_id", name="uq_announcement_exchange_id"),
        Index("ix_announcements_instrument_published", "instrument_token", "published_at"),
        Index("ix_announcements_classification_published", "classification", "published_at"),
    )


# ===========================================================================
# FORECAST BENCHMARKS (RC-10B)
# ===========================================================================

class ForecastBenchmark(Base):
    """Records individual AI forecast outcomes for accuracy tracking."""

    __tablename__ = "forecast_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    instrument_token: Mapped[str] = mapped_column(String(50), nullable=False)
    forecast_direction: Mapped[str] = mapped_column(String(10), nullable=False)
    actual_direction: Mapped[str] = mapped_column(String(10), nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    forecast_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actual_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    model_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_forecast_benchmarks_instrument", "instrument_token"),
        Index("ix_forecast_benchmarks_timestamp", "forecast_timestamp"),
        Index("ix_forecast_benchmarks_correct", "correct"),
    )
