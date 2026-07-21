"""Tests for strategy/fill_tracker.py."""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from strategy.fill_tracker import StrategyFillTracker
from strategy.contracts import StrategyConfig
from execution.fills import FillEvent
from execution.contracts import ExecutionOrderSide
from risk.fill_event_bus import FillEventBus


@pytest.fixture
def base_config():
    return StrategyConfig(
        strategy_id="test_strat",
        strategy_type="mock",
        name="Test",
    )

@pytest.fixture
def fill_event_bus():
    return FillEventBus()


class TestStrategyFillTracker:
    def test_creation(self, base_config, fill_event_bus):
        tracker = StrategyFillTracker(base_config, fill_event_bus)
        assert tracker.positions == {}
        assert tracker.fill_count == 0
        assert tracker.realized_pnl == Decimal("0")

    @pytest.mark.asyncio
    async def test_buy_fill_creates_long_position(self, base_config, fill_event_bus):
        tracker = StrategyFillTracker(base_config, fill_event_bus)
        await tracker.subscribe()

        fill = FillEvent(
            fill_id="f1",
            order_id="o1",
            client_order_id="c1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("2500"),
            fill_timestamp=datetime.utcnow(),
        )

        await fill_event_bus.publish(fill)
        await asyncio.sleep(0.05)

        assert "RELIANCE" in tracker.positions
        assert tracker.positions["RELIANCE"].net_quantity == Decimal("100")
        assert tracker.positions["RELIANCE"].direction == "LONG"
        assert tracker.fill_count == 1

    @pytest.mark.asyncio
    async def test_sell_fill_creates_short_position(self, base_config, fill_event_bus):
        tracker = StrategyFillTracker(base_config, fill_event_bus)
        await tracker.subscribe()

        fill = FillEvent(
            fill_id="f1",
            order_id="o1",
            client_order_id="c1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.SELL,
            quantity=Decimal("50"),
            price=Decimal("2500"),
            fill_timestamp=datetime.utcnow(),
        )

        await fill_event_bus.publish(fill)
        await asyncio.sleep(0.05)

        assert tracker.positions["RELIANCE"].net_quantity == Decimal("50")
        assert tracker.positions["RELIANCE"].direction == "SHORT"

    @pytest.mark.asyncio
    async def test_multiple_buys_aggregate(self, base_config, fill_event_bus):
        tracker = StrategyFillTracker(base_config, fill_event_bus)
        await tracker.subscribe()

        for i in range(3):
            fill = FillEvent(
                fill_id=f"f{i}",
                order_id=f"o{i}",
                client_order_id=f"c{i}",
                instrument_token="RELIANCE",
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("100"),
                price=Decimal(f"{2500 + i}"),
                fill_timestamp=datetime.utcnow(),
            )
            await fill_event_bus.publish(fill)

        await asyncio.sleep(0.1)

        pos = tracker.positions["RELIANCE"]
        assert pos.net_quantity == Decimal("300")
        assert pos.total_buy_quantity == Decimal("300")

    @pytest.mark.asyncio
    async def test_buy_then_sell_flattens(self, base_config, fill_event_bus):
        tracker = StrategyFillTracker(base_config, fill_event_bus)
        await tracker.subscribe()

        buy = FillEvent(
            fill_id="f1",
            order_id="o1",
            client_order_id="c1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("2500"),
            fill_timestamp=datetime.utcnow(),
        )
        await fill_event_bus.publish(buy)
        await asyncio.sleep(0.05)

        sell = FillEvent(
            fill_id="f2",
            order_id="o2",
            client_order_id="c2",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.SELL,
            quantity=Decimal("100"),
            price=Decimal("2600"),
            fill_timestamp=datetime.utcnow(),
        )
        await fill_event_bus.publish(sell)
        await asyncio.sleep(0.05)

        assert "RELIANCE" not in tracker.positions
        assert tracker.fill_count == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_tracking(self, base_config, fill_event_bus):
        tracker = StrategyFillTracker(base_config, fill_event_bus)
        await tracker.subscribe()
        await tracker.unsubscribe()

        fill = FillEvent(
            fill_id="f1",
            order_id="o1",
            client_order_id="c1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("2500"),
            fill_timestamp=datetime.utcnow(),
        )
        await fill_event_bus.publish(fill)
        await asyncio.sleep(0.05)

        assert tracker.fill_count == 0

    @pytest.mark.asyncio
    async def test_callback_invoked(self, base_config, fill_event_bus):
        received = []
        def callback(fill):
            received.append(fill)

        tracker = StrategyFillTracker(base_config, fill_event_bus)
        await tracker.subscribe(callback)

        fill = FillEvent(
            fill_id="f1",
            order_id="o1",
            client_order_id="c1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("2500"),
            fill_timestamp=datetime.utcnow(),
        )
        await fill_event_bus.publish(fill)
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].fill_id == "f1"
