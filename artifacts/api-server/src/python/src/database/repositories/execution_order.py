"""ExecutionOrderRepository — persists ExecutionOrder state.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
Follows the session-injection pattern established by MinuteBarRepository.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.contracts import ExecutionOrder, ExecutionOrderStatus
from src.execution.state_machine import OrderState


class ExecutionOrderRepository:
    """Repository for execution_orders table.

    Persists order definitions and runtime state (status, filled_quantity,
    average_fill_price, sequence_number).  Follows the convention that the
    caller owns the session and commit/rollback.
    """

    def __init__(self, model_class: Any | None = None) -> None:
        if model_class is None:
            from src.database.models import ExecutionOrderModel
            model_class = ExecutionOrderModel
        self._model = model_class

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(
        self,
        order: ExecutionOrder,
        state: OrderState | None,
        session: AsyncSession,
    ) -> None:
        """Upsert an order and its current runtime state."""
        filled_quantity = state.filled_quantity if state else 0
        avg_price = state.average_fill_price if state else None
        seq = state.sequence_number if state else 0
        status = state.status.value if state else "CREATED"

        # Check if exists
        stmt = select(self._model).where(self._model.id == order.order_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.status = status
            existing.filled_quantity = filled_quantity
            existing.average_fill_price = avg_price
            existing.sequence_number = seq
            existing.updated_at = order.created_at  # caller provides tz-aware
        else:
            record = self._model(
                id=order.order_id,
                client_order_id=order.client_order_id,
                instrument_token=order.instrument_token,
                side=order.side.value,
                order_type=order.order_type.value,
                quantity=order.quantity,
                limit_price=order.limit_price,
                trigger_price=order.trigger_price,
                product=order.product,
                validity=order.validity,
                status=status,
                filled_quantity=filled_quantity,
                average_fill_price=avg_price,
                sequence_number=seq,
                exchange=order.exchange,
                created_at=order.created_at,
                updated_at=order.created_at,
            )
            session.add(record)

    async def update_status(
        self,
        order_id: UUID,
        new_status: ExecutionOrderStatus,
        session: AsyncSession,
    ) -> None:
        """Update only the status field (lightweight path)."""
        stmt = select(self._model).where(self._model.id == order_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            record.status = new_status.value

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        order_id: UUID,
        session: AsyncSession,
    ) -> OrderState | None:
        """Return a hydrated OrderState or None."""
        stmt = select(self._model).where(self._model.id == order_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._hydrate_state(record)

    async def get_by_client_order_id(
        self,
        client_order_id: str,
        session: AsyncSession,
    ) -> OrderState | None:
        stmt = select(self._model).where(
            self._model.client_order_id == client_order_id
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._hydrate_state(record)

    async def list_active(
        self,
        session: AsyncSession,
    ) -> list[OrderState]:
        """Return all non-terminal orders (OPEN, PARTIALLY_FILLED, CREATED, etc.)."""
        terminal = {"REJECTED", "FILLED", "CANCELLED", "EXPIRED", "FAILED"}
        stmt = select(self._model).where(self._model.status.not_in(terminal))
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_state(r) for r in records]

    async def list_all(
        self,
        session: AsyncSession,
    ) -> list[OrderState]:
        """Return every persisted order state."""
        stmt = select(self._model)
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_state(r) for r in records]

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

    def _hydrate_state(self, record: Any) -> OrderState:
        """Reconstruct an OrderState from a DB record."""
        from src.execution.contracts import (
            ExecutionOrder,
            ExecutionOrderSide,
            ExecutionOrderType,
            ExecutionOrderStatus,
        )

        order = ExecutionOrder(
            order_id=record.id,
            client_order_id=record.client_order_id,
            instrument_token=record.instrument_token,
            side=ExecutionOrderSide(record.side),
            order_type=ExecutionOrderType(record.order_type),
            quantity=record.quantity,
            limit_price=record.limit_price,
            trigger_price=record.trigger_price,
            product=record.product,
            validity=record.validity,
            exchange=record.exchange,
            created_at=record.created_at,
        )

        state = OrderState(order=order)
        state._status = ExecutionOrderStatus(record.status)
        state._filled_quantity = record.filled_quantity
        state._average_fill_price = record.average_fill_price
        state._sequence_number = record.sequence_number
        return state
