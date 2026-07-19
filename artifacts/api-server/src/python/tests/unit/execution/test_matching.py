"""Unit tests for order matching logic."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.contracts import ExecutionOrder, ExecutionOrderSide, ExecutionOrderStatus, ExecutionOrderType
from src.execution.matching import MarketSnapshot, OrderMatcher, TriggerStateTracker
from src.execution.policies import BasisPointsSlippagePolicy, FixedTicksSlippagePolicy


# ==================================================================
# Helpers
# ==================================================================

def _make_snapshot(
    ltp: Decimal = Decimal("100"),
    bid: Decimal | None = Decimal("99"),
    ask: Decimal | None = Decimal("101"),
    bid_qty: int | None = 500,
    ask_qty: int | None = 500,
    event_id: str = "evt-001",
    tick_size: Decimal = Decimal("0.05"),
) -> MarketSnapshot:
    return MarketSnapshot(
        instrument_token=123456,
        timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        last_traded_price=ltp,
        bid_price=bid,
        ask_price=ask,
        bid_quantity=bid_qty,
        ask_quantity=ask_qty,
        event_id=event_id,
        tick_size=tick_size,
    )


def _make_order(
    order_type: ExecutionOrderType,
    side: ExecutionOrderSide = ExecutionOrderSide.BUY,
    quantity: int = 100,
    limit_price: Decimal | None = None,
    trigger_price: Decimal | None = None,
) -> ExecutionOrder:
    kwargs = {
        "client_order_id": f"test-{uuid4().hex[:8]}",
        "instrument_token": 123456,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
    }
    if limit_price is not None:
        kwargs["limit_price"] = limit_price
    if trigger_price is not None:
        kwargs["trigger_price"] = trigger_price
    return ExecutionOrder(**kwargs)


# ==================================================================
# MARKET Orders
# ==================================================================

class TestMarketOrders:
    def test_market_buy_uses_ask(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, ExecutionOrderSide.BUY)
        snapshot = _make_snapshot(ask=Decimal("101"), ask_qty=100)
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("101")

    def test_market_buy_fallback_to_ltp(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, ExecutionOrderSide.BUY)
        snapshot = _make_snapshot(ask=None, ask_qty=None)
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("100")

    def test_market_sell_uses_bid(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, ExecutionOrderSide.SELL)
        snapshot = _make_snapshot(bid=Decimal("99"), bid_qty=100)
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("99")

    def test_market_sell_fallback_to_ltp(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, ExecutionOrderSide.SELL)
        snapshot = _make_snapshot(bid=None, bid_qty=None)
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("100")

    def test_market_order_not_executable_when_filled(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET)
        snapshot = _make_snapshot()
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.FILLED, filled_quantity=100, remaining_quantity=0, snapshot=snapshot)
        assert not result.executable


# ==================================================================
# LIMIT Orders
# ==================================================================

class TestLimitOrders:
    def test_marketable_limit_buy(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.LIMIT, ExecutionOrderSide.BUY, limit_price=Decimal("101"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("101")

    def test_non_marketable_limit_buy(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.LIMIT, ExecutionOrderSide.BUY, limit_price=Decimal("99"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert not result.executable

    def test_marketable_limit_sell(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.LIMIT, ExecutionOrderSide.SELL, limit_price=Decimal("99"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("99")

    def test_non_marketable_limit_sell(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.LIMIT, ExecutionOrderSide.SELL, limit_price=Decimal("101"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert not result.executable

    def test_limit_price_protection_after_slippage(self):
        matcher = OrderMatcher(slippage_policy=BasisPointsSlippagePolicy(basis_points=Decimal("100")))
        order = _make_order(ExecutionOrderType.LIMIT, ExecutionOrderSide.BUY, limit_price=Decimal("100.50"))
        snapshot = _make_snapshot(ltp=Decimal("100"), tick_size=Decimal("0.05"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        # Without protection, 100 bps slippage would make price 101.00
        # But limit protection caps it at 100.50
        assert result.fill_event.price <= Decimal("100.50")


# ==================================================================
# STOP_MARKET Orders
# ==================================================================

class TestStopMarketOrders:
    def test_buy_trigger_when_ltp_ge_trigger(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(ExecutionOrderType.STOP_MARKET, ExecutionOrderSide.BUY, trigger_price=Decimal("100"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert tracker.is_triggered(order.order_id)

    def test_buy_not_triggered_when_ltp_lt_trigger(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(ExecutionOrderType.STOP_MARKET, ExecutionOrderSide.BUY, trigger_price=Decimal("101"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert not result.executable
        assert not tracker.is_triggered(order.order_id)

    def test_sell_trigger_when_ltp_le_trigger(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(ExecutionOrderType.STOP_MARKET, ExecutionOrderSide.SELL, trigger_price=Decimal("100"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert tracker.is_triggered(order.order_id)

    def test_sell_not_triggered_when_ltp_gt_trigger(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(ExecutionOrderType.STOP_MARKET, ExecutionOrderSide.SELL, trigger_price=Decimal("99"))
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert not result.executable
        assert not tracker.is_triggered(order.order_id)

    def test_triggered_sticky(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(ExecutionOrderType.STOP_MARKET, ExecutionOrderSide.BUY, trigger_price=Decimal("100"))

        # First event triggers
        snapshot1 = _make_snapshot(ltp=Decimal("100"), event_id="evt-1")
        from src.execution.contracts import ExecutionOrderStatus
        result1 = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot1)
        assert result1.executable

        # Second event: still executable even if LTP drops below trigger
        snapshot2 = _make_snapshot(ltp=Decimal("99"), event_id="evt-2")
        result2 = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot2)
        assert result2.executable


# ==================================================================
# STOP_LIMIT Orders
# ==================================================================

class TestStopLimitOrders:
    def test_buy_trigger_and_execute(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(
            ExecutionOrderType.STOP_LIMIT,
            ExecutionOrderSide.BUY,
            trigger_price=Decimal("100"),
            limit_price=Decimal("101"),
        )
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("101")

    def test_buy_trigger_without_immediate_fill(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(
            ExecutionOrderType.STOP_LIMIT,
            ExecutionOrderSide.BUY,
            trigger_price=Decimal("100"),
            limit_price=Decimal("99"),
        )
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        # Triggered but limit 99 < LTP 100, so not executable
        assert not result.executable
        assert tracker.is_triggered(order.order_id)

    def test_sell_trigger_and_execute(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(
            ExecutionOrderType.STOP_LIMIT,
            ExecutionOrderSide.SELL,
            trigger_price=Decimal("100"),
            limit_price=Decimal("99"),
        )
        snapshot = _make_snapshot(ltp=Decimal("100"))
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.price == Decimal("99")

    def test_triggered_sticky(self):
        tracker = TriggerStateTracker()
        matcher = OrderMatcher(trigger_tracker=tracker)
        order = _make_order(
            ExecutionOrderType.STOP_LIMIT,
            ExecutionOrderSide.BUY,
            trigger_price=Decimal("100"),
            limit_price=Decimal("101"),
        )

        snapshot1 = _make_snapshot(ltp=Decimal("100"), event_id="evt-1")
        from src.execution.contracts import ExecutionOrderStatus
        result1 = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot1)
        assert result1.executable

        # Still triggered on next event
        snapshot2 = _make_snapshot(ltp=Decimal("99"), event_id="evt-2")
        result2 = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot2)
        # LTP 99 <= limit 101, so executable
        assert result2.executable


# ==================================================================
# Partial Fills
# ==================================================================

class TestPartialFills:
    def test_partial_fill_due_to_liquidity(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        snapshot = _make_snapshot(ask_qty=30)  # Only 30 available
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.quantity == 30
        assert result.fill_event.remaining_quantity == 70

    def test_multiple_partial_fills(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        from src.execution.contracts import ExecutionOrderStatus

        snapshot1 = _make_snapshot(ask_qty=30, event_id="evt-1")
        result1 = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot1)
        assert result1.fill_event.quantity == 30

        snapshot2 = _make_snapshot(ask_qty=40, event_id="evt-2")
        result2 = matcher.match(order, status=ExecutionOrderStatus.PARTIALLY_FILLED, filled_quantity=30, remaining_quantity=70, snapshot=snapshot2)
        assert result2.fill_event.quantity == 40
        assert result2.fill_event.cumulative_filled_quantity == 70
        assert result2.fill_event.remaining_quantity == 30

    def test_full_fill(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        snapshot = _make_snapshot(ask_qty=500)
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.OPEN, filled_quantity=0, remaining_quantity=100, snapshot=snapshot)
        assert result.executable
        assert result.fill_event.quantity == 100
        assert result.fill_event.remaining_quantity == 0

    def test_overfill_prevention(self):
        matcher = OrderMatcher()
        order = _make_order(ExecutionOrderType.MARKET, quantity=100)
        snapshot = _make_snapshot(ask_qty=200)
        from src.execution.contracts import ExecutionOrderStatus
        result = matcher.match(order, status=ExecutionOrderStatus.PARTIALLY_FILLED, filled_quantity=60, remaining_quantity=40, snapshot=snapshot)
        assert result.executable
        # Should fill only remaining 40, not 200
        assert result.fill_event.quantity == 40
        assert result.fill_event.remaining_quantity == 0


# ==================================================================
# Tick Size Rounding
# ==================================================================

class TestTickSizeRounding:
    def test_slippage_rounded_to_tick(self):
        policy = BasisPointsSlippagePolicy(basis_points=Decimal("7"))
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        # 100 * 1.0007 = 100.07, rounded to nearest 0.05 = 100.05
        assert price == Decimal("100.05")

    def test_fixed_ticks_no_rounding_needed(self):
        policy = FixedTicksSlippagePolicy(ticks=1)
        price = policy.apply_slippage(
            side=ExecutionOrderSide.BUY,
            price=Decimal("100"),
            tick_size=Decimal("0.05"),
        )
        assert price == Decimal("100.05")
