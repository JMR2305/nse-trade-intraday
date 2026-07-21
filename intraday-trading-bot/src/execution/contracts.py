"""Stub for execution/contracts.py - RC-7 frozen module.
Minimal types needed for strategy package imports."""
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ExecutionOrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    ACCEPTED = "ACCEPTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ExecutionOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL_M"


class ExecutionOrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionOrderAction(str, Enum):
    SUBMIT = "SUBMIT"
    VALIDATE = "VALIDATE"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    OPEN = "OPEN"
    PARTIALLY_FILL = "PARTIALLY_FILL"
    FILL = "FILL"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    CANCEL = "CANCEL"
    EXPIRE = "EXPIRE"
    FAIL = "FAIL"


class ExecutionOrder(BaseModel, frozen=True):
    client_order_id: str
    instrument_token: str
    side: ExecutionOrderSide
    order_type: ExecutionOrderType
    quantity: Decimal
    limit_price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    status: ExecutionOrderStatus = ExecutionOrderStatus.CREATED
    filled_quantity: Decimal = Decimal("0")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FillRecord(BaseModel, frozen=True):
    fill_id: str
    order_id: str
    instrument_token: str
    side: ExecutionOrderSide
    quantity: Decimal
    price: Decimal
    timestamp: datetime


class ExecutionAuditEvent(BaseModel, frozen=True):
    event_id: str
    order_id: str
    client_order_id: str
    sequence_number: int
    previous_state: ExecutionOrderStatus
    new_state: ExecutionOrderStatus
    action: ExecutionOrderAction
    actor: str
    reason: str
    event_timestamp: datetime
    fill_record: Optional[FillRecord] = None
