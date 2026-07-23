"""Batch 9D-B — Production hardening tests.

Covers:
  TestStrategyMetrics          — MetricsCollector counters and latency
  TestStrategyHealthMonitor    — threshold-based health computation
  TestFaultIsolator            — error budget enforcement and isolation
  TestCoordinatorHealthIntegration — coordinator.get_health() / get_all_health()
  TestCoordinatorMetricsIntegration — coordinator.get_metrics() / get_all_metrics()
  TestGracefulShutdown         — coordinator.shutdown() ordered sequence

All persistence uses AsyncMock — no real DB connections.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategy.coordinator import StrategyCoordinator, ShutdownResult
from strategy.contracts import (
    StrategyConfig,
    StrategyLifecycleState,
    Signal,
    SignalAction,
)
from strategy.fault_isolation import FaultAction, FaultBudget, FaultIsolator
from strategy.health import StrategyHealthMonitor, StrategyHealthStatus
from strategy.metrics import MetricsCollector, StrategyMetrics
from market_data.contracts import CompletedBar
from market_data.service import MarketDataService
from execution.contracts import ExecutionOrderSide
from risk.fill_event_bus import FillEventBus
from strategy.context_builder import ContextBuilder
from strategy.signal_router import SignalRouter
from strategy.runtime import StrategyRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockStrategy:
    @property
    def strategy_type(self):
        return "mock"
    def on_bar(self, bar, ctx): return None
    def on_tick(self, tick, ctx): return None
    def on_fill(self, fill, ctx): return None
    def validate_config(self, cfg): return []


def make_config(sid="strat_1"):
    return StrategyConfig(
        strategy_id=sid,
        strategy_type="mock",
        name="Test",
        instrument_tokens=["RELIANCE"],
    )


def make_bar():
    return CompletedBar(
        instrument_token="RELIANCE",
        timestamp=datetime.utcnow(),
        open=Decimal("100"), high=Decimal("110"),
        low=Decimal("95"), close=Decimal("105"),
        volume=Decimal("10000"), interval="1m",
    )


def make_coordinator(
    with_metrics=False,
    with_health=False,
    with_fault=False,
    persistence=None,
    engine=None,
):
    mds = MarketDataService()
    feb = FillEventBus()
    cb = ContextBuilder(mds)
    sr = SignalRouter()
    mc = MetricsCollector() if with_metrics else None
    hm = StrategyHealthMonitor(mc) if (with_health and mc) else None
    fi = FaultIsolator() if with_fault else None
    return (
        StrategyCoordinator(
            mds, feb, cb, sr,
            persistence=persistence,
            engine=engine,
            metrics=mc,
            health_monitor=hm,
            fault_isolator=fi,
        ),
        mc, hm, fi,
    )


def patch_session_context(mock_session):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


# ---------------------------------------------------------------------------
# TestStrategyMetrics
# ---------------------------------------------------------------------------

class TestStrategyMetrics:

    @pytest.mark.asyncio
    async def test_initial_metrics_all_zero(self):
        mc = MetricsCollector()
        mc.initialize("s1")
        m = mc.get_metrics("s1")
        assert m is not None
        assert m.bars_processed == 0
        assert m.signals_emitted == 0
        assert m.error_count == 0
        assert m.consecutive_errors == 0

    @pytest.mark.asyncio
    async def test_record_bar_increments_counter(self):
        mc = MetricsCollector()
        await mc.record_bar("s1", 12.5)
        m = mc.get_metrics("s1")
        assert m.bars_processed == 1
        assert m.last_bar_latency_ms == pytest.approx(12.5)

    @pytest.mark.asyncio
    async def test_record_bar_computes_avg_latency(self):
        mc = MetricsCollector()
        await mc.record_bar("s1", 10.0)
        await mc.record_bar("s1", 20.0)
        m = mc.get_metrics("s1")
        assert m.bars_processed == 2
        assert m.avg_bar_latency_ms == pytest.approx(15.0)

    @pytest.mark.asyncio
    async def test_record_error_increments_consecutive(self):
        mc = MetricsCollector()
        await mc.record_error("s1")
        await mc.record_error("s1")
        m = mc.get_metrics("s1")
        assert m.consecutive_errors == 2
        assert m.error_count == 2

    @pytest.mark.asyncio
    async def test_record_bar_resets_consecutive_errors(self):
        mc = MetricsCollector()
        await mc.record_error("s1")
        await mc.record_error("s1")
        await mc.record_bar("s1", 5.0)
        m = mc.get_metrics("s1")
        assert m.consecutive_errors == 0
        assert m.error_count == 2  # total error count preserved

    @pytest.mark.asyncio
    async def test_record_success_resets_consecutive(self):
        mc = MetricsCollector()
        await mc.record_error("s1")
        await mc.record_success("s1")
        m = mc.get_metrics("s1")
        assert m.consecutive_errors == 0

    @pytest.mark.asyncio
    async def test_record_signal_increments(self):
        mc = MetricsCollector()
        await mc.record_signal("s1")
        await mc.record_signal("s1")
        m = mc.get_metrics("s1")
        assert m.signals_emitted == 2

    @pytest.mark.asyncio
    async def test_record_fill_increments(self):
        mc = MetricsCollector()
        await mc.record_fill("s1")
        m = mc.get_metrics("s1")
        assert m.fill_count == 1

    @pytest.mark.asyncio
    async def test_get_all_metrics_returns_all(self):
        mc = MetricsCollector()
        mc.initialize("s1")
        mc.initialize("s2")
        all_m = mc.get_all_metrics()
        assert "s1" in all_m
        assert "s2" in all_m

    @pytest.mark.asyncio
    async def test_remove_drops_strategy(self):
        mc = MetricsCollector()
        mc.initialize("s1")
        mc.remove("s1")
        assert mc.get_metrics("s1") is None

    @pytest.mark.asyncio
    async def test_metrics_are_immutable_snapshots(self):
        mc = MetricsCollector()
        await mc.record_bar("s1", 5.0)
        snapshot1 = mc.get_metrics("s1")
        await mc.record_bar("s1", 10.0)
        snapshot2 = mc.get_metrics("s1")
        assert snapshot1.bars_processed == 1
        assert snapshot2.bars_processed == 2

    @pytest.mark.asyncio
    async def test_no_metrics_returns_none(self):
        mc = MetricsCollector()
        assert mc.get_metrics("nonexistent") is None


# ---------------------------------------------------------------------------
# TestStrategyHealthMonitor
# ---------------------------------------------------------------------------

class TestStrategyHealthMonitor:

    def _monitor(self, **kwargs):
        mc = MetricsCollector()
        return StrategyHealthMonitor(mc, **kwargs), mc

    def test_unknown_for_new_strategy(self):
        monitor, mc = self._monitor()
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_healthy_with_no_errors(self):
        monitor, mc = self._monitor()
        await mc.record_bar("s1", 10.0)
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_degraded_on_consecutive_error_threshold(self):
        monitor, mc = self._monitor(degraded_consecutive_errors=3)
        for _ in range(3):
            await mc.record_error("s1")
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_unhealthy_on_higher_consecutive_errors(self):
        monitor, mc = self._monitor(
            degraded_consecutive_errors=3,
            unhealthy_consecutive_errors=5,
        )
        for _ in range(5):
            await mc.record_error("s1")
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_degraded_on_high_latency(self):
        monitor, mc = self._monitor(degraded_latency_ms=200.0, unhealthy_latency_ms=1000.0)
        await mc.record_bar("s1", 300.0)
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_unhealthy_on_very_high_latency(self):
        monitor, mc = self._monitor(degraded_latency_ms=200.0, unhealthy_latency_ms=1000.0)
        await mc.record_bar("s1", 1500.0)
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_healthy_after_error_reset(self):
        monitor, mc = self._monitor(degraded_consecutive_errors=3)
        await mc.record_error("s1")
        await mc.record_error("s1")
        await mc.record_bar("s1", 5.0)  # resets consecutive
        report = monitor.compute_health("s1")
        assert report.status == StrategyHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_report_contains_correct_counts(self):
        monitor, mc = self._monitor()
        await mc.record_bar("s1", 50.0)
        await mc.record_signal("s1")
        report = monitor.compute_health("s1")
        assert report.bars_processed == 1
        assert report.signals_emitted == 1
        assert report.last_bar_latency_ms == pytest.approx(50.0)

    def test_is_healthy_convenience(self):
        monitor, mc = self._monitor()
        assert monitor.is_healthy("s1") is False  # UNKNOWN → not healthy

    @pytest.mark.asyncio
    async def test_get_all_health(self):
        monitor, mc = self._monitor()
        await mc.record_bar("s1", 5.0)
        await mc.record_bar("s2", 5.0)
        reports = monitor.get_all_health(["s1", "s2"])
        assert "s1" in reports and "s2" in reports

    @pytest.mark.asyncio
    async def test_any_unhealthy(self):
        monitor, mc = self._monitor(unhealthy_consecutive_errors=2)
        await mc.record_error("s1")
        await mc.record_error("s1")
        await mc.record_bar("s2", 5.0)
        assert monitor.any_unhealthy(["s1", "s2"]) is True
        assert monitor.any_unhealthy(["s2"]) is False


# ---------------------------------------------------------------------------
# TestFaultIsolator
# ---------------------------------------------------------------------------

class TestFaultIsolator:

    @pytest.mark.asyncio
    async def test_returns_none_within_budget(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=5))
        action = await fi.record_error("s1")
        assert action == FaultAction.NONE

    @pytest.mark.asyncio
    async def test_returns_pause_on_budget_breach(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=3, auto_pause_on_breach=True))
        for _ in range(3):
            action = await fi.record_error("s1")
        assert action == FaultAction.PAUSE

    @pytest.mark.asyncio
    async def test_returns_stop_when_configured(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=3, auto_pause_on_breach=False))
        for _ in range(3):
            action = await fi.record_error("s1")
        assert action == FaultAction.STOP

    @pytest.mark.asyncio
    async def test_isolated_sticky_after_breach(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=2))
        for _ in range(2):
            await fi.record_error("s1")
        assert fi.is_isolated("s1") is True
        action = await fi.record_error("s1")  # already isolated
        assert action == FaultAction.PAUSE

    @pytest.mark.asyncio
    async def test_reset_isolation_clears_flag(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=1))
        await fi.record_error("s1")
        assert fi.is_isolated("s1") is True
        await fi.reset_isolation("s1")
        assert fi.is_isolated("s1") is False

    @pytest.mark.asyncio
    async def test_record_success_resets_consecutive(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=5))
        await fi.record_error("s1")
        await fi.record_error("s1")
        await fi.record_success("s1")
        status = fi.get_status("s1")
        assert status.consecutive_errors == 0

    @pytest.mark.asyncio
    async def test_custom_budget_per_strategy(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=10))
        fi.configure_budget("s1", FaultBudget(max_consecutive_errors=2))
        for _ in range(2):
            action = await fi.record_error("s1")
        assert action == FaultAction.PAUSE

    @pytest.mark.asyncio
    async def test_per_minute_rate_isolation(self):
        fi = FaultIsolator(FaultBudget(max_errors_per_minute=3, max_consecutive_errors=100))
        for _ in range(3):
            action = await fi.record_error("s1")
        assert action == FaultAction.PAUSE
        assert fi.is_isolated("s1") is True

    @pytest.mark.asyncio
    async def test_isolation_reason_set(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=2))
        await fi.record_error("s1")
        await fi.record_error("s1")
        reason = fi.get_isolation_reason("s1")
        assert reason is not None and len(reason) > 0

    @pytest.mark.asyncio
    async def test_get_status_returns_correct_counts(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=10))
        await fi.record_error("s1")
        status = fi.get_status("s1")
        assert status.consecutive_errors == 1
        assert status.is_isolated is False

    @pytest.mark.asyncio
    async def test_remove_clears_all_state(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=1))
        await fi.record_error("s1")
        fi.remove("s1")
        assert fi.is_isolated("s1") is False
        status = fi.get_status("s1")
        assert status.consecutive_errors == 0

    @pytest.mark.asyncio
    async def test_independent_budgets_per_strategy(self):
        fi = FaultIsolator(FaultBudget(max_consecutive_errors=3))
        await fi.record_error("s1")
        await fi.record_error("s1")
        # s2 has no errors — should not be affected
        status_s2 = fi.get_status("s2")
        assert status_s2.consecutive_errors == 0
        assert status_s2.is_isolated is False


# ---------------------------------------------------------------------------
# TestCoordinatorHealthIntegration
# ---------------------------------------------------------------------------

class TestCoordinatorHealthIntegration:

    @pytest.mark.asyncio
    async def test_get_health_returns_report(self):
        coord, mc, hm, fi = make_coordinator(with_metrics=True, with_health=True)
        await coord.register(make_config(), MockStrategy())
        report = coord.get_health("strat_1")
        assert report is not None
        assert report.strategy_id == "strat_1"

    @pytest.mark.asyncio
    async def test_get_health_healthy_for_new_strategy(self):
        """After register(), metrics are initialized — health is HEALTHY (no errors yet)."""
        coord, mc, hm, fi = make_coordinator(with_metrics=True, with_health=True)
        await coord.register(make_config(), MockStrategy())
        report = coord.get_health("strat_1")
        # metrics.initialize() is called on register → entry exists → no errors → HEALTHY
        assert report.status == StrategyHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_get_all_health_covers_all_registered(self):
        coord, mc, hm, fi = make_coordinator(with_metrics=True, with_health=True)
        for i in range(3):
            await coord.register(make_config(f"s{i}"), MockStrategy())
        reports = coord.get_all_health()
        assert len(reports) == 3

    @pytest.mark.asyncio
    async def test_get_health_returns_none_without_monitor(self):
        coord, *_ = make_coordinator(with_metrics=False, with_health=False)
        await coord.register(make_config(), MockStrategy())
        assert coord.get_health("strat_1") is None

    @pytest.mark.asyncio
    async def test_get_all_health_returns_empty_without_monitor(self):
        coord, *_ = make_coordinator()
        assert coord.get_all_health() == {}


# ---------------------------------------------------------------------------
# TestCoordinatorMetricsIntegration
# ---------------------------------------------------------------------------

class TestCoordinatorMetricsIntegration:

    @pytest.mark.asyncio
    async def test_get_metrics_initialized_on_register(self):
        coord, mc, hm, fi = make_coordinator(with_metrics=True)
        await coord.register(make_config(), MockStrategy())
        m = coord.get_metrics("strat_1")
        assert m is not None
        assert m.strategy_id == "strat_1"

    @pytest.mark.asyncio
    async def test_get_metrics_returns_none_without_collector(self):
        coord, *_ = make_coordinator()
        await coord.register(make_config(), MockStrategy())
        assert coord.get_metrics("strat_1") is None

    @pytest.mark.asyncio
    async def test_get_all_metrics_covers_all_registered(self):
        coord, mc, hm, fi = make_coordinator(with_metrics=True)
        for i in range(2):
            await coord.register(make_config(f"s{i}"), MockStrategy())
        all_m = coord.get_all_metrics()
        assert "s0" in all_m and "s1" in all_m

    @pytest.mark.asyncio
    async def test_metrics_removed_on_deregister(self):
        coord, mc, hm, fi = make_coordinator(with_metrics=True)
        await coord.register(make_config(), MockStrategy())
        assert coord.get_metrics("strat_1") is not None
        await coord.deregister("strat_1")
        assert coord.get_metrics("strat_1") is None


# ---------------------------------------------------------------------------
# TestGracefulShutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:

    @pytest.mark.asyncio
    async def test_shutdown_returns_shutdown_result(self):
        coord, *_ = make_coordinator()
        result = await coord.shutdown()
        assert isinstance(result, ShutdownResult)

    @pytest.mark.asyncio
    async def test_shutdown_stops_all_active_strategies(self):
        coord, *_ = make_coordinator()
        for i in range(3):
            await coord.register(make_config(f"s{i}"), MockStrategy())
            await coord.start(f"s{i}")

        result = await coord.shutdown()
        assert len(result.strategies_stopped) == 3
        assert len(result.strategies_failed) == 0

    @pytest.mark.asyncio
    async def test_shutdown_marks_coordinator_as_shutting_down(self):
        coord, *_ = make_coordinator()
        assert coord.is_shutting_down() is False
        await coord.shutdown()
        assert coord.is_shutting_down() is True

    @pytest.mark.asyncio
    async def test_register_rejected_after_shutdown(self):
        coord, *_ = make_coordinator()
        await coord.shutdown()
        result = await coord.register(make_config(), MockStrategy())
        assert result.success is False
        assert "shutting down" in result.error_message

    @pytest.mark.asyncio
    async def test_shutdown_with_no_active_strategies(self):
        coord, *_ = make_coordinator()
        await coord.register(make_config(), MockStrategy())
        # Not started — so runtimes dict is empty
        result = await coord.shutdown()
        assert result.strategies_stopped == []
        assert result.strategies_failed == []

    @pytest.mark.asyncio
    async def test_shutdown_completes_after_timeout_param(self):
        coord, *_ = make_coordinator()
        # Even with a tiny timeout, shutdown must complete
        result = await coord.shutdown(timeout_seconds=0.1)
        assert isinstance(result, ShutdownResult)

    @pytest.mark.asyncio
    async def test_shutdown_flushes_snapshots_when_persistence_set(self):
        persistence = MagicMock()
        persistence.save_strategy = AsyncMock()
        persistence.save_state_snapshot = AsyncMock()
        engine = MagicMock()
        mds = MarketDataService()
        feb = FillEventBus()
        cb = ContextBuilder(mds)
        sr = SignalRouter()
        coord = StrategyCoordinator(
            mds, feb, cb, sr,
            persistence=persistence,
            engine=engine,
        )
        await coord.register(make_config(), MockStrategy())

        mock_session = AsyncMock()
        with patch("strategy.coordinator.SessionContext") as MockSC:
            MockSC.return_value = patch_session_context(mock_session)
            await coord.start("strat_1")
            result = await coord.shutdown()

        # save_state_snapshot is called once per active runtime during shutdown
        persistence.save_state_snapshot.assert_awaited()
        assert result.snapshots_flushed >= 1

    @pytest.mark.asyncio
    async def test_shutdown_result_completed_at_is_recent(self):
        coord, *_ = make_coordinator()
        before = datetime.now(timezone.utc)
        result = await coord.shutdown()
        after = datetime.now(timezone.utc)
        assert before <= result.completed_at <= after

    @pytest.mark.asyncio
    async def test_shutdown_idempotent_second_call(self):
        coord, *_ = make_coordinator()
        result1 = await coord.shutdown()
        result2 = await coord.shutdown()
        assert isinstance(result1, ShutdownResult)
        assert isinstance(result2, ShutdownResult)

    @pytest.mark.asyncio
    async def test_fault_isolation_cleared_on_resume(self):
        coord, mc, hm, fi = make_coordinator(with_fault=True)
        await coord.register(make_config(), MockStrategy())
        await coord.start("strat_1")
        # Manually isolate
        fi._isolated["strat_1"] = "test isolation"
        assert fi.is_isolated("strat_1") is True
        # Resume should clear isolation
        await coord.resume("strat_1")
        assert fi.is_isolated("strat_1") is False
        await coord.stop("strat_1")
