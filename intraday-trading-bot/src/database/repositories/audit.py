"""Audit log repository."""

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from src.database.models import AuditLog


class AuditRepository:
    """Repository for audit_logs table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, audit_id: int) -> Optional[AuditLog]:
        """Get audit log by ID."""
        result = await self._session.execute(
            select(AuditLog).where(AuditLog.id == audit_id)
        )
        return result.scalar_one_or_none()

    async def get_by_table(self, table_name: str, limit: int = 100) -> List[AuditLog]:
        """Get audit logs for a table."""
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.table_name == table_name)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_record(self, table_name: str, record_id: str) -> List[AuditLog]:
        """Get audit logs for a specific record."""
        result = await self._session.execute(
            select(AuditLog)
            .where(
                AuditLog.table_name == table_name,
                AuditLog.record_id == record_id,
            )
            .order_by(desc(AuditLog.created_at))
        )
        return list(result.scalars().all())

    async def get_by_actor(self, actor: str, limit: int = 100) -> List[AuditLog]:
        """Get audit logs by actor."""
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.actor == actor)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> AuditLog:
        """Create a new audit log entry."""
        log = AuditLog(**kwargs)
        self._session.add(log)
        await self._session.flush()
        await self._session.refresh(log)
        return log
