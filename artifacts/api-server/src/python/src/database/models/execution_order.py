"""SQLAlchemy ORM model for execution_orders table.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from src.database.models.base import Base


class ExecutionOrderModel(Base):
    """Persistent representation of an ExecutionOrder and its runtime state."""

    __tablename__ = "execution_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_order_id = Column(Text, nullable=False, unique=True, index=True)
    instrument_token = Column(Integer, nullable=False, index=True)
    side = Column(Text, nullable=False)
    order_type = Column(Text, nullable=False)
    quantity = Column(Integer, nullable=False)
    limit_price = Column(Numeric, nullable=True)
    trigger_price = Column(Numeric, nullable=True)
    product = Column(Text, nullable=False, default="CNC")
    validity = Column(Text, nullable=False, default="DAY")
    status = Column(Text, nullable=False, default="CREATED", index=True)
    filled_quantity = Column(Integer, nullable=False, default=0)
    average_fill_price = Column(Numeric, nullable=True)
    sequence_number = Column(Integer, nullable=False, default=0)
    exchange = Column(Text, nullable=False, default="NSE")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionOrderModel(id={self.id}, client_order_id={self.client_order_id}, "
            f"status={self.status}, filled_quantity={self.filled_quantity})>"
        )
