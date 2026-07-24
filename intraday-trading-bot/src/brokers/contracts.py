"""RC-10D: Broker-neutral domain contracts.

All models are frozen Pydantic v2.  Monetary and quantity fields use Decimal.
All timestamps are timezone-aware (UTC).  Raw Zerodha dicts must never leave
the zerodha/ sub-package — callers always receive these normalised types.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class BrokerOrderStatus(str, Enum):
    """Canonical broker order states — broker-neutral superset of Zerodha states."""
    PENDING = "PENDING"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    OPEN = "OPEN"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    MODIFICATION_PENDING = "MODIFICATION_PENDING"
    CANCELLATION_PENDING = "CANCELLATION_PENDING"
    UNKNOWN = "UNKNOWN"


class BrokerSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class BrokerProduct(str, Enum):
    MIS = "MIS"
    CNC = "CNC"
    NRML = "NRML"


class BrokerValidity(str, Enum):
    DAY = "DAY"
    IOC = "IOC"


class BrokerExchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"


class BrokerVariety(str, Enum):
    REGULAR = "regular"
    AMO = "amo"
    CO = "co"


class ReconciliationDiscrepancyType(str, Enum):
    LOCAL_ONLY = "LOCAL_ONLY"
    BROKER_ONLY = "BROKER_ONLY"
    STATE_MISMATCH = "STATE_MISMATCH"
    FILL_MISMATCH = "FILL_MISMATCH"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    MISSING_EXCHANGE_ORDER_ID = "MISSING_EXCHANGE_ORDER_ID"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    UNRESOLVED_BROKER_EVENT = "UNRESOLVED_BROKER_EVENT"


class BrokerHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class CorrelationStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    UNCERTAIN = "UNCERTAIN"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Core request / response
# ---------------------------------------------------------------------------

class BrokerOrderRequest(BaseModel):
    """Broker-neutral order request sent by RC-7 to the broker layer."""

    model_config = ConfigDict(frozen=True)

    # identity
    internal_order_id: str
    idempotency_key: str

    # instrument
    exchange: BrokerExchange = BrokerExchange.NSE
    trading_symbol: str
    instrument_token: Optional[str] = None

    # order attributes
    transaction_type: BrokerSide
    quantity: Decimal
    order_type: BrokerOrderType
    product: BrokerProduct = BrokerProduct.MIS
    validity: BrokerValidity = BrokerValidity.DAY
    variety: BrokerVariety = BrokerVariety.REGULAR

    # optional price fields
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    disclosed_quantity: Optional[Decimal] = None

    # metadata
    tag: Optional[str] = None
    paper_mode: bool = True


class BrokerOrderResponse(BaseModel):
    """Normalised response after order placement.

    For MARKET orders in paper mode, ``filled_quantity`` and ``average_price``
    are populated immediately (synchronous paper fill).  For live orders,
    these fields are updated asynchronously via WebSocket order updates; at
    placement time they default to None / 0.
    """

    model_config = ConfigDict(frozen=True)

    internal_order_id: str
    broker_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None
    status: BrokerOrderStatus
    paper_mode: bool = True
    message: Optional[str] = None
    rejected_reason: Optional[str] = None
    placed_at: Optional[datetime] = None
    # Fill fields — populated for synchronous fills (paper mode) or after
    # reconciliation; None/0 for async live orders at placement time.
    filled_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None


class BrokerTrade(BaseModel):
    """A single trade / fill returned by the broker."""

    model_config = ConfigDict(frozen=True)

    trade_id: str
    broker_order_id: str
    exchange_order_id: Optional[str] = None
    trading_symbol: str
    exchange: str
    transaction_type: BrokerSide
    quantity: Decimal
    price: Decimal
    fill_timestamp: datetime
    product: str


class BrokerPosition(BaseModel):
    """Current open position as reported by the broker."""

    model_config = ConfigDict(frozen=True)

    trading_symbol: str
    exchange: str
    instrument_token: Optional[str] = None
    product: str
    quantity: Decimal
    overnight_quantity: Decimal = Decimal("0")
    average_price: Decimal
    close_price: Decimal = Decimal("0")
    last_price: Decimal = Decimal("0")
    pnl: Decimal = Decimal("0")
    m2m: Decimal = Decimal("0")
    unrealised: Decimal = Decimal("0")
    realised: Decimal = Decimal("0")
    buy_quantity: Decimal = Decimal("0")
    buy_price: Decimal = Decimal("0")
    sell_quantity: Decimal = Decimal("0")
    sell_price: Decimal = Decimal("0")


class BrokerHolding(BaseModel):
    """Delivery holding as reported by the broker."""

    model_config = ConfigDict(frozen=True)

    trading_symbol: str
    exchange: str
    instrument_token: Optional[str] = None
    isin: Optional[str] = None
    product: str
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal = Decimal("0")
    close_price: Decimal = Decimal("0")
    pnl: Decimal = Decimal("0")
    day_change: Decimal = Decimal("0")
    day_change_percentage: Decimal = Decimal("0")


class BrokerMargins(BaseModel):
    """Account margin summary."""

    model_config = ConfigDict(frozen=True)

    available_cash: Decimal
    available_margin: Decimal
    used_margin: Decimal
    payin_amount: Decimal = Decimal("0")
    span_margin: Decimal = Decimal("0")
    option_premium: Decimal = Decimal("0")
    net: Decimal = Decimal("0")


class BrokerFunds(BaseModel):
    """Full funds / balance breakdown."""

    model_config = ConfigDict(frozen=True)

    equity: BrokerMargins
    commodity: Optional[BrokerMargins] = None


class BrokerInstrument(BaseModel):
    """Normalised instrument master entry."""

    model_config = ConfigDict(frozen=True)

    instrument_token: str
    exchange_token: str
    trading_symbol: str
    name: str
    last_price: Decimal = Decimal("0")
    expiry: Optional[str] = None
    strike: Optional[Decimal] = None
    tick_size: Decimal = Decimal("0.05")
    lot_size: Decimal = Decimal("1")
    instrument_type: str
    segment: str
    exchange: str


class BrokerOrderUpdate(BaseModel):
    """Normalised inbound order update from WebSocket or REST poll."""

    model_config = ConfigDict(frozen=True)

    broker_order_id: str
    internal_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None
    trading_symbol: str
    exchange: str
    transaction_type: BrokerSide
    status: BrokerOrderStatus
    quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    pending_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    rejected_reason: Optional[str] = None
    exchange_timestamp: Optional[datetime] = None
    received_at: datetime
    source: str = "websocket"  # "websocket" | "rest"
    paper_mode: bool = True


class BrokerSession(BaseModel):
    """Persisted broker session metadata (tokens redacted for repr)."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = None
    broker_name: str = "zerodha"
    created_at: datetime
    expires_at: Optional[datetime] = None
    is_valid: bool = False
    paper_mode: bool = True

    def __repr__(self) -> str:
        return (
            f"BrokerSession(session_id={self.session_id!r}, "
            f"user_id={self.user_id!r}, valid={self.is_valid}, "
            f"paper={self.paper_mode})"
        )


