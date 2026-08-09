"""Tests for Batch 9C — Strategy Persistence and Recovery.

Target: ~80 tests covering ORM models, repositories, persistence adapter,
recovery manager, idempotency, and integration contracts.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database.models import StrategyModel, StrategySignalModel, StrategyStateModel
from src.database.repositories.strategy import StrategyRepository
from src.database.repositories.strategy_signal import StrategySignalRepository
from src.database.repositories.strategy_state import StrategyStateRepository
from src.strategy.persistence import (
    StrategyConfigRecord,
    StrategySignalRecord,
    StrategyStateSnapshotRecord,
    StrategyPersistenceAdapter,
)
from src.strategy.recovery import (
    StrategyRecoveryManager,
    StrategyRecoveryResult,
)


# ------------------------------------------------------------------
# NOTE: These tests assume src/database/models.py already contains
# the three Batch 9C model classes (StrategyModel, StrategySignalModel,
# StrategyStateModel) added to the flat file.
# ------------------------------------------------------------------


# NOTE: no custom event_loop fixture and no session-scoped async fixtures:
# pytest-asyncio (asyncio_default_fixture_loop_scope = "function") runs each
# test on its own loop, so a session-scoped engine causes ScopeMismatch.
# The in-memory SQLite engine is cheap to build per test.
@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False, future=True)
    # Only create the 3 strategy tables — Base.metadata.create_all would fail
    # in SQLite because existing models (e.g. RiskStateModel) use JSONB, a
    # PostgreSQL-only type.
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: [
            t.create(c, checkfirst=True)
            for t in [
                StrategyModel.__table__,
                StrategySignalModel.__table__,
                StrategyStateModel.__table__,
            ]
        ])
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    async_session = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def strategy_repo():
    return StrategyRepository()


@pytest.fixture
def signal_repo():
    return StrategySignalRepository()


@pytest.fixture
def state_repo():
    return StrategyStateRepository()


@pytest.fixture
def persistence_adapter(strategy_repo, signal_repo, state_repo):
    return StrategyPersistenceAdapter(
        strategy_repo=strategy_repo,
        signal_repo=signal_repo,
        state_repo=state_repo,
    )


# ==================================================================
# 1. ORM Model Construction Tests
# ==================================================================

class TestStrategyModel:
    def test_model_inherits_base(self):
        from src.database.models import Base
        assert issubclass(StrategyModel, Base)

    def test_table_name(self):
        assert StrategyModel.__tablename__ == "strategies"

    def test_has_uuid_primary_key(self):
        assert hasattr(StrategyModel, "id")

    def test_strategy_id_column(self):
        assert hasattr(StrategyModel, "strategy_id")

    def test_lifecycle_state_column(self):
        assert hasattr(StrategyModel, "lifecycle_state")

    def test_configuration_json_column(self):
        assert hasattr(StrategyModel, "configuration")

    def test_instrument_tokens_json_column(self):
        assert hasattr(StrategyModel, "instrument_tokens")

    def test_created_at_timezone_aware(self):
        col = StrategyModel.__table__.c.created_at
        assert col.type.timezone is True

    def test_updated_at_timezone_aware(self):
        col = StrategyModel.__table__.c.updated_at
        assert col.type.timezone is True

    def test_unique_constraint_on_strategy_id(self):
        constraints = [c.name for c in StrategyModel.__table__.constraints]
        assert "uq_strategies_strategy_id" in constraints

    def test_no_duplicate_unique_on_column(self):
        col = StrategyModel.__table__.c.strategy_id
        assert col.unique is False or col.unique is None

    def test_indexes_exist(self):
        idx_names = {idx.name for idx in StrategyModel.__table__.indexes}
        assert "ix_strategies_account_lifecycle" in idx_names
        assert "ix_strategies_type_state" in idx_names

    def test_account_id_nullable(self):
        col = StrategyModel.__table__.c.account_id
        assert col.nullable is True


class TestStrategySignalModel:
    def test_model_inherits_base(self):
        from src.database.models import Base
        assert issubclass(StrategySignalModel, Base)

    def test_table_name(self):
        assert StrategySignalModel.__tablename__ == "strategy_signals"

    def test_quantity_is_numeric(self):
        col = StrategySignalModel.__table__.c.quantity
        assert str(col.type) == "NUMERIC(20, 8)"

    def test_limit_price_is_numeric(self):
        col = StrategySignalModel.__table__.c.limit_price
        assert str(col.type) == "NUMERIC(20, 8)"

    def test_trigger_price_is_numeric(self):
        col = StrategySignalModel.__table__.c.trigger_price
        assert str(col.type) == "NUMERIC(20, 8)"

    def test_timestamp_timezone_aware(self):
        col = StrategySignalModel.__table__.c.timestamp
        assert col.type.timezone is True

    def test_routing_status_default(self):
        col = StrategySignalModel.__table__.c.routing_status
        assert col.default.arg == "PENDING"

    def test_unique_constraint_on_signal_id(self):
        constraints = [c.name for c in StrategySignalModel.__table__.constraints]
        assert "uq_strategy_signals_signal_id" in constraints

    def test_no_duplicate_unique_on_column(self):
        col = StrategySignalModel.__table__.c.signal_id
        assert col.unique is False or col.unique is None

    def test_pending_index_exists(self):
        idx_names = {idx.name for idx in StrategySignalModel.__table__.indexes}
        assert "ix_strategy_signals_pending" in idx_names

    def test_routed_coid_index_exists(self):
        idx_names = {idx.name for idx in StrategySignalModel.__table__.indexes}
        assert "ix_strategy_signals_routed_coid" in idx_names

    def test_signal_id_is_uuid_type(self):
        col = StrategySignalModel.__table__.c.signal_id
        assert "UUID" in str(col.type).upper()

    def test_extra_data_column_exists(self):
        cols = {c.name for c in StrategySignalModel.__table__.columns}
        assert "extra_data" in cols

    def test_metadata_column_does_not_exist(self):
        cols = {c.name for c in StrategySignalModel.__table__.columns}
        assert "metadata" not in cols

    def test_account_id_nullable(self):
        col = StrategySignalModel.__table__.c.account_id
        assert col.nullable is True


class TestStrategyStateModel:
    def test_model_inherits_base(self):
        from src.database.models import Base
        assert issubclass(StrategyStateModel, Base)

    def test_table_name(self):
        assert StrategyStateModel.__tablename__ == "strategy_state_snapshots"

    def test_emitted_signal_count_is_integer(self):
        col = StrategyStateModel.__table__.c.emitted_signal_count
        assert str(col.type).upper() == "INTEGER"

    def test_routed_signal_count_is_integer(self):
        col = StrategyStateModel.__table__.c.routed_signal_count
        assert str(col.type).upper() == "INTEGER"

    def test_rejected_signal_count_is_integer(self):
        col = StrategyStateModel.__table__.c.rejected_signal_count
        assert str(col.type).upper() == "INTEGER"

    def test_fill_count_is_integer(self):
        col = StrategyStateModel.__table__.c.fill_count
        assert str(col.type).upper() == "INTEGER"

    def test_snapshot_timestamp_timezone_aware(self):
        col = StrategyStateModel.__table__.c.snapshot_timestamp
        assert col.type.timezone is True

    def test_unique_constraint_strategy_timestamp(self):
        constraints = [c.name for c in StrategyStateModel.__table__.constraints]
        assert "uq_strategy_state_snapshots_strategy_timestamp" in constraints

    def test_latest_index_exists(self):
        idx_names = {idx.name for idx in StrategyStateModel.__table__.indexes}
        assert "ix_strategy_state_snapshots_strategy_latest" in idx_names

    def test_extra_data_column_exists(self):
        cols = {c.name for c in StrategyStateModel.__table__.columns}
        assert "extra_data" in cols

    def test_metadata_column_does_not_exist(self):
        cols = {c.name for c in StrategyStateModel.__table__.columns}
        assert "metadata" not in cols


# ==================================================================
# 2. Repository Save / Load / Update Tests
# ==================================================================

class TestStrategyRepository:
    async def test_save_new_strategy(self, async_session, strategy_repo):
        model = await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="SMA_CROSSOVER", name="Test Strategy",
            account_id="acc1", configuration={"fast": 10, "slow": 20},
            instrument_tokens=["12345"], lifecycle_state="REGISTERED",
            enabled=True,
        )
        assert model.strategy_id == "s1"
        assert model.strategy_type == "SMA_CROSSOVER"

    async def test_save_is_upsert(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="SMA_CROSSOVER", name="Test Strategy",
            account_id="acc1", configuration={"fast": 10},
            instrument_tokens=["12345"], lifecycle_state="REGISTERED",
            enabled=True,
        )
        model2 = await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="SMA_CROSSOVER", name="Updated Name",
            account_id="acc1", configuration={"fast": 15},
            instrument_tokens=["12345", "67890"], lifecycle_state="ACTIVE",
            enabled=True,
        )
        assert model2.name == "Updated Name"
        assert model2.lifecycle_state == "ACTIVE"

    async def test_load_existing(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="T", name="N", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="R",
            enabled=True,
        )
        loaded = await strategy_repo.load(async_session, "s1")
        assert loaded is not None
        assert loaded.strategy_id == "s1"

    async def test_load_missing_returns_none(self, async_session, strategy_repo):
        loaded = await strategy_repo.load(async_session, "missing")
        assert loaded is None

    async def test_list_non_terminal_excludes_stopped(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s_active", strategy_type="T", name="A", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE",
            enabled=True,
        )
        await strategy_repo.save(
            session=async_session,
            strategy_id="s_stopped", strategy_type="T", name="S", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="STOPPED",
            enabled=True,
        )
        non_term = await strategy_repo.list_non_terminal(async_session)
        ids = {m.strategy_id for m in non_term}
        assert "s_active" in ids
        assert "s_stopped" not in ids

    async def test_list_non_terminal_excludes_error(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s_err", strategy_type="T", name="E", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ERROR",
            enabled=True,
        )
        non_term = await strategy_repo.list_non_terminal(async_session)
        assert all(m.strategy_id != "s_err" for m in non_term)

    async def test_update_lifecycle_state(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="T", name="N", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="REGISTERED",
            enabled=True,
        )
        ok = await strategy_repo.update_lifecycle_state(async_session, "s1", "ACTIVE")
        assert ok is True
        loaded = await strategy_repo.load(async_session, "s1")
        assert loaded.lifecycle_state == "ACTIVE"

    async def test_update_lifecycle_state_missing_returns_false(self, async_session, strategy_repo):
        ok = await strategy_repo.update_lifecycle_state(async_session, "missing", "ACTIVE")
        assert ok is False

    async def test_hydrate_config(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="T", name="N", account_id="a",
            configuration={"k": "v"}, instrument_tokens=["t1"],
            lifecycle_state="ACTIVE", enabled=True,
        )
        loaded = await strategy_repo.load(async_session, "s1")
        data = StrategyRepository._hydrate_config(loaded)
        assert data["strategy_id"] == "s1"
        assert data["configuration"] == {"k": "v"}
        assert data["instrument_tokens"] == ["t1"]

    async def test_save_without_account_id(self, async_session, strategy_repo):
        model = await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="T", name="N", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="R",
            enabled=True,
        )
        assert model.account_id is None


class TestStrategySignalRepository:
    async def test_save_new_signal(self, async_session, signal_repo):
        sig_id = uuid4()
        model = await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="12345", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150.50"), trigger_price=None,
            timestamp=datetime.now(timezone.utc), routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={"source": "test"},
        )
        assert model.signal_id == sig_id
        assert model.quantity == Decimal("100")

    async def test_save_upsert(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        model2 = await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="SELL", side="SELL",
            quantity=Decimal("200"), order_type="MARKET",
            limit_price=None, trigger_price=None,
            timestamp=ts, routing_status="ROUTED",
            routed_client_order_id="oid1", rejection_reason=None,
            extra_data={},
        )
        assert model2.action == "SELL"
        assert model2.routed_client_order_id == "oid1"

    async def test_load_existing(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        loaded = await signal_repo.load(async_session, sig_id)
        assert loaded is not None
        assert loaded.signal_id == sig_id

    async def test_list_pending(self, async_session, signal_repo):
        ts = datetime.now(timezone.utc)
        pending_id = uuid4()
        routed_id = uuid4()
        await signal_repo.save(
            session=async_session,
            signal_id=pending_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        await signal_repo.save(
            session=async_session,
            signal_id=routed_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="ROUTED",
            routed_client_order_id="oid1", rejection_reason=None,
            extra_data={},
        )
        pending = await signal_repo.list_pending(async_session)
        assert len(pending) == 1
        assert pending[0].signal_id == pending_id

    async def test_list_pending_by_strategy(self, async_session, signal_repo):
        ts = datetime.now(timezone.utc)
        sig_a = uuid4()
        sig_b = uuid4()
        await signal_repo.save(
            session=async_session,
            signal_id=sig_a, strategy_id="sA", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        await signal_repo.save(
            session=async_session,
            signal_id=sig_b, strategy_id="sB", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        pending = await signal_repo.list_pending(async_session, strategy_id="sA")
        assert len(pending) == 1
        assert pending[0].signal_id == sig_a

    async def test_update_routing_status(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        ok = await signal_repo.update_routing_status(
            async_session, sig_id, "ROUTED", routed_client_order_id="oid1"
        )
        assert ok is True
        loaded = await signal_repo.load(async_session, sig_id)
        assert loaded.routing_status == "ROUTED"
        assert loaded.routed_client_order_id == "oid1"

    async def test_is_routed_true(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="ROUTED",
            routed_client_order_id="oid1", rejection_reason=None,
            extra_data={},
        )
        assert await signal_repo.is_routed(async_session, sig_id) is True

    async def test_is_routed_false(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        assert await signal_repo.is_routed(async_session, sig_id) is False

    async def test_decimal_hydration(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("123.45678901"), order_type="LIMIT",
            limit_price=Decimal("999.99999999"), trigger_price=Decimal("888.88888888"),
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        loaded = await signal_repo.load(async_session, sig_id)
        assert loaded.quantity == Decimal("123.45678901")
        assert loaded.limit_price == Decimal("999.99999999")
        assert loaded.trigger_price == Decimal("888.88888888")

    async def test_hydrate_signal(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={"k": "v"},
        )
        loaded = await signal_repo.load(async_session, sig_id)
        data = StrategySignalRepository._hydrate_signal(loaded)
        assert data["signal_id"] == sig_id
        assert data["extra_data"] == {"k": "v"}

    async def test_save_without_account_id(self, async_session, signal_repo):
        sig_id = uuid4()
        model = await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=datetime.now(timezone.utc), routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        assert model.account_id is None


class TestStrategyStateRepository:
    async def test_save_snapshot(self, async_session, state_repo):
        ts = datetime.now(timezone.utc)
        model = await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=["oid1", "oid2"], latest_signal_timestamp=ts,
            emitted_signal_count=5, routed_signal_count=3,
            rejected_signal_count=1, fill_count=2,
            extra_data={"version": "1.0"}, snapshot_timestamp=ts,
        )
        assert model.strategy_id == "s1"
        assert model.lifecycle_state == "ACTIVE"
        assert model.emitted_signal_count == 5

    async def test_load_latest(self, async_session, state_repo):
        ts1 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=[], latest_signal_timestamp=ts1,
            emitted_signal_count=1, routed_signal_count=0,
            rejected_signal_count=0, fill_count=0,
            extra_data={}, snapshot_timestamp=ts1,
        )
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="PAUSED",
            pending_order_ids=[], latest_signal_timestamp=ts2,
            emitted_signal_count=2, routed_signal_count=1,
            rejected_signal_count=0, fill_count=1,
            extra_data={}, snapshot_timestamp=ts2,
        )
        latest = await state_repo.load_latest(async_session, "s1")
        assert latest.lifecycle_state == "PAUSED"
        assert latest.emitted_signal_count == 2

    async def test_load_latest_none(self, async_session, state_repo):
        latest = await state_repo.load_latest(async_session, "missing")
        assert latest is None

    async def test_list_by_strategy(self, async_session, state_repo):
        ts1 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=[], latest_signal_timestamp=ts1,
            emitted_signal_count=1, routed_signal_count=0,
            rejected_signal_count=0, fill_count=0,
            extra_data={}, snapshot_timestamp=ts1,
        )
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="PAUSED",
            pending_order_ids=[], latest_signal_timestamp=ts2,
            emitted_signal_count=2, routed_signal_count=1,
            rejected_signal_count=0, fill_count=1,
            extra_data={}, snapshot_timestamp=ts2,
        )
        all_snaps = await state_repo.list_by_strategy(async_session, "s1")
        assert len(all_snaps) == 2

    async def test_list_latest_all(self, async_session, state_repo):
        ts = datetime.now(timezone.utc)
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=[], latest_signal_timestamp=ts,
            emitted_signal_count=1, routed_signal_count=0,
            rejected_signal_count=0, fill_count=0,
            extra_data={}, snapshot_timestamp=ts,
        )
        await state_repo.save(
            session=async_session,
            strategy_id="s2", lifecycle_state="PAUSED",
            pending_order_ids=[], latest_signal_timestamp=ts,
            emitted_signal_count=5, routed_signal_count=3,
            rejected_signal_count=0, fill_count=2,
            extra_data={}, snapshot_timestamp=ts,
        )
        latest = await state_repo.list_latest_all(async_session)
        ids = {m.strategy_id for m in latest}
        assert ids == {"s1", "s2"}

    async def test_hydrate_snapshot(self, async_session, state_repo):
        ts = datetime.now(timezone.utc)
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=["a", "b"], latest_signal_timestamp=ts,
            emitted_signal_count=10, routed_signal_count=5,
            rejected_signal_count=2, fill_count=3,
            extra_data={"k": "v"}, snapshot_timestamp=ts,
        )
        loaded = await state_repo.load_latest(async_session, "s1")
        data = StrategyStateRepository._hydrate_snapshot(loaded)
        assert data["strategy_id"] == "s1"
        assert data["pending_order_ids"] == ["a", "b"]
        assert data["emitted_signal_count"] == 10
        assert data["extra_data"] == {"k": "v"}
        assert isinstance(data["emitted_signal_count"], int)

    async def test_counts_are_int_not_decimal(self, async_session, state_repo):
        ts = datetime.now(timezone.utc)
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=[], latest_signal_timestamp=ts,
            emitted_signal_count=42, routed_signal_count=10,
            rejected_signal_count=5, fill_count=3,
            extra_data={}, snapshot_timestamp=ts,
        )
        loaded = await state_repo.load_latest(async_session, "s1")
        assert isinstance(loaded.emitted_signal_count, int)
        assert isinstance(loaded.routed_signal_count, int)
        assert isinstance(loaded.rejected_signal_count, int)
        assert isinstance(loaded.fill_count, int)


# ==================================================================
# 3. Persistence Adapter Tests
# ==================================================================

class TestStrategyPersistenceAdapter:
    async def test_save_and_load_strategy(self, async_session, persistence_adapter):
        record = StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA_CROSSOVER", name="Test",
            account_id="acc1", configuration={"fast": 10},
            instrument_tokens=["12345"], lifecycle_state="REGISTERED", enabled=True,
        )
        await persistence_adapter.save_strategy(async_session, record)
        loaded = await persistence_adapter.load_strategy(async_session, "s1")
        assert loaded is not None
        assert loaded.strategy_id == "s1"
        assert loaded.configuration == {"fast": 10}

    async def test_save_strategy_idempotent(self, async_session, persistence_adapter):
        record = StrategyConfigRecord(
            strategy_id="s1", strategy_type="T", name="N", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="R", enabled=True,
        )
        await persistence_adapter.save_strategy(async_session, record)
        record2 = StrategyConfigRecord(
            strategy_id="s1", strategy_type="T", name="Updated", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="A", enabled=True,
        )
        await persistence_adapter.save_strategy(async_session, record2)
        loaded = await persistence_adapter.load_strategy(async_session, "s1")
        assert loaded.name == "Updated"
        assert loaded.lifecycle_state == "A"

    async def test_save_and_load_signal(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        sig_id = uuid4()
        record = StrategySignalRecord(
            signal_id=sig_id, strategy_id="s1", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        )
        await persistence_adapter.save_signal(async_session, record)
        loaded = await persistence_adapter.load_signal(async_session, sig_id)
        assert loaded is not None
        assert loaded.signal_id == sig_id
        assert loaded.quantity == Decimal("100")

    async def test_mark_signal_routed(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        sig_id = uuid4()
        record = StrategySignalRecord(
            signal_id=sig_id, strategy_id="s1", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        )
        await persistence_adapter.save_signal(async_session, record)
        ok = await persistence_adapter.mark_signal_routed(async_session, sig_id, "oid1")
        assert ok is True
        loaded = await persistence_adapter.load_signal(async_session, sig_id)
        assert loaded.routing_status == "ROUTED"
        assert loaded.routed_client_order_id == "oid1"

    async def test_is_signal_routed(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        sig_id = uuid4()
        record = StrategySignalRecord(
            signal_id=sig_id, strategy_id="s1", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="ROUTED",
            routed_client_order_id="oid1",
        )
        await persistence_adapter.save_signal(async_session, record)
        assert await persistence_adapter.is_signal_routed(async_session, sig_id) is True

    async def test_save_state_snapshot(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        record = StrategyStateSnapshotRecord(
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=["oid1"], latest_signal_timestamp=ts,
            emitted_signal_count=5, routed_signal_count=3,
            rejected_signal_count=1, fill_count=2,
        )
        await persistence_adapter.save_state_snapshot(async_session, record)
        loaded = await persistence_adapter.load_latest_state_snapshot(async_session, "s1")
        assert loaded is not None
        assert loaded.strategy_id == "s1"
        assert loaded.emitted_signal_count == 5
        assert isinstance(loaded.emitted_signal_count, int)

    async def test_list_non_terminal_strategies(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s_active", strategy_type="T", name="A", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s_stopped", strategy_type="T", name="S", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="STOPPED", enabled=True,
        ))
        non_term = await persistence_adapter.list_non_terminal_strategies(async_session)
        ids = {r.strategy_id for r in non_term}
        assert "s_active" in ids
        assert "s_stopped" not in ids

    async def test_list_pending_signals(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        sig_id = uuid4()
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=sig_id, strategy_id="s1", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        ))
        pending = await persistence_adapter.list_pending_signals(async_session)
        assert len(pending) == 1
        assert pending[0].signal_id == sig_id


# ==================================================================
# 4. Recovery Manager Tests
# ==================================================================

class FakeStrategyFactory:
    def __init__(self):
        self.created: List[str] = []

    async def create(self, strategy_type: str, strategy_id: str, config: Dict[str, Any]) -> Any:
        self.created.append(strategy_id)
        return {"id": strategy_id, "type": strategy_type}


class FakeStrategyRegistry:
    def __init__(self):
        self._registered: set = set()
        self.transitions: List[tuple] = []
        self.subscriptions: List[tuple] = []

    async def register(self, strategy_id: str, instance: Any, lifecycle_state: str) -> None:
        self._registered.add(strategy_id)

    async def transition(self, strategy_id: str, target_state: str) -> bool:
        self.transitions.append((strategy_id, target_state))
        return True

    async def subscribe_market_data(self, strategy_id: str, instrument_tokens: List[str]) -> None:
        self.subscriptions.append((strategy_id, instrument_tokens))

    async def is_registered(self, strategy_id: str) -> bool:
        return strategy_id in self._registered


class FakeSignalRouter:
    def __init__(self):
        self.enqueued: List[Any] = []

    async def enqueue(self, signal: Any) -> None:
        self.enqueued.append(signal)


class TestStrategyRecoveryManager:
    async def test_recover_no_strategies(self, async_session, persistence_adapter):
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert result.strategies_restored == []
        assert result.strategies_skipped == []
        assert result.signals_restored == 0
        assert result.signals_requeued == 0
        assert result.errors == []

    async def test_recover_active_strategy(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={"fast": 10}, instrument_tokens=["12345"],
            lifecycle_state="ACTIVE", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_restored
        assert ("s1", "STARTING") in registry.transitions
        assert ("s1", "ACTIVE") in registry.transitions
        assert len(registry.subscriptions) == 1
        assert registry.subscriptions[0] == ("s1", ["12345"])

    async def test_recover_paused_strategy(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=["12345"],
            lifecycle_state="PAUSED", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_restored
        assert ("s1", "PAUSED") in registry.transitions
        assert len(registry.subscriptions) == 0

    async def test_recover_starting_strategy(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="STARTING", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_restored
        assert ("s1", "STARTING") in registry.transitions

    async def test_recover_registered_strategy(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="REGISTERED", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_restored

    async def test_recover_skips_terminal_strategies(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="STOPPED", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" not in result.strategies_restored
        assert "s1" not in result.strategies_skipped
        assert len(factory.created) == 0

    async def test_recover_dedups_already_registered(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        registry._registered.add("s1")
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_skipped
        assert len(factory.created) == 0

    async def test_recover_pending_signals(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        ts = datetime.now(timezone.utc)
        sig_id = uuid4()
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t1", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert result.signals_restored == 1
        assert result.signals_requeued == 1
        assert len(router.enqueued) == 1
        assert router.enqueued[0]["signal_id"] == sig_id

    async def test_recover_skips_already_routed_signals(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        ts = datetime.now(timezone.utc)
        sig_id = uuid4()
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=sig_id, strategy_id="s1", account_id="a",
            instrument_token="t1", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="ROUTED",
            routed_client_order_id="oid1",
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert result.signals_restored == 1
        assert result.signals_requeued == 0
        assert len(router.enqueued) == 0

    async def test_recover_idempotent(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result1 = await manager.recover(async_session)
        result2 = await manager.recover(async_session)
        assert "s1" in result1.strategies_restored
        assert "s1" in result2.strategies_skipped
        assert result2.signals_requeued == 0

    async def test_recover_collects_errors(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))

        class BrokenFactory:
            async def create(self, strategy_type: str, strategy_id: str, config: Dict[str, Any]) -> Any:
                raise RuntimeError("factory failure")

        factory = BrokenFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_skipped
        assert any("factory failure" in e for e in result.errors)

    async def test_recover_result_structure(self, async_session, persistence_adapter):
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert isinstance(result, StrategyRecoveryResult)
        assert hasattr(result, "strategies_restored")
        assert hasattr(result, "strategies_skipped")
        assert hasattr(result, "signals_restored")
        assert hasattr(result, "signals_requeued")
        assert hasattr(result, "errors")
        assert hasattr(result, "recovery_timestamp")
        assert isinstance(result.recovery_timestamp, datetime)

    async def test_recover_with_state_snapshot(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        await persistence_adapter.save_state_snapshot(async_session, StrategyStateSnapshotRecord(
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=["oid1"], latest_signal_timestamp=ts,
            emitted_signal_count=10, routed_signal_count=5,
            rejected_signal_count=2, fill_count=3,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_restored

        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        for i in range(3):
            await persistence_adapter.save_signal(async_session, StrategySignalRecord(
                signal_id=uuid4(), strategy_id="s1", account_id="a",
                instrument_token="t1", action="BUY", side="BUY",
                quantity=Decimal("100"), order_type="LIMIT",
                limit_price=Decimal("150"), trigger_price=None,
                timestamp=ts, routing_status="PENDING",
            ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert result.signals_restored == 3
        assert result.signals_requeued == 3
        assert len(router.enqueued) == 3

    async def test_recovery_skips_mixed_routed_and_pending(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id="a",
            configuration={}, instrument_tokens=[], lifecycle_state="ACTIVE", enabled=True,
        ))
        pending_id = uuid4()
        routed_id = uuid4()
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=pending_id, strategy_id="s1", account_id="a",
            instrument_token="t1", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        ))
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=routed_id, strategy_id="s1", account_id="a",
            instrument_token="t1", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("150"), trigger_price=None,
            timestamp=ts, routing_status="ROUTED",
            routed_client_order_id="oid1",
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert result.signals_restored == 2
        assert result.signals_requeued == 1
        assert len(router.enqueued) == 1
        assert router.enqueued[0]["signal_id"] == pending_id

    async def test_strategy_state_snapshot_counts_as_int(self, async_session, state_repo):
        ts = datetime.now(timezone.utc)
        await state_repo.save(
            session=async_session,
            strategy_id="s1", lifecycle_state="ACTIVE",
            pending_order_ids=[], latest_signal_timestamp=ts,
            emitted_signal_count=999999, routed_signal_count=888888,
            rejected_signal_count=777777, fill_count=666666,
            extra_data={}, snapshot_timestamp=ts,
        )
        loaded = await state_repo.load_latest(async_session, "s1")
        data = StrategyStateRepository._hydrate_snapshot(loaded)
        assert data["emitted_signal_count"] == 999999
        assert isinstance(data["emitted_signal_count"], int)

    async def test_strategy_record_timestamps(self, async_session, strategy_repo):
        created = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)
        await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="T", name="N", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="R",
            enabled=True, created_at=created, updated_at=updated,
        )
        loaded = await strategy_repo.load(async_session, "s1")
        # SQLite strips timezone info; compare naive datetimes
        assert loaded.created_at.replace(tzinfo=None) == created.replace(tzinfo=None)
        assert loaded.updated_at.replace(tzinfo=None) == updated.replace(tzinfo=None)

    async def test_signal_decimal_precision(self, async_session, signal_repo):
        sig_id = uuid4()
        ts = datetime.now(timezone.utc)
        await signal_repo.save(
            session=async_session,
            signal_id=sig_id, strategy_id="s1", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("0.00000001"), order_type="LIMIT",
            limit_price=Decimal("0.00000001"), trigger_price=Decimal("0.00000001"),
            timestamp=ts, routing_status="PENDING",
            routed_client_order_id=None, rejection_reason=None,
            extra_data={},
        )
        loaded = await signal_repo.load(async_session, sig_id)
        assert loaded.quantity == Decimal("0.00000001")
        assert loaded.limit_price == Decimal("0.00000001")

    async def test_recovery_with_unknown_lifecycle_state(self, async_session, persistence_adapter):
        await persistence_adapter.save_strategy(async_session, StrategyConfigRecord(
            strategy_id="s1", strategy_type="SMA", name="Test", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="UNKNOWN_STATE", enabled=True,
        ))
        factory = FakeStrategyFactory()
        registry = FakeStrategyRegistry()
        router = FakeSignalRouter()
        manager = StrategyRecoveryManager(persistence_adapter, factory, registry, router)
        result = await manager.recover(async_session)
        assert "s1" in result.strategies_restored

    async def test_persistence_adapter_list_pending_by_strategy(self, async_session, persistence_adapter):
        ts = datetime.now(timezone.utc)
        sig_a = uuid4()
        sig_b = uuid4()
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=sig_a, strategy_id="sA", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        ))
        await persistence_adapter.save_signal(async_session, StrategySignalRecord(
            signal_id=sig_b, strategy_id="sB", account_id=None,
            instrument_token="t", action="BUY", side="BUY",
            quantity=Decimal("100"), order_type="LIMIT",
            limit_price=Decimal("100"), trigger_price=None,
            timestamp=ts, routing_status="PENDING",
        ))
        pending = await persistence_adapter.list_pending_signals(async_session, strategy_id="sA")
        assert len(pending) == 1
        assert pending[0].signal_id == sig_a

    async def test_no_commit_in_repository(self, async_session, strategy_repo):
        await strategy_repo.save(
            session=async_session,
            strategy_id="s1", strategy_type="T", name="N", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="R",
            enabled=True,
        )
        await async_session.rollback()
        loaded = await strategy_repo.load(async_session, "s1")
        assert loaded is None

    async def test_no_commit_in_adapter(self, async_session, persistence_adapter):
        record = StrategyConfigRecord(
            strategy_id="s1", strategy_type="T", name="N", account_id=None,
            configuration={}, instrument_tokens=[], lifecycle_state="R", enabled=True,
        )
        await persistence_adapter.save_strategy(async_session, record)
        await async_session.rollback()
        loaded = await persistence_adapter.load_strategy(async_session, "s1")
        assert loaded is None
