"""Batch 9D-A — Runtime wiring and recovery integration tests.

Covers:
  TestSessionContext          — commit/rollback/close behaviour
  TestCoordinatorPersistence  — lifecycle transitions → adapter calls
  TestCoordinatorRecovery     — recover() invokes StrategyRecoveryManager
  TestRuntimeSignalPersistence — signals persisted before routing callback
  TestRoutingStatusUpdate     — coordinator._route_signal_task marks routed/rejected
  TestStateSnapshotPersistence — runtime pushes snapshots after bars
  TestNoCommitInCoordinator   — AST audit: no bare session.commit() in new code

All persistence calls use AsyncMock — no real DB connections.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from strategy.coordinator import StrategyCoordinator, ShutdownResult
from strategy.contracts import (
    StrategyConfig,
    StrategyLifecycleState,
    Signal,
    SignalAction,
)
from strategy.exceptions import StrategyNotFoundError
from strategy.runtime import StrategyRuntime
from strategy.session_context import SessionContext
from market_data.contracts import CompletedBar
from market_data.service import MarketDataService
from execution.contracts import ExecutionOrderSide, ExecutionOrderType
from risk.fill_event_bus import FillEventBus
from strategy.context_builder import ContextBuilder
from strategy.signal_router import SignalRouter


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class MockStrategy:
    @property
    def strategy_type(self):
        return "mock"

    def on_bar(self, bar, context):
        return None

    def on_tick(self, tick, context):
        return None

    def on_fill(self, fill_event, context):
        return None

    def validate_config(self, config):
        return []


def make_config(strategy_id: str = "strat_1") -> StrategyConfig:
    return StrategyConfig(
        strategy_id=strategy_id,
        strategy_type="mock",
        name="Test",
        instrument_tokens=["RELIANCE"],
    )


def make_signal(strategy_id: str = "strat_1") -> Signal:
    return Signal(
        strategy_id=strategy_id,
        instrument_token="RELIANCE",
        action=SignalAction.ENTER_LONG,
        side=ExecutionOrderSide.BUY,
        quantity=Decimal("100"),
    )


def make_bar() -> CompletedBar:
    return CompletedBar(
        instrument_token="RELIANCE",
        timestamp=datetime.utcnow(),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("10000"),
        interval="1m",
    )


def make_persistence() -> MagicMock:
    p = MagicMock()
    p.save_strategy = AsyncMock()
    p.save_signal = AsyncMock()
    p.save_state_snapshot = AsyncMock()
    p.mark_signal_routed = AsyncMock(return_value=True)
    p.mark_signal_rejected = AsyncMock(return_value=True)
    p.list_non_terminal_strategies = AsyncMock(return_value=[])
    p.list_all_signals = AsyncMock(return_value=[])
    p.load_latest_state_snapshot = AsyncMock(return_value=None)
    return p


def make_engine() -> MagicMock:
    return MagicMock()


def patch_session_context(mock_session: AsyncMock):
    """Return a context-manager patch that yields mock_session on __aenter__."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


# ---------------------------------------------------------------------------
# TestSessionContext
# ---------------------------------------------------------------------------

class TestSessionContext:
    @pytest.mark.asyncio
    async def test_aenter_returns_session(self):
        engine = MagicMock()
        mock_session = AsyncMock()
        with patch("strategy.session_context.AsyncSession", return_value=mock_session):
            async with SessionContext(engine) as session:
                assert session is mock_session

    @pytest.mark.asyncio
    async def test_commit_on_clean_exit(self):
        engine = MagicMock()
        mock_session = AsyncMock()
        with patch("strategy.session_context.AsyncSession", return_value=mock_session):
            async with SessionContext(engine):
                pass
        mock_session.commit.assert_awaited_once()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_on_exception(self):
        engine = MagicMock()
        mock_session = AsyncMock()
        with patch("strategy.session_context.AsyncSession", return_value=mock_session):
            with pytest.raises(ValueError):
                async with SessionContext(engine):
                    raise ValueError("boom")
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_always_called(self):
        """close() fires whether the block succeeds or raises."""
        engine = MagicMock()
        mock_session = AsyncMock()
        with patch("strategy.session_context.AsyncSession", return_value=mock_session):
            try:
                async with SessionContext(engine):
                    raise RuntimeError("test")
            except RuntimeError:
                pass
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_reraises(self):
        engine = MagicMock()
        mock_session = AsyncMock()
        with patch("strategy.session_context.AsyncSession", return_value=mock_session):
            with pytest.raises(KeyError):
                async with SessionContext(engine):
                    raise KeyError("not found")

    @pytest.mark.asyncio
    async def test_session_none_after_exit(self):
        engine = MagicMock()
        mock_session = AsyncMock()
        with patch("strategy.session_context.AsyncSession", return_value=mock_session):
            ctx = SessionContext(engine)
            async with ctx:
                pass
            assert ctx._session is None

    @pytest.mark.asyncio
    async def test_no_commit_in_repositories(self):
        """Session.commit() must not be called inside repository or adapter code."""
        repo_dir = Path("src/database/repositories")
        adapter_path = Path("src/strategy/persistence.py")
        recovery_path = Path("src/strategy/recovery.py")
        banned = {"commit", "rollback", "close"}
        violations = []
        for path in [*repo_dir.glob("strategy*.py"), adapter_path, recovery_path]:
            if not path.exists():
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in banned:
                    violations.append(f"{path}:.{node.attr}")
        assert violations == [], f"Banned calls found: {violations}"


