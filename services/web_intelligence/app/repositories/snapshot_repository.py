"""Repository for raw snapshots."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import RawSnapshot
from app.repositories.orm_models import RawSnapshotORM


class SnapshotRepository:
    """Async repository for raw snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, snapshot_id: str) -> RawSnapshot | None:
        """Get snapshot metadata by ID."""
        result = await self._session.execute(
            select(RawSnapshotORM).where(RawSnapshotORM.id == snapshot_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def save(self, snapshot: RawSnapshot) -> None:
        """Save a raw snapshot."""
        orm = self._to_orm(snapshot)
        self._session.add(orm)
        await self._session.commit()

    def _to_domain(self, orm: RawSnapshotORM) -> RawSnapshot:
        return RawSnapshot(
            id=orm.id,
            source_id=orm.source_id,
            requested_url=orm.requested_url,
            canonical_url=orm.canonical_url,
            retrieved_at=orm.retrieved_at,
            http_status=orm.http_status,
            content_type=orm.content_type,
            content_hash=orm.content_hash,
            raw_content_location=orm.raw_content_location,
            response_headers=orm.response_headers or {},
            fetch_duration_ms=orm.fetch_duration_ms,
            parser_version=orm.parser_version,
            collection_run_id=orm.collection_run_id,
            data_quality_status=orm.data_quality_status,
            error_code=orm.error_code,
            error_message=orm.error_message,
        )

    def _to_orm(self, snapshot: RawSnapshot) -> RawSnapshotORM:
        return RawSnapshotORM(
            id=snapshot.id,
            source_id=snapshot.source_id,
            requested_url=snapshot.requested_url,
            canonical_url=snapshot.canonical_url,
            retrieved_at=snapshot.retrieved_at,
            http_status=snapshot.http_status,
            content_type=snapshot.content_type,
            content_hash=snapshot.content_hash,
            raw_content_location=snapshot.raw_content_location,
            response_headers=snapshot.response_headers,
            fetch_duration_ms=snapshot.fetch_duration_ms,
            parser_version=snapshot.parser_version,
            collection_run_id=snapshot.collection_run_id,
            data_quality_status=snapshot.data_quality_status,
            error_code=snapshot.error_code,
            error_message=snapshot.error_message,
        )
