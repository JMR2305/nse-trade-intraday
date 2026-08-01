"""Tests for /ready endpoint — parser check and no persistent test artifacts (defect G)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.api.health import router


@pytest.fixture()
def app():
    a = FastAPI()
    a.include_router(router)
    return a


def test_health_returns_healthy(app):
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_readiness_cleans_up_test_artifact():
    """/ready must not accumulate test snapshot files — it must delete after round-trip."""
    deleted_paths = []

    class _FakeStorage:
        def store(self, content):
            return "test/fake.bin"

        def retrieve(self, path):
            return b"readiness_check"

        def delete(self, path):
            deleted_paths.append(path)

    with (
        patch("app.api.health.AsyncSessionLocal") as mock_sl,
        patch("app.api.health.SnapshotStorage", return_value=_FakeStorage()),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.execute = AsyncMock()
        mock_sl.return_value = mock_ctx

        from app.api.health import readiness_check
        result = await readiness_check()

    assert result["checks"]["storage"] is True
    assert "test/fake.bin" in deleted_paths, "Test artifact must be deleted after probe"


@pytest.mark.asyncio
async def test_readiness_includes_scrapling_check():
    """/ready response must include a 'scrapling' key showing parser availability."""
    with (
        patch("app.api.health.AsyncSessionLocal") as mock_sl,
        patch("app.api.health.SnapshotStorage") as mock_storage_cls,
    ):
        mock_storage = MagicMock()
        mock_storage.store.return_value = "test/fake.bin"
        mock_storage.retrieve.return_value = b"readiness_check"
        mock_storage.delete.return_value = None
        mock_storage_cls.return_value = mock_storage

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.execute = AsyncMock()
        mock_sl.return_value = mock_ctx

        from app.api.health import readiness_check
        result = await readiness_check()

    assert "scrapling" in result["checks"]


@pytest.mark.asyncio
async def test_readiness_503_when_db_fails():
    """/ready must return 503 when the database check fails."""
    with (
        patch("app.api.health.AsyncSessionLocal") as mock_sl,
        patch("app.api.health.SnapshotStorage") as mock_storage_cls,
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.execute = AsyncMock(side_effect=RuntimeError("db down"))
        mock_sl.return_value = mock_ctx

        mock_storage = MagicMock()
        mock_storage.store.return_value = "test/fake.bin"
        mock_storage.retrieve.return_value = b"readiness_check"
        mock_storage.delete.return_value = None
        mock_storage_cls.return_value = mock_storage

        from fastapi import HTTPException
        from app.api.health import readiness_check
        with pytest.raises(HTTPException) as exc_info:
            await readiness_check()

    assert exc_info.value.status_code == 503
