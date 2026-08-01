"""Health and readiness endpoints."""
import contextlib

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.logging import get_logger
from app.repositories.database import AsyncSessionLocal
from app.storage.snapshot_storage import SnapshotStorage

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "healthy", "service": "web-intelligence"}


@router.get("/ready")
async def readiness_check() -> dict[str, object]:
    """Readiness probe — validates database connectivity and storage accessibility."""
    checks: dict[str, bool] = {}

    # Database check
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error("readiness_database_failed", error=str(e))
        checks["database"] = False

    # Storage round-trip check — clean up the test artifact immediately
    try:
        storage = SnapshotStorage()
        test_content = b"readiness_check"
        path = storage.store(test_content)
        retrieved = storage.retrieve(path)
        assert retrieved == test_content
        # Remove the test artifact so probes don't accumulate files on disk
        with contextlib.suppress(Exception):
            storage.delete(path)
        checks["storage"] = True
    except Exception as e:
        logger.error("readiness_storage_failed", error=str(e))
        checks["storage"] = False

    # Parser availability check — instantiate the adapter, which raises in
    # production mode when the scrapling library is not installed.
    try:
        from app.collectors.scrapling_adapter import ScraplingAdapter
        ScraplingAdapter()
        checks["scrapling"] = True
    except Exception as e:
        logger.error("readiness_parser_failed", error=str(e))
        checks["scrapling"] = False

    all_ready = all(checks.values())
    if not all_ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "service": "web-intelligence", "checks": checks}
