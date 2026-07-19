"""SQLAlchemy ORM model for execution_trades table.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ExecutionTradeModel(Base):
    """Persistent representation of an ExecutionTrade."""

    __tablename__ = "execution_trades"

    trade_id = Column(Text, primary_key=True)
    fill_id = Column(
        Text,
        ForeignKey("execution_fills.fill_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    client_order_id = Column(Text, nullable=False, index=True)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instrument_token = Column(Integer, nullable=False, index=True)
    side = Column(Text, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric, nullable=False)
    gross_value = Column(Numeric, nullable=False)
    position_impact = Column(Text, nullable=False)
    realized_pnl = Column(Numeric, nullable=False, default=Decimal("0"))
    cumulative_realized_pnl = Column(Numeric, nullable=False, default=Decimal("0"))
    market_timestamp = Column(DateTime(timezone=True), nullable=False)
    trade_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ExecutionTradeModel(trade_id={self.trade_id}, fill_id={self.fill_id}, "
            f"impact={self.position_impact}, realized_pnl={self.realized_pnl})>"
        )
