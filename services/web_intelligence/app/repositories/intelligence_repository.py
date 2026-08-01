"""Repository for intelligence records."""
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import IntelligenceRecord
from app.repositories.orm_models import IntelligenceRecordORM


class IntelligenceRepository:
    """Async repository for intelligence records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, record_id: str) -> IntelligenceRecord | None:
        """Get a record by ID."""
        result = await self._session.execute(
            select(IntelligenceRecordORM).where(IntelligenceRecordORM.id == record_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def list_records(
        self,
        *,
        source_id: str | None = None,
        record_type: str | None = None,
        validation_status: str | None = None,
        data_quality_status: str | None = None,
        confidence_status: str | None = None,
        first_seen_after: datetime | None = None,
        first_seen_before: datetime | None = None,
        last_seen_after: datetime | None = None,
        last_seen_before: datetime | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[IntelligenceRecord], int]:
        """List records with filters and pagination. Returns (records, total_count)."""
        query = select(IntelligenceRecordORM)

        def _apply_filters(q: Any) -> Any:
            if source_id:
                q = q.where(IntelligenceRecordORM.source_id == source_id)
            if record_type:
                q = q.where(IntelligenceRecordORM.record_type == record_type)
            if validation_status:
                q = q.where(IntelligenceRecordORM.validation_status == validation_status)
            if data_quality_status:
                q = q.where(IntelligenceRecordORM.data_quality_status == data_quality_status)
            if confidence_status:
                q = q.where(IntelligenceRecordORM.confidence_status == confidence_status)
            if first_seen_after:
                q = q.where(IntelligenceRecordORM.first_seen_at >= first_seen_after)
            if first_seen_before:
                q = q.where(IntelligenceRecordORM.first_seen_at <= first_seen_before)
            if last_seen_after:
                q = q.where(IntelligenceRecordORM.last_seen_at >= last_seen_after)
            if last_seen_before:
                q = q.where(IntelligenceRecordORM.last_seen_at <= last_seen_before)
            if published_after:
                q = q.where(IntelligenceRecordORM.published_at >= published_after)
            if published_before:
                q = q.where(IntelligenceRecordORM.published_at <= published_before)
            return q

        query = _apply_filters(query)

        # Efficient COUNT using SELECT COUNT(*) — never loads all rows into memory
        count_query = _apply_filters(
            select(func.count()).select_from(IntelligenceRecordORM)
        )
        count_result = await self._session.execute(count_query)
        total = count_result.scalar_one()

        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        records = [self._to_domain(r) for r in result.scalars().all()]
        return records, total

    async def save(self, record: IntelligenceRecord) -> None:
        """Save or update an intelligence record."""
        orm = self._to_orm(record)
        await self._session.merge(orm)
        await self._session.commit()

    async def update_last_seen(self, record_id: str, snapshot_id: str, content_hash: str, data_quality_status: str) -> None:
        """Update last_seen_at for an existing record when content changes."""
        result = await self._session.execute(
            select(IntelligenceRecordORM).where(IntelligenceRecordORM.id == record_id)
        )
        orm = result.scalar_one_or_none()
        if orm:
            orm.last_seen_at = datetime.utcnow()
            orm.raw_snapshot_id = snapshot_id
            orm.content_hash = content_hash
            orm.data_quality_status = data_quality_status
            await self._session.commit()

    async def find_duplicate(
        self,
        canonical_url: str,
        title: str,
        source_reference: str,
        content_hash: str,
        source_id: str | None = None,
    ) -> IntelligenceRecord | None:
        """Find a potential duplicate record scoped to the same source.

        All three lookup branches are scoped by ``source_id`` when provided so
        that collisions across different approved sources can never silently
        suppress each other's records.
        """
        # Priority: source_reference exact match, then content_hash, then canonical_url+title
        if source_reference:
            q = select(IntelligenceRecordORM).where(
                IntelligenceRecordORM.source_reference == source_reference
            )
            if source_id:
                q = q.where(IntelligenceRecordORM.source_id == source_id)
            result = await self._session.execute(q)
            orm = result.scalar_one_or_none()
            if orm:
                return self._to_domain(orm)

        q = select(IntelligenceRecordORM).where(
            IntelligenceRecordORM.content_hash == content_hash
        )
        if source_id:
            q = q.where(IntelligenceRecordORM.source_id == source_id)
        result = await self._session.execute(q)
        orm = result.scalar_one_or_none()
        if orm:
            return self._to_domain(orm)

        q = select(IntelligenceRecordORM).where(
            IntelligenceRecordORM.canonical_url == canonical_url,
            IntelligenceRecordORM.title == title,
        )
        if source_id:
            q = q.where(IntelligenceRecordORM.source_id == source_id)
        result = await self._session.execute(q)
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    def _to_domain(self, orm: IntelligenceRecordORM) -> IntelligenceRecord:
        return IntelligenceRecord(
            id=orm.id,
            source_id=orm.source_id,
            record_type=orm.record_type,
            title=orm.title,
            summary=orm.summary,
            published_at=orm.published_at,
            effective_at=orm.effective_at,
            canonical_url=orm.canonical_url,
            source_reference=orm.source_reference,
            content_hash=orm.content_hash,
            raw_snapshot_id=orm.raw_snapshot_id,
            confidence_status=orm.confidence_status,
            validation_status=orm.validation_status,
            data_quality_status=orm.data_quality_status,
            parser_version=orm.parser_version,
            first_seen_at=orm.first_seen_at,
            last_seen_at=orm.last_seen_at,
            metadata=orm.metadata_ or {},
        )

    def _to_orm(self, record: IntelligenceRecord) -> IntelligenceRecordORM:
        return IntelligenceRecordORM(
            id=record.id,
            source_id=record.source_id,
            record_type=record.record_type,
            title=record.title,
            summary=record.summary,
            published_at=record.published_at,
            effective_at=record.effective_at,
            canonical_url=record.canonical_url,
            source_reference=record.source_reference,
            content_hash=record.content_hash,
            raw_snapshot_id=record.raw_snapshot_id,
            confidence_status=record.confidence_status,
            validation_status=record.validation_status,
            data_quality_status=getattr(record, "data_quality_status", "unknown"),
            parser_version=record.parser_version,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            metadata=record.metadata,
        )
