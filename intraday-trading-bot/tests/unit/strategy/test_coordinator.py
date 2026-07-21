"""Tests for strategy/coordinator.py."""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from strategy.coordinator import StrategyCoordinator
from strategy.contracts import (
    StrategyConfig,
    StrategyLifecycleState,
    StrategyRegistrationResult,
)
from strategy.strategy_protocol import Strategy
from strategy.runtime import StrategyRuntime
from strategy.signal_router import SignalRouter
from strategy.context_builder import ContextBuilder
from strategy.exceptions import (
    StrategyNotFoundError,
    StrategyAlreadyRegisteredError,
)
from market_data.service import MarketDataService
from risk.fill_event_bus import FillEventBus


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


@pytest.fixture
def coordinator():
    mds = MarketDataService()
    feb = FillEventBus()
    cb = ContextBuilder(mds)
    sr = SignalRouter()
    return StrategyCoordinator(mds, feb, cb, sr)

@pytest.fixture
def base_config():
    return StrategyConfig(
        strategy_id="test_strat",
        strategy_type="mock",
        name="Test Strategy",
        instrument_tokens=["RELIANCE"],
    )


class TestStrategyCoordinator:
    @pytest.mark.asyncio
    async def test_register_strategy(self, coordinator, base_config):
        strategy = MockStrategy()
        result = await coordinator.register(base_config, strategy)
        assert result.success is True
        assert result.strategy_id == "test_strat"

    @pytest.mark.asyncio
    async def test_register_duplicate_fails(self, coordinator, base_config):
        strategy = MockStrategy()
        await coordinator.register(base_config, strategy)
        result = await coordinator.register(base_config, strategy)
        assert result.success is False
        assert "already registered" in result.error_message

    @pytest.mark.asyncio
    async def test_register_invalid_config(self, coordinator):
        class BadStrategy(MockStrategy):
            def validate_config(self, config):
                return ["parameter X is invalid"]

        config = StrategyConfig(
            strategy_id="bad",
            strategy_type="bad",
            name="Bad",
        )
        strategy = BadStrategy()
        result = await coordinator.register(config, strategy)
        assert result.success is False
        assert "validation failed" in result.error_message

    @pytest.mark.asyncio
    async def test_start_strategy(self, coordinator, base_config):
        strategy = MockStrategy()
        await coordinator.register(base_config, strategy)
        await coordinator.start("test_strat")

        state = coordinator.get_strategy("test_strat")
        assert state is not None
        assert state.lifecycle_state == StrategyLifecycleState.ACTIVE

        await coordinator.stop("test_strat")

    @pytest.mark.asyncio
    async def test_start_unregistered_raises(self, coordinator):
        with pytest.raises(StrategyNotFoundError):
            await coordinator.start("nonexistent")

    @pytest.mark.asyncio
    async def test_stop_strategy(self, coordinator, base_config):
        strategy = MockStrategy()
        await coordinator.register(base_config, strategy)
        await coordinator.start("test_strat")
        await coordinator.stop("test_strat")

        state = coordinator.get_strategy("test_strat")
        assert state.lifecycle_state == StrategyLifecycleState.STOPPED

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, coordinator, base_config):
        strategy = MockStrategy()
        await coordinator.register(base_config, strategy)
        await coordinator.start("test_strat")

        await coordinator.pause("test_strat")
        state = coordinator.get_strategy("test_strat")
        assert state.lifecycle_state == StrategyLifecycleState.PAUSED

        await coordinator.resume("test_strat")
        state = coordinator.get_strategy("test_strat")
        assert state.lifecycle_state == StrategyLifecycleState.ACTIVE

        await coordinator.stop("test_strat")

    @pytest.mark.asyncio
    async def test_deregister(self, coordinator, base_config):
        strategy = MockStrategy()
        await coordinator.register(base_config, strategy)
        await coordinator.start("test_strat")
        await coordinator.deregister("test_strat")

        assert coordinator.get_strategy("test_strat") is None

    @pytest.mark.asyncio
    async def test_list_strategies(self, coordinator):
        for i in range(3):
            config = StrategyConfig(
                strategy_id=f"strat_{i}",
                strategy_type="mock",
                name=f"Strategy {i}",
            )
            strategy = MockStrategy()
            await coordinator.register(config, strategy)

        strategies = coordinator.list_strategies()
        assert len(strategies) == 3
        assert all(s.lifecycle_state == StrategyLifecycleState.REGISTERED for s in strategies)

    @pytest.mark.asyncio
    async def test_emergency_stop_all(self, coordinator, base_config):
        for i in range(3):
            config = StrategyConfig(
                strategy_id=f"strat_{i}",
                strategy_type="mock",
                name=f"Strategy {i}",
                instrument_tokens=["RELIANCE"],
            )
            strategy = MockStrategy()
            await coordinator.register(config, strategy)
            await coordinator.start(f"strat_{i}")

        await coordinator.emergency_stop_all(reason="market crash")

        for i in range(3):
            state = coordinator.get_strategy(f"strat_{i}")
            assert state.lifecycle_state == StrategyLifecycleState.STOPPED

    @pytest.mark.asyncio
    async def test_get_strategy_not_found(self, coordinator):
        assert coordinator.get_strategy("nonexistent") is None

    @pytest.mark.asyncio
    async def test_per_strategy_locking(self, coordinator, base_config):
        strategy = MockStrategy()
        await coordinator.register(base_config, strategy)

        await coordinator.start("test_strat")
        await coordinator.pause("test_strat")
        await coordinator.resume("test_strat")
        await coordinator.stop("test_strat")