# ---------------------------------------------------------------------------
# TestCoordinatorPersistence
# ---------------------------------------------------------------------------

class TestCoordinatorPersistence:

    def _make_coordinator(self, persistence=None, engine=None):
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        return StrategyCoordinator(
            mds, feb, cb, sr,
            persistence=persistence,
            engine=engine,
        )

    @pytest.mark.asyncio
    async def test_register_calls_save_strategy(self):
        persistence = make_persistence()
        engine = make_engine()
        coord = self._make_coordinator(persistence, engine)
        config = make_config()

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            result = await coord.register(config, MockStrategy())

        assert result.success is True
        persistence.save_strategy.assert_awaited_once()
        call_args = persistence.save_strategy.call_args
        record = call_args.args[1] if len(call_args.args) >= 2 else call_args.kwargs.get("record")
        assert record.lifecycle_state == StrategyLifecycleState.REGISTERED.value

    @pytest.mark.asyncio
    async def test_start_persists_active_state(self):
        persistence = make_persistence()
        engine = make_engine()
        coord = self._make_coordinator(persistence, engine)
        config = make_config()

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.register(config, MockStrategy())
            await coord.start("strat_1")
            await coord.stop("strat_1")

        # save_strategy should have been called for REGISTERED, ACTIVE, STOPPED
        assert persistence.save_strategy.await_count >= 3
        states = [
            (c.args[1] if len(c.args) >= 2 else c.kwargs["record"]).lifecycle_state
            for c in persistence.save_strategy.call_args_list
        ]
        assert StrategyLifecycleState.ACTIVE.value in states
        assert StrategyLifecycleState.STOPPED.value in states

    @pytest.mark.asyncio
    async def test_pause_persists_paused_state(self):
        persistence = make_persistence()
        engine = make_engine()
        coord = self._make_coordinator(persistence, engine)

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.register(make_config(), MockStrategy())
            await coord.start("strat_1")
            await coord.pause("strat_1")
            await coord.stop("strat_1")

        states = [
            (c.args[1] if len(c.args) >= 2 else c.kwargs["record"]).lifecycle_state
            for c in persistence.save_strategy.call_args_list
        ]
        assert StrategyLifecycleState.PAUSED.value in states

    @pytest.mark.asyncio
    async def test_resume_persists_active_state(self):
        persistence = make_persistence()
        engine = make_engine()
        coord = self._make_coordinator(persistence, engine)

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.register(make_config(), MockStrategy())
            await coord.start("strat_1")
            await coord.pause("strat_1")
            await coord.resume("strat_1")
            await coord.stop("strat_1")

        states = [
            (c.args[1] if len(c.args) >= 2 else c.kwargs["record"]).lifecycle_state
            for c in persistence.save_strategy.call_args_list
        ]
        # ACTIVE appears at least twice (start + resume)
        assert states.count(StrategyLifecycleState.ACTIVE.value) >= 2

    @pytest.mark.asyncio
    async def test_no_persistence_calls_without_adapter(self):
        """Coordinator without persistence/engine never calls save_strategy."""
        coord = self._make_coordinator()
        result = await coord.register(make_config(), MockStrategy())
        assert result.success is True
        # No exception, no persistence calls — covered by not raising

    @pytest.mark.asyncio
    async def test_persistence_failure_does_not_break_registration(self):
        """If save_strategy raises, register() still succeeds."""
        persistence = make_persistence()
        persistence.save_strategy = AsyncMock(side_effect=Exception("DB down"))
        engine = make_engine()
        coord = self._make_coordinator(persistence, engine)

        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(AsyncMock())
            result = await coord.register(make_config(), MockStrategy())

        assert result.success is True

    @pytest.mark.asyncio
    async def test_shutting_down_rejects_register(self):
        coord = self._make_coordinator()
        coord._shutting_down = True
        result = await coord.register(make_config(), MockStrategy())
        assert result.success is False
        assert "shutting down" in result.error_message

    @pytest.mark.asyncio
    async def test_deregister_calls_save_stopped(self):
        persistence = make_persistence()
        engine = make_engine()
        coord = self._make_coordinator(persistence, engine)

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.register(make_config(), MockStrategy())
            await coord.deregister("strat_1")

        states = [
            (c.args[1] if len(c.args) >= 2 else c.kwargs["record"]).lifecycle_state
            for c in persistence.save_strategy.call_args_list
        ]
        assert StrategyLifecycleState.STOPPED.value in states

    @pytest.mark.asyncio
    async def test_backward_compat_no_persistence_kwarg(self):
        """StrategyCoordinator(mds, feb, cb, sr) — 4-arg form still works."""
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        coord = StrategyCoordinator(mds, feb, cb, sr)
        result = await coord.register(make_config(), MockStrategy())
        assert result.success is True


