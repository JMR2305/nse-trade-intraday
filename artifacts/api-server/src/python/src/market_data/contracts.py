"""Immutable market-data contracts.

All monetary values use Decimal. All timestamps are timezone-aware.

NOTE: If minute bars require additional uniqueness constraints,
the recommended schema change is:
  ALTER TABLE minute_bars ADD CONSTRAINT uq_minute_bars_token_timestamp
  UNIQUE (instrument_token, timestamp);
This is NOT implemented in this patch to avoid modifying ORM models.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataQualityState(str, Enum):
    """Per-instrument data quality states."""
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    BACKFILLING = "BACKFILLING"
    DISCONNECTED = "DISCONNECTED"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    GAP_DETECTED = "GAP_DETECTED"


class MarketDepthLevel(BaseModel):
    """A single level of the market depth book."""
    model_config = ConfigDict(frozen=True)

    price: Decimal
    quantity: int = Field(..., ge=0)
    orders: int | None = Field(default=None, ge=0)


class Tick(BaseModel):
    """A single market tick from the exchange.

    Immutable.  All prices are Decimal.  exchange_timestamp is the
    exchange-assigned time; received_at is the local wall-clock time
    when the tick arrived in our process.
    """
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    exchange_timestamp: datetime  # tz-aware, exchange time (IST for NSE)
    received_at: datetime  # tz-aware, UTC
    last_price: Decimal
    last_quantity: int = Field(..., ge=0)
    cumulative_volume: int = Field(..., ge=0)
    average_price: Decimal | None = None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    change: Decimal | None = None
    open_interest: int | None = Field(default=None, ge=0)
    buy_quantity: int | None = Field(default=None, ge=0)
    sell_quantity: int | None = Field(default=None, ge=0)
    market_depth: list[MarketDepthLevel] | None = None

    @field_validator("exchange_timestamp", "received_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v

    def fingerprint(self) -> tuple:
        """Unique fingerprint for duplicate detection."""
        return (
            self.instrument_token,
            self.exchange_timestamp,
            self.last_price,
            self.cumulative_volume,
        )


class Quote(BaseModel):
    """A top-of-book quote snapshot."""
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    exchange_timestamp: datetime
    received_at: datetime
    last_price: Decimal
    volume: int = Field(..., ge=0)
    buy_quantity: int = Field(..., ge=0)
    sell_quantity: int = Field(..., ge=0)
    depth: list[MarketDepthLevel] | None = None

    @field_validator("exchange_timestamp", "received_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


class CompletedBar(BaseModel):
    """A fully-formed 1-minute OHLCV bar.

    volume is the *minute delta* (not cumulative daily volume).
    """
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    timestamp: datetime  # floor(exchange_timestamp) to minute, IST
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(..., ge=0)
    oi: int | None = Field(default=None, ge=0)
    is_backfilled: bool = False
    source: Literal["live", "backfill"] = "live"

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v

    @field_validator("timestamp")
    @classmethod
    def _floor_to_minute(cls, v: datetime) -> datetime:
        return v.replace(second=0, microsecond=0)

    @model_validator(mode="after")
    def _high_ge_low(self) -> "CompletedBar":
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self


class SubscriptionRequest(BaseModel):
    """Request to subscribe to market data for an instrument."""
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    consumer_id: str = Field(..., min_length=1)
    priority: int = Field(default=0, ge=0)


class DataGap(BaseModel):
    """Represents a missing interval of minute bars."""
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    start: datetime  # inclusive
    end: datetime    # exclusive
    gap_type: Literal["MISSING", "CONFLICT", "UNRESOLVED"] = "MISSING"
    resolution_attempts: int = Field(default=0, ge=0)

    @field_validator("start", "end")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


class DataQualityStatus(BaseModel):
    """Snapshot of data quality for a single instrument."""
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    state: DataQualityState
    last_tick_at: datetime | None = None
    last_bar_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    details: str | None = None
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


class DataQualityEvent(BaseModel):
    """Emitted whenever an instrument's quality state changes."""
    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(..., gt=0)
    previous_state: DataQualityState
    new_state: DataQualityState
    reason: str
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v
