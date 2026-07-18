"""Trading session repository."""

from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc

from src.database.models import TradingSession


class SessionRepository:
    """Repository for trading_sessions table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_session_id(self, session_id: str) -> Optional[TradingSession]:
        """Get session by session_id."""
        result = await self._session.execute(
            select(TradingSession).where(TradingSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Optional[TradingSession]:
        """Get session by idempotency key."""
        result = await self._session.execute(
            select(TradingSession).where(TradingSession.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get_active_session(self) -> Optional[TradingSession]:
        """Get the single active session (not ended)."""
        result = await self._session.execute(
            select(TradingSession)
            .where(TradingSession.ended_at.is_(None))
            .order_by(desc(TradingSession.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> List[TradingSession]:
        """Get all sessions that have not ended."""
        result = await self._session.execute(
            select(TradingSession).where(TradingSession.ended_at.is_(None))
        )
        return list(result.scalars().all())

    async def get_last_session(self) -> Optional[TradingSession]:
        """Get the most recently created session."""
        result = await self._session.execute(
            select(TradingSession).order_by(desc(TradingSession.created_at)).limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> TradingSession:
        """Create a new trading session."""
        session = TradingSession(**kwargs)
        self._session.add(session)
        await self._session.flush()
        await self._session.refresh(session)
        return session

    async def update(self, session_id: str, **kwargs) -> Optional[TradingSession]:
        """Update session fields."""
        kwargs["updated_at"] = datetime.now(timezone.utc)
        await self._session.execute(
            update(TradingSession)
            .where(TradingSession.session_id == session_id)
            .values(**kwargs)
        )
        return await self.get_by_session_id(session_id)

    async def end_session(self, session_id: str) -> Optional[TradingSession]:
        """Mark session as ended."""
        return await self.update(
            session_id,
            status="CLOSED",
            ended_at=datetime.now(timezone.utc),
        )
