"""StrategyRepository — session-injected CRUD for StrategyModel.

Follows the project-wide contract:
- AsyncSession is injected by the caller.
- No commit, rollback, or close — transaction ownership stays with the caller.
- Domain objects are hydrated without coupling ORM to domain contracts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import StrategyModel


class StrategyRepository:
    """Async repository for strategy persistence."""

    async def save(
        self,
        session: AsyncSession,
        strategy_id: str,
        strategy_type: str,
        name: str,
        account_id: Optional[str],
        configuration: Dict[str, Any],
        instrument_tokens: List[str],
        lifecycle_state: str,
        enabled: bool,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> StrategyModel:
        """Upsert a strategy record by strategy_id. Idempotent save."""
        now = datetime.now(timezone.utc)
        created_at = created_at or now
        updated_at = updated_at or now

        result = await session.execute(
            select(StrategyModel).where(StrategyModel.strategy_id == strategy_id)
        )
        existing: Optional[StrategyModel] = result.scalar_one_or_none()

        if existing is not None:
            existing.strategy_type = strategy_type
            existing.name = name
            existing.account_id = account_id
            existing.configuration = configuration
            existing.instrument_tokens = instrument_tokens
            existing.lifecycle_state = lifecycle_state
            existing.enabled = enabled
            existing.updated_at = updated_at
            return existing

        model = StrategyModel(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            name=name,
            account_id=account_id,
            configuration=configuration,
            instrument_tokens=instrument_tokens,
            lifecycle_state=lifecycle_state,
            enabled=enabled,
            created_at=created_at,
            updated_at=updated_at,
        )
        session.add(model)
        return model

    async def load(
        self,
        session: AsyncSession,
        strategy_id: str,
    ) -> Optional[StrategyModel]:
        """Load a single strategy by its natural key."""
        result = await session.execute(
            select(StrategyModel).where(StrategyModel.strategy_id == strategy_id)
        )
        return result.scalar_one_or_none()

    async def list_non_terminal(
        self,
        session: AsyncSession,
        terminal_states: Optional[List[str]] = None,
    ) -> List[StrategyModel]:
        """Return all strategies whose lifecycle_state is not terminal."""
        terminal_states = terminal_states or ["STOPPED", "ERROR"]
        result = await session.execute(
            select(StrategyModel).where(
                StrategyModel.lifecycle_state.notin_(terminal_states)
            )
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        session: AsyncSession,
    ) -> List[StrategyModel]:
        """Return every strategy record."""
        result = await session.execute(select(StrategyModel))
        return list(result.scalars().all())

    async def update_lifecycle_state(
        self,
        session: AsyncSession,
        strategy_id: str,
        lifecycle_state: str,
    ) -> bool:
        """Update the lifecycle_state of a strategy. Returns True if found."""
        result = await session.execute(
            update(StrategyModel)
            .where(StrategyModel.strategy_id == strategy_id)
            .values(lifecycle_state=lifecycle_state, updated_at=datetime.now(timezone.utc))
        )
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # Hydration helpers — decouple ORM from domain
    # ------------------------------------------------------------------
    @staticmethod
    def _hydrate_config(model: StrategyModel) -> Dict[str, Any]:
        """Reconstruct a StrategyConfig-compatible dict from an ORM row."""
        return {
            "strategy_id": model.strategy_id,
            "strategy_type": model.strategy_type,
            "name": model.name,
            "account_id": model.account_id,
            "configuration": dict(model.configuration) if model.configuration else {},
            "instrument_tokens": list(model.instrument_tokens) if model.instrument_tokens else [],
            "lifecycle_state": model.lifecycle_state,
            "enabled": model.enabled,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }
