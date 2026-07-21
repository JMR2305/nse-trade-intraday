"""Tests for strategy/runtime.py."""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from strategy.runtime import StrategyRuntime
from strategy.contracts import (
    Signal,
    SignalAction,
    StrategyConfig,
    StrategyLifecycleState,
    StrategyContext,
)
from strategy.strategy_protocol import Strategy
from strategy.context_builder import ContextBuilder
from strategy.fill_tracker import StrategyFillTracker
from strategy.exceptions import StrategyRuntimeError
from market_data.contracts import CompletedBar, Tick
from market_data.service import MarketDataService
from execution.fills import FillEvent
from execution.contracts import ExecutionOrderSide, ExecutionOrderType
from risk.fill_event_bus import FillEventBus


class MockStrategy:
    """Mock strategy for testing."""

    def __init__(self, bar_signal=None, tick_signal=None, fill_signal=None):
        self.bar_signal = bar_signal
        self.tick_signal = tick_signal
        self.fill_signal = fill_signal
        self.bars_received = []
        self.ticks_received = []
        self.fills_received = []

    @property
    def strategy_type(self):
        return "mock"

    def on_bar(self, bar, context):
        self.bars_received.append(bar)
        return self.bar_signal

    def on_tick(self, tick, context):
        self.ticks_received.append(tick)
        return self.tick_signal

    def on_fill(self, fill_event, context):
        self.fills_received.append(fill_event)
        return self.fill_signal

    def validate_config(self, config):
        return []


@pytest.fixture
def market_data_service():
    return MarketDataService()

@pytest.fixture
def fill_event_bus():
    return FillEventBus()

@pytest.fixture
def context_builder(market_data_service):
    return ContextBuilder(market_data_service)

@pytest.fixture
def base_config():
    return StrategyConfig(
        strategy_id="test_strat",
        strategy_type="mock",
        name="Test Strategy",
        instrument_tokens=["RELIANCE"],
    )


