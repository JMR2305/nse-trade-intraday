"""Stub for execution/fills.py - RC-7 frozen module."""
from decimal import Decimal
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any

from execution.contracts import ExecutionOrderSide


class FillEvent(BaseModel, frozen=True):
    fill_id: str
    order_id: str
    client_order_id: str
    instrument_token: str
    side: ExecutionOrderSide
    quantity: Decimal
    price: Decimal
    fill_timestamp: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)
