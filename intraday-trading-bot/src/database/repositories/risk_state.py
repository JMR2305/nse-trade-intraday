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
            existing.trade_count = snapshot.trade_count
            existing.order_count = snapshot.order_count
            existing.emergency_halt_active = snapshot.emergency_halt_active
            existing.circuit_breaker_triggered = snapshot.circuit_breaker_triggered
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
            trade_count=snapshot.trade_count,
            order_count=snapshot.order_count,
            emergency_halt_active=snapshot.emergency_halt_active,
            circuit_breaker_triggered=snapshot.circuit_breaker_triggered,
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
        """Reconstruct RiskStateSnapshot from ORM model.

        Backward-compatible: RC-8B columns default to 0/False for old rows
        that were persisted before the 0002 migration.
        """
        return RiskStateSnapshot(
            account_id=model.account_id,
            snapshot_timestamp=model.snapshot_timestamp,
            daily_realized_pnl=Decimal(str(model.daily_realized_pnl)),
            daily_turnover=Decimal(str(model.daily_turnover)),
            peak_equity=Decimal(str(model.peak_equity)),
            message_counts=dict(model.message_counts or {}),
            kill_switch_active=bool(model.kill_switch_active),
            kill_switch_reason=model.kill_switch_reason,
            # RC-8B fields: use getattr with defaults for old rows
            trade_count=int(getattr(model, "trade_count", None) or 0),
            order_count=int(getattr(model, "order_count", None) or 0),
            emergency_halt_active=bool(getattr(model, "emergency_halt_active", False) or False),
            circuit_breaker_triggered=bool(
                getattr(model, "circuit_breaker_triggered", False) or False
            ),
        )