# ---------------------------------------------------------------------------
# TestCoordinatorRecovery
# ---------------------------------------------------------------------------

class TestCoordinatorRecovery:

    def _make_coordinator(self):
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        persistence = make_persistence()
        return StrategyCoordinator(
            mds, feb, cb, sr,
            persistence=persistence,
            engine=make_engine(),
        ), persistence

    @pytest.mark.asyncio
    async def test_recover_returns_result_with_no_records(self):
        coord, persistence = self._make_coordinator()
        persistence.list_non_terminal_strategies = AsyncMock(return_value=[])
        persistence.list_all_signals = AsyncMock(return_value=[])

        session = AsyncMock()
        result = await coord.recover(session)

        assert result.strategies_restored == []
        assert result.signals_restored == 0
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_recover_without_persistence_returns_empty(self):
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        coord = StrategyCoordinator(mds, feb, cb, sr)
        session = AsyncMock()
        result = await coord.recover(session)
        assert result.strategies_restored == []

    @pytest.mark.asyncio
    async def test_recover_calls_list_non_terminal(self):
        coord, persistence = self._make_coordinator()
        persistence.list_non_terminal_strategies = AsyncMock(return_value=[])
        persistence.list_all_signals = AsyncMock(return_value=[])

        session = AsyncMock()
        await coord.recover(session)
        persistence.list_non_terminal_strategies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recover_calls_list_all_signals(self):
        coord, persistence = self._make_coordinator()
        persistence.list_non_terminal_strategies = AsyncMock(return_value=[])
        persistence.list_all_signals = AsyncMock(return_value=[])

        session = AsyncMock()
        await coord.recover(session)
        persistence.list_all_signals.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recover_null_factory_skips_all_strategies(self):
        """Without a factory, all strategies land in errors/skipped."""
        from src.strategy.persistence import StrategyConfigRecord

        coord, persistence = self._make_coordinator()
        rec = StrategyConfigRecord(
            strategy_id="s1",
            strategy_type="mock",
            name="S1",
            account_id=None,
            configuration={},
            instrument_tokens=["RELIANCE"],
            lifecycle_state="ACTIVE",
            enabled=True,
        )
        persistence.list_non_terminal_strategies = AsyncMock(return_value=[rec])
        persistence.list_all_signals = AsyncMock(return_value=[])

        session = AsyncMock()
        result = await coord.recover(session)
        # No factory → create() raises → strategy ends up in errors or skipped
        assert "s1" in result.strategies_skipped or len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_recover_with_factory_restores_strategy(self):
        from src.strategy.persistence import StrategyConfigRecord

        coord, persistence = self._make_coordinator()
        rec = StrategyConfigRecord(
            strategy_id="s1",
            strategy_type="mock",
            name="S1",
            account_id=None,
            configuration={},
            instrument_tokens=["RELIANCE"],
            lifecycle_state="REGISTERED",
            enabled=True,
        )
        persistence.list_non_terminal_strategies = AsyncMock(return_value=[rec])
        persistence.list_all_signals = AsyncMock(return_value=[])
        persistence.load_latest_state_snapshot = AsyncMock(return_value=None)

        class MockFactory:
            async def create(self, strategy_type, strategy_id, config):
                return MockStrategy()

        session = AsyncMock()
        result = await coord.recover(session, factory=MockFactory())
        assert "s1" in result.strategies_restored


