"""Portfolio and position contracts.

Immutable snapshots for positions, cash, and portfolio state.
All monetary values use Decimal.  Timestamps are timezone-aware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


# ------------------------------------------------------------------
# PositionDirection
# ------------------------------------------------------------------

class PositionDirection:
    """Position direction constants."""
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


# ------------------------------------------------------------------
# PositionSnapshot
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PositionSnapshot:
    """Immutable snapshot of a position at a point in time.

    Net quantity is positive for LONG, negative for SHORT, zero for FLAT.
    """
    instrument_token: int
    net_quantity: int  # positive=LONG, negative=SHORT, zero=FLAT
    direction: str  # PositionDirection.LONG/SHORT/FLAT
    average_buy_price: Decimal  # weighted avg of all buy fills
    average_sell_price: Decimal  # weighted avg of all sell fills
    total_buy_quantity: int  # cumulative buy quantity
    total_sell_quantity: int  # cumulative sell quantity
    total_buy_value: Decimal  # cumulative buy gross value
    total_sell_value: Decimal  # cumulative sell gross value
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    market_price: Decimal | None  # last known market price for unrealized P&L
    market_timestamp: datetime | None
    position_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Validate consistency
        if self.net_quantity > 0 and self.direction != PositionDirection.LONG:
            raise ValueError(f"net_quantity {self.net_quantity} > 0 but direction is {self.direction}")
        if self.net_quantity < 0 and self.direction != PositionDirection.SHORT:
            raise ValueError(f"net_quantity {self.net_quantity} < 0 but direction is {self.direction}")
        if self.net_quantity == 0 and self.direction != PositionDirection.FLAT:
            raise ValueError(f"net_quantity {self.net_quantity} == 0 but direction is {self.direction}")

    @property
    def is_long(self) -> bool:
        return self.direction == PositionDirection.LONG

    @property
    def is_short(self) -> bool:
        return self.direction == PositionDirection.SHORT

    @property
    def is_flat(self) -> bool:
        return self.direction == PositionDirection.FLAT

    @property
    def market_value(self) -> Decimal:
        """Market value at last known price."""
        if self.market_price is None:
            return Decimal("0")
        return Decimal(self.net_quantity) * self.market_price

    @property
    def exposure(self) -> Decimal:
        """Absolute exposure (quantity * avg price)."""
        if self.net_quantity == 0:
            return Decimal("0")
        if self.is_long:
            return Decimal(self.net_quantity) * self.average_buy_price
        return Decimal(abs(self.net_quantity)) * self.average_sell_price


# ------------------------------------------------------------------
# CashLedger
# ------------------------------------------------------------------

@dataclass
class CashLedger:
    """Mutable cash tracking.  Protected by position lock in PositionEngine.

    BUY fills decrease cash (debit).
    SELL fills increase cash (credit).
    """
    balance: Decimal = Decimal("0")
    total_credits: Decimal = Decimal("0")
    total_debits: Decimal = Decimal("0")
    transaction_count: int = 0

    def credit(self, amount: Decimal) -> None:
        """Record a cash inflow (e.g., SELL fill)."""
        if amount <= 0:
            raise ValueError(f"Credit amount must be positive, got {amount}")
        self.balance += amount
        self.total_credits += amount
        self.transaction_count += 1

    def debit(self, amount: Decimal) -> None:
        """Record a cash outflow (e.g., BUY fill)."""
        if amount <= 0:
            raise ValueError(f"Debit amount must be positive, got {amount}")
        self.balance -= amount
        self.total_debits += amount
        self.transaction_count += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "total_credits": self.total_credits,
            "total_debits": self.total_debits,
            "transaction_count": self.transaction_count,
        }

    def reset(self) -> None:
        self.balance = Decimal("0")
        self.total_credits = Decimal("0")
        self.total_debits = Decimal("0")
        self.transaction_count = 0


# ------------------------------------------------------------------
# PortfolioSnapshot
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PortfolioSnapshot:
    """Immutable portfolio-wide snapshot.

    Captures cash, all positions, and aggregate P&L at a point in time.
    """
    cash: Decimal
    equity: Decimal  # cash + market_value of all positions
    positions: tuple[PositionSnapshot, ...]
    market_value: Decimal  # sum of position market values
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal  # realized + unrealized
    buying_power: Decimal  # paper: cash + margin (simplified = cash)
    margin_used: Decimal  # paper: sum of position exposures
    trade_count: int
    turnover: Decimal
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] | None = None
