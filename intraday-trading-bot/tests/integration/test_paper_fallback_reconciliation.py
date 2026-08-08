"""Integration test: paper-fallback tags survive to post-session reconciliation.

Uses an in-memory SQLite async DB (no external services) to prove:
  - A correlation row tagged paper_fallback_reason="token_expired" is matched
    by internal_order_id — even when the row was created before the current
    UTC date (delayed / post-midnight reconciliation run).
  - The tagged order is excluded from LOCAL_ONLY discrepancy checks.
  - The persisted broker_reconciliation_runs row carries paper_fallback_count.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, MagicMock

from src.brokers.contracts import ReconciliationDiscrepancyType
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.reconciliation import ReconciliationEngine
# Schema mirrors migrations/versions/0006 + 0007 for the columns exercised
# here.  Raw DDL is used because SQLite cannot autoincrement BigInteger PKs
# from the SQLAlchemy models.
_DDL = [
    """
    CREATE TABLE broker_order_correlations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        internal_order_id VARCHAR(64) NOT NULL,
        idempotency_key VARCHAR(100) NOT NULL UNIQUE,
        broker_order_id VARCHAR(64),
        exchange_order_id VARCHAR(64),
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
        paper_mode BOOLEAN NOT NULL DEFAULT 1,
        trading_symbol VARCHAR(50),
        exchange VARCHAR(10),
        error_message TEXT,
        paper_fallback_reason VARCHAR(50),
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL,
        reconciled_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE broker_reconciliation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id VARCHAR(64) NOT NULL UNIQUE,
        trigger VARCHAR(50) NOT NULL,
        started_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP,
        orders_checked INTEGER NOT NULL DEFAULT 0,
        clean BOOLEAN NOT NULL DEFAULT 1,
        discrepancy_count INTEGER NOT NULL DEFAULT 0,
        paper_mode BOOLEAN NOT NULL DEFAULT 1,
        paper_fallback_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE broker_reconciliation_discrepancies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id VARCHAR(64) NOT NULL,
        discrepancy_type VARCHAR(50) NOT NULL,
        internal_order_id VARCHAR(64),
        broker_order_id VARCHAR(64),
        trading_symbol VARCHAR(50),
        description TEXT,
        local_value TEXT,
        broker_value TEXT,
        requires_manual_review BOOLEAN NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_engine():
    config = ZerodhaBrokerConfig(
        api_key="key",
        api_secret="secret",
        paper_trading=False,
        enabled=True,
        live_trading_enabled=True,
    )
    gateway = MagicMock()
    gateway.get_order_book = AsyncMock(return_value=[])
    gateway.get_trades = AsyncMock(return_value=[])
    health = BrokerHealthTracker(paper_mode=False)
    return ReconciliationEngine(
        config=config, health_tracker=health, order_gateway=gateway
    )


async def _insert_fallback_correlation(
    session: AsyncSession, internal_order_id: str, created_at: datetime
) -> None:
    await session.execute(text("""
        INSERT INTO broker_order_correlations
            (internal_order_id, idempotency_key, broker_order_id, status,
             paper_mode, trading_symbol, exchange, paper_fallback_reason,
             created_at, updated_at)
        VALUES
            (:ioid, :idem, :boid, 'CONFIRMED', 1, 'RELIANCE', 'NSE',
             'token_expired', :ts, :ts)
    """), {
        "ioid": internal_order_id,
        "idem": f"idem-{internal_order_id}",
        "boid": f"PAPER-{internal_order_id}",
        "ts": created_at,
    })
    await session.flush()


@pytest.mark.asyncio
async def test_fallback_persisted_yesterday_still_bucketed(db_session):
    """A delayed run after UTC midnight must still bucket the fallback order."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    await _insert_fallback_correlation(db_session, "101", created_at=yesterday)

    engine = _make_engine()
    local_orders = [
        {"id": 101, "broker_order_id": "PAPER-101", "symbol": "RELIANCE", "status": "COMPLETE"},
        {"id": 102, "broker_order_id": "BRK-MISSING", "symbol": "INFY", "status": "OPEN"},
    ]
    report = await engine.run(
        trigger="eod", local_orders=local_orders, db_session=db_session
    )

    assert report.paper_fallback_orders == 1
    assert report.paper_fallback_reasons == {"token_expired": 1}
    assert report.orders_checked == 2

    # Fallback order must NOT be flagged; only the genuinely missing one is.
    local_only = [
        d for d in report.discrepancies
        if d.discrepancy_type == ReconciliationDiscrepancyType.LOCAL_ONLY
    ]
    assert len(local_only) == 1
    assert local_only[0].internal_order_id == "102"

    # Persisted run row carries the separate count line.
    row = (await db_session.execute(text(
        "SELECT paper_fallback_count, orders_checked FROM broker_reconciliation_runs "
        "WHERE run_id = :rid"
    ), {"rid": report.run_id})).fetchone()
    assert row is not None
    assert row.paper_fallback_count == 1
    assert row.orders_checked == 2


@pytest.mark.asyncio
async def test_untagged_orders_unaffected(db_session):
    """Orders without a fallback tag go through normal checks unchanged."""
    engine = _make_engine()
    local_orders = [
        {"id": 201, "broker_order_id": "BRK-201", "symbol": "TCS", "status": "OPEN"},
    ]
    report = await engine.run(
        trigger="eod", local_orders=local_orders, db_session=db_session
    )
    assert report.paper_fallback_orders == 0
    types = [d.discrepancy_type for d in report.discrepancies]
    assert ReconciliationDiscrepancyType.LOCAL_ONLY in types

    row = (await db_session.execute(text(
        "SELECT paper_fallback_count FROM broker_reconciliation_runs WHERE run_id = :rid"
    ), {"rid": report.run_id})).fetchone()
    assert row is not None
    assert row.paper_fallback_count == 0
