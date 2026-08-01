"""API endpoints for raw snapshots (metadata only)."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import RawSnapshot
from app.logging import get_logger
from app.repositories.database import get_db
from app.repositories.snapshot_repository import SnapshotRepository

logger = get_logger(__name__)
router = APIRouter()


@router.get("/snapshots/{snapshot_id}/metadata")
async def get_snapshot_metadata(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get snapshot metadata. Raw content is NOT exposed."""
    repo = SnapshotRepository(db)
    snapshot = await repo.get_by_id(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    # Return metadata only, never the raw content
    return {
        "id": snapshot.id,
        "source_id": snapshot.source_id,
        "requested_url": snapshot.requested_url,
        "canonical_url": snapshot.canonical_url,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "http_status": snapshot.http_status,
        "content_type": snapshot.content_type,
        "content_hash": snapshot.content_hash,
        "raw_content_location": snapshot.raw_content_location,
        "fetch_duration_ms": snapshot.fetch_duration_ms,
        "parser_version": snapshot.parser_version,
        "collection_run_id": snapshot.collection_run_id,
        "data_quality_status": snapshot.data_quality_status.value,
        "error_code": snapshot.error_code,
        "error_message": snapshot.error_message,
    }
