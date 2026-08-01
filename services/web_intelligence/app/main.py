"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, intelligence, sources, collection_runs, snapshots
from app.config import settings
from app.logging import configure_logging, get_logger
from app.repositories.database import AsyncSessionLocal
from app.repositories.source_registry import create_default_registry

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Application lifespan handler.

    Schema management is exclusively via Alembic migrations.
    ``init_db`` / ``create_all`` is intentionally NOT called here.
    Run ``alembic upgrade head`` before starting the service.
    """
    configure_logging()
    logger.info(
        "web_intelligence_service_starting",
        host=settings.service_host,
        port=settings.service_port,
    )

    # Load persisted sources from DB so operator-added sources survive restarts.
    # create_default_registry only inserts defaults when the DB is empty.
    async with AsyncSessionLocal() as session:
        registry = create_default_registry(session=session)
        await registry.sync_from_db()
        app.state.registry = registry

    yield
    logger.info("web_intelligence_service_stopping")


app = FastAPI(
    title="ApexQuant Web Intelligence Collector",
    description="Isolated intelligence collection service. Read-only API. No trading integration.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router, tags=["Health"])
app.include_router(sources.router, prefix="/api/v1", tags=["Sources"])
app.include_router(collection_runs.router, prefix="/api/v1", tags=["Collection Runs"])
app.include_router(intelligence.router, prefix="/api/v1", tags=["Intelligence"])
app.include_router(snapshots.router, prefix="/api/v1", tags=["Snapshots"])


@app.get("/")
async def root() -> dict[str, str]:
    """Service root — confirms isolation and version."""
    return {
        "service": "ApexQuant Web Intelligence Collector",
        "version": "0.1.0",
        "status": "isolated_read_only_service",
    }
