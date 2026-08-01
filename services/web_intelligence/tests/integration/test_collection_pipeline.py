"""Integration test for full collection pipeline with fixtures."""
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.fetch_client import FetchClient
from app.domain.enums import CollectionRunStatus, SourceType
from app.domain.models import ApprovedSource
from app.parsers.base_parser import ParserRegistry
from app.parsers.fixture_parser import FixtureParser
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.database import Base
from app.repositories.intelligence_repository import IntelligenceRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.orm_models import ApprovedSourceORM, CollectionRunORM, IntelligenceRecordORM, RawSnapshotORM  # noqa: F401 — ensure ORM classes are registered
from app.services.collection import CollectionService
from app.services.deduplication import DeduplicationService
from app.storage.snapshot_storage import SnapshotStorage


@pytest.fixture
async def db_session():
    """Fresh isolated in-memory SQLite DB per test — no shared state between tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with _Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_fixture_collection_pipeline(db_session):
    """Test full collection pipeline using local HTML fixture."""
    session = db_session
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_fixture.html"
    source = ApprovedSource(
        id="test_fixture",
        name="Test Fixture Source",
        base_url=f"file://{fixture_path}",
        source_type=SourceType.LOCAL_HTML_FIXTURE,
        enabled=True,
        user_agent="Test/1.0",
        parser_name="fixture_parser",
        request_interval_seconds=0.1,
        maximum_requests_per_hour=10000,
    )

    parser_registry = ParserRegistry()
    parser_registry.register(FixtureParser())

    snapshot_repo = SnapshotRepository(session)
    intelligence_repo = IntelligenceRepository(session)
    run_repo = CollectionRunRepository(session)
    dedup = DeduplicationService(intelligence_repo)
    storage = SnapshotStorage()
    fetch_client = FetchClient()

    service = CollectionService(
        fetch_client=fetch_client,
        parser_registry=parser_registry,
        snapshot_repo=snapshot_repo,
        intelligence_repo=intelligence_repo,
        run_repo=run_repo,
        dedup_service=dedup,
        storage=storage,
    )

    run = await service.collect_source(source)
    assert run.status == CollectionRunStatus.COMPLETED
    assert run.pages_succeeded == 1
    assert run.records_extracted == 2


@pytest.mark.asyncio
async def test_idempotent_repeated_collection(db_session):
    """Test that repeated collection of same fixture is idempotent."""
    session = db_session
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_fixture.html"
    source = ApprovedSource(
        id="test_fixture_idempotent",
        name="Test Fixture Source",
        base_url=f"file://{fixture_path}",
        source_type=SourceType.LOCAL_HTML_FIXTURE,
        enabled=True,
        user_agent="Test/1.0",
        parser_name="fixture_parser",
        request_interval_seconds=0.1,
        maximum_requests_per_hour=10000,
    )

    parser_registry = ParserRegistry()
    parser_registry.register(FixtureParser())

    snapshot_repo = SnapshotRepository(session)
    intelligence_repo = IntelligenceRepository(session)
    run_repo = CollectionRunRepository(session)
    dedup = DeduplicationService(intelligence_repo)
    storage = SnapshotStorage()
    fetch_client = FetchClient()

    service = CollectionService(
        fetch_client=fetch_client,
        parser_registry=parser_registry,
        snapshot_repo=snapshot_repo,
        intelligence_repo=intelligence_repo,
        run_repo=run_repo,
        dedup_service=dedup,
        storage=storage,
    )

    run1 = await service.collect_source(source)
    run2 = await service.collect_source(source)

    assert run1.status == CollectionRunStatus.COMPLETED
    assert run2.status == CollectionRunStatus.COMPLETED
    assert run2.duplicates_ignored == run1.records_inserted
