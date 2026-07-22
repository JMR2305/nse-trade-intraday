"""StrategyPersistenceAdapter — bridges strategy runtime to DB repositories.

This module provides thin adapters that persist strategy state, signals, and
snapshots to PostgreSQL via the repository layer.  It does NOT modify any
frozen strategy engine internals; it only hooks into the public APIs.

Design principles:
- Session is injected by the caller (service layer / coordinator).
- No commit / rollback / close — transaction ownership stays with the caller.
- Idempotent saves — repeated calls with the same IDs are safe.
- Domain contracts (strategy/contracts.py) are never imported by ORM code.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.repositories.strategy import StrategyRepository
from src.database.repositories.strategy_signal import StrategySignalRepository
from src.database.repositories.strategy_state import StrategyStateRepository

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Domain-friendly data transfer objects (decoupled from ORM)
# ------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyConfigRecord:
    """Plain dataclass representing a strategy record for persistence."""
    strategy_id: str
    strategy_type: str
    name: str
    account_id: Optional[str]
    configuration: Dict[str, Any]
    instrument_tokens: List[str]
    lifecycle_state: str
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class StrategySignalRecord:
    """Plain dataclass representing a strategy signal for persistence."""
    signal_id: UUID
    strategy_id: str
    account_id: Optional[str]
    instrument_token: str
    action: str
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Optional[Decimal]
    trigger_price: Optional[Decimal]
    timestamp: datetime
    routing_status: str = "PENDING"
    routed_client_order_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyStateSnapshotRecord:
    """Plain dataclass representing a strategy state snapshot for persistence."""
    strategy_id: str
    lifecycle_state: str
    pending_order_ids: List[str] = field(default_factory=list)
    latest_signal_timestamp: Optional[datetime] = None
    emitted_signal_count: int = 0
    routed_signal_count: int = 0
    rejected_signal_count: int = 0
    fill_count: int = 0
    extra_data: Dict[str, Any] = field(default_factory=dict)
    snapshot_timestamp: Optional[datetime] = None


# ------------------------------------------------------------------
# Persistence Adapter
# ------------------------------------------------------------------

class StrategyPersistenceAdapter:
    """Adapter that persists strategy runtime state to the database.

    Usage:
        adapter = StrategyPersistenceAdapter()
        await adapter.save_strategy(session, config_record)
        await adapter.save_signal(session, signal_record)
        await adapter.save_state_snapshot(session, snapshot_record)
    """

    def __init__(
        self,
        strategy_repo: Optional[StrategyRepository] = None,
        signal_repo: Optional[StrategySignalRepository] = None,
        state_repo: Optional[StrategyStateRepository] = None,
    ) -> None:
        self._strategy_repo = strategy_repo or StrategyRepository()
        self._signal_repo = signal_repo or StrategySignalRepository()
        self._state_repo = state_repo or StrategyStateRepository()

    # ------------------------------------------------------------------
    # Strategy record persistence
    # ------------------------------------------------------------------
    async def save_strategy(
        self,
        session: AsyncSession,
        record: StrategyConfigRecord,
    ) -> None:
        """Persist (upsert) a strategy registration record. Idempotent."""
        await self._strategy_repo.save(
            session=session,
            strategy_id=record.strategy_id,
            strategy_type=record.strategy_type,
            name=record.name,
            account_id=record.account_id,
            configuration=record.configuration,
            instrument_tokens=record.instrument_tokens,
            lifecycle_state=record.lifecycle_state,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        logger.debug("Persisted strategy %s", record.strategy_id)

    async def load_strategy(
        self,
        session: AsyncSession,
        strategy_id: str,
    ) -> Optional[StrategyConfigRecord]:
        """Load a strategy record and return a domain-friendly dataclass."""
        model = await self._strategy_repo.load(session, strategy_id)
        if model is None:
            return None
        data = StrategyRepository._hydrate_config(model)
        return StrategyConfigRecord(**data)

    async def list_non_terminal_strategies(
        self,
        session: AsyncSession,
        terminal_states: Optional[List[str]] = None,
    ) -> List[StrategyConfigRecord]:
        """Return all non-terminal strategy records as dataclasses."""
        models = await self._strategy_repo.list_non_terminal(
            session, terminal_states=terminal_states
        )
        return [StrategyConfigRecord(**StrategyRepository._hydrate_config(m)) for m in models]

    # ------------------------------------------------------------------
    # Signal persistence
    # ------------------------------------------------------------------
    async def save_signal(
        self,
        session: AsyncSession,
        record: StrategySignalRecord,
    ) -> None:
        """Persist (upsert) a strategy signal. Idempotent by signal_id."""
        await self._signal_repo.save(
            session=session,
            signal_id=record.signal_id,
            strategy_id=record.strategy_id,
            account_id=record.account_id,
            instrument_token=record.instrument_token,
            action=record.action,
            side=record.side,
            quantity=record.quantity,
            order_type=record.order_type,
            limit_price=record.limit_price,
            trigger_price=record.trigger_price,
            timestamp=record.timestamp,
            routing_status=record.routing_status,
            routed_client_order_id=record.routed_client_order_id,
            rejection_reason=record.rejection_reason,
            extra_data=record.extra_data,
        )
        logger.debug("Persisted signal %s", record.signal_id)

    async def load_signal(
        self,
        session: AsyncSession,
        signal_id: UUID,
    ) -> Optional[StrategySignalRecord]:
        """Load a signal record and return a domain-friendly dataclass."""
        model = await self._signal_repo.load(session, signal_id)
        if model is None:
            return None
        data = StrategySignalRepository._hydrate_signal(model)
        return StrategySignalRecord(**data)

    async def list_pending_signals(
        self,
        session: AsyncSession,
        strategy_id: Optional[str] = None,
    ) -> List[StrategySignalRecord]:
        """Return pending signals as dataclasses."""
        models = await self._signal_repo.list_pending(session, strategy_id=strategy_id)
        return [
            StrategySignalRecord(**StrategySignalRepository._hydrate_signal(m))
            for m in models
        ]

    async def list_all_signals(
        self,
        session: AsyncSession,
        strategy_id: Optional[str] = None,
    ) -> List[StrategySignalRecord]:
        """Return all signals regardless of routing status.

        Used by the recovery manager to account for every signal seen
        during recovery — both pending (to re-queue) and already-routed
        (to skip and count). Optionally filtered by strategy_id.
        """
        models = await self._signal_repo.list_all(session, strategy_id=strategy_id)
        return [
            StrategySignalRecord(**StrategySignalRepository._hydrate_signal(m))
            for m in models
        ]

    async def mark_signal_routed(
        self,
        session: AsyncSession,
        signal_id: UUID,
        client_order_id: str,
    ) -> bool:
        """Mark a signal as routed with its assigned client_order_id."""
        return await self._signal_repo.update_routing_status(
            session=session,
            signal_id=signal_id,
            routing_status="ROUTED",
            routed_client_order_id=client_order_id,
        )

    async def mark_signal_rejected(
        self,
        session: AsyncSession,
        signal_id: UUID,
        reason: str,
    ) -> bool:
        """Mark a signal as rejected with a reason."""
        return await self._signal_repo.update_routing_status(
            session=session,
            signal_id=signal_id,
            routing_status="REJECTED",
            rejection_reason=reason,
        )

    async def is_signal_routed(
        self,
        session: AsyncSession,
        signal_id: UUID,
    ) -> bool:
        """Return True if the signal has already been routed."""
        return await self._signal_repo.is_routed(session, signal_id)

    # ------------------------------------------------------------------
    # State snapshot persistence
    # ------------------------------------------------------------------
    async def save_state_snapshot(
        self,
        session: AsyncSession,
        record: StrategyStateSnapshotRecord,
    ) -> None:
        """Persist a new strategy state snapshot. Append-only."""
        await self._state_repo.save(
            session=session,
            strategy_id=record.strategy_id,
            lifecycle_state=record.lifecycle_state,
            pending_order_ids=record.pending_order_ids,
            latest_signal_timestamp=record.latest_signal_timestamp,
            emitted_signal_count=record.emitted_signal_count,
            routed_signal_count=record.routed_signal_count,
            rejected_signal_count=record.rejected_signal_count,
            fill_count=record.fill_count,
            extra_data=record.extra_data,
            snapshot_timestamp=record.snapshot_timestamp,
        )
        logger.debug("Persisted state snapshot for %s", record.strategy_id)

    async def load_latest_state_snapshot(
        self,
        session: AsyncSession,
        strategy_id: str,
    ) -> Optional[StrategyStateSnapshotRecord]:
        """Load the latest state snapshot for a strategy."""
        model = await self._state_repo.load_latest(session, strategy_id)
        if model is None:
            return None
        data = StrategyStateRepository._hydrate_snapshot(model)
        return StrategyStateSnapshotRecord(**data)
