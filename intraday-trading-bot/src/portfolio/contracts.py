"""RC-10C1: Portfolio domain contracts.

All models are immutable Pydantic models (frozen=True).
Decimal is used for money, prices, quantities, ratios, and percentages.
Timestamps are always timezone-aware (UTC).
NaN and infinite Decimal values are rejected at validation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Helpers ────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_decimal(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Cannot coerce {v!r} to Decimal")


def _reject_nan_inf(v: Decimal) -> Decimal:
    if not v.is_finite():
        raise ValueError(f"Decimal value must be finite (got {v})")
    return v


def _coerce_and_validate(v) -> Decimal:
    return _reject_nan_inf(_coerce_decimal(v))


# ── Enums ──────────────────────────────────────────────────────────────────

class PortfolioStatus(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZING = "INITIALIZING"
    RECOVERING = "RECOVERING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    CLOSED = "CLOSED"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    PENDING_OPEN = "PENDING_OPEN"


class AllocationStatus(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LimitSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class PortfolioDiscrepancyType(str, Enum):
    LOCAL_ONLY_POSITION = "LOCAL_ONLY_POSITION"
    BROKER_ONLY_POSITION = "BROKER_ONLY_POSITION"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    AVG_PRICE_MISMATCH = "AVG_PRICE_MISMATCH"
    REALISED_PNL_MISMATCH = "REALISED_PNL_MISMATCH"
    MARGIN_MISMATCH = "MARGIN_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"
    MISSING_FILL = "MISSING_FILL"
    DUPLICATE_FILL = "DUPLICATE_FILL"
    STALE_BROKER_SNAPSHOT = "STALE_BROKER_SNAPSHOT"
    STALE_LOCAL_STATE = "STALE_LOCAL_STATE"
    UNKNOWN_INSTRUMENT = "UNKNOWN_INSTRUMENT"
    UNRESOLVED_ORDER = "UNRESOLVED_ORDER"


class PortfolioEventType(str, Enum):
    PORTFOLIO_INITIALIZED = "portfolio_initialized"
    CAPITAL_DEPOSITED = "capital_deposited"
    CAPITAL_WITHDRAWN = "capital_withdrawn"
    ORDER_RESERVED = "order_reserved"
    ORDER_RESERVATION_RELEASED = "order_reservation_released"
    FILL_RECEIVED = "fill_received"
    POSITION_OPENED = "position_opened"
    POSITION_INCREASED = "position_increased"
    POSITION_REDUCED = "position_reduced"
    POSITION_CLOSED = "position_closed"
    FEE_RECORDED = "fee_recorded"
    MARGIN_UPDATED = "margin_updated"
    BROKER_SNAPSHOT_RECEIVED = "broker_snapshot_received"
    RECONCILIATION_COMPLETED = "reconciliation_completed"
    DISCREPANCY_DETECTED = "discrepancy_detected"
    LIMIT_BREACHED = "limit_breached"
    PORTFOLIO_HALTED = "portfolio_halted"
    PORTFOLIO_RESUMED = "portfolio_resumed"
    MARKET_PRICE_UPDATED = "market_price_updated"
    END_OF_DAY_SNAPSHOT = "end_of_day_snapshot"


class PortfolioHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


# ── Primitive value objects ────────────────────────────────────────────────

class CashBalance(BaseModel):
    """Current cash state — clearly distinguished from margin."""
    model_config = ConfigDict(frozen=True)

    total: Decimal = Field(..., description="Total cash deposited")
    available: Decimal = Field(..., description="Cash not blocked by reservations")
    blocked: Decimal = Field(Decimal("0"), description="Cash reserved for pending orders")
    reserved: Decimal = Field(Decimal("0"), description="Mandatory configured reserve")
    currency: str = Field("INR")
    as_of: datetime = Field(default_factory=_utcnow)
    source: str = Field("internal", description="'internal' or 'broker'")

    @field_validator("total", "available", "blocked", "reserved", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class MarginState(BaseModel):
    """Margin state — broker-confirmed in live mode, estimated in paper."""
    model_config = ConfigDict(frozen=True)

    available: Decimal = Field(Decimal("0"))
    used: Decimal = Field(Decimal("0"))
    total: Decimal = Field(Decimal("0"))
    currency: str = Field("INR")
    is_estimated: bool = Field(True)
    as_of: datetime = Field(default_factory=_utcnow)
    source: str = Field("internal")

    @field_validator("available", "used", "total", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class BuyingPower(BaseModel):
    """Effective capital available for new positions."""
    model_config = ConfigDict(frozen=True)

    gross: Decimal = Field(..., description="Cash + margin before exposure deductions")
    net: Decimal = Field(..., description="Gross minus current exposure")
    allocated: Decimal = Field(Decimal("0"), description="Currently reserved via pending decisions")
    as_of: datetime = Field(default_factory=_utcnow)

    @field_validator("gross", "net", "allocated", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


# ── Position ───────────────────────────────────────────────────────────────

class PortfolioLot(BaseModel):
    """A single fill lot used for FIFO average-cost / realised P&L tracking."""
    model_config = ConfigDict(frozen=True)

    lot_id: str = Field(default_factory=lambda: str(uuid4()))
    fill_id: str
    quantity: Decimal
    price: Decimal
    fees: Decimal = Field(Decimal("0"))
    filled_at: datetime = Field(default_factory=_utcnow)

    @field_validator("quantity", "price", "fees", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class PortfolioPosition(BaseModel):
    """A live or closed position in the portfolio."""
    model_config = ConfigDict(frozen=True)

    position_id: str = Field(default_factory=lambda: str(uuid4()))
    instrument_token: int
    trading_symbol: str
    exchange: str = Field("NSE")
    sector: Optional[str] = None
    strategy_id: Optional[str] = None
    session_id: Optional[str] = None

    side: PositionSide
    status: PositionStatus = Field(PositionStatus.OPEN)

    quantity: Decimal = Field(Decimal("0"))
    average_cost: Decimal = Field(Decimal("0"))
    last_price: Optional[Decimal] = None
    last_price_as_of: Optional[datetime] = None

    realised_pnl: Decimal = Field(Decimal("0"))
    unrealised_pnl: Decimal = Field(Decimal("0"))
    total_fees: Decimal = Field(Decimal("0"))

    lots: List[PortfolioLot] = Field(default_factory=list)
    applied_fill_ids: List[str] = Field(default_factory=list)

    opened_at: datetime = Field(default_factory=_utcnow)
    closed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("quantity", "average_cost", "realised_pnl", "unrealised_pnl", "total_fees", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)

    @field_validator("last_price", mode="before")
    @classmethod
    def _coerce_opt(cls, v):
        return _coerce_and_validate(v) if v is not None else None

    @property
    def market_value(self) -> Decimal:
        if self.last_price is None:
            return self.quantity * self.average_cost
        return self.quantity * self.last_price

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.average_cost


# ── Exposure ───────────────────────────────────────────────────────────────

class InstrumentExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_token: int
    trading_symbol: str
    sector: Optional[str] = None
    strategy_id: Optional[str] = None
    gross_value: Decimal = Field(Decimal("0"))
    net_value: Decimal = Field(Decimal("0"))
    portfolio_pct: Decimal = Field(Decimal("0"))
    as_of: datetime = Field(default_factory=_utcnow)

    @field_validator("gross_value", "net_value", "portfolio_pct", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class SectorExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector: str
    gross_value: Decimal = Field(Decimal("0"))
    net_value: Decimal = Field(Decimal("0"))
    portfolio_pct: Decimal = Field(Decimal("0"))
    instrument_count: int = Field(0)
    as_of: datetime = Field(default_factory=_utcnow)

    @field_validator("gross_value", "net_value", "portfolio_pct", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class StrategyExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    gross_value: Decimal = Field(Decimal("0"))
    net_value: Decimal = Field(Decimal("0"))
    portfolio_pct: Decimal = Field(Decimal("0"))
    position_count: int = Field(0)
    allocated_capital: Decimal = Field(Decimal("0"))
    as_of: datetime = Field(default_factory=_utcnow)

    @field_validator("gross_value", "net_value", "portfolio_pct", "allocated_capital", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class ExposureSnapshot(BaseModel):
    """Point-in-time portfolio exposure summary."""
    model_config = ConfigDict(frozen=True)

    portfolio_id: str
    gross_exposure: Decimal = Field(Decimal("0"))
    net_exposure: Decimal = Field(Decimal("0"))
    long_exposure: Decimal = Field(Decimal("0"))
    short_exposure: Decimal = Field(Decimal("0"))
    pending_order_exposure: Decimal = Field(Decimal("0"))
    reserved_capital_exposure: Decimal = Field(Decimal("0"))
    gross_exposure_pct: Decimal = Field(Decimal("0"))
    net_exposure_pct: Decimal = Field(Decimal("0"))

    instrument_exposures: List[InstrumentExposure] = Field(default_factory=list)
    sector_exposures: List[SectorExposure] = Field(default_factory=list)
    strategy_exposures: List[StrategyExposure] = Field(default_factory=list)

    prices_stale: bool = Field(False)
    as_of: datetime = Field(default_factory=_utcnow)

    @field_validator(
        "gross_exposure", "net_exposure", "long_exposure", "short_exposure",
        "pending_order_exposure", "reserved_capital_exposure",
        "gross_exposure_pct", "net_exposure_pct",
        mode="before"
    )
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


# ── P&L ───────────────────────────────────────────────────────────────────

class PositionPnL(BaseModel):
    model_config = ConfigDict(frozen=True)

    position_id: str
    instrument_token: int
    trading_symbol: str
    strategy_id: Optional[str] = None
    realised: Decimal = Field(Decimal("0"))
    unrealised: Decimal = Field(Decimal("0"))
    gross: Decimal = Field(Decimal("0"))
    net: Decimal = Field(Decimal("0"))
    brokerage: Decimal = Field(Decimal("0"))
    taxes: Decimal = Field(Decimal("0"))
    fees_total: Decimal = Field(Decimal("0"))
    charges_confirmed: bool = Field(False)
    as_of: datetime = Field(default_factory=_utcnow)

    @field_validator("realised", "unrealised", "gross", "net", "brokerage", "taxes", "fees_total", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


class PortfolioPnL(BaseModel):
    """Aggregate P&L across the entire portfolio."""
    model_config = ConfigDict(frozen=True)

    portfolio_id: str
    realised: Decimal = Field(Decimal("0"))
    unrealised: Decimal = Field(Decimal("0"))
    gross: Decimal = Field(Decimal("0"))
    net: Decimal = Field(Decimal("0"))
    daily_pnl: Decimal = Field(Decimal("0"))
    brokerage_total: Decimal = Field(Decimal("0"))
    taxes_total: Decimal = Field(Decimal("0"))
    fees_total: Decimal = Field(Decimal("0"))
    estimated_fees: Decimal = Field(Decimal("0"))
    confirmed_fees: Decimal = Field(Decimal("0"))
    equity: Decimal = Field(Decimal("0"))
    peak_equity: Decimal = Field(Decimal("0"))
    drawdown: Decimal = Field(Decimal("0"))
    drawdown_pct: Decimal = Field(Decimal("0"))
    trading_date: Optional[str] = None  # IST date YYYY-MM-DD
    as_of: datetime = Field(default_factory=_utcnow)
    position_pnls: List[PositionPnL] = Field(default_factory=list)
    by_strategy: Dict[str, Decimal] = Field(default_factory=dict)
    by_instrument: Dict[str, Decimal] = Field(default_factory=dict)

    @field_validator(
        "realised", "unrealised", "gross", "net", "daily_pnl",
        "brokerage_total", "taxes_total", "fees_total",
        "estimated_fees", "confirmed_fees",
        "equity", "peak_equity", "drawdown", "drawdown_pct",
        mode="before"
    )
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


# ── Capital allocation ─────────────────────────────────────────────────────

class CapitalAllocation(BaseModel):
    """A request for capital allocation."""
    model_config = ConfigDict(frozen=True)

    allocation_id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str
    instrument_token: int
    trading_symbol: str
    requested_capital: Decimal
    side: str
    signal_confidence: Optional[Decimal] = None
    session_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    requested_at: datetime = Field(default_factory=_utcnow)

    @field_validator("requested_capital", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)

    @field_validator("signal_confidence", mode="before")
    @classmethod
    def _coerce_opt(cls, v):
        return _coerce_and_validate(v) if v is not None else None


class AllocationDecision(BaseModel):
    """Result of a capital allocation evaluation."""
    model_config = ConfigDict(frozen=True)

    allocation_id: str
    strategy_id: str
    instrument_token: int
    trading_symbol: str
    status: AllocationStatus
    requested_capital: Decimal
    approved_capital: Decimal = Field(Decimal("0"))
    rejected_capital: Decimal = Field(Decimal("0"))
    reason_codes: List[str] = Field(default_factory=list)
    binding_limit: Optional[str] = None
    portfolio_state_version: int = Field(0)
    decided_at: datetime = Field(default_factory=_utcnow)
    expires_at: Optional[datetime] = None

    @field_validator("requested_capital", "approved_capital", "rejected_capital", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)

    @property
    def is_approved(self) -> bool:
        return self.status in (AllocationStatus.APPROVED, AllocationStatus.PARTIAL)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


# ── Position sizing ────────────────────────────────────────────────────────

class PositionSizeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    instrument_token: int
    trading_symbol: str
    strategy_id: str
    side: str
    entry_price: Decimal
    stop_price: Optional[Decimal] = None
    available_capital: Decimal
    risk_per_trade: Optional[Decimal] = None
    signal_confidence: Optional[Decimal] = None
    volatility: Optional[Decimal] = None
    lot_size: int = Field(1)
    tick_size: Decimal = Field(Decimal("0.05"))
    min_order_value: Optional[Decimal] = None
    max_order_value: Optional[Decimal] = None
    sector: Optional[str] = None
    portfolio_state_version: int = Field(0)
    requested_at: datetime = Field(default_factory=_utcnow)

    @field_validator("entry_price", "available_capital", "tick_size", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)

    @field_validator("stop_price", "risk_per_trade", "signal_confidence",
                     "volatility", "min_order_value", "max_order_value", mode="before")
    @classmethod
    def _coerce_opt(cls, v):
        return _coerce_and_validate(v) if v is not None else None


class PositionSizeDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    instrument_token: int
    trading_symbol: str
    approved: bool
    raw_quantity: Decimal = Field(Decimal("0"))
    approved_quantity: Decimal = Field(Decimal("0"))
    estimated_order_value: Decimal = Field(Decimal("0"))
    estimated_risk: Decimal = Field(Decimal("0"))
    portfolio_pct: Decimal = Field(Decimal("0"))
    applied_constraints: List[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    portfolio_state_version: int = Field(0)
    decided_at: datetime = Field(default_factory=_utcnow)

    @field_validator("raw_quantity", "approved_quantity", "estimated_order_value",
                     "estimated_risk", "portfolio_pct", mode="before")
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


# ── Portfolio limits ───────────────────────────────────────────────────────

class LimitCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit_name: str
    allowed: bool
    current_value: Optional[Decimal] = None
    proposed_value: Optional[Decimal] = None
    configured_limit: Optional[Decimal] = None
    reason: Optional[str] = None
    severity: LimitSeverity = Field(LimitSeverity.INFO)
    portfolio_state_version: int = Field(0)
    checked_at: datetime = Field(default_factory=_utcnow)

    @field_validator("current_value", "proposed_value", "configured_limit", mode="before")
    @classmethod
    def _coerce_opt(cls, v):
        return _coerce_and_validate(v) if v is not None else None


class LimitCheckReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    results: List[LimitCheckResult] = Field(default_factory=list)
    binding_result: Optional[LimitCheckResult] = None
    checked_at: datetime = Field(default_factory=_utcnow)

    @property
    def violations(self) -> List[LimitCheckResult]:
        return [r for r in self.results if not r.allowed]


# ── Portfolio state snapshot ───────────────────────────────────────────────

class PortfolioSnapshot(BaseModel):
    """Persisted point-in-time portfolio state + checksum."""
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    portfolio_id: str
    version: int
    status: PortfolioStatus
    paper_mode: bool
    checksum: Optional[str] = None

    total_cash: Decimal
    available_cash: Decimal
    used_margin: Decimal
    buying_power_net: Decimal
    equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    realised_pnl: Decimal
    unrealised_pnl: Decimal
    daily_pnl: Decimal
    drawdown: Decimal
    drawdown_pct: Decimal
    peak_equity: Decimal
    open_position_count: int
    pending_reservation_count: int

    state_json: Optional[Dict[str, Any]] = None
    snapshotted_at: datetime = Field(default_factory=_utcnow)

    @field_validator(
        "total_cash", "available_cash", "used_margin", "buying_power_net",
        "equity", "gross_exposure", "net_exposure",
        "realised_pnl", "unrealised_pnl", "daily_pnl",
        "drawdown", "drawdown_pct", "peak_equity",
        mode="before"
    )
    @classmethod
    def _coerce(cls, v): return _coerce_and_validate(v)


# ── Portfolio event ────────────────────────────────────────────────────────

class PortfolioEvent(BaseModel):
    """An immutable event in the portfolio event ledger."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: str
    event_type: PortfolioEventType
    event_version: int = Field(1)
    portfolio_id: str

    internal_order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    fill_id: Optional[str] = None
    strategy_id: Optional[str] = None
    instrument_token: Optional[int] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None

    payload: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=_utcnow)
    sequence: Optional[int] = None


