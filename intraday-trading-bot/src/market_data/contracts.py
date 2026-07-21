"""Stub for market_data/contracts.py - RC-6 frozen module."""
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any


class Tick(BaseModel, frozen=True):
    instrument_token: str
    timestamp: datetime
    last_price: Decimal
    last_quantity: Decimal
    volume: Decimal
    buy_price: Decimal
    buy_quantity: Decimal
    sell_price: Decimal
    sell_quantity: Decimal
    ohlc_open: Optional[Decimal] = None
    ohlc_high: Optional[Decimal] = None
    ohlc_low: Optional[Decimal] = None
    ohlc_close: Optional[Decimal] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Quote(BaseModel, frozen=True):
    instrument_token: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    depth: Dict[str, Any] = Field(default_factory=dict)


class CompletedBar(BaseModel, frozen=True):
    instrument_token: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    interval: str  # e.g., "1m", "5m"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DataQualityStatus(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    DEGRADED = "DEGRADED"
    GAP = "GAP"


class DataQualityEvent(BaseModel, frozen=True):
    instrument_token: str
    status: DataQualityStatus
    timestamp: datetime
    message: str


class SubscriptionRequest(BaseModel, frozen=True):
    instrument_token: str
    mode: str = "full"


class DataGap(BaseModel, frozen=True):
    instrument_token: str
    from_timestamp: datetime
    to_timestamp: datetime
    expected_bars: int
