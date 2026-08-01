"""Repository for collection runs."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CollectionRun
from app.repositories.orm_models import CollectionRunORM


class CollectionRunRepository:
    """Async repository for collection runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, run_id: str) -> CollectionRun | None:
        """Get a collection run by ID."""
        result = await self._session.execute(
            select(CollectionRunORM).where(CollectionRunORM.id == run_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def list_runs(
        self,
        source_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[CollectionRun], int]:
        """List collection runs with optional source filter."""
        query = select(CollectionRunORM)
        if source_id:
            query = query.where(CollectionRunORM.source_id == source_id)

        total_result = await self._session.execute(query)
        total = len(total_result.scalars().all())

        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        runs = [self._to_domain(r) for r in result.scalars().all()]
        return runs, total

    async def save(self, run: CollectionRun) -> None:
        """Save or update a collection run."""
        orm = self._to_orm(run)
        await self._session.merge(orm)
        await self._session.commit()

    async def update_status(
        self,
        run_id: str,
        status: str,
        completed_at: datetime | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """Update run status."""
        result = await self._session.execute(
            select(CollectionRunORM).where(CollectionRunORM.id == run_id)
        )
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = status
            if completed_at:
                orm.completed_at = completed_at
            if failure_reason:
                orm.failure_reason = failure_reason
            await self._session.commit()

    def _to_domain(self, orm: CollectionRunORM) -> CollectionRun:
        return CollectionRun(
            id=orm.id,
            source_id=orm.source_id,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
            status=orm.status,
            pages_requested=orm.pages_requested,
            pages_succeeded=orm.pages_succeeded,
            pages_failed=orm.pages_failed,
            records_extracted=orm.records_extracted,
            records_inserted=orm.records_inserted,
            records_updated=orm.records_updated,
            duplicates_ignored=orm.duplicates_ignored,
            failure_reason=orm.failure_reason,
        )

    def _to_orm(self, run: CollectionRun) -> CollectionRunORM:
        return CollectionRunORM(
            id=run.id,
            source_id=run.source_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status,
            pages_requested=run.pages_requested,
            pages_succeeded=run.pages_succeeded,
            pages_failed=run.pages_failed,
            records_extracted=run.records_extracted,
            records_inserted=run.records_inserted,
            records_updated=run.records_updated,
            duplicates_ignored=run.duplicates_ignored,
            failure_reason=run.failure_reason,
        )
