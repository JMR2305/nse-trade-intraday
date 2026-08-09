"""Integration-test isolation: wipe mutable state between test modules.

Sessions are idempotent per trading day, so state written by one module
(orders, positions, an active session) leaks into the next and breaks
"empty" expectations. Truncate everything except the seeded instrument
master before each module.
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL, Base

_KEEP_TABLES = {"instrument_master"}


def _truncate_all() -> None:
    async def _run() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                # Some models register on Base only when their module is
                # imported later, so metadata can list tables that were never
                # created — truncate only those that actually exist.
                existing = {
                    row[0]
                    for row in (
                        await conn.execute(
                            text(
                                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                            )
                        )
                    ).fetchall()
                }
                tables = [
                    t.name for t in Base.metadata.sorted_tables
                    if t.name not in _KEEP_TABLES and t.name in existing
                ]
                if tables:
                    quoted = ", ".join(f'"{t}"' for t in tables)
                    await conn.execute(
                        text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
                    )
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture(scope="module", autouse=True)
def _clean_database_per_module():
    _truncate_all()
    yield
