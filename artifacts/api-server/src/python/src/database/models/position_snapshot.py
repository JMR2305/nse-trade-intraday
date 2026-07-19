"""SQLAlchemy ORM model for position_snapshots table.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from src.database.models.base import Base


class PositionSnapshotModel(Base):
    """Persistent representation of a PositionSnapshot (latest per instrument)."""

    __tablename__ = "position_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_token = Column(Integer, nullable=False, unique=True, index=True)
    net_quantity = Column(Integer, nullable=False)
    direction = Column(Text, nullable=False)
    average_buy_price = Column(Numeric, nullable=False)
    average_sell_price = Column(Numeric, nullable=False)
    total_buy_quantity = Column(Integer, nullable=False, default=0)
    total_sell_quantity = Column(Integer, nullable=False, default=0)
    total_buy_value = Column(Numeric, nullable=False, default=Decimal("0"))
    total_sell_value = Column(Numeric, nullable=False, default=Decimal("0"))
    realized_pnl = Column(Numeric, nullable=False, default=Decimal("0"))
    unrealized_pnl = Column(Numeric, nullable=False, default=Decimal("0"))
    market_price = Column(Numeric, nullable=True)
    market_timestamp = Column(DateTime(timezone=True), nullable=True)
    snapshot_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PositionSnapshotModel(instrument_token={self.instrument_token}, "
            f"net_quantity={self.net_quantity}, direction={self.direction})>"
        )
