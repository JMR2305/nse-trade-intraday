"""Integration tests for the Strategy Engine."""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from strategy.coordinator import StrategyCoordinator
from strategy.runtime import StrategyRuntime
from strategy.signal_router import SignalRouter
from strategy.context_builder import ContextBuilder
from strategy.contracts import (
    StrategyConfig,
    Signal,
    SignalAction,
    StrategyLifecycleState,
)
from strategy.built_in.sma_crossover import SmaCrossoverStrategy
from execution.contracts import ExecutionOrderSide, ExecutionOrder
from market_data.contracts import CompletedBar
from market_data.service import MarketDataService
from risk.fill_event_bus import FillEventBus


@pytest.fixture
def base_coordinator():
    mds = MarketDataService()
    feb = FillEventBus()
    cb = ContextBuilder(mds)
    sr = SignalRouter()
    return StrategyCoordinator(mds, feb, cb, sr)


class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_sma_strategy(self, base_coordinator):
        executed_orders = []

        async def execution_callback(session_id, order):
            executed_orders.append(order)

        router = SignalRouter(execution_callback=execution_callback)
        coordinator = StrategyCoordinator(
            base_coordinator._market_data,
            base_coordinator._fill_bus,
            base_coordinator._context_builder,
            router,
        )

        config = StrategyConfig(
            strategy_id="sma_integration",
            strategy_type="sma_crossover",
            name="SMA Integration Test",
            instrument_tokens=["RELIANCE"],
            parameters={
                "short_period": 3,
                "long_period": 5,
                "quantity": 50,
            },
            max_position_quantity=Decimal("1000"),
        )

        strategy = SmaCrossoverStrategy()

        result = await coordinator.register(config, strategy)
        assert result.success is True

        await coordinator.start("sma_integration")

        # Falling-then-rising series so short SMA crosses above long SMA
        # (short_period=3, long_period=5 from config — crossover fires at bar 9)
        prices = [110, 108, 106, 104, 102, 100, 101, 103, 106, 110]
        for price in prices:
            bar = CompletedBar(
                instrument_token="RELIANCE",
                timestamp=datetime.utcnow(),
                open=Decimal(str(price)),
                high=Decimal(str(price + 1)),
                low=Decimal(str(price - 1)),
                close=Decimal(str(price)),
                volume=Decimal("1000"),
                interval="1m",
            )
            # Use the public publish_bar helper — do not access _subscribers directly
            await base_coordinator._market_data.publish_bar("RELIANCE", bar)
            await asyncio.sleep(0.02)

        await asyncio.sleep(0.2)

        await coordinator.stop("sma_integration")

        assert len(executed_orders) >= 1
        assert executed_orders[0].instrument_token == "RELIANCE"
        assert executed_orders[0].quantity == Decimal("50")

    @pytest.mark.asyncio
    async def test_multi_strategy_no_conflict(self, base_coordinator):
        async def execution_callback(session_id, order):
            pass

        router = SignalRouter(execution_callback=execution_callback)
        coordinator = StrategyCoordinator(
            base_coordinator._market_data,
            base_coordinator._fill_bus,
            base_coordinator._context_builder,
            router,
        )

        config1 = StrategyConfig(
            strategy_id="sma_1",
            strategy_type="sma_crossover",
            name="SMA 1",
            instrument_tokens=["RELIANCE"],
            parameters={"short_period": 3, "long_period": 5, "quantity": 50},
        )
        strat1 = SmaCrossoverStrategy()
        await coordinator.register(config1, strat1)
        await coordinator.start("sma_1")

        config2 = StrategyConfig(
            strategy_id="sma_2",
            strategy_type="sma_crossover",
            name="SMA 2",
            instrument_tokens=["TCS"],
            parameters={"short_period": 3, "long_period": 5, "quantity": 30},
        )
        strat2 = SmaCrossoverStrategy()
        await coordinator.register(config2, strat2)
        await coordinator.start("sma_2")

        states = coordinator.list_strategies()
        assert len(states) == 2
        assert all(s.lifecycle_state == StrategyLifecycleState.ACTIVE for s in states)

        await coordinator.emergency_stop_all()

    @pytest.mark.asyncio
    async def test_emergency_stop_cancels_all(self, base_coordinator):
        config = StrategyConfig(
            strategy_id="emergency_test",
            strategy_type="mock",
            name="Emergency Test",
            instrument_tokens=["RELIANCE"],
        )

        class SimpleStrategy:
            @property
            def strategy_type(self):
                return "mock"
            def on_bar(self, bar, ctx):
                return None
            def on_tick(self, tick, ctx):
                return None
            def on_fill(self, fill, ctx):
                return None
            def validate_config(self, config):
                return []

        await base_coordinator.register(config, SimpleStrategy())
        await base_coordinator.start("emergency_test")

        assert base_coordinator.get_strategy("emergency_test").lifecycle_state == StrategyLifecycleState.ACTIVE

        await base_coordinator.emergency_stop_all("test emergency")

        assert base_coordinator.get_strategy("emergency_test").lifecycle_state == StrategyLifecycleState.STOPPED
