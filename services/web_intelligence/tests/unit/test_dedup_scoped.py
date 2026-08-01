"""Tests for source-scoped deduplication (defect F fix).

These tests use a real SQLite in-memory database so the WHERE clause
filtering is actually executed.
"""
import pytest
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.domain.enums import ConfidenceStatus, DataQualityStatus, RecordType, ValidationStatus
from app.domain.models import IntelligenceRecord
from app.repositories.database import Base
from app.repositories.intelligence_repository import IntelligenceRepository
from app.repositories.orm_models import IntelligenceRecordORM


# ---------------------------------------------------------------------------
# Per-test in-memory SQLite fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def mem_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _orm_record(
    record_id: str,
    source_id: str,
    source_reference: str = "ref-1",
    content_hash: str = "abc123",
    canonical_url: str = "https://example.com/a",
    title: str = "Test",
) -> IntelligenceRecordORM:
    return IntelligenceRecordORM(
        id=record_id,
        source_id=source_id,
        record_type=RecordType.GENERIC,
        title=title,
        summary="Summary",
        canonical_url=canonical_url,
        source_reference=source_reference,
        content_hash=content_hash,
        raw_snapshot_id="snap-1",
        confidence_status=ConfidenceStatus.MEDIUM,
        validation_status=ValidationStatus.PENDING,
        data_quality_status=DataQualityStatus.VALID,
        parser_version="1.0",
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Cross-source isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_source_same_reference_not_a_duplicate(mem_session):
    """Same source_reference from a different source must NOT be detected as a duplicate."""
    # Insert a record for source-a
    mem_session.add(_orm_record("r-a", "source-a", source_reference="ref-1"))
    await mem_session.commit()

    repo = IntelligenceRepository(mem_session)

    # Look up for source-b — must NOT match source-a's row
    result = await repo.find_duplicate(
        canonical_url="https://example.com/a",
        title="Test",
        source_reference="ref-1",
        content_hash="abc123",
        source_id="source-b",
    )
    assert result is None, "Cross-source duplicate must not be reported"


@pytest.mark.asyncio
async def test_cross_source_same_content_hash_not_a_duplicate(mem_session):
    """Same content_hash from a different source must NOT be detected as a duplicate."""
    mem_session.add(_orm_record("r-a", "source-a", content_hash="deadbeef"))
    await mem_session.commit()

    repo = IntelligenceRepository(mem_session)
    result = await repo.find_duplicate(
        canonical_url="https://other.example.com/b",
        title="Different Title",
        source_reference="ref-99",
        content_hash="deadbeef",
        source_id="source-b",
    )
    assert result is None, "Cross-source hash collision must not suppress different source's record"


@pytest.mark.asyncio
async def test_same_source_same_reference_is_a_duplicate(mem_session):
    """Same source_reference from the same source IS a duplicate."""
    mem_session.add(_orm_record("r-a", "source-a", source_reference="ref-1"))
    await mem_session.commit()

    repo = IntelligenceRepository(mem_session)
    result = await repo.find_duplicate(
        canonical_url="https://example.com/a",
        title="Test",
        source_reference="ref-1",
        content_hash="abc123",
        source_id="source-a",
    )
    assert result is not None, "Same-source duplicate must be detected"
    assert result.id == "r-a"


@pytest.mark.asyncio
async def test_no_source_id_matches_any_source(mem_session):
    """When source_id is omitted the lookup is unscoped (backward-compat)."""
    mem_session.add(_orm_record("r-a", "source-a", source_reference="ref-1"))
    await mem_session.commit()

    repo = IntelligenceRepository(mem_session)
    result = await repo.find_duplicate(
        canonical_url="https://example.com/a",
        title="Test",
        source_reference="ref-1",
        content_hash="abc123",
        source_id=None,
    )
    assert result is not None


# ---------------------------------------------------------------------------
# SQL COUNT correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_records_count_uses_sql_not_python_len(mem_session):
    """list_records() total must use SELECT COUNT(*), not len(all_rows)."""
    # Insert 5 records for source-x, 3 for source-y
    for i in range(5):
        mem_session.add(_orm_record(f"rx-{i}", "source-x", source_reference=f"ref-x-{i}"))
    for i in range(3):
        mem_session.add(_orm_record(f"ry-{i}", "source-y", source_reference=f"ref-y-{i}"))
    await mem_session.commit()

    repo = IntelligenceRepository(mem_session)

    # Page size 2, first page — total must reflect all 5 for source-x
    records, total = await repo.list_records(source_id="source-x", offset=0, limit=2)
    assert len(records) == 2, "Page should have 2 items"
    assert total == 5, "Total must count all 5 rows, not just the 2 returned"

    # Without filter — total is 8
    records_all, total_all = await repo.list_records(offset=0, limit=2)
    assert total_all == 8
