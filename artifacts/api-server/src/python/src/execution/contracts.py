"""Execution domain contracts.

Immutable Pydantic models for orders, audit events, and fill records.
All monetary values use Decimal. All timestamps are timezone-aware.

NOTE: These contracts are isolated from existing order/trade models to avoid
import dependencies. Future integration batches will provide adapter/mapper layers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------

class ExecutionOrderStatus(str, Enum):
    """Lifecycle states for an execution order.

    String values are chosen to match common trading terminology for
    easy mapping to existing project enums in future integration.
    """
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ExecutionOrderType(str, Enum):
    """Supported order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class ExecutionOrderSide(str, Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class ExecutionOrderAction(str, Enum):
    """Actions that drive state transitions."""
    SUBMIT = "submit"
    VALIDATE = "validate"
    ACCEPT = "accept"
    REJECT = "reject"
    OPEN = "open"
    PARTIALLY_FILL = "partially_fill"
    FILL = "fill"
    REQUEST_CANCEL = "request_cancel"
    CANCEL = "cancel"
    EXPIRE = "expire"
    FAIL = "fail"


# ------------------------------------------------------------------
# Terminal states
# ------------------------------------------------------------------

TERMINAL_STATES: frozenset[ExecutionOrderStatus] = frozenset({
    ExecutionOrderStatus.REJECTED,
    ExecutionOrderStatus.FILLED,
    ExecutionOrderStatus.CANCELLED,
    ExecutionOrderStatus.EXPIRED,
    ExecutionOrderStatus.FAILED,
})


# ------------------------------------------------------------------
# FillRecord
# ------------------------------------------------------------------

class FillRecord(BaseModel):
    """A single fill against an order.

    Immutable.  Used by the state machine to track partial fills.
    """
    model_config = ConfigDict(frozen=True)

    fill_id: UUID = Field(default_factory=uuid4)
    quantity: int = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)
    filled_at: datetime
    metadata: dict[str, Any] | None = None

    @field_validator("filled_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("filled_at must be timezone-aware")
        return v


# ------------------------------------------------------------------
# ExecutionOrder
# ------------------------------------------------------------------

class ExecutionOrder(BaseModel):
    """A paper-execution order contract.

    Immutable after construction.  The state machine operates on a
    mutable copy (see OrderStateMachine) while this contract remains
    the source of truth for construction-time validation.
    """
    model_config = ConfigDict(frozen=True)

    order_id: UUID = Field(default_factory=uuid4)
    client_order_id: str = Field(..., min_length=1)
    instrument_token: int = Field(..., gt=0)
    side: ExecutionOrderSide
    order_type: ExecutionOrderType
    quantity: int = Field(..., gt=0)
    limit_price: Decimal | None = None
    trigger_price: Decimal | None = None
    product: str = Field(default="CNC", min_length=1)
    validity: str = Field(default="DAY", min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exchange: str = Field(default="NSE", min_length=1)
    metadata: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Timestamp validation
    # ------------------------------------------------------------------
    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("created_at must be timezone-aware")
        return v

    # ------------------------------------------------------------------
    # Price validation by order type
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_prices(self) -> "ExecutionOrder":
        # LIMIT requires limit_price
        if self.order_type == ExecutionOrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("LIMIT orders require limit_price")
            if self.limit_price <= 0:
                raise ValueError("limit_price must be positive")

        # MARKET must not have limit_price
        if self.order_type == ExecutionOrderType.MARKET:
            if self.limit_price is not None:
                raise ValueError("MARKET orders must not specify limit_price")

        # STOP_MARKET requires trigger_price, no limit_price
        if self.order_type == ExecutionOrderType.STOP_MARKET:
            if self.trigger_price is None:
                raise ValueError("STOP_MARKET orders require trigger_price")
            if self.trigger_price <= 0:
                raise ValueError("trigger_price must be positive")
            if self.limit_price is not None:
                raise ValueError("STOP_MARKET orders must not specify limit_price")

        # STOP_LIMIT requires both trigger_price and limit_price
        if self.order_type == ExecutionOrderType.STOP_LIMIT:
            if self.trigger_price is None:
                raise ValueError("STOP_LIMIT orders require trigger_price")
            if self.limit_price is None:
                raise ValueError("STOP_LIMIT orders require limit_price")
            if self.trigger_price <= 0:
                raise ValueError("trigger_price must be positive")
            if self.limit_price <= 0:
                raise ValueError("limit_price must be positive")

        return self

    def is_terminal(self, status: ExecutionOrderStatus) -> bool:
        """Check if a given status is terminal."""
        return status in TERMINAL_STATES


# ------------------------------------------------------------------
# ExecutionAuditEvent
# ------------------------------------------------------------------

class ExecutionAuditEvent(BaseModel):
    """Immutable record of a successful state transition.

    Generated by the state machine on every accepted transition.
    """
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    client_order_id: str
    sequence_number: int = Field(..., ge=0)
    previous_state: ExecutionOrderStatus
    new_state: ExecutionOrderStatus
    action: ExecutionOrderAction
    reason: str | None = None
    event_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = Field(default="system")
    metadata: dict[str, Any] | None = None
    fill_record: FillRecord | None = None

    @field_validator("event_timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("event_timestamp must be timezone-aware")
        return v
