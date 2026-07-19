"""Unit tests for the matching engine.

Covers end-to-end integration: market data → matching → state machine.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderSide,
    ExecutionOrderStatus,
    ExecutionOrderType,
)
from src.execution.engine import MatchingEngine
from src.execution.matching import MarketSnapshot
from src.execution.state_machine import OrderStateMachine


# ==================================================================
# Helpers
# ==================================================================

def _make_order(
    order_type: ExecutionOrderType,
    side: ExecutionOrderSide = ExecutionOrderSide.BUY,
    quantity: int = 100,
    limit_price: Decimal | None = None,
    trigger_price: Decimal | None = None,
    instrument_token: int = 123456,
) -> ExecutionOrder:
    kwargs = {
        "client_order_id": f"test-{uuid4().hex[:8]}",
        "instrument_token": instrument_token,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
    }
    if limit_price is not None:
        kwargs["limit_price"] = limit_price
    if trigger_price is not None:
        kwargs["trigger_price"] = trigger_price
    return ExecutionOrder(**kwargs)


def _make_snapshot(
    instrument_token: int = 123456,
    ltp: Decimal = Decimal("100"),
    bid: Decimal | None = Decimal("99"),
    ask: Decimal | None = Decimal("101"),
    bid_qty: int | None = 500,
    ask_qty: int | None = 500,
    event_id: str = "evt-001",
    timestamp: datetime = datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
) -> MarketSnapshot:
    return MarketSnapshot(
        instrument_token=instrument_token,
        timestamp=timestamp,
        last_traded_price=ltp,
        bid_price=bid,
        ask_price=ask,
        bid_quantity=bid_qty,
        ask_quantity=ask_qty,
        event_id=event_id,
    )


@pytest.fixture
def machine() -> OrderStateMachine:
    return OrderStateMachine()


@pytest.fixture
def engine(machine: OrderStateMachine) -> MatchingEngine:
    return MatchingEngine(state_machine=machine)


# ==================================================================
# State Machine Integration
# ==================================================================

class TestStateMachineIntegration:
    @pytest.mark.asyncio
    async def test_open_to_partially_filled(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        snapshot = _make_snapshot(ask_qty=30)
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 1
        assert result.fills[0].quantity == 30

        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.PARTIALLY_FILLED
        assert state.filled_quantity == 30
        assert state.remaining_quantity == 70

    @pytest.mark.asyncio
    async def test_open_to_filled(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        snapshot = _make_snapshot(ask_qty=500)
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 1
        assert result.fills[0].quantity == 100

        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.FILLED
        assert state.filled_quantity == 100
        assert state.remaining_quantity == 0

    @pytest.mark.asyncio
    async def test_partially_filled_to_filled(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        # First partial fill
        snapshot1 = _make_snapshot(ask_qty=40, event_id="evt-1")
        await engine.on_market_data(snapshot1)

        # Second fill completes it
        snapshot2 = _make_snapshot(ask_qty=100, event_id="evt-2")
        result = await engine.on_market_data(snapshot2)

        assert len(result.fills) == 1
        assert result.fills[0].quantity == 60  # remaining after first fill

        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.FILLED
        assert state.filled_quantity == 100

    @pytest.mark.asyncio
    async def test_terminal_order_never_matched(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        # Fill completely
        snapshot1 = _make_snapshot(ask_qty=500, event_id="evt-1")
        await engine.on_market_data(snapshot1)

        # Another event arrives
        snapshot2 = _make_snapshot(ask_qty=500, event_id="evt-2")
        result = await engine.on_market_data(snapshot2)

        assert len(result.fills) == 0
        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_cancellation_prevents_later_fill(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        # Cancel the order
        await machine.request_cancel(order.order_id)
        await machine.cancel(order.order_id)

        # Market event arrives late
        snapshot = _make_snapshot(event_id="evt-late")
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 0
        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_rejected_order_never_matched(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.reject(order.order_id, reason="Risk limit")

        snapshot = _make_snapshot()
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 0
        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.REJECTED


# ==================================================================
# Idempotency
# ==================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_market_event_no_double_fill(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        snapshot = _make_snapshot(ask_qty=500, event_id="evt-dup")

        result1 = await engine.on_market_data(snapshot)
        assert len(result1.fills) == 1

        result2 = await engine.on_market_data(snapshot)
        assert len(result2.fills) == 0  # Duplicate event, no second fill

        state = machine.get_state(order.order_id)
        assert state.filled_quantity == 100  # Not 200

    @pytest.mark.asyncio
    async def test_deterministic_fill_id(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        snapshot = _make_snapshot(ask_qty=500, event_id="evt-det")
        result = await engine.on_market_data(snapshot)

        fill_id_1 = result.fills[0].fill_id

        # Fresh engine + machine for replay (deterministic replay guarantee)
        machine2 = OrderStateMachine()
        engine2 = MatchingEngine(state_machine=machine2)
        engine2.register_order(order)
        await machine2.validate(order.order_id)
        await machine2.accept(order.order_id)
        await engine2.activate_order(order.order_id)
        result2 = await engine2.on_market_data(snapshot)
        fill_id_2 = result2.fills[0].fill_id

        assert fill_id_1 == fill_id_2


# ==================================================================
# Concurrency
# ==================================================================

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_events_for_one_order(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        snapshot1 = _make_snapshot(ask_qty=30, event_id="evt-c1")
        snapshot2 = _make_snapshot(ask_qty=40, event_id="evt-c2")

        results = await asyncio.gather(
            engine.on_market_data(snapshot1),
            engine.on_market_data(snapshot2),
        )

        # One should fill 30, one should fill 40 (order of execution may vary)
        total_filled = sum(
            f.quantity for r in results for f in r.fills
        )
        assert total_filled == 70

        state = machine.get_state(order.order_id)
        assert state.filled_quantity == 70
        assert state.remaining_quantity == 30

    @pytest.mark.asyncio
    async def test_concurrent_orders_on_one_instrument(self, engine: MatchingEngine, machine: OrderStateMachine):
        order1 = _make_order(ExecutionOrderType.MARKET, quantity=100, instrument_token=123456)
        order2 = _make_order(ExecutionOrderType.MARKET, quantity=100, instrument_token=123456)

        for order in [order1, order2]:
            engine.register_order(order)
            await machine.validate(order.order_id)
            await machine.accept(order.order_id)
            await engine.activate_order(order.order_id)

        snapshot = _make_snapshot(ask_qty=500, event_id="evt-multi")
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 2

        state1 = machine.get_state(order1.order_id)
        state2 = machine.get_state(order2.order_id)
        assert state1.filled_quantity == 100
        assert state2.filled_quantity == 100

    @pytest.mark.asyncio
    async def test_no_overfill_under_concurrency(self, engine: MatchingEngine, machine: OrderStateMachine):
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        # Two events each offering 60 — if both fill, that would be 120
        snapshot1 = _make_snapshot(ask_qty=60, event_id="evt-o1")
        snapshot2 = _make_snapshot(ask_qty=60, event_id="evt-o2")

        results = await asyncio.gather(
            engine.on_market_data(snapshot1),
            engine.on_market_data(snapshot2),
        )

        total_filled = sum(
            f.quantity for r in results for f in r.fills
        )
        assert total_filled <= 100

        state = machine.get_state(order.order_id)
        assert state.filled_quantity <= 100


# ==================================================================
# Replay
# ==================================================================

class TestReplay:
    @pytest.mark.asyncio
    async def test_identical_stream_produces_identical_fills(self):
        """Same order + same event stream = same fills (deterministic)."""
        machine1 = OrderStateMachine()
        engine1 = MatchingEngine(state_machine=machine1)

        machine2 = OrderStateMachine()
        engine2 = MatchingEngine(state_machine=machine2)

        order = _make_order(ExecutionOrderType.MARKET, quantity=100)

        for engine, machine in [(engine1, machine1), (engine2, machine2)]:
            engine.register_order(order)
            await machine.validate(order.order_id)
            await machine.accept(order.order_id)
            await engine.activate_order(order.order_id)

        snapshots = [
            _make_snapshot(ask_qty=30, event_id="evt-r1"),
            _make_snapshot(ask_qty=40, event_id="evt-r2"),
            _make_snapshot(ask_qty=50, event_id="evt-r3"),
        ]

        fills1 = []
        fills2 = []

        for snap in snapshots:
            result1 = await engine1.on_market_data(snap)
            fills1.extend(result1.fills)
            result2 = await engine2.on_market_data(snap)
            fills2.extend(result2.fills)

        assert len(fills1) == len(fills2)
        for f1, f2 in zip(fills1, fills2):
            assert f1.fill_id == f2.fill_id
            assert f1.quantity == f2.quantity
            assert f1.price == f2.price

    @pytest.mark.asyncio
    async def test_no_wall_clock_dependency(self, engine: MatchingEngine, machine: OrderStateMachine):
        """Engine uses market event timestamps, not wall clock."""
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        snapshot = _make_snapshot(
            timestamp=datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            event_id="evt-old",
        )
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 1
        # Fill timestamp should be from the snapshot, not now()
        assert result.fills[0].market_timestamp == snapshot.timestamp

class TestStopLimitIntegration:
    """STOP_LIMIT can trigger without filling immediately, then fill later."""

    @pytest.mark.asyncio
    async def test_stop_limit_trigger_without_immediate_fill(self, engine: MatchingEngine, machine: OrderStateMachine):
        """Trigger activates but limit is not marketable — no fill."""
        order = _make_order(
            ExecutionOrderType.STOP_LIMIT,
            ExecutionOrderSide.BUY,
            quantity=100,
            trigger_price=Decimal("100"),
            limit_price=Decimal("99"),  # limit below current LTP
        )
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        # LTP hits trigger (100) but limit 99 < LTP 100, so not marketable
        snapshot = _make_snapshot(ltp=Decimal("100"), ask=Decimal("101"), event_id="evt-sl1")
        result = await engine.on_market_data(snapshot)

        assert len(result.fills) == 0
        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.OPEN  # still open, trigger activated

    @pytest.mark.asyncio
    async def test_stop_limit_fills_later_when_marketable(self, engine: MatchingEngine, machine: OrderStateMachine):
        """Trigger activates, then later LTP drops below limit — fill occurs."""
        order = _make_order(
            ExecutionOrderType.STOP_LIMIT,
            ExecutionOrderSide.BUY,
            quantity=100,
            trigger_price=Decimal("100"),
            limit_price=Decimal("99"),
        )
        engine.register_order(order)
        await machine.validate(order.order_id)
        await machine.accept(order.order_id)
        await engine.activate_order(order.order_id)

        # Event 1: Trigger activates (LTP=100) but not marketable (limit=99 < LTP=100)
        snapshot1 = _make_snapshot(ltp=Decimal("100"), ask=Decimal("101"), event_id="evt-sl2a")
        result1 = await engine.on_market_data(snapshot1)
        assert len(result1.fills) == 0

        # Event 2: LTP drops to 98, now limit 99 is marketable
        snapshot2 = _make_snapshot(ltp=Decimal("98"), ask=Decimal("99"), event_id="evt-sl2b")
        result2 = await engine.on_market_data(snapshot2)

        assert len(result2.fills) == 1
        assert result2.fills[0].quantity == 100
        assert result2.fills[0].price == Decimal("99")

        state = machine.get_state(order.order_id)
        assert state.status == ExecutionOrderStatus.FILLED
