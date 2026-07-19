"""ExecutionTradeRepository — persists ExecutionTrade records.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.trades import ExecutionTrade


class ExecutionTradeRepository:
    """Repository for execution_trades table.

    Trades are immutable and idempotent by trade_id (derived from fill_id).
    """

    def __init__(self, model_class: Any | None = None) -> None:
        if model_class is None:
            from src.database.models import ExecutionTradeModel
            model_class = ExecutionTradeModel
        self._model = model_class

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(self, trade: ExecutionTrade, session: AsyncSession) -> None:
        """Persist a trade.  Idempotent by trade_id PK."""
        record = self._model(
            trade_id=trade.trade_id,
            fill_id=trade.fill_id,
            order_id=trade.order_id,
            instrument_token=trade.instrument_token,
            side=trade.side.value,
            quantity=trade.quantity,
            price=trade.price,
            gross_value=trade.gross_value,
            position_impact=trade.position_impact,
            realized_pnl=trade.realized_pnl,
            cumulative_realized_pnl=trade.cumulative_realized_pnl,
            market_timestamp=trade.market_timestamp,
            trade_timestamp=trade.trade_timestamp,
            metadata=trade.metadata,
        )
        session.add(record)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_fill_id(
        self,
        fill_id: str,
        session: AsyncSession,
    ) -> ExecutionTrade | None:
        """Lookup a trade by its originating fill_id."""
        stmt = select(self._model).where(self._model.fill_id == fill_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._hydrate_trade(record)

    async def get_trades_for_instrument(
        self,
        instrument_token: int,
        session: AsyncSession,
    ) -> list[ExecutionTrade]:
        """Return all trades for an instrument, ordered by trade_timestamp."""
        stmt = (
            select(self._model)
            .where(self._model.instrument_token == instrument_token)
            .order_by(self._model.trade_timestamp)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_trade(r) for r in records]

    async def get_all(
        self,
        session: AsyncSession,
    ) -> list[ExecutionTrade]:
        """Return all trades, ordered by trade_timestamp."""
        stmt = select(self._model).order_by(self._model.trade_timestamp)
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_trade(r) for r in records]

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

    def _hydrate_trade(self, record: Any) -> ExecutionTrade:
        from src.execution.contracts import ExecutionOrderSide

        return ExecutionTrade(
            trade_id=record.trade_id,
            fill_id=record.fill_id,
            order_id=record.order_id,
            client_order_id=record.client_order_id,
            instrument_token=record.instrument_token,
            side=ExecutionOrderSide(record.side),
            quantity=record.quantity,
            price=record.price,
            gross_value=record.gross_value,
            position_impact=record.position_impact,
            realized_pnl=record.realized_pnl,
            cumulative_realized_pnl=record.cumulative_realized_pnl,
            market_timestamp=record.market_timestamp,
            trade_timestamp=record.trade_timestamp,
            metadata=record.metadata,
        )
