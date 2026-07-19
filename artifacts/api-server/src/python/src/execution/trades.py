"""Trade record contracts and ledger.

ExecutionTrade is an immutable record of a completed fill from the
position engine's perspective.  It is distinct from Batch 7B's FillEvent
(which is the matching engine's output) and from Batch 7A's FillRecord
(which is the state machine's internal tracking).

TradeLedger maintains a deterministic, append-only history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.execution.contracts import ExecutionOrderSide


# ------------------------------------------------------------------
# ExecutionTrade
# ------------------------------------------------------------------

class ExecutionTrade(BaseModel):
    """Immutable record of a trade from the position engine perspective.

    Created from a FillEvent after position impact is computed.
    """
    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., min_length=1)
    fill_id: str = Field(..., min_length=1)
    order_id: UUID
    client_order_id: str
    instrument_token: int = Field(..., gt=0)
    side: ExecutionOrderSide
    quantity: int = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)
    gross_value: Decimal = Field(..., gt=0)
    position_impact: str = Field(..., pattern=r"^(OPEN|ADD|REDUCE|CLOSE|REVERSE)$")
    realized_pnl: Decimal = Field(default=Decimal("0"))
    cumulative_realized_pnl: Decimal = Field(default=Decimal("0"))
    market_timestamp: datetime
    trade_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] | None = None

    @field_validator("market_timestamp", "trade_timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


# ------------------------------------------------------------------
# TradeLedger
# ------------------------------------------------------------------

class TradeLedger:
    """Deterministic, append-only trade history.

    Idempotent: duplicate fill_id is silently ignored.
    """

    def __init__(self) -> None:
        self._trades: list[ExecutionTrade] = []
        self._seen_fill_ids: set[str] = set()

    def record(self, trade: ExecutionTrade) -> bool:
        """Record a trade.  Returns True if newly recorded, False if duplicate.

        Thread-safe for reads; caller must hold position lock for writes.
        """
        if trade.fill_id in self._seen_fill_ids:
            return False
        self._seen_fill_ids.add(trade.fill_id)
        self._trades.append(trade)
        return True

    def get_trades(self, instrument_token: int | None = None) -> tuple[ExecutionTrade, ...]:
        """Return all trades, optionally filtered by instrument."""
        if instrument_token is None:
            return tuple(self._trades)
        return tuple(t for t in self._trades if t.instrument_token == instrument_token)

    def get_trade_by_fill_id(self, fill_id: str) -> ExecutionTrade | None:
        """Lookup a trade by its originating fill_id."""
        for t in self._trades:
            if t.fill_id == fill_id:
                return t
        return None

    def reset(self) -> None:
        """Clear ledger for deterministic replay tests."""
        self._trades.clear()
        self._seen_fill_ids.clear()

    @property
    def trade_count(self) -> int:
        return len(self._trades)

    @property
    def total_turnover(self) -> Decimal:
        """Sum of gross values of all trades."""
        return sum((t.gross_value for t in self._trades), Decimal("0"))
