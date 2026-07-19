"""FillEventRepository — persists FillEvent records.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.fills import FillEvent


class FillEventRepository:
    """Repository for execution_fills table.

    FillEvents are immutable and idempotent by fill_id (SHA-256 PK).
    """

    def __init__(self, model_class: Any | None = None) -> None:
        if model_class is None:
            from src.database.models import FillEventModel
            model_class = FillEventModel
        self._model = model_class

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(self, fill: FillEvent, session: AsyncSession) -> None:
        """Persist a fill event.  Idempotent by fill_id PK."""
        record = self._model(
            fill_id=fill.fill_id,
            event_id=fill.event_id,
            order_id=fill.order_id,
            client_order_id=fill.client_order_id,
            instrument_token=fill.instrument_token,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            gross_value=fill.gross_value,
            market_event_id=fill.market_event_id,
            market_timestamp=fill.market_timestamp,
            fill_timestamp=fill.fill_timestamp,
            slippage_bps=fill.slippage_bps,
            metadata=fill.metadata,
        )
        session.add(record)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_fill_id(
        self,
        fill_id: str,
        session: AsyncSession,
    ) -> FillEvent | None:
        """Lookup a fill by its deterministic fill_id."""
        stmt = select(self._model).where(self._model.fill_id == fill_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._hydrate_fill(record)

    async def get_fills_for_order(
        self,
        order_id: UUID,
        session: AsyncSession,
    ) -> list[FillEvent]:
        """Return all fills for an order, ordered by fill_timestamp."""
        stmt = (
            select(self._model)
            .where(self._model.order_id == order_id)
            .order_by(self._model.fill_timestamp)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_fill(r) for r in records]

    async def get_all_fills(
        self,
        session: AsyncSession,
    ) -> list[FillEvent]:
        """Return all fills, ordered by fill_timestamp."""
        stmt = select(self._model).order_by(self._model.fill_timestamp)
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_fill(r) for r in records]

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

    def _hydrate_fill(self, record: Any) -> FillEvent:
        from src.execution.contracts import ExecutionOrderSide

        return FillEvent(
            fill_id=record.fill_id,
            event_id=record.event_id,
            order_id=record.order_id,
            client_order_id=record.client_order_id,
            instrument_token=record.instrument_token,
            side=ExecutionOrderSide(record.side),
            quantity=record.quantity,
            price=record.price,
            gross_value=record.gross_value,
            market_event_id=record.market_event_id,
            market_timestamp=record.market_timestamp,
            fill_timestamp=record.fill_timestamp,
            slippage_bps=record.slippage_bps,
            liquidity_source="paper",
            metadata=record.metadata,
        )
