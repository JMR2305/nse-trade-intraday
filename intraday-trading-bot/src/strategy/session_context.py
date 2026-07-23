"""SessionContext — scoped AsyncSession with automatic commit / rollback.

Opens exactly one AsyncSession per context block.
  - Commits on clean exit.
  - Rolls back *and* closes on any exception (exception is re-raised).
  - Session is always closed regardless of outcome.

Repositories and adapters must NEVER call session.commit(), session.rollback(),
or session.close().  That responsibility belongs exclusively here.

Usage::

    async with SessionContext(engine) as session:
        await adapter.save_strategy(session, record)
        await adapter.save_signal(session, signal_record)
        # commit fires automatically in __aexit__
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = logging.getLogger(__name__)


class SessionContext:
    """Async context manager that owns exactly one database transaction.

    Parameters
    ----------
    engine:
        The SQLAlchemy async engine to open a session against.
    """

    __slots__ = ("_engine", "_session")

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine: AsyncEngine = engine
        self._session: Optional[AsyncSession] = None

    async def __aenter__(self) -> AsyncSession:
        self._session = AsyncSession(self._engine, expire_on_commit=False)
        return self._session

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
