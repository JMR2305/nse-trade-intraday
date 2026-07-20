"""
Risk State Repository.

Follows the session-injected pattern: caller provides AsyncSession,
repository never commits. Hydration methods reconstruct domain objects
from ORM records without coupling domain to ORM.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import RiskStateModel
from src.risk.contracts import RiskStateSnapshot


class RiskStateRepository:
    """Repository for risk state snapshot persistence."""

    async def save(self, snapshot: RiskStateSnapshot, session: AsyncSession) -> RiskStateModel:
        """Save or update a risk state snapshot."""
        stmt = (
            select(RiskStateModel)
            .where(RiskStateModel.account_id == snapshot.account_id)
            .where(RiskStateModel.snapshot_timestamp == snapshot.snapshot_timestamp)
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.daily_realized_pnl = snapshot.daily_realized_pnl
            existing.daily_turnover = snapshot.daily_turnover
            existing.peak_equity = snapshot.peak_equity
            existing.kill_switch_active = snapshot.kill_switch_active
            existing.kill_switch_reason = snapshot.kill_switch_reason
            existing.message_counts = dict(snapshot.message_counts)
            return existing

        model = RiskStateModel(
            account_id=snapshot.account_id,
            snapshot_timestamp=snapshot.snapshot_timestamp,
            daily_realized_pnl=snapshot.daily_realized_pnl,
            daily_turnover=snapshot.daily_turnover,
            peak_equity=snapshot.peak_equity,
            kill_switch_active=snapshot.kill_switch_active,
            kill_switch_reason=snapshot.kill_switch_reason,
            message_counts=dict(snapshot.message_counts),
        )
        session.add(model)
        return model

    async def load_latest(
        self,
        account_id: str,
        session: AsyncSession,
    ) -> Optional[RiskStateSnapshot]:
        """Load the most recent risk state snapshot for an account."""
        stmt = (
            select(RiskStateModel)
            .where(RiskStateModel.account_id == account_id)
            .order_by(desc(RiskStateModel.snapshot_timestamp))
            .limit(1)
        )
        result = await session.execute(stmt)
        model = result.scalar_one_or_none()

        if model is None:
            return None

        return self._hydrate_snapshot(model)

    async def load_all_for_account(
        self,
        account_id: str,
        session: AsyncSession,
        limit: int = 100,
    ) -> List[RiskStateSnapshot]:
        """Load all snapshots for an account, newest first."""
        stmt = (
            select(RiskStateModel)
            .where(RiskStateModel.account_id == account_id)
            .order_by(desc(RiskStateModel.snapshot_timestamp))
            .limit(limit)
        )
        result = await session.execute(stmt)
        models = result.scalars().all()
        return [self._hydrate_snapshot(m) for m in models]

    @staticmethod
    def _hydrate_snapshot(model: RiskStateModel) -> RiskStateSnapshot:
        """Reconstruct RiskStateSnapshot from ORM model."""
        return RiskStateSnapshot(
            account_id=model.account_id,
            snapshot_timestamp=model.snapshot_timestamp,
            daily_realized_pnl=Decimal(str(model.daily_realized_pnl)),
            daily_turnover=Decimal(str(model.daily_turnover)),
            peak_equity=Decimal(str(model.peak_equity)),
            message_counts=dict(model.message_counts or {}),
            kill_switch_active=bool(model.kill_switch_active),
            kill_switch_reason=model.kill_switch_reason,
        )
