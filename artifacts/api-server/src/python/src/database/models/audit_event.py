"""SQLAlchemy ORM model for execution_audit_events table.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AuditEventModel(Base):
    """Persistent representation of an ExecutionAuditEvent."""

    __tablename__ = "execution_audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_order_id = Column(Text, nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    previous_state = Column(Text, nullable=False)
    new_state = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    actor = Column(Text, nullable=False, default="system")
    reason = Column(Text, nullable=True)
    event_timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    fill_record = Column(JSONB, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("order_id", "sequence_number", name="uq_audit_event_order_seq"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditEventModel(id={self.id}, order_id={self.order_id}, "
            f"action={self.action}, seq={self.sequence_number})>"
        )
