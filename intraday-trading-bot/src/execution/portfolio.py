"""Stub for execution/portfolio.py - RC-7 frozen module."""
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Literal

PositionDirection = Literal["LONG", "SHORT", "FLAT"]


@dataclass(frozen=True)
class PositionSnapshot:
    instrument_token: str
    net_quantity: Decimal
    direction: PositionDirection
    average_buy_price: Decimal = Decimal("0")
    average_sell_price: Decimal = Decimal("0")
    total_buy_quantity: Decimal = Decimal("0")
    total_sell_quantity: Decimal = Decimal("0")
    total_buy_value: Decimal = Decimal("0")
    total_sell_value: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    position_timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if self.direction == "FLAT" and self.net_quantity != Decimal("0"):
            raise ValueError("FLAT position must have zero net_quantity")


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    buying_power: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    trade_count: int = 0
    turnover: Decimal = Decimal("0")
    timestamp: datetime = field(default_factory=datetime.utcnow)
