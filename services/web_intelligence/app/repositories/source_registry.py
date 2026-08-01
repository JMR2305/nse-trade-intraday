"""Approved source registry with database persistence."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import SourceType
from app.domain.models import ApprovedSource
from app.logging import get_logger
from app.repositories.orm_models import ApprovedSourceORM

logger = get_logger(__name__)


class SourceRegistry:
    """Registry of approved intelligence sources with DB persistence."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session
        self._sources: dict[str, ApprovedSource] = {}

    def register(self, source: ApprovedSource) -> None:
        """Register an approved source in memory."""
        self._sources[source.id] = source

    def get(self, source_id: str) -> ApprovedSource | None:
        """Get a source by ID."""
        return self._sources.get(source_id)

    def list_all(self) -> list[ApprovedSource]:
        """List all registered sources."""
        return list(self._sources.values())

    def list_enabled(self) -> list[ApprovedSource]:
        """List only enabled sources."""
        return [s for s in self._sources.values() if s.enabled]

    async def disable(self, source_id: str) -> bool:
        """Disable a source. Upserts to DB if session available. Returns True if found."""
        src = self._sources.get(source_id)
        if src is None:
            return False
        updated = src.model_copy(update={"enabled": False, "updated_at": datetime.utcnow()})
        self._sources[source_id] = updated

        if self._session:
            await self._upsert_enabled(source_id, enabled=0)

        return True

    async def enable(self, source_id: str) -> bool:
        """Enable a source. Upserts to DB if session available. Returns True if found."""
        src = self._sources.get(source_id)
        if src is None:
            return False
        updated = src.model_copy(update={"enabled": True, "updated_at": datetime.utcnow()})
        self._sources[source_id] = updated

        if self._session:
            await self._upsert_enabled(source_id, enabled=1)

        return True

    async def _upsert_enabled(self, source_id: str, *, enabled: int) -> None:
        """Persist the enabled/disabled state to the DB.

        If the source is a default (not yet in the DB), it is inserted so
        subsequent restarts load the correct state via sync_from_db().
        """
        src = self._sources.get(source_id)
        if src is None or self._session is None:
            return
        result = await self._session.execute(
            select(ApprovedSourceORM).where(ApprovedSourceORM.id == source_id)
        )
        orm = result.scalar_one_or_none()
        if orm:
            orm.enabled = enabled
            orm.updated_at = datetime.utcnow()
        else:
            # Default source not yet in DB — insert it so state persists across restarts
            orm = ApprovedSourceORM(
                id=src.id,
                name=src.name,
                base_url=src.base_url,
                source_type=src.source_type,
                enabled=enabled,
                robots_policy=src.robots_policy or "",
                request_interval_seconds=src.request_interval_seconds,
                maximum_requests_per_hour=src.maximum_requests_per_hour,
                user_agent=src.user_agent,
                parser_name=src.parser_name,
                created_at=src.created_at,
                updated_at=datetime.utcnow(),
            )
            self._session.add(orm)
        await self._session.commit()
        logger.info(
            "source_enabled_state_persisted",
            source_id=source_id,
            enabled=bool(enabled),
        )

    async def sync_from_db(self) -> None:
        """Load all persisted sources from the database into the in-memory registry.

        Overwrites any in-memory entry for the same ID so the DB is always the
        authority on source state after startup.
        """
        if not self._session:
            return
        result = await self._session.execute(select(ApprovedSourceORM))
        for orm in result.scalars().all():
            source = ApprovedSource(
                id=orm.id,
                name=orm.name,
                base_url=orm.base_url,
                source_type=orm.source_type,
                enabled=bool(orm.enabled),
                robots_policy=orm.robots_policy,
                request_interval_seconds=orm.request_interval_seconds,
                maximum_requests_per_hour=orm.maximum_requests_per_hour,
                user_agent=orm.user_agent,
                parser_name=orm.parser_name,
                created_at=orm.created_at,
                updated_at=orm.updated_at,
            )
            self._sources[orm.id] = source
        logger.info("source_registry_synced_from_db", count=len(self._sources))

    def clear(self) -> None:
        """Clear all sources (mainly for tests)."""
        self._sources.clear()


def create_default_registry(session: AsyncSession | None = None) -> SourceRegistry:
    """Create a registry pre-loaded with default POC sources.

    Default sources are registered in memory only.  They are intentionally NOT
    written to the database here — ``sync_from_db()`` must be called
    afterwards to overlay any operator-persisted rows on top of the defaults.
    If operator rows exist for the same IDs, ``sync_from_db`` will overwrite
    the in-memory defaults with the persisted state (preserving operator
    enabled/disabled choices across restarts).
    """
    registry = SourceRegistry(session=session)

    registry.register(
        ApprovedSource(
            id="generic_test_page",
            name="Generic Approved Static Page Test Source",
            base_url="https://example.com/apexquant-test",
            source_type=SourceType.GENERIC_STATIC_PAGE,
            enabled=True,
            robots_policy="allow",
            request_interval_seconds=5.0,
            maximum_requests_per_hour=60,
            user_agent="ApexQuant-WebIntelligence/0.1.0 (+https://apexquant.ai/bot)",
            parser_name="generic_static_parser",
        )
    )

    registry.register(
        ApprovedSource(
            id="local_fixture_source",
            name="Local HTML Fixture Source",
            base_url="file://tests/fixtures",
            source_type=SourceType.LOCAL_HTML_FIXTURE,
            enabled=True,
            robots_policy="allow",
            request_interval_seconds=0.1,
            maximum_requests_per_hour=10000,
            user_agent="ApexQuant-WebIntelligence-Test/0.1.0",
            parser_name="fixture_parser",
        )
    )

    return registry
