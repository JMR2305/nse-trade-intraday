"""Incident repository."""

from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc

from src.database.models import Incident


class IncidentRepository:
    """Repository for incidents table operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, incident_id: int) -> Optional[Incident]:
        """Get incident by ID."""
        result = await self._session.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        return result.scalar_one_or_none()

    async def get_by_session(self, session_id: str, status: Optional[str] = None) -> List[Incident]:
        """Get incidents for a session."""
        query = select(Incident).where(Incident.session_id == session_id)
        if status:
            query = query.where(Incident.status == status)
        query = query.order_by(desc(Incident.created_at))
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_open_incidents(self) -> List[Incident]:
        """Get all unresolved incidents."""
        result = await self._session.execute(
            select(Incident)
            .where(Incident.status.in_(["OPEN", "INVESTIGATING"]))
            .order_by(desc(Incident.created_at))
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> Incident:
        """Create a new incident."""
        incident = Incident(**kwargs)
        self._session.add(incident)
        await self._session.flush()
        await self._session.refresh(incident)
        return incident

    async def resolve(
        self, incident_id: int, resolved_by: str, notes: Optional[str] = None
    ) -> Optional[Incident]:
        """Resolve an incident."""
        kwargs = {
            "status": "RESOLVED",
            "resolved_at": datetime.now(timezone.utc),
            "resolved_by": resolved_by,
        }
        if notes:
            kwargs["resolution_notes"] = notes

        await self._session.execute(
            update(Incident).where(Incident.id == incident_id).values(**kwargs)
        )
        return await self.get_by_id(incident_id)
