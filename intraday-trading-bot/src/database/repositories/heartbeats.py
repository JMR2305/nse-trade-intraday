"""System heartbeat repository."""

from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.database.models import SystemHeartbeat


class HeartbeatRepository:
    """Repository for system_heartbeats table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_service(self, service_name: str) -> Optional[SystemHeartbeat]:
        """Get heartbeat for a service."""
        result = await self._session.execute(
            select(SystemHeartbeat).where(SystemHeartbeat.service_name == service_name)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> List[SystemHeartbeat]:
        """Get all heartbeats."""
        result = await self._session.execute(select(SystemHeartbeat))
        return list(result.scalars().all())

    async def get_unhealthy(self) -> List[SystemHeartbeat]:
        """Get all unhealthy services."""
        result = await self._session.execute(
            select(SystemHeartbeat).where(SystemHeartbeat.status != "HEALTHY")
        )
        return list(result.scalars().all())

    async def upsert(self, service_name: str, status: str = "HEALTHY") -> SystemHeartbeat:
        """Create or update heartbeat for a service."""
        existing = await self.get_by_service(service_name)
        if existing:
            await self._session.execute(
                update(SystemHeartbeat)
                .where(SystemHeartbeat.service_name == service_name)
                .values(
                    last_beat=datetime.now(timezone.utc),
                    status=status,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return await self.get_by_service(service_name)

        heartbeat = SystemHeartbeat(
            service_name=service_name,
            last_beat=datetime.now(timezone.utc),
            status=status,
        )
        self._session.add(heartbeat)
        await self._session.flush()
        await self._session.refresh(heartbeat)
        return heartbeat

    async def record_failure(self, service_name: str) -> Optional[SystemHeartbeat]:
        """Record a failure for a service."""
        existing = await self.get_by_service(service_name)
        if not existing:
            return await self.upsert(service_name, status="UNHEALTHY")

        await self._session.execute(
            update(SystemHeartbeat)
            .where(SystemHeartbeat.service_name == service_name)
            .values(
                last_beat=datetime.now(timezone.utc),
                status="UNHEALTHY",
                consecutive_failures=SystemHeartbeat.consecutive_failures + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return await self.get_by_service(service_name)

    async def record_success(self, service_name: str) -> Optional[SystemHeartbeat]:
        """Record success for a service."""
        existing = await self.get_by_service(service_name)
        if not existing:
            return await self.upsert(service_name, status="HEALTHY")

        await self._session.execute(
            update(SystemHeartbeat)
            .where(SystemHeartbeat.service_name == service_name)
            .values(
                last_beat=datetime.now(timezone.utc),
                status="HEALTHY",
                consecutive_failures=0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return await self.get_by_service(service_name)
