"""PositionSnapshotRepository — persists PositionSnapshot records.

Batch 7D — Execution Recovery, Persistence & Replay Foundation.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.execution.portfolio import PositionSnapshot


class PositionSnapshotRepository:
    """Repository for position_snapshots table.

    Stores the latest snapshot per instrument (UPSERT semantics).
    """

    def __init__(self, model_class: Any | None = None) -> None:
        if model_class is None:
            from src.database.models import PositionSnapshotModel
            model_class = PositionSnapshotModel
        self._model = model_class

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save_snapshot(
        self,
        snapshot: PositionSnapshot,
        session: AsyncSession,
    ) -> None:
        """Upsert a position snapshot (latest per instrument)."""
        stmt = select(self._model).where(
            self._model.instrument_token == snapshot.instrument_token
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.net_quantity = snapshot.net_quantity
            existing.direction = snapshot.direction
            existing.average_buy_price = snapshot.average_buy_price
            existing.average_sell_price = snapshot.average_sell_price
            existing.total_buy_quantity = snapshot.total_buy_quantity
            existing.total_sell_quantity = snapshot.total_sell_quantity
            existing.total_buy_value = snapshot.total_buy_value
            existing.total_sell_value = snapshot.total_sell_value
            existing.realized_pnl = snapshot.realized_pnl
            existing.unrealized_pnl = snapshot.unrealized_pnl
            existing.market_price = snapshot.market_price
            existing.market_timestamp = snapshot.market_timestamp
            existing.snapshot_timestamp = snapshot.position_timestamp
            existing.metadata = snapshot.metadata
        else:
            record = self._model(
                instrument_token=snapshot.instrument_token,
                net_quantity=snapshot.net_quantity,
                direction=snapshot.direction,
                average_buy_price=snapshot.average_buy_price,
                average_sell_price=snapshot.average_sell_price,
                total_buy_quantity=snapshot.total_buy_quantity,
                total_sell_quantity=snapshot.total_sell_quantity,
                total_buy_value=snapshot.total_buy_value,
                total_sell_value=snapshot.total_sell_value,
                realized_pnl=snapshot.realized_pnl,
                unrealized_pnl=snapshot.unrealized_pnl,
                market_price=snapshot.market_price,
                market_timestamp=snapshot.market_timestamp,
                snapshot_timestamp=snapshot.position_timestamp,
                metadata=snapshot.metadata,
            )
            session.add(record)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_latest(
        self,
        instrument_token: int,
        session: AsyncSession,
    ) -> PositionSnapshot | None:
        """Return the latest snapshot for an instrument, or None."""
        stmt = select(self._model).where(
            self._model.instrument_token == instrument_token
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._hydrate_snapshot(record)

    async def get_all_open(
        self,
        session: AsyncSession,
    ) -> list[PositionSnapshot]:
        """Return all non-flat position snapshots."""
        stmt = select(self._model).where(
            self._model.direction != "FLAT"
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_snapshot(r) for r in records]

    async def get_all(
        self,
        session: AsyncSession,
    ) -> list[PositionSnapshot]:
        """Return all position snapshots."""
        stmt = select(self._model)
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._hydrate_snapshot(r) for r in records]

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

    def _hydrate_snapshot(self, record: Any) -> PositionSnapshot:
        return PositionSnapshot(
            instrument_token=record.instrument_token,
            net_quantity=record.net_quantity,
            direction=record.direction,
            average_buy_price=record.average_buy_price,
            average_sell_price=record.average_sell_price,
            total_buy_quantity=record.total_buy_quantity,
            total_sell_quantity=record.total_sell_quantity,
            total_buy_value=record.total_buy_value,
            total_sell_value=record.total_sell_value,
            realized_pnl=record.realized_pnl,
            unrealized_pnl=record.unrealized_pnl,
            market_price=record.market_price,
            market_timestamp=record.market_timestamp,
            position_timestamp=record.snapshot_timestamp,
            metadata=record.metadata,
        )
