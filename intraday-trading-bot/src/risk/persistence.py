"""
Risk state persistence adapters.

Follows the repository pattern: adapters wrap the RiskEngine and persist
state snapshots to PostgreSQL via the repository layer. No direct DB access.

Session is injected by caller — adapters never commit.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Any, Dict
from datetime import datetime

from .contracts import RiskStateSnapshot
from .engine import RiskEngine


class RiskEnginePersistenceAdapter:
    """Wraps RiskEngine and persists state snapshots to the database."""

    def __init__(self, engine: RiskEngine, repository: Optional[Any] = None):
        self._engine: RiskEngine = engine
        self._repository: Optional[Any] = repository

    async def pre_trade_check(self, *args, **kwargs) -> Any:
        result = await self._engine.pre_trade_check(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))
        return result

    async def post_trade_check(self, *args, **kwargs) -> Any:
        result = await self._engine.post_trade_check(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))
        return result

    async def record_fill(self, *args, **kwargs) -> None:
        await self._engine.record_fill(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))

    async def activate_kill_switch(self, *args, **kwargs) -> None:
        await self._engine.activate_kill_switch(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))

    async def deactivate_kill_switch(self, *args, **kwargs) -> None:
        await self._engine.deactivate_kill_switch(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))

    async def register_account(self, *args, **kwargs) -> None:
        await self._engine.register_account(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))

    async def reset_account(self, *args, **kwargs) -> None:
        await self._engine.reset_account(*args, **kwargs)
        account_id = args[0] if args else kwargs.get("account_id")
        await self._persist_state(account_id, kwargs.get("session"))

    async def load_state(self, account_id: str, session: Optional[Any] = None) -> Optional[RiskStateSnapshot]:
        if self._repository is None or session is None:
            return None
        return await self._repository.load_latest(account_id, session)

    async def restore_state(self, account_id: str, session: Optional[Any] = None) -> None:
        snapshot = await self.load_state(account_id, session)
        if snapshot is not None:
            from .state import RiskState
            state = RiskState.from_snapshot(snapshot)
            self._engine._states[account_id] = state

    async def _persist_state(self, account_id: Optional[str], session: Optional[Any]) -> None:
        if account_id is None or session is None or self._repository is None:
            return
        state = self._engine._states.get(account_id)
        if state is None:
            return
        snapshot = state.to_snapshot(datetime.utcnow())
        await self._repository.save(snapshot, session)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)