class TestStrategyRuntime:
    @pytest.mark.asyncio
    async def test_runtime_creation(self, base_config, context_builder, market_data_service, fill_event_bus):
        strategy = MockStrategy()
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )
        assert runtime.strategy_id == "test_strat"
        assert runtime.lifecycle_state == StrategyLifecycleState.REGISTERED

    @pytest.mark.asyncio
    async def test_start_transitions_to_active(self, base_config, context_builder, market_data_service, fill_event_bus):
        strategy = MockStrategy()
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )
        result = await runtime.start()
        assert result.success is True
        assert result.new_state == StrategyLifecycleState.ACTIVE
        assert runtime.lifecycle_state == StrategyLifecycleState.ACTIVE
        await runtime.stop()

    @pytest.mark.asyncio
    async def test_stop_transitions_to_stopped(self, base_config, context_builder, market_data_service, fill_event_bus):
        strategy = MockStrategy()
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )
        await runtime.start()
        result = await runtime.stop()
        assert result.success is True
        assert result.new_state == StrategyLifecycleState.STOPPED
        assert runtime.lifecycle_state == StrategyLifecycleState.STOPPED

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, base_config, context_builder, market_data_service, fill_event_bus):
        strategy = MockStrategy()
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )
        await runtime.start()

        pause_result = await runtime.pause()
        assert pause_result.new_state == StrategyLifecycleState.PAUSED
        assert runtime.can_emit_signals is False

        resume_result = await runtime.resume()
        assert resume_result.new_state == StrategyLifecycleState.ACTIVE
        assert runtime.can_emit_signals is True

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_process_bar_emits_signal(self, base_config, context_builder, market_data_service, fill_event_bus):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
        )
        strategy = MockStrategy(bar_signal=signal)
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )

        await runtime.start()

        bar = CompletedBar(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("10000"),
            interval="1m",
        )
        await runtime.on_bar(bar)

        await asyncio.sleep(0.1)

        emitted = runtime.get_next_signal()
        assert emitted is not None
        assert emitted.instrument_token == "RELIANCE"
        assert emitted.action == SignalAction.ENTER_LONG

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_no_signal_when_paused(self, base_config, context_builder, market_data_service, fill_event_bus):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
        )
        strategy = MockStrategy(bar_signal=signal)
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )

        await runtime.start()
        await runtime.pause()

        bar = CompletedBar(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("10000"),
            interval="1m",
        )
        await runtime.on_bar(bar)

        await asyncio.sleep(0.1)
        emitted = runtime.get_next_signal()
        assert emitted is None

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_strategy_error_transitions_to_error(self, base_config, context_builder, market_data_service, fill_event_bus):
        class FailingStrategy(MockStrategy):
            def on_bar(self, bar, context):
                raise RuntimeError("Strategy failure")

        strategy = FailingStrategy()
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )

        await runtime.start()

        bar = CompletedBar(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("10000"),
            interval="1m",
        )

        # on_bar queues the bar; processing happens in the background _run_loop.
        # We wait for the loop to process it and transition to ERROR state.
        await runtime.on_bar(bar)
        await asyncio.sleep(0.2)

        assert runtime.lifecycle_state == StrategyLifecycleState.ERROR

    @pytest.mark.asyncio
    async def test_signal_callback_invoked(self, base_config, context_builder, market_data_service, fill_event_bus):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
        )
        strategy = MockStrategy(bar_signal=signal)

        received_signals = []
        def callback(s):
            received_signals.append(s)

        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
            signal_callback=callback,
        )

        await runtime.start()

        bar = CompletedBar(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("10000"),
            interval="1m",
        )
        await runtime.on_bar(bar)

        await asyncio.sleep(0.1)
        assert len(received_signals) == 1
        assert received_signals[0].instrument_token == "RELIANCE"

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_fill_tracking(self, base_config, context_builder, market_data_service, fill_event_bus):
        strategy = MockStrategy()
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )

        await runtime.start()

        fill = FillEvent(
            fill_id="fill_1",
            order_id="order_1",
            client_order_id="client_1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("50"),
            price=Decimal("100"),
            fill_timestamp=datetime.utcnow(),
        )

        await fill_event_bus.publish(fill)
        await asyncio.sleep(0.1)

        assert runtime.positions["RELIANCE"].net_quantity == Decimal("50")
        assert runtime.positions["RELIANCE"].direction == "LONG"

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_deterministic_signal_sequence(self, base_config, context_builder, market_data_service, fill_event_bus):
        strat1 = MockStrategy(bar_signal=Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
        ))
        strat2 = MockStrategy(bar_signal=Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
        ))

        runtime1 = StrategyRuntime(
            config=base_config,
            strategy=strat1,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )
        runtime2 = StrategyRuntime(
            config=base_config,
            strategy=strat2,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )

        await runtime1.start()
        await runtime2.start()

        bar = CompletedBar(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("10000"),
            interval="1m",
        )

        await runtime1.on_bar(bar)
        await runtime2.on_bar(bar)
        await asyncio.sleep(0.1)

        s1 = runtime1.get_next_signal()
        s2 = runtime2.get_next_signal()
        assert s1.action == s2.action
        assert s1.quantity == s2.quantity

        await runtime1.stop()
        await runtime2.stop()

    @pytest.mark.asyncio
    async def test_signal_strategy_id_mismatch(self, base_config, context_builder, market_data_service, fill_event_bus):
        bad_signal = Signal(
            strategy_id="wrong_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
        )
        strategy = MockStrategy(bar_signal=bad_signal)
        runtime = StrategyRuntime(
            config=base_config,
            strategy=strategy,
            context_builder=context_builder,
            market_data_service=market_data_service,
            fill_event_bus=fill_event_bus,
        )

        await runtime.start()

        bar = CompletedBar(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("95"),
            close=Decimal("105"),
            volume=Decimal("10000"),
            interval="1m",
        )

        # on_bar queues the bar; the mismatch error fires in the background _run_loop
        # and transitions the runtime to ERROR state.
        await runtime.on_bar(bar)
        await asyncio.sleep(0.2)

        assert runtime.lifecycle_state == StrategyLifecycleState.ERROR
