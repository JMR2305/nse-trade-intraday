"""StrategySignalRepository — session-injected CRUD for StrategySignalModel.

Follows the project-wide contract:
- AsyncSession is injected by the caller.
- No commit, rollback, or close.
- Domain objects hydrated without coupling ORM to domain contracts.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import StrategySignalModel


class StrategySignalRepository:
    """Async repository for strategy signal persistence."""

    async def save(
        self,
        session: AsyncSession,
        signal_id: UUID,
        strategy_id: str,
        account_id: Optional[str],
        instrument_token: str,
        action: str,
        side: str,
        quantity: Decimal,
        order_type: str,
        limit_price: Optional[Decimal],
        trigger_price: Optional[Decimal],
        timestamp: datetime,
        routing_status: str,
        routed_client_order_id: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> StrategySignalModel:
        """Upsert a signal record by signal_id (idempotent save)."""
        result = await session.execute(
            select(StrategySignalModel).where(
                StrategySignalModel.signal_id == signal_id
            )
        )
        existing: Optional[StrategySignalModel] = result.scalar_one_or_none()

        if existing is not None:
            existing.strategy_id = strategy_id
            existing.account_id = account_id
            existing.instrument_token = instrument_token
            existing.action = action
            existing.side = side
            existing.quantity = quantity
            existing.order_type = order_type
            existing.limit_price = limit_price
            existing.trigger_price = trigger_price
            existing.timestamp = timestamp
            existing.routing_status = routing_status
            existing.routed_client_order_id = routed_client_order_id
            existing.rejection_reason = rejection_reason
            existing.extra_data = extra_data or {}
            return existing

        model = StrategySignalModel(
            signal_id=signal_id,
            strategy_id=strategy_id,
            account_id=account_id,
            instrument_token=instrument_token,
            action=action,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            trigger_price=trigger_price,
            timestamp=timestamp,
            routing_status=routing_status,
            routed_client_order_id=routed_client_order_id,
            rejection_reason=rejection_reason,
            extra_data=extra_data or {},
        )
        session.add(model)
        return model

    async def load(
        self,
        session: AsyncSession,
        signal_id: UUID,
    ) -> Optional[StrategySignalModel]:
        """Load a single signal by its natural key."""
        result = await session.execute(
            select(StrategySignalModel).where(
                StrategySignalModel.signal_id == signal_id
            )
        )
        return result.scalar_one_or_none()

    async def list_pending(
        self,
        session: AsyncSession,
        strategy_id: Optional[str] = None,
    ) -> List[StrategySignalModel]:
        """Return signals with routing_status == 'PENDING'.

        Optionally filtered by strategy_id.
        """
        stmt = select(StrategySignalModel).where(
            StrategySignalModel.routing_status == "PENDING"
        )
        if strategy_id is not None:
            stmt = stmt.where(StrategySignalModel.strategy_id == strategy_id)
        stmt = stmt.order_by(StrategySignalModel.timestamp)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_strategy(
        self,
        session: AsyncSession,
        strategy_id: str,
    ) -> List[StrategySignalModel]:
        """Return all signals for a given strategy, ordered by timestamp."""
        result = await session.execute(
            select(StrategySignalModel)
            .where(StrategySignalModel.strategy_id == strategy_id)
            .order_by(StrategySignalModel.timestamp)
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        session: AsyncSession,
        strategy_id: Optional[str] = None,
    ) -> List[StrategySignalModel]:
        """Return all signals regardless of routing status.

        Used by the recovery manager to produce a full accounting of
        every signal seen during recovery — both pending and already-routed.
        Optionally filtered by strategy_id.
        """
        stmt = select(StrategySignalModel)
        if strategy_id is not None:
            stmt = stmt.where(StrategySignalModel.strategy_id == strategy_id)
        stmt = stmt.order_by(StrategySignalModel.timestamp)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_routing_status(
        self,
        session: AsyncSession,
        signal_id: UUID,
        routing_status: str,
        routed_client_order_id: Optional[str] = None,
        rejection_reason: Optional[str] = None,
    ) -> bool:
        """Update the routing status of a signal. Returns True if found."""
        values = {"routing_status": routing_status}
        if routed_client_order_id is not None:
            values["routed_client_order_id"] = routed_client_order_id
        if rejection_reason is not None:
            values["rejection_reason"] = rejection_reason

        result = await session.execute(
            update(StrategySignalModel)
            .where(StrategySignalModel.signal_id == signal_id)
            .values(values)
        )
        return result.rowcount > 0

    async def is_routed(
        self,
        session: AsyncSession,
        signal_id: UUID,
    ) -> bool:
        """Return True if the signal has already been routed (has a client_order_id)."""
        result = await session.execute(
            select(StrategySignalModel.routed_client_order_id).where(
                StrategySignalModel.signal_id == signal_id
            )
        )
        cid = result.scalar_one_or_none()
        return cid is not None

    # ------------------------------------------------------------------
    # Hydration helper
    # ------------------------------------------------------------------
    @staticmethod
    def _hydrate_signal(model: StrategySignalModel) -> Dict[str, Any]:
        """Serialize an ORM model to a plain dict suitable for domain reconstruction."""
        return {
            "signal_id": model.signal_id,
            "strategy_id": model.strategy_id,
            "account_id": model.account_id,
            "instrument_token": model.instrument_token,
            "action": model.action,
            "side": model.side,
            "quantity": model.quantity,
            "order_type": model.order_type,
            "limit_price": model.limit_price,
            "trigger_price": model.trigger_price,
            "timestamp": model.timestamp,
            "routing_status": model.routing_status,
            "routed_client_order_id": model.routed_client_order_id,
            "rejection_reason": model.rejection_reason,
            "extra_data": dict(model.extra_data) if model.extra_data else {},
        }