class BrokerHealth(BaseModel):
    """Point-in-time broker health snapshot."""

    model_config = ConfigDict(frozen=True)

    status: BrokerHealthStatus
    authenticated: bool = False
    session_valid: bool = False
    rest_reachable: bool = False
    websocket_connected: bool = False
    paper_mode: bool = True
    last_successful_request: Optional[datetime] = None
    last_broker_event: Optional[datetime] = None
    reconnect_count: int = 0
    rate_limited: bool = False
    unresolved_orders: int = 0
    reconciliation_status: Optional[str] = None
    failure_reason: Optional[str] = None
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_ready(self) -> bool:
        """True when broker is capable of accepting new orders."""
        return (
            self.status in (BrokerHealthStatus.HEALTHY, BrokerHealthStatus.DEGRADED)
            and self.authenticated
            and self.session_valid
        )

    @property
    def is_live(self) -> bool:
        return not self.paper_mode


class BrokerCapabilities(BaseModel):
    """Capabilities advertised by a broker adapter."""

    model_config = ConfigDict(frozen=True)

    broker_name: str
    supports_live_orders: bool = False
    supports_websocket: bool = False
    supports_historical_data: bool = False
    supports_options: bool = False
    supports_futures: bool = False
    paper_mode_only: bool = True
    max_orders_per_second: int = 10
    supported_exchanges: List[str] = Field(default_factory=list)
    supported_products: List[str] = Field(default_factory=list)
    supported_order_types: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reconciliation contracts
# ---------------------------------------------------------------------------

class ReconciliationDiscrepancy(BaseModel):
    """A single reconciliation finding."""

    model_config = ConfigDict(frozen=True)

    discrepancy_type: ReconciliationDiscrepancyType
    internal_order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    trading_symbol: Optional[str] = None
    description: str
    local_value: Optional[str] = None
    broker_value: Optional[str] = None
    requires_manual_review: bool = False


class ReconciliationReport(BaseModel):
    """Full output of one reconciliation run."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    trigger: str  # startup | post_reconnect | uncertain_submission | periodic | eod
    started_at: datetime
    completed_at: Optional[datetime] = None
    discrepancies: List[ReconciliationDiscrepancy] = Field(default_factory=list)
    orders_checked: int = 0
    clean: bool = True
    paper_mode: bool = True

    @property
    def has_discrepancies(self) -> bool:
        return len(self.discrepancies) > 0
