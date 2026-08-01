"""API endpoints for approved sources."""
from fastapi import APIRouter, HTTPException

from app.domain.models import ApprovedSource
from app.logging import get_logger
from app.repositories.source_registry import create_default_registry

logger = get_logger(__name__)
router = APIRouter()

_registry = create_default_registry()


@router.get("/sources")
async def list_sources() -> dict[str, list[ApprovedSource]]:
    """List all approved sources."""
    sources = _registry.list_all()
    return {"sources": sources}


@router.get("/sources/{source_id}")
async def get_source(source_id: str) -> ApprovedSource:
    """Get a specific approved source."""
    source = _registry.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return source
