"""RC-10C1 Portfolio Core — frozen domain contracts.

All monetary values use Decimal.  All timestamps are timezone-aware.
NaN and infinite values are rejected at construction.
Models are immutable (frozen=True) unless mutation is explicitly required
for performance-critical incremental tracking.

Distinction conventions:
  - Fields named *_broker_* hold broker-reported values.
  - Fields named *_local_* or with no prefix hold internally computed values.
  - Every snapshot carries an as_of timestamp and a source label.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decimal(v: Any) -> Decimal:
    """Coerce *v* to Decimal and reject NaN / infinite values."""
    try:
        d = Decimal(str(v))
    except InvalidOperation as exc:
        raise ValueError(f"Cannot convert {v!r} to Decimal: {exc}") from exc
    if not d.is_finite():
        raise ValueError(f"Decimal value must be finite, got {d}")
    return d


def _tz(v: datetime) -> datetime:
    """Ensure *v* is timezone-aware."""
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError("datetime must be timezone-aware")
    return v


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PortfolioStatus(str, Enum):
    INITIALISING = "INITIALISING"
    RECOVERING   = "RECOVERING"
    RECONCILING  = "RECONCILING"
    READY        = "READY"
    DEGRADED     = "DEGRADED"   # running but with unresolved discrepancies
    HALTED       = "HALTED"     # kill-switch or critical limit breach
    UNAVAILABLE  = "UNAVAILABLE"


class PositionSide(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    PENDING  = "PENDING"   # order reserved, no fill yet
    OPEN     = "OPEN"
    REDUCING = "REDUCING"  # partially closed
    CLOSED   = "CLOSED"


class AllocationStatus(str, Enum):
    APPROVED  = "APPROVED"
    REJECTED  = "REJECTED"
    EXPIRED   = "EXPIRED"
    COMMITTED = "COMMITTED"   # used — no longer available
    RELEASED  = "RELEASED"    # reservation cancelled


class LimitSeverity(str, Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"


class PortfolioDiscrepancyType(str, Enum):
    LOCAL_ONLY_POSITION    = "LOCAL_ONLY_POSITION"
    BROKER_ONLY_POSITION   = "BROKER_ONLY_POSITION"
    QUANTITY_MISMATCH      = "QUANTITY_MISMATCH"
    AVG_PRICE_MISMATCH     = "AVG_PRICE_MISMATCH"
    REALISED_PNL_MISMATCH  = "REALISED_PNL_MISMATCH"
    MARGIN_MISMATCH        = "MARGIN_MISMATCH"
    CASH_MISMATCH          = "CASH_MISMATCH"
    MISSING_FILL           = "MISSING_FILL"
    DUPLICATE_FILL         = "DUPLICATE_FILL"
    STALE_BROKER_SNAPSHOT  = "STALE_BROKER_SNAPSHOT"
    STALE_LOCAL_STATE      = "STALE_LOCAL_STATE"
    UNKNOWN_INSTRUMENT     = "UNKNOWN_INSTRUMENT"
    UNRESOLVED_ORDER       = "UNRESOLVED_ORDER"


class PortfolioEventType(str, Enum):
    PORTFOLIO_INITIALIZED         = "portfolio_initialized"
    CAPITAL_DEPOSITED             = "capital_deposited"
    CAPITAL_WITHDRAWN             = "capital_withdrawn"
    ORDER_RESERVED                = "order_reserved"
    ORDER_RESERVATION_RELEASED    = "order_reservation_released"
    FILL_RECEIVED                 = "fill_received"
    POSITION_OPENED               = "position_opened"
    POSITION_INCREASED            = "position_increased"
    POSITION_REDUCED              = "position_reduced"
    POSITION_CLOSED               = "position_closed"
    FEE_RECORDED                  = "fee_recorded"
    MARGIN_UPDATED                = "margin_updated"
    BROKER_SNAPSHOT_RECEIVED      = "broker_snapshot_received"
    RECONCILIATION_COMPLETED      = "reconciliation_completed"
    DISCREPANCY_DETECTED          = "discrepancy_detected"
    LIMIT_BREACHED                = "limit_breached"
    PORTFOLIO_HALTED              = "portfolio_halted"
    PORTFOLIO_RESUMED             = "portfolio_resumed"
    END_OF_DAY_SNAPSHOT           = "end_of_day_snapshot"
    MARKET_PRICE_UPDATED          = "market_price_updated"
    SNAPSHOT_TAKEN                = "snapshot_taken"
    STATE_RECOVERED               = "state_recovered"


class PortfolioHealthStatus(str, Enum):
    HEALTHY   = "HEALTHY"
    DEGRADED  = "DEGRADED"
    DOWN      = "DOWN"
    UNKNOWN   = "UNKNOWN"
    DISABLED  = "DISABLED"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class CashBalance(BaseModel):
    """Immutable cash balance snapshot."""
    model_config = ConfigDict(frozen=True)

    available: Decimal = Field(..., description="Free cash available to deploy")
    blocked: Decimal   = Field(..., description="Cash reserved for pending orders")
    total: Decimal     = Field(..., description="available + blocked")
    currency: str      = Field(default="INR")
    as_of: datetime    = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str        = Field(default="local")

    @field_validator("available", "blocked", "total", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @field_validator("as_of", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v

    @model_validator(mode="after")
    def _check(self) -> "CashBalance":
        if self.available < Decimal("0"):
            raise ValueError("available cash cannot be negative")
        if self.blocked < Decimal("0"):
            raise ValueError("blocked cash cannot be negative")
        expected = self.available + self.blocked
        if abs(self.total - expected) > Decimal("0.01"):
            raise ValueError(
                f"total {self.total} != available {self.available} + blocked {self.blocked}"
            )
        return self


class MarginState(BaseModel):
    """Immutable margin snapshot."""
    model_config = ConfigDict(frozen=True)

    used: Decimal      = Field(..., description="Margin currently consumed by positions")
    available: Decimal = Field(..., description="Margin still available")
    total: Decimal     = Field(..., description="used + available")
    as_of: datetime    = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str        = Field(default="local")

    @field_validator("used", "available", "total", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @field_validator("as_of", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v

    @model_validator(mode="after")
    def _check(self) -> "MarginState":
        if self.used < Decimal("0"):
            raise ValueError("used margin cannot be negative")
        if self.available < Decimal("0"):
            raise ValueError("available margin cannot be negative")
        return self


class BuyingPower(BaseModel):
    """Total deployable capital accounting for cash + margin – reserves."""
    model_config = ConfigDict(frozen=True)

    gross: Decimal   = Field(..., description="Cash + available margin")
    net: Decimal     = Field(..., description="gross – cash_reserve")
    reserved: Decimal = Field(..., description="Amount locked for minimum reserve")
    as_of: datetime  = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str      = Field(default="local")

    @field_validator("gross", "net", "reserved", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @field_validator("as_of", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v

    @model_validator(mode="after")
    def _check(self) -> "BuyingPower":
        if self.net < Decimal("0"):
            raise ValueError("net buying power cannot be negative")
        return self


# ---------------------------------------------------------------------------
# Position / lot models
# ---------------------------------------------------------------------------

class PortfolioLot(BaseModel):
    """One lot (fill) that makes up a position."""
    model_config = ConfigDict(frozen=True)

    lot_id: UUID         = Field(default_factory=uuid4)
    fill_id: str         = Field(..., description="Source fill idempotency key")
    quantity: int        = Field(..., gt=0)
    entry_price: Decimal = Field(..., gt=Decimal("0"))
    filled_at: datetime
    fees: Decimal        = Field(default=Decimal("0"))
    strategy_id: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("entry_price", "fees", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @field_validator("filled_at", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v


class PortfolioPosition(BaseModel):
    """Current live state of a position (mutable tracking model — NOT frozen)."""
    model_config = ConfigDict(frozen=False)

    position_id: UUID            = Field(default_factory=uuid4)
    instrument_token: int        = Field(..., gt=0)
    instrument_symbol: str       = Field(..., min_length=1)
    side: PositionSide
    status: PositionStatus       = Field(default=PositionStatus.OPEN)
    open_quantity: int           = Field(default=0, ge=0)
    closed_quantity: int         = Field(default=0, ge=0)
    average_entry_price: Decimal = Field(default=Decimal("0"))
    last_market_price: Decimal | None = None
    last_price_as_of: datetime | None = None
    unrealised_pnl: Decimal      = Field(default=Decimal("0"))
    realised_pnl: Decimal        = Field(default=Decimal("0"))
    total_fees: Decimal          = Field(default=Decimal("0"))
    lots: list[PortfolioLot]     = Field(default_factory=list)
    strategy_id: str | None      = None
    sector: str | None           = None
    opened_at: datetime          = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None   = None
    version: int                 = Field(default=0)
    metadata: dict[str, Any] | None = None

    @field_validator(
        "average_entry_price", "unrealised_pnl", "realised_pnl", "total_fees",
        mode="before",
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @property
    def market_value(self) -> Decimal:
        if self.last_market_price is None or self.open_quantity == 0:
            return Decimal("0")
        return Decimal(str(self.open_quantity)) * self.last_market_price

    @property
    def cost_basis(self) -> Decimal:
        return Decimal(str(self.open_quantity)) * self.average_entry_price

    @property
    def gross_exposure(self) -> Decimal:
        price = self.last_market_price or self.average_entry_price
        return Decimal(str(self.open_quantity)) * price


# ---------------------------------------------------------------------------
# Exposure models
# ---------------------------------------------------------------------------

class InstrumentExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_token: int
    instrument_symbol: str
    absolute_value: Decimal   = Field(..., description="Market value of open position")
    portfolio_pct: Decimal    = Field(..., description="% of total portfolio equity")
    pending_value: Decimal    = Field(default=Decimal("0"), description="Reserved for pending orders")
    as_of: datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("absolute_value", "portfolio_pct", "pending_value", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class SectorExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector: str
    absolute_value: Decimal = Field(...)
    portfolio_pct: Decimal  = Field(...)
    position_count: int     = Field(default=0, ge=0)
    as_of: datetime         = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("absolute_value", "portfolio_pct", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class StrategyExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    absolute_value: Decimal = Field(...)
    portfolio_pct: Decimal  = Field(...)
    allocated_capital: Decimal = Field(default=Decimal("0"))
    position_count: int     = Field(default=0, ge=0)
    as_of: datetime         = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("absolute_value", "portfolio_pct", "allocated_capital", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class ExposureSnapshot(BaseModel):
    """Full portfolio exposure at a point in time."""
    model_config = ConfigDict(frozen=True)

    gross_exposure: Decimal         = Field(...)
    net_exposure: Decimal           = Field(...)
    long_exposure: Decimal          = Field(default=Decimal("0"))
    short_exposure: Decimal         = Field(default=Decimal("0"))
    pending_order_exposure: Decimal = Field(default=Decimal("0"))
    reserved_capital_exposure: Decimal = Field(default=Decimal("0"))
    instrument_exposures: tuple[InstrumentExposure, ...] = Field(default=())
    sector_exposures: tuple[SectorExposure, ...] = Field(default=())
    strategy_exposures: tuple[StrategyExposure, ...] = Field(default=())
    portfolio_equity: Decimal       = Field(default=Decimal("0"))
    stale_prices: bool              = Field(default=False)
    as_of: datetime                 = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_version: int              = Field(default=0)

    @field_validator(
        "gross_exposure", "net_exposure", "long_exposure", "short_exposure",
        "pending_order_exposure", "reserved_capital_exposure", "portfolio_equity",
        mode="before",
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


# ---------------------------------------------------------------------------
# P&L models
# ---------------------------------------------------------------------------

class PositionPnL(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_token: int
    instrument_symbol: str
    realised: Decimal           = Field(default=Decimal("0"))
    unrealised: Decimal         = Field(default=Decimal("0"))
    total: Decimal              = Field(default=Decimal("0"))
    estimated_fees: Decimal     = Field(default=Decimal("0"))
    confirmed_fees: Decimal     = Field(default=Decimal("0"))
    fees_are_estimated: bool    = Field(default=True)
    as_of: datetime             = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "realised", "unrealised", "total",
        "estimated_fees", "confirmed_fees",
        mode="before",
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class PortfolioPnL(BaseModel):
    """Aggregate portfolio P&L."""
    model_config = ConfigDict(frozen=True)

    realised: Decimal           = Field(default=Decimal("0"))
    unrealised: Decimal         = Field(default=Decimal("0"))
    gross: Decimal              = Field(default=Decimal("0"))
    net: Decimal                = Field(default=Decimal("0"))
    brokerage: Decimal          = Field(default=Decimal("0"))
    taxes: Decimal              = Field(default=Decimal("0"))
    other_fees: Decimal         = Field(default=Decimal("0"))
    daily_pnl: Decimal          = Field(default=Decimal("0"))
    peak_equity: Decimal        = Field(default=Decimal("0"))
    current_equity: Decimal     = Field(default=Decimal("0"))
    drawdown: Decimal           = Field(default=Decimal("0"), description="Fraction 0–1")
    drawdown_amount: Decimal    = Field(default=Decimal("0"), description="INR amount")
    fees_are_estimated: bool    = Field(default=True)
    position_pnls: tuple[PositionPnL, ...] = Field(default=())
    as_of: datetime             = Field(default_factory=lambda: datetime.now(timezone.utc))
    trading_date: str           = Field(default="")  # YYYY-MM-DD in IST
    state_version: int          = Field(default=0)

    @field_validator(
        "realised", "unrealised", "gross", "net",
        "brokerage", "taxes", "other_fees",
        "daily_pnl", "peak_equity", "current_equity",
        "drawdown", "drawdown_amount",
        mode="before",
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @model_validator(mode="after")
    def _validate_drawdown(self) -> "PortfolioPnL":
        if not (Decimal("0") <= self.drawdown <= Decimal("1")):
            raise ValueError(f"drawdown must be in [0, 1], got {self.drawdown}")
        return self


# ---------------------------------------------------------------------------
# Allocation models
# ---------------------------------------------------------------------------

class CapitalAllocation(BaseModel):
    """Snapshot of capital allocated to a strategy at a point in time."""
    model_config = ConfigDict(frozen=True)

    allocation_id: UUID      = Field(default_factory=uuid4)
    strategy_id: str
    allocated_capital: Decimal
    reserved_capital: Decimal = Field(default=Decimal("0"))
    utilised_capital: Decimal = Field(default=Decimal("0"))
    status: AllocationStatus  = Field(default=AllocationStatus.APPROVED)
    as_of: datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("allocated_capital", "reserved_capital", "utilised_capital", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class AllocationDecision(BaseModel):
    """Result of a capital-allocation evaluation request."""
    model_config = ConfigDict(frozen=True)

    decision_id: UUID        = Field(default_factory=uuid4)
    strategy_id: str
    instrument_token: int | None = None
    requested_capital: Decimal
    approved_capital: Decimal
    rejected_capital: Decimal    = Field(default=Decimal("0"))
    status: AllocationStatus
    reason_codes: tuple[str, ...] = Field(default=())
    binding_limit: str | None    = None
    portfolio_state_version: int = Field(default=0)
    decided_at: datetime         = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None  = None
    correlation_id: str | None   = None

    @field_validator(
        "requested_capital", "approved_capital", "rejected_capital", mode="before"
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)

    @field_validator("decided_at", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        _now = now or datetime.now(timezone.utc)
        return _now >= self.expires_at


# ---------------------------------------------------------------------------
# Position sizing models
# ---------------------------------------------------------------------------

class PositionSizeRequest(BaseModel):
    """Input to the position sizer."""
    model_config = ConfigDict(frozen=True)

    request_id: UUID           = Field(default_factory=uuid4)
    instrument_token: int      = Field(..., gt=0)
    instrument_symbol: str
    side: PositionSide
    entry_price: Decimal       = Field(..., gt=Decimal("0"))
    stop_price: Decimal | None = None
    strategy_id: str | None    = None
    sector: str | None         = None
    signal_confidence: Decimal = Field(default=Decimal("1.0"))
    volatility_pct: Decimal | None = None
    lot_size: int              = Field(default=1, ge=1)
    tick_size: Decimal         = Field(default=Decimal("0.05"))
    available_capital: Decimal | None = None   # override; uses portfolio state if None
    requested_at: datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None

    @field_validator(
        "entry_price", "signal_confidence", "tick_size", mode="before"
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class PositionSizeDecision(BaseModel):
    """Output of the position sizer."""
    model_config = ConfigDict(frozen=True)

    request_id: UUID
    instrument_token: int
    side: PositionSide
    raw_quantity: int              = Field(default=0, ge=0)
    approved_quantity: int         = Field(default=0, ge=0)
    estimated_order_value: Decimal = Field(default=Decimal("0"))
    estimated_risk: Decimal        = Field(default=Decimal("0"))
    pct_of_portfolio: Decimal      = Field(default=Decimal("0"))
    applied_constraints: tuple[str, ...] = Field(default=())
    approved: bool                 = Field(default=True)
    rejection_reason: str | None   = None
    decided_at: datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_version: int             = Field(default=0)

    @field_validator(
        "estimated_order_value", "estimated_risk", "pct_of_portfolio", mode="before"
    )
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


# ---------------------------------------------------------------------------
# Limit check models
# ---------------------------------------------------------------------------

class LimitCheckResult(BaseModel):
    """Result of checking a single portfolio limit."""
    model_config = ConfigDict(frozen=True)

    limit_name: str
    allowed: bool
    current_value: Decimal
    proposed_value: Decimal
    configured_limit: Decimal
    severity: LimitSeverity     = Field(default=LimitSeverity.INFO)
    reason: str                 = Field(default="")
    state_version: int          = Field(default=0)

    @field_validator("current_value", "proposed_value", "configured_limit", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _decimal(v)


class LimitCheckReport(BaseModel):
    """Aggregate of all limit checks for a proposed action."""
    model_config = ConfigDict(frozen=True)

    overall_allowed: bool
    results: tuple[LimitCheckResult, ...]
    blocking_limit: str | None  = None
    critical_count: int         = Field(default=0, ge=0)
    warning_count: int          = Field(default=0, ge=0)
    checked_at: datetime        = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_version: int          = Field(default=0)


# ---------------------------------------------------------------------------
# Portfolio snapshot
# ---------------------------------------------------------------------------

class PortfolioSnapshot(BaseModel):
    """Full authoritative portfolio state snapshot."""
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID              = Field(default_factory=uuid4)
    portfolio_id: str              = Field(default="default")
    status: PortfolioStatus        = Field(default=PortfolioStatus.INITIALISING)
    version: int                   = Field(default=0, ge=0)
    cash: CashBalance
    margin: MarginState
    buying_power: BuyingPower
    exposure: ExposureSnapshot
    pnl: PortfolioPnL
    open_positions: tuple[PortfolioPosition, ...] = Field(default=())
    closed_positions_today: int    = Field(default=0, ge=0)
    pending_order_count: int       = Field(default=0, ge=0)
    paper_mode: bool               = Field(default=True)
    snapshotted_at: datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))
    checksum: str | None           = None
    metadata: dict[str, Any] | None = None

    @field_validator("snapshotted_at", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v


# ---------------------------------------------------------------------------
# Portfolio event (ledger entry)
# ---------------------------------------------------------------------------

class PortfolioEvent(BaseModel):
    """Immutable entry in the portfolio event ledger."""
    model_config = ConfigDict(frozen=True)

    event_id: UUID              = Field(default_factory=uuid4)
    idempotency_key: str        = Field(..., min_length=1)
    event_type: PortfolioEventType
    version: int                = Field(default=1, ge=1)
    portfolio_id: str           = Field(default="default")
    instrument_token: int | None = None
    internal_order_id: str | None = None
    broker_order_id: str | None   = None
    strategy_id: str | None       = None
    correlation_id: str | None    = None
    payload: dict[str, Any]       = Field(default_factory=dict)
    occurred_at: datetime         = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence: int | None          = None   # assigned by ledger on write

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _tz(cls, v: Any) -> datetime:
        return _tz(v) if isinstance(v, datetime) else v


# ---------------------------------------------------------------------------
# Reconciliation models
# ---------------------------------------------------------------------------

class PortfolioDiscrepancy(BaseModel):
    """A single detected discrepancy between local and broker state."""
    model_config = ConfigDict(frozen=True)

    discrepancy_id: UUID        = Field(default_factory=uuid4)
    discrepancy_type: PortfolioDiscrepancyType
    instrument_token: int | None = None
    instrument_symbol: str | None = None
    local_value: str | None     = None   # string for generality (qty, price, etc.)
    broker_value: str | None    = None
    severity: LimitSeverity     = Field(default=LimitSeverity.WARNING)
    resolved: bool              = Field(default=False)
    resolution_note: str | None = None
    detected_at: datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))


class PortfolioReconciliationReport(BaseModel):
    """Result of one reconciliation run."""
    model_config = ConfigDict(frozen=True)

    run_id: UUID                  = Field(default_factory=uuid4)
    portfolio_id: str             = Field(default="default")
    dry_run: bool                 = Field(default=True)
    discrepancies: tuple[PortfolioDiscrepancy, ...] = Field(default=())
    critical_count: int           = Field(default=0, ge=0)
    warning_count: int            = Field(default=0, ge=0)
    portfolio_ready: bool         = Field(default=True)
    notes: str                    = Field(default="")
    started_at: datetime          = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    state_version: int            = Field(default=0)
    broker_snapshot_age_s: float | None = None


# ---------------------------------------------------------------------------
# Portfolio health
# ---------------------------------------------------------------------------

class PortfolioHealth(BaseModel):
    """Live health and readiness of the portfolio service."""
    model_config = ConfigDict(frozen=True)

    status: PortfolioHealthStatus = Field(default=PortfolioHealthStatus.UNKNOWN)
    initialized: bool             = Field(default=False)
    recovered: bool               = Field(default=False)
    reconciled: bool              = Field(default=False)
    liveness: bool                = Field(default=False)
    readiness: bool               = Field(default=False)   # must be True for new orders
    degraded: bool                = Field(default=False)
    failure_reason: str | None    = None
    paper_mode: bool              = Field(default=True)
    state_freshness_s: float | None = None
    broker_freshness_s: float | None = None
    market_price_freshness_s: float | None = None
    unresolved_discrepancies: int = Field(default=0, ge=0)
    critical_limit_breaches: int  = Field(default=0, ge=0)
    last_snapshot_at: datetime | None = None
    last_reconciliation_at: datetime | None = None
    portfolio_status: PortfolioStatus = Field(default=PortfolioStatus.INITIALISING)
    checked_at: datetime          = Field(default_factory=lambda: datetime.now(timezone.utc))
