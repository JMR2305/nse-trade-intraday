"""Database connection and session management."""

from typing import Optional

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from sqlalchemy.engine import make_url

from src.core.config import settings
from src.core.logging import logger

# Base class for all models
Base = declarative_base()

# Lazy singletons — created on first use, not at import time.
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


def get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first call."""
    global _engine
    if _engine is None:
        # asyncpg does not accept libpq's `sslmode` query parameter —
        # translate it to the asyncpg `ssl` connect arg instead.
        url = make_url(settings.database_url)
        connect_args = {}
        sslmode = url.query.get("sslmode")
        if sslmode is not None and url.drivername.endswith("asyncpg"):
            url = url.difference_update_query(["sslmode"])
            if sslmode in ("disable", "allow", "prefer"):
                connect_args["ssl"] = False
            else:  # require / verify-ca / verify-full
                connect_args["ssl"] = True
        _engine = create_async_engine(
            url,
            connect_args=connect_args,
            echo=settings.debug,
            future=True,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory() -> async_sessionmaker:
    """Return the shared session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncSession:
    """Get a database session for dependency injection."""
    async with get_session_factory()() as session:
        try:
            yield session
            # Commit at the request boundary: repositories/services never
            # commit themselves (enforced by the no-bare-commit audit), so
            # the unit-of-work must be committed here or every API write
            # silently rolls back when the session closes.
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """Check if database is reachable."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


async def init_db() -> None:
    """Initialize database tables (for development only). Use Alembic in production."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")