# ── Reconciliation ─────────────────────────────────────────────────────────

class PortfolioDiscrepancy(BaseModel):
    model_config = ConfigDict(frozen=True)

    discrepancy_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    discrepancy_type: PortfolioDiscrepancyType
    instrument_token: Optional[int] = None
    trading_symbol: Optional[str] = None
    internal_order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    description: str
    local_value: Optional[str] = None
    broker_value: Optional[str] = None
    requires_manual_review: bool = Field(True)
    is_critical: bool = Field(False)
    resolved: bool = Field(False)
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    detected_at: datetime = Field(default_factory=_utcnow)


class PortfolioReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    portfolio_id: str
    trigger: str
    dry_run: bool = Field(False)
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    discrepancies: List[PortfolioDiscrepancy] = Field(default_factory=list)
    positions_checked: int = Field(0)
    fills_checked: int = Field(0)
    orders_checked: int = Field(0)
    cash_checked: bool = Field(False)
    clean: bool = Field(True)
    critical_count: int = Field(0)
    applied_corrections: List[str] = Field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0


# ── Health ─────────────────────────────────────────────────────────────────

class PortfolioHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    portfolio_id: str
    status: PortfolioHealthStatus = Field(PortfolioHealthStatus.UNKNOWN)
    is_live: bool = Field(False)
    is_ready: bool = Field(False)
    is_halted: bool = Field(False)

    initialized: bool = Field(False)
    recovered: bool = Field(False)
    reconciled: bool = Field(False)

    state_freshness_seconds: Optional[float] = None
    broker_freshness_seconds: Optional[float] = None
    market_price_freshness_seconds: Optional[float] = None

    unresolved_discrepancies: int = Field(0)
    critical_discrepancies: int = Field(0)
    critical_limit_breaches: int = Field(0)

    last_snapshot_at: Optional[datetime] = None
    last_reconciliation_at: Optional[datetime] = None
    last_event_processed_at: Optional[datetime] = None

    failure_reason: Optional[str] = None
    paper_mode: bool = Field(True)
    checked_at: datetime = Field(default_factory=_utcnow)
