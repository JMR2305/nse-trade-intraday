"""StrategyStateRepository — session-injected CRUD for StrategyStateModel.

Follows the project-wide contract:
- AsyncSession is injected by the caller.
- No commit, rollback, or close.
- Domain objects hydrated without coupling ORM to domain contracts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import StrategyStateModel


class StrategyStateRepository:
    """Async repository for strategy state snapshot persistence."""

    async def save(
        self,
        session: AsyncSession,
        strategy_id: str,
        lifecycle_state: str,
        pending_order_ids: List[str],
        latest_signal_timestamp: Optional[datetime],
        emitted_signal_count: int,
        routed_signal_count: int,
        rejected_signal_count: int,
        fill_count: int,
        extra_data: Optional[Dict[str, Any]] = None,
        snapshot_timestamp: Optional[datetime] = None,
    ) -> StrategyStateModel:
        """Insert a new strategy state snapshot. Append-only."""
        now = datetime.now(timezone.utc)
        model = StrategyStateModel(
            strategy_id=strategy_id,
            lifecycle_state=lifecycle_state,
            pending_order_ids=list(pending_order_ids),
            latest_signal_timestamp=latest_signal_timestamp,
            emitted_signal_count=emitted_signal_count,
            routed_signal_count=routed_signal_count,
            rejected_signal_count=rejected_signal_count,
            fill_count=fill_count,
            extra_data=extra_data or {},
            snapshot_timestamp=snapshot_timestamp or now,
        )
        session.add(model)
        return model

    async def load_latest(
        self,
        session: AsyncSession,
        strategy_id: str,
    ) -> Optional[StrategyStateModel]:
        """Return the most recent snapshot for a given strategy_id."""
        result = await session.execute(
            select(StrategyStateModel)
            .where(StrategyStateModel.strategy_id == strategy_id)
            .order_by(StrategyStateModel.snapshot_timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_strategy(
        self,
        session: AsyncSession,
        strategy_id: str,
    ) -> List[StrategyStateModel]:
        """Return all snapshots for a strategy, newest first."""
        result = await session.execute(
            select(StrategyStateModel)
            .where(StrategyStateModel.strategy_id == strategy_id)
            .order_by(StrategyStateModel.snapshot_timestamp.desc())
        )
        return list(result.scalars().all())

    async def list_latest_all(
        self,
        session: AsyncSession,
    ) -> List[StrategyStateModel]:
        """Return the latest snapshot for every strategy_id."""
        result = await session.execute(
            select(StrategyStateModel).order_by(
                StrategyStateModel.strategy_id,
                StrategyStateModel.snapshot_timestamp.desc(),
            )
        )
        all_rows = list(result.scalars().all())
        seen: set = set()
        latest: List[StrategyStateModel] = []
        for row in all_rows:
            if row.strategy_id not in seen:
                seen.add(row.strategy_id)
                latest.append(row)
        return latest

    # ------------------------------------------------------------------
    # Hydration helper
    # ------------------------------------------------------------------
    @staticmethod
    def _hydrate_snapshot(model: StrategyStateModel) -> Dict[str, Any]:
        """Serialize an ORM model to a plain dict suitable for domain reconstruction."""
        return {
            "strategy_id": model.strategy_id,
            "lifecycle_state": model.lifecycle_state,
            "pending_order_ids": list(model.pending_order_ids) if model.pending_order_ids else [],
            "latest_signal_timestamp": model.latest_signal_timestamp,
            "emitted_signal_count": model.emitted_signal_count,
            "routed_signal_count": model.routed_signal_count,
            "rejected_signal_count": model.rejected_signal_count,
            "fill_count": model.fill_count,
            "extra_data": dict(model.extra_data) if model.extra_data else {},
            "snapshot_timestamp": model.snapshot_timestamp,
        }
