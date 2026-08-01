"""Tests for source registry DB persistence round-trip (defect D fix)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.domain.enums import SourceType
from app.domain.models import ApprovedSource
from app.repositories.source_registry import SourceRegistry, create_default_registry


# ---------------------------------------------------------------------------
# sync_from_db loads persisted sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_from_db_loads_sources():
    """Sources persisted in DB must be loaded into memory by sync_from_db."""
    from app.repositories.orm_models import ApprovedSourceORM

    # Build a fake ORM row
    orm_row = ApprovedSourceORM(
        id="persisted-src",
        name="Persisted Source",
        base_url="https://persisted.example.com",
        source_type=SourceType.GENERIC_STATIC_PAGE,
        enabled=1,
        robots_policy="allow",
        request_interval_seconds=5.0,
        maximum_requests_per_hour=60,
        user_agent="Bot/1.0",
        parser_name="generic_static_parser",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [orm_row]
    mock_session.execute = AsyncMock(return_value=mock_result)

    registry = SourceRegistry(session=mock_session)
    assert registry.get("persisted-src") is None  # Not loaded yet

    await registry.sync_from_db()

    src = registry.get("persisted-src")
    assert src is not None
    assert src.name == "Persisted Source"
    assert src.enabled is True


@pytest.mark.asyncio
async def test_sync_from_db_overwrites_in_memory_defaults():
    """sync_from_db must overwrite default in-memory entries with DB state."""
    from app.repositories.orm_models import ApprovedSourceORM

    # DB row for 'generic_test_page' has enabled=False (operator disabled it)
    orm_row = ApprovedSourceORM(
        id="generic_test_page",
        name="Generic Approved Static Page Test Source",
        base_url="https://example.com/apexquant-test",
        source_type=SourceType.GENERIC_STATIC_PAGE,
        enabled=0,  # Operator disabled this source
        robots_policy="allow",
        request_interval_seconds=5.0,
        maximum_requests_per_hour=60,
        user_agent="ApexQuant-WebIntelligence/0.1.0",
        parser_name="generic_static_parser",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [orm_row]
    mock_session.execute = AsyncMock(return_value=mock_result)

    registry = create_default_registry(session=mock_session)
    # Default has enabled=True
    assert registry.get("generic_test_page").enabled is True

    await registry.sync_from_db()

    # After sync, DB state (enabled=False) must win
    assert registry.get("generic_test_page").enabled is False


@pytest.mark.asyncio
async def test_sync_from_db_no_session_is_noop():
    """sync_from_db without a session must be a no-op (no errors)."""
    registry = SourceRegistry(session=None)
    registry.register(ApprovedSource(
        id="local",
        name="Local",
        base_url="https://local.example.com",
        source_type=SourceType.GENERIC_STATIC_PAGE,
        user_agent="Test",
        parser_name="test",
    ))
    await registry.sync_from_db()  # Must not raise
    assert registry.get("local") is not None