# ---------------------------------------------------------------------------
# TestRuntimeSignalPersistence
# ---------------------------------------------------------------------------

class TestRuntimeSignalPersistence:

    def _make_runtime(self, persistence=None, engine=None):
        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        strategy = MockStrategy()
        return StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            persistence=persistence,
            engine=engine,
        )

    @pytest.mark.asyncio
    async def test_signal_persisted_before_callback(self):
        """save_signal must be awaited before signal_callback fires."""
        persistence = make_persistence()
        engine = make_engine()

        callback_order = []

        def signal_callback(signal):
            callback_order.append("callback")

        persistence.save_signal = AsyncMock(
            side_effect=lambda *a, **kw: callback_order.append("persist") or None
        )

        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        signal = make_signal()
        strategy = MockStrategy()
        strategy.on_bar = lambda bar, ctx: signal

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            signal_callback=signal_callback,
            persistence=persistence,
            engine=engine,
        )

        mock_session = AsyncMock()
        with patch("strategy.runtime.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await runtime.start()
            await runtime.on_bar(make_bar())
            await asyncio.sleep(0.15)
            await runtime.stop()

        assert "persist" in callback_order
        assert "callback" in callback_order
        assert callback_order.index("persist") < callback_order.index("callback")

    @pytest.mark.asyncio
    async def test_save_signal_called_with_pending_status(self):
        persistence = make_persistence()
        engine = make_engine()

        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        signal = make_signal()
        strategy = MockStrategy()
        strategy.on_bar = lambda bar, ctx: signal

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            persistence=persistence,
            engine=engine,
        )

        mock_session = AsyncMock()
        with patch("strategy.runtime.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await runtime.start()
            await runtime.on_bar(make_bar())
            await asyncio.sleep(0.15)
            await runtime.stop()

        persistence.save_signal.assert_awaited()
        call_args = persistence.save_signal.call_args
        record = call_args.args[1] if len(call_args.args) >= 2 else call_args.kwargs["record"]
        assert record.routing_status == "PENDING"

    @pytest.mark.asyncio
    async def test_no_persistence_does_not_call_save_signal(self):
        """Runtime without persistence/engine never calls save_signal."""
        persistence = make_persistence()
        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        signal = make_signal()
        strategy = MockStrategy()
        strategy.on_bar = lambda bar, ctx: signal

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
        )

        await runtime.start()
        await runtime.on_bar(make_bar())
        await asyncio.sleep(0.1)
        await runtime.stop()

        persistence.save_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_signal_persistence_failure_does_not_drop_signal(self):
        """If save_signal raises, signal still reaches the queue and callback."""
        persistence = make_persistence()
        persistence.save_signal = AsyncMock(side_effect=Exception("DB error"))
        engine = make_engine()

        received = []

        def callback(s):
            received.append(s)

        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        signal = make_signal()
        strategy = MockStrategy()
        strategy.on_bar = lambda bar, ctx: signal

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            signal_callback=callback,
            persistence=persistence,
            engine=engine,
        )

        mock_session = AsyncMock()
        with patch("strategy.runtime.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await runtime.start()
            await runtime.on_bar(make_bar())
            await asyncio.sleep(0.15)
            await runtime.stop()

        assert len(received) == 1


# ---------------------------------------------------------------------------
# TestRoutingStatusUpdate
# ---------------------------------------------------------------------------

class TestRoutingStatusUpdate:

    def _make_coordinator_with_persistence(self):
        persistence = make_persistence()
        engine = make_engine()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        coord = StrategyCoordinator(
            mds, feb, cb, sr,
            persistence=persistence,
            engine=engine,
        )
        return coord, persistence

    @pytest.mark.asyncio
    async def test_mark_signal_routed_called_on_success(self):
        from strategy.contracts import SignalRoutingResult
        coord, persistence = self._make_coordinator_with_persistence()
        config = make_config()

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.register(config, MockStrategy())

        signal = make_signal()
        routed_result = SignalRoutingResult(
            signal_id=signal.signal_id,
            routed=True,
            client_order_id="coid_123",
            status="ROUTED",
        )
        coord._signal_router.route_signal = AsyncMock(return_value=routed_result)

        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord._route_signal_task(signal)

        persistence.mark_signal_routed.assert_awaited_once()
        call = persistence.mark_signal_routed.call_args
        assert call.args[1] == signal.signal_id or call.kwargs.get("signal_id") == signal.signal_id

    @pytest.mark.asyncio
    async def test_mark_signal_rejected_called_on_rejection(self):
        from strategy.contracts import SignalRoutingResult
        coord, persistence = self._make_coordinator_with_persistence()
        config = make_config()

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.register(config, MockStrategy())

        signal = make_signal()
        rejected_result = SignalRoutingResult(
            signal_id=signal.signal_id,
            routed=False,
            status="REJECTED",
            rejection_reason="rate limit",
        )
        coord._signal_router.route_signal = AsyncMock(return_value=rejected_result)

        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord._route_signal_task(signal)

        persistence.mark_signal_rejected.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_routing_persistence_without_adapter(self):
        """Without persistence/engine, _route_signal_task never calls mark_signal_routed."""
        from strategy.contracts import SignalRoutingResult
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        coord = StrategyCoordinator(mds, feb, cb, sr)
        await coord.register(make_config(), MockStrategy())

        signal = make_signal()
        routed_result = SignalRoutingResult(
            signal_id=signal.signal_id,
            routed=True,
            client_order_id="coid_xyz",
            status="ROUTED",
        )
        coord._signal_router.route_signal = AsyncMock(return_value=routed_result)
        # Should not raise even without persistence
        await coord._route_signal_task(signal)


# ---------------------------------------------------------------------------
# TestStateSnapshotPersistence
# ---------------------------------------------------------------------------

class TestStateSnapshotPersistence:

    @pytest.mark.asyncio
    async def test_snapshot_pushed_after_bar(self):
        persistence = make_persistence()
        engine = make_engine()

        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        strategy = MockStrategy()

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            persistence=persistence,
            engine=engine,
        )

        mock_session = AsyncMock()
        with patch("strategy.runtime.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await runtime.start()
            await runtime.on_bar(make_bar())
            await asyncio.sleep(0.2)
            await runtime.stop()

        persistence.save_state_snapshot.assert_awaited()

    @pytest.mark.asyncio
    async def test_snapshot_lifecycle_state_matches_runtime(self):
        persistence = make_persistence()
        engine = make_engine()

        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        strategy = MockStrategy()

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            persistence=persistence,
            engine=engine,
        )

        mock_session = AsyncMock()
        with patch("strategy.runtime.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await runtime.start()
            await runtime.on_bar(make_bar())
            await asyncio.sleep(0.2)
            await runtime.stop()

        call = persistence.save_state_snapshot.call_args
        record = call.args[1] if len(call.args) >= 2 else call.kwargs["record"]
        assert record.lifecycle_state == StrategyLifecycleState.ACTIVE.value

    @pytest.mark.asyncio
    async def test_snapshot_failure_does_not_break_bar_processing(self):
        persistence = make_persistence()
        persistence.save_state_snapshot = AsyncMock(side_effect=Exception("DB error"))
        engine = make_engine()

        received = []

        def callback(s):
            received.append(s)

        config = make_config()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        signal = make_signal()
        strategy = MockStrategy()
        strategy.on_bar = lambda bar, ctx: signal

        runtime = StrategyRuntime(
            config=config,
            strategy=strategy,
            context_builder=cb,
            market_data_service=mds,
            fill_event_bus=feb,
            signal_callback=callback,
            persistence=persistence,
            engine=engine,
        )

        mock_session = AsyncMock()
        with patch("strategy.runtime.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await runtime.start()
            await runtime.on_bar(make_bar())
            await asyncio.sleep(0.2)
            await runtime.stop()

        # Signal still delivered despite snapshot failure
        assert len(received) == 1


# ---------------------------------------------------------------------------
# TestNoCommitInCoordinator
# ---------------------------------------------------------------------------

class TestNoCommitInCoordinator:

    def _scan_file(self, path: str) -> list[str]:
        """Return list of bare .commit()/.rollback()/.close() call locations."""
        text = Path(path).read_text()
        tree = ast.parse(text)
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"commit", "rollback", "close"}:
                violations.append(f"{path}:line~{getattr(node, 'lineno', '?')}:.{node.attr}")
        return violations

    def test_no_commit_in_coordinator(self):
        violations = self._scan_file("src/strategy/coordinator.py")
        # SessionContext itself is allowed to have commit/rollback/close
        # but coordinator.py must not call them directly on the session
        assert violations == [], f"Violations: {violations}"

    def test_no_commit_in_runtime(self):
        violations = self._scan_file("src/strategy/runtime.py")
        assert violations == [], f"Violations: {violations}"

    def test_no_commit_in_persistence(self):
        violations = self._scan_file("src/strategy/persistence.py")
        assert violations == [], f"Violations: {violations}"
