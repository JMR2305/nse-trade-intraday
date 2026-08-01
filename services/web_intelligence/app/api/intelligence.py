"""API endpoints for intelligence records."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.models import IntelligenceRecord
from app.logging import get_logger
from app.repositories.database import get_db
from app.repositories.intelligence_repository import IntelligenceRepository

logger = get_logger(__name__)
router = APIRouter()


@router.get("/intelligence")
async def list_intelligence(
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
    offset: int = Query(0, ge=0),
    limit: int = Query(settings.api_default_page_size, ge=1, le=settings.api_max_page_size),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List intelligence records with filters and pagination."""
    repo = IntelligenceRepository(db)
    records, total = await repo.list_records(
        source_id=source_id,
        record_type=record_type,
        validation_status=validation_status,
        data_quality_status=data_quality_status,
        confidence_status=confidence_status,
        first_seen_after=first_seen_after,
        first_seen_before=first_seen_before,
        last_seen_after=last_seen_after,
        last_seen_before=last_seen_before,
        published_after=published_after,
        published_before=published_before,
        offset=offset,
        limit=limit,
    )
    return {
        "records": records,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/intelligence/{record_id}")
async def get_intelligence_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
) -> IntelligenceRecord:
    """Get a specific intelligence record."""
    repo = IntelligenceRepository(db)
    record = await repo.get_by_id(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    return record
