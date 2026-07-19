"""Fill event contracts and builder.

FillEvent is the rich immutable output of the matching engine.
It extends the concept of Batch 7A's FillRecord with additional
execution metadata (slippage, market event reference, gross value).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.execution.contracts import ExecutionOrderSide


# ------------------------------------------------------------------
# FillEvent
# ------------------------------------------------------------------

class FillEvent(BaseModel):
    """Immutable record of a simulated fill produced by the matching engine.

    This is the engine's output contract.  It is richer than Batch 7A's
    FillRecord (which is the state machine's internal tracking structure).
    The engine creates a FillEvent; the state machine creates a FillRecord.
    """
    model_config = ConfigDict(frozen=True)

    fill_id: str = Field(..., min_length=1)
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    client_order_id: str
    instrument_token: int = Field(..., gt=0)
    side: ExecutionOrderSide
    quantity: int = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)
    gross_value: Decimal = Field(..., gt=0)
    market_event_id: str = Field(..., min_length=1)
    market_timestamp: datetime
    fill_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cumulative_filled_quantity: int = Field(..., ge=0)
    remaining_quantity: int = Field(..., ge=0)
    liquidity_source: str = Field(default="paper")
    slippage_bps: Decimal = Field(default=Decimal("0"))
    metadata: dict[str, Any] | None = None

    @field_validator("market_timestamp", "fill_timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _validate_gross_value(self) -> "FillEvent":
        """Validate that gross_value == quantity * price."""
        expected = Decimal(self.quantity) * self.price
        if self.gross_value != expected:
            raise ValueError(
                f"gross_value {self.gross_value} != quantity*price {expected}"
            )
        return self


# ------------------------------------------------------------------
# FillEventBuilder
# ------------------------------------------------------------------

class FillEventBuilder:
    """Deterministic builder for FillEvent instances.

    Guarantees:
      - deterministic fill_id from (order_id, market_event_id, sequence)
      - gross_value = quantity * price
      - timestamps are timezone-aware
    """

    def __init__(self) -> None:
        self._sequence_counters: dict[str, int] = {}

    def build(
        self,
        order_id: UUID,
        client_order_id: str,
        instrument_token: int,
        side: ExecutionOrderSide,
        quantity: int,
        price: Decimal,
        market_event_id: str,
        market_timestamp: datetime,
        cumulative_filled_quantity: int,
        remaining_quantity: int,
        slippage_bps: Decimal = Decimal("0"),
        liquidity_source: str = "paper",
        metadata: dict[str, Any] | None = None,
    ) -> FillEvent:
        """Build a FillEvent with deterministic ID and validated gross value."""
        # Deterministic fill_id
        seq_key = f"{order_id}:{market_event_id}"
        seq = self._sequence_counters.get(seq_key, 0) + 1
        self._sequence_counters[seq_key] = seq

        deterministic_id = hashlib.sha256(
            f"{order_id}:{market_event_id}:{seq}".encode()
        ).hexdigest()[:32]

        gross_value = Decimal(quantity) * price

        return FillEvent(
            fill_id=deterministic_id,
            order_id=order_id,
            client_order_id=client_order_id,
            instrument_token=instrument_token,
            side=side,
            quantity=quantity,
            price=price,
            gross_value=gross_value,
            market_event_id=market_event_id,
            market_timestamp=market_timestamp,
            cumulative_filled_quantity=cumulative_filled_quantity,
            remaining_quantity=remaining_quantity,
            slippage_bps=slippage_bps,
            liquidity_source=liquidity_source,
            metadata=metadata,
        )

    def reset(self) -> None:
        """Clear sequence counters.  Useful for deterministic replay tests."""
        self._sequence_counters.clear()
