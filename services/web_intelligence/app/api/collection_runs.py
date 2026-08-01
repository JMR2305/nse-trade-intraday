"""API endpoints for collection runs."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.models import CollectionRun
from app.logging import get_logger
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.database import get_db

logger = get_logger(__name__)
router = APIRouter()


@router.get("/collection-runs")
async def list_collection_runs(
    source_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(settings.api_default_page_size, ge=1, le=settings.api_max_page_size),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[CollectionRun] | int]:
    """List collection runs with optional source filter."""
    repo = CollectionRunRepository(db)
    runs, total = await repo.list_runs(source_id=source_id, offset=offset, limit=limit)
    return {"runs": runs, "total": total, "offset": offset, "limit": limit}


@router.get("/collection-runs/{run_id}")
async def get_collection_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> CollectionRun:
    """Get a specific collection run."""
    repo = CollectionRunRepository(db)
    run = await repo.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Collection run {run_id} not found")
    return run
