"""AuditEventRepository — persists ExecutionAuditEvent records.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.contracts import ExecutionAuditEvent


class AuditEventRepository:
    """Repository for execution_audit_events table.

    Append-only.  Every successful state transition produces one record.
    """

    def __init__(self, model_class: Any | None = None) -> None:
        if model_class is None:
            from src.database.models import AuditEventModel
            model_class = AuditEventModel
        self._model = model_class

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(
        self,
        event: ExecutionAuditEvent,
        session: AsyncSession,
    ) -> None:
        """Persist an audit event.  Idempotent by (order_id, sequence_number)."""
        fill_record_json = None
        if event.fill_record is not None:
            fill_record_json = {
                "fill_id": str(event.fill_record.fill_id),
                "quantity": event.fill_record.quantity,
                "price": str(event.fill_record.price),
                "filled_at": event.fill_record.filled_at.isoformat(),
                "metadata": event.fill_record.metadata,
            }

        record = self._model(
            id=event.event_id,
            order_id=event.order_id,
            client_order_id=event.client_order_id,
            sequence_number=event.sequence_number,
            previous_state=event.previous_state.value,
            new_state=event.new_state.value,
            action=event.action.value,
            actor=event.actor,
            reason=event.reason,
            event_timestamp=event.event_timestamp,
            fill_record=fill_record_json,
            metadata=event.metadata,
        )
        session.add(record)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_events_for_order(
        self,
        order_id: UUID,
        session: AsyncSession,
    ) -> list[ExecutionAuditEvent]:
        """Return all audit events for an order, ordered by sequence_number."""
        stmt = (
            select(self._model)
            .where(self._model.order_id == order_id)
            .order_by(self._model.sequence_number)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_event(r) for r in records]

    async def get_latest_sequence(
        self,
        order_id: UUID,
        session: AsyncSession,
    ) -> int:
        """Return the highest sequence_number for an order, or -1 if none."""
        stmt = (
            select(self._model.sequence_number)
            .where(self._model.order_id == order_id)
            .order_by(desc(self._model.sequence_number))
            .limit(1)
        )
        result = await session.execute(stmt)
        seq = result.scalar_one_or_none()
        return seq if seq is not None else -1

    async def get_all_events(
        self,
        session: AsyncSession,
        after_sequence: int | None = None,
    ) -> list[ExecutionAuditEvent]:
        """Return all audit events, optionally filtered by global sequence."""
        stmt = select(self._model).order_by(
            self._model.order_id,
            self._model.sequence_number,
        )
        if after_sequence is not None:
            stmt = stmt.where(self._model.sequence_number > after_sequence)
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_event(r) for r in records]

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

    def _hydrate_event(self, record: Any) -> ExecutionAuditEvent:
        from src.execution.contracts import (
            ExecutionOrderStatus,
            ExecutionOrderAction,
            FillRecord,
        )
        from datetime import datetime
        from decimal import Decimal

        fill_record = None
        if record.fill_record:
            fill_record = FillRecord(
                fill_id=UUID(record.fill_record["fill_id"]),
                quantity=record.fill_record["quantity"],
                price=Decimal(record.fill_record["price"]),
                filled_at=datetime.fromisoformat(record.fill_record["filled_at"]),
                metadata=record.fill_record.get("metadata"),
            )

        return ExecutionAuditEvent(
            event_id=record.id,
            order_id=record.order_id,
            client_order_id=record.client_order_id,
            sequence_number=record.sequence_number,
            previous_state=ExecutionOrderStatus(record.previous_state),
            new_state=ExecutionOrderStatus(record.new_state),
            action=ExecutionOrderAction(record.action),
            reason=record.reason,
            event_timestamp=record.event_timestamp,
            actor=record.actor,
            metadata=record.metadata,
            fill_record=fill_record,
        )
