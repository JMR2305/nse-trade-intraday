"""Typer CLI for admin operations."""
import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

from app.collectors.fetch_client import FetchClient
from app.domain.enums import CollectionRunStatus
from app.logging import configure_logging, get_logger
from app.parsers.base_parser import ParserRegistry
from app.parsers.fixture_parser import FixtureParser
from app.parsers.generic_static_parser import GenericStaticParser
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.database import AsyncSessionLocal, init_db
from app.repositories.intelligence_repository import IntelligenceRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.source_registry import create_default_registry
from app.security.robots_checker import RobotsChecker
from app.services.collection import CollectionService
from app.services.deduplication import DeduplicationService
from app.storage.snapshot_storage import SnapshotStorage

configure_logging()
logger = get_logger(__name__)
app = typer.Typer(help="ApexQuant Web Intelligence Collector CLI")


@app.command()
def list_sources() -> None:
    """List all approved sources."""
    registry = create_default_registry()
    for src in registry.list_all():
        status = "enabled" if src.enabled else "disabled"
        typer.echo(f"{src.id}: {src.name} [{status}] -> {src.base_url}")


@app.command()
def validate_source(source_id: str) -> None:
    """Validate a source configuration."""
    registry = create_default_registry()
    source = registry.get(source_id)
    if not source:
        typer.echo(f"ERROR: Source {source_id} not found", err=True)
        raise typer.Exit(1)

    typer.echo(f"Source: {source.name}")
    typer.echo(f"  URL: {source.base_url}")
    typer.echo(f"  Type: {source.source_type.value}")
    typer.echo(f"  Parser: {source.parser_name}")
    typer.echo(f"  Enabled: {source.enabled}")
    typer.echo(f"  Interval: {source.request_interval_seconds}s")
    typer.echo(f"  Max req/hour: {source.maximum_requests_per_hour}")
    typer.echo("Validation: OK")


@app.command()
def check_robots(source_id: str) -> None:
    """Check robots.txt policy for a source."""

    async def _run() -> None:
        registry = create_default_registry()
        source = registry.get(source_id)
        if not source:
            typer.echo(f"ERROR: Source {source_id} not found", err=True)
            raise typer.Exit(1)

        checker = RobotsChecker()
        allowed = await checker.is_allowed(source.base_url, source.user_agent)
        status = "ALLOWED" if allowed else "DISALLOWED"
        typer.echo(f"robots.txt check for {source_id}: {status}")

    asyncio.run(_run())


@app.command()
def collect_source(source_id: str, url: Optional[str] = None) -> None:
    """Collect from a single approved source."""

    async def _run() -> None:
        await init_db()
        registry = create_default_registry()
        source = registry.get(source_id)
        if not source:
            typer.echo(f"ERROR: Source {source_id} not found", err=True)
            raise typer.Exit(1)

        if not source.enabled:
            typer.echo(f"ERROR: Source {source_id} is disabled", err=True)
            raise typer.Exit(1)

        # Check robots.txt
        if source.source_type.value != "local_html_fixture":
            checker = RobotsChecker()
            allowed = await checker.is_allowed(source.base_url, source.user_agent)
            if not allowed:
                typer.echo(f"ERROR: robots.txt disallows {source_id}", err=True)
                raise typer.Exit(1)

        parser_registry = ParserRegistry()
        parser_registry.register(GenericStaticParser())
        parser_registry.register(FixtureParser())

        async with AsyncSessionLocal() as session:
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

            run = await service.collect_source(source, url=url)
            typer.echo(f"Collection run: {run.id}")
            typer.echo(f"Status: {run.status.value}")
            typer.echo(f"Pages: {run.pages_succeeded}/{run.pages_requested}")
            typer.echo(f"Records: {run.records_inserted} inserted, {run.records_updated} updated, {run.duplicates_ignored} duplicates")

    asyncio.run(_run())


@app.command()
def collect_all() -> None:
    """Collect from all enabled sources."""

    async def _run() -> None:
        await init_db()
        registry = create_default_registry()
        enabled = registry.list_enabled()

        parser_registry = ParserRegistry()
        parser_registry.register(GenericStaticParser())
        parser_registry.register(FixtureParser())

        async with AsyncSessionLocal() as session:
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

            for source in enabled:
                typer.echo(f"Collecting: {source.id}...")
                run = await service.collect_source(source)
                typer.echo(f"  -> {run.status.value}")

    asyncio.run(_run())


@app.command()
def inspect_run(run_id: str) -> None:
    """Inspect a collection run."""

    async def _run() -> None:
        await init_db()
        async with AsyncSessionLocal() as session:
            repo = CollectionRunRepository(session)
            run = await repo.get_by_id(run_id)
            if not run:
                typer.echo(f"ERROR: Run {run_id} not found", err=True)
                raise typer.Exit(1)

            typer.echo(json.dumps(run.model_dump(mode="json"), indent=2, default=str))

    asyncio.run(_run())


@app.command()
def disable_source(source_id: str) -> None:
    """Disable a source (persisted to DB so the change survives restart)."""

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            registry = create_default_registry(session=session)
            await registry.sync_from_db()
            if await registry.disable(source_id):
                typer.echo(f"Source {source_id} disabled")
            else:
                typer.echo(f"ERROR: Source {source_id} not found", err=True)
                raise typer.Exit(1)

    asyncio.run(_run())


@app.command()
def enable_source(source_id: str) -> None:
    """Enable a source (persisted to DB so the change survives restart)."""

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            registry = create_default_registry(session=session)
            await registry.sync_from_db()
            if await registry.enable(source_id):
                typer.echo(f"Source {source_id} enabled")
            else:
                typer.echo(f"ERROR: Source {source_id} not found", err=True)
                raise typer.Exit(1)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
