"""Pytest configuration and fixtures."""

import asyncio
import importlib
import importlib.abc
import importlib.util
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Single-identity import namespace guard.
#
# The bot's source modules import each other with bare names (e.g.
# `from execution.contracts import ...`), which requires `src` on sys.path
# (pytest `pythonpath = ["src"]`), while this conftest and many tests import
# via the `src.` prefix. Without intervention the SAME file can be imported
# under TWO module identities (`database.models` and `src.database.models`),
# which registers every ORM table twice on the shared SQLAlchemy MetaData and
# raises InvalidRequestError depending on import order.
#
# This meta-path finder makes every bare import of a bot package an ALIAS of
# its `src.`-prefixed module, guaranteeing one module object per file.
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
_SRC_TOP_PACKAGES = {
    p.name for p in _SRC_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()
}


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):  # already executed under its src.* name
        pass


class _SrcAliasFinder(importlib.abc.MetaPathFinder):
    """Redirect `import <pkg>...` to the already-imported `src.<pkg>...`."""

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".", 1)[0]
        if top not in _SRC_TOP_PACKAGES:
            return None
        module = importlib.import_module(f"src.{fullname}")
        spec = importlib.util.spec_from_loader(fullname, _AliasLoader(module))
        if getattr(module, "__path__", None) is not None:
            spec.submodule_search_locations = list(module.__path__)
        return spec


if not any(isinstance(f, _SrcAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _SrcAliasFinder())
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from sqlalchemy.engine import make_url

from src.core.config import settings as _settings


def _default_test_database_url() -> str:
    """Derive an isolated test DB URL from the configured database.

    Reuses the configured Postgres server but a dedicated `intraday_bot_test`
    database so integration tests NEVER touch the shared application DB.
    Strips libpq-style `sslmode` (asyncpg rejects it).
    """
    url = make_url(_settings.database_url)
    url = url.set(database="intraday_bot_test")
    if "sslmode" in url.query:
        url = url.difference_update_query(["sslmode"])
    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", _default_test_database_url())

# Point the application's own lazy engine at the SAME isolated test DB —
# some services use the session factory directly rather than the
# get_db_session dependency, so overriding only the dependency is not enough.
_settings.database_url = TEST_DATABASE_URL

from src.main import app  # noqa: E402  (must come after settings override)
from src.database.connection import Base, get_db_session  # noqa: E402
import src.database.connection as _db_connection  # noqa: E402

# Pre-create the app's engine with NullPool: TestClient creates a fresh event
# loop per `with` block, and pooled asyncpg connections created on one loop
# blow up with "attached to a different loop" when reused on the next.
from sqlalchemy.pool import NullPool  # noqa: E402

_db_connection._engine = create_async_engine(
    TEST_DATABASE_URL, echo=False, future=True, poolclass=NullPool
)

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True, pool_pre_ping=True)


def _create_all_tables_eagerly() -> None:
    """Create all tables in the isolated test DB before any test runs.

    Integration tests exercise the app's own engine/session factory (not
    just the `db_engine` fixture), so the schema must exist up-front.
    Uses a throwaway engine + asyncio.run so no loop-bound state leaks
    into pytest-asyncio's per-test loops.
    """
    async def _create() -> None:
        from sqlalchemy import insert

        from src.database.models import InstrumentMaster

        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.begin() as conn:
                # Hermetic per-run: previous runs leave sessions/orders that
                # break idempotent-session and active-session expectations.
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
                # The order router currently records instrument_token=0 for
                # symbol-based paper orders; seed a placeholder instrument so
                # the orders FK is satisfiable.
                await conn.execute(
                    insert(InstrumentMaster).values(
                        instrument_token=0,
                        exchange="NSE",
                        tradingsymbol="__TEST_PLACEHOLDER__",
                        name="Test placeholder instrument",
                        instrument_type="EQ",
                        segment="NSE",
                        lot_size=1,
                        is_tradable=True,
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_create())


_create_all_tables_eagerly()

TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db_session] = override_get_db


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="module")
def client() -> Generator:
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers() -> dict:
    from src.services.operator_auth_service import operator_auth_service
    token = operator_auth_service.create_access_token("test_user")
    return {"Authorization": f"Bearer {token}"}
