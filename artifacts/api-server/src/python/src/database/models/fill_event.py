"""SQLAlchemy ORM model for execution_fills table.

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class FillEventModel(Base):
    """Persistent representation of a FillEvent."""

    __tablename__ = "execution_fills"

    fill_id = Column(Text, primary_key=True)
    event_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_order_id = Column(Text, nullable=False, index=True)
    instrument_token = Column(Integer, nullable=False, index=True)
    side = Column(Text, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric, nullable=False)
    gross_value = Column(Numeric, nullable=False)
    market_event_id = Column(Text, nullable=False, index=True)
    market_timestamp = Column(DateTime(timezone=True), nullable=False)
    fill_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    slippage_bps = Column(Numeric, nullable=False, default=Decimal("0"))
    metadata_ = Column("metadata", JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<FillEventModel(fill_id={self.fill_id}, order_id={self.order_id}, "
            f"qty={self.quantity}, price={self.price})>"
        )
