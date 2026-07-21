"""Tests for strategy/signal_router.py."""
import pytest
import asyncio
from decimal import Decimal
from uuid import uuid4

from strategy.signal_router import SignalRouter
from strategy.contracts import Signal, SignalAction, StrategyConfig, SignalRoutingResult
from strategy.exceptions import InvalidSignalError, SignalValidationError
from execution.contracts import ExecutionOrderSide, ExecutionOrderType, ExecutionOrder


class TestSignalRouter:
    @pytest.fixture
    def router(self):
        return SignalRouter()

    @pytest.fixture
    def valid_signal(self):
        return Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            order_type=ExecutionOrderType.MARKET,
            reason="test",
        )

    @pytest.fixture
    def strategy_config(self):
        return StrategyConfig(
            strategy_id="test_strat",
            strategy_type="test",
            name="Test",
            max_position_quantity=Decimal("500"),
            max_orders_per_minute=10,
        )

    @pytest.mark.asyncio
    async def test_validate_signal_positive_quantity(self, router, valid_signal, strategy_config):
        result = await router.route_signal(valid_signal, "session_1", strategy_config)
        assert result.routed is True
        assert result.status == "ROUTED"
        assert result.client_order_id is not None

    @pytest.mark.asyncio
    async def test_validate_signal_zero_quantity(self, router, strategy_config):
        with pytest.raises(Exception):
            Signal(
                strategy_id="test_strat",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_validate_signal_negative_quantity(self, router, strategy_config):
        with pytest.raises(Exception):
            Signal(
                strategy_id="test_strat",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("-10"),
            )

    @pytest.mark.asyncio
    async def test_validate_signal_empty_instrument(self, router, strategy_config):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
        )
        result = await router.route_signal(signal, "session_1", strategy_config)
        assert result.routed is False
        assert "instrument_token" in result.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_validate_signal_hold_action(self, router, strategy_config):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.HOLD,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
        )
        result = await router.route_signal(signal, "session_1", strategy_config)
        assert result.routed is False
        assert "HOLD" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_limit_order_requires_price(self, router, strategy_config):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
            order_type=ExecutionOrderType.LIMIT,
            limit_price=None,
        )
        result = await router.route_signal(signal, "session_1", strategy_config)
        assert result.routed is False
        assert "limit_price" in result.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_position_limit_exceeded(self, router, strategy_config):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("1000"),
        )
        result = await router.route_signal(signal, "session_1", strategy_config)
        assert result.routed is False
        assert "exceeds" in result.rejection_reason.lower()

    @pytest.mark.asyncio
    async def test_rate_limit(self, router, strategy_config):
        for i in range(strategy_config.max_orders_per_minute):
            signal = Signal(
                strategy_id="test_strat",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("10"),
            )
            result = await router.route_signal(signal, "session_1", strategy_config)
            assert result.routed is True

        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
        )
        result = await router.route_signal(signal, "session_1", strategy_config)
        assert result.routed is False
        assert "Rate limit" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_execution_callback(self, router, valid_signal, strategy_config):
        executed = []
        async def callback(session_id, order):
            executed.append((session_id, order))

        router_with_cb = SignalRouter(execution_callback=callback)
        result = await router_with_cb.route_signal(valid_signal, "session_123", strategy_config)

        assert result.routed is True
        assert len(executed) == 1
        assert executed[0][0] == "session_123"
        assert isinstance(executed[0][1], ExecutionOrder)
        assert executed[0][1].instrument_token == "RELIANCE"
        assert executed[0][1].side == ExecutionOrderSide.BUY
        assert executed[0][1].quantity == Decimal("100")

    @pytest.mark.asyncio
    async def test_execution_callback_failure(self, valid_signal, strategy_config):
        async def failing_callback(session_id, order):
            raise RuntimeError("Execution failed")

        router = SignalRouter(execution_callback=failing_callback)
        result = await router.route_signal(valid_signal, "session_1", strategy_config)

        assert result.routed is False
        assert "Execution callback failed" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_cancel_pending_for_strategy(self, router, valid_signal, strategy_config):
        for _ in range(3):
            s = Signal(
                strategy_id="test_strat",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("10"),
            )
            await router.route_signal(s, "session_1", strategy_config)

        count = await router.cancel_pending_for_strategy("test_strat")
        assert count == 3

    @pytest.mark.asyncio
    async def test_cancel_pending_only_targets_strategy(self, router, strategy_config):
        s1 = Signal(
            strategy_id="strat_1",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
        )
        s2 = Signal(
            strategy_id="strat_2",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
        )
        await router.route_signal(s1, "session_1", strategy_config)
        await router.route_signal(s2, "session_1", strategy_config)

        count = await router.cancel_pending_for_strategy("strat_1")
        assert count == 1

    def test_detect_conflict_no_conflict(self, router):
        signals = [
            Signal(
                strategy_id="s1",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("10"),
            ),
        ]
        result = router.detect_conflict(signals)
        assert result.has_conflict is False

    def test_detect_conflict_opposing(self, router):
        signals = [
            Signal(
                strategy_id="s1",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("10"),
            ),
            Signal(
                strategy_id="s2",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_SHORT,
                side=ExecutionOrderSide.SELL,
                quantity=Decimal("10"),
            ),
        ]
        result = router.detect_conflict(signals)
        assert result.has_conflict is True
        assert "Opposing" in result.conflict_reason
        assert len(result.rejected_signals) == 2

    def test_detect_conflict_same_direction_ok(self, router):
        signals = [
            Signal(
                strategy_id="s1",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("10"),
            ),
            Signal(
                strategy_id="s2",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("20"),
            ),
        ]
        result = router.detect_conflict(signals)
        assert result.has_conflict is False

    def test_detect_conflict_different_instruments(self, router):
        signals = [
            Signal(
                strategy_id="s1",
                instrument_token="RELIANCE",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("10"),
            ),
            Signal(
                strategy_id="s2",
                instrument_token="TCS",
                action=SignalAction.ENTER_SHORT,
                side=ExecutionOrderSide.SELL,
                quantity=Decimal("10"),
            ),
        ]
        result = router.detect_conflict(signals)
        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_map_signal_to_order(self, router, valid_signal):
        order = router._map_signal_to_order(valid_signal)
        assert isinstance(order, ExecutionOrder)
        assert order.instrument_token == valid_signal.instrument_token
        assert order.side == valid_signal.side
        assert order.quantity == valid_signal.quantity
        assert order.order_type == valid_signal.order_type
        assert "signal_id" in order.metadata
        assert "strategy_id" in order.metadata
