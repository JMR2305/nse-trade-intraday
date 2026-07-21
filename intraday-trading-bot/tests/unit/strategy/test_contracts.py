"""Tests for strategy/contracts.py."""
import pytest
from decimal import Decimal
from datetime import datetime
from uuid import UUID

from strategy.contracts import (
    Signal,
    SignalAction,
    StrategyConfig,
    StrategyContext,
    StrategyLifecycleState,
    StrategyStateSnapshot,
    StrategyPerformanceSnapshot,
    SignalRoutingResult,
    StrategyRegistrationResult,
    ConflictResolution,
)
from execution.contracts import ExecutionOrderSide, ExecutionOrderType
from execution.portfolio import PortfolioSnapshot, PositionSnapshot


class TestSignal:
    def test_signal_creation(self):
        signal = Signal(
            strategy_id="test_strat",
            instrument_token="RELIANCE",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            reason="test",
        )
        assert signal.strategy_id == "test_strat"
        assert signal.instrument_token == "RELIANCE"
        assert signal.action == SignalAction.ENTER_LONG
        assert signal.side == ExecutionOrderSide.BUY
        assert signal.quantity == Decimal("100")
        assert signal.is_entry is True
        assert signal.is_exit is False

    def test_signal_is_entry_exit(self):
        enter_long = Signal(
            strategy_id="s",
            instrument_token="t",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("1"),
        )
        assert enter_long.is_entry is True
        assert enter_long.is_exit is False

        exit_long = Signal(
            strategy_id="s",
            instrument_token="t",
            action=SignalAction.EXIT_LONG,
            side=ExecutionOrderSide.SELL,
            quantity=Decimal("1"),
        )
        assert exit_long.is_entry is False
        assert exit_long.is_exit is True

    def test_signal_immutable(self):
        signal = Signal(
            strategy_id="s",
            instrument_token="t",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("1"),
        )
        with pytest.raises(Exception):
            signal.strategy_id = "other"

    def test_signal_quantity_must_be_positive(self):
        with pytest.raises(Exception):
            Signal(
                strategy_id="s",
                instrument_token="t",
                action=SignalAction.ENTER_LONG,
                side=ExecutionOrderSide.BUY,
                quantity=Decimal("0"),
            )

    def test_signal_auto_generates_uuid(self):
        signal = Signal(
            strategy_id="s",
            instrument_token="t",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("1"),
        )
        assert isinstance(signal.signal_id, UUID)

    def test_signal_with_limit_order(self):
        signal = Signal(
            strategy_id="s",
            instrument_token="t",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("10"),
            order_type=ExecutionOrderType.LIMIT,
            limit_price=Decimal("1500.50"),
        )
        assert signal.limit_price == Decimal("1500.50")
        assert signal.order_type == ExecutionOrderType.LIMIT


class TestStrategyConfig:
    def test_config_creation(self):
        config = StrategyConfig(
            strategy_id="test_1",
            strategy_type="sma_crossover",
            name="Test Strategy",
            instrument_tokens=["RELIANCE", "TCS"],
        )
        assert config.strategy_id == "test_1"
        assert config.strategy_type == "sma_crossover"
        assert config.name == "Test Strategy"
        assert config.instrument_tokens == ["RELIANCE", "TCS"]
        assert config.max_position_quantity == Decimal("1000")
        assert config.max_orders_per_minute == 10
        assert config.enabled is True

    def test_config_defaults(self):
        config = StrategyConfig(
            strategy_id="test",
            strategy_type="test",
            name="Test",
        )
        assert config.description is None
        assert config.instrument_tokens == []
        assert config.bar_timeframe == "1m"
        assert config.parameters == {}

    def test_config_immutable(self):
        config = StrategyConfig(
            strategy_id="test",
            strategy_type="test",
            name="Test",
        )
        with pytest.raises(Exception):
            config.name = "Other"


class TestStrategyLifecycleState:
    def test_enum_values(self):
        assert StrategyLifecycleState.REGISTERED.value == "REGISTERED"
        assert StrategyLifecycleState.ACTIVE.value == "ACTIVE"
        assert StrategyLifecycleState.STOPPED.value == "STOPPED"


class TestStrategyStateSnapshot:
    def test_snapshot_creation(self):
        snap = StrategyStateSnapshot(
            strategy_id="test",
            lifecycle_state=StrategyLifecycleState.ACTIVE,
            filled_today=5,
            rejected_today=1,
        )
        assert snap.strategy_id == "test"
        assert snap.lifecycle_state == StrategyLifecycleState.ACTIVE
        assert snap.filled_today == 5
        assert snap.rejected_today == 1
        assert snap.current_signals == []
        assert snap.pending_orders == []


class TestStrategyPerformanceSnapshot:
    def test_snapshot_defaults(self):
        snap = StrategyPerformanceSnapshot(
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )
        assert snap.total_trades == 0
        assert snap.win_rate == Decimal("0")
        assert snap.max_drawdown == Decimal("0")
        assert snap.sharpe_ratio is None
        assert snap.return_pct is None


class TestSignalRoutingResult:
    def test_result_creation(self):
        from uuid import uuid4
        result = SignalRoutingResult(
            signal_id=uuid4(),
            routed=True,
            client_order_id="order_123",
            status="ROUTED",
        )
        assert result.routed is True
        assert result.client_order_id == "order_123"

    def test_result_rejected(self):
        from uuid import uuid4
        result = SignalRoutingResult(
            signal_id=uuid4(),
            routed=False,
            status="REJECTED",
            rejection_reason="Invalid quantity",
        )
        assert result.routed is False
        assert result.rejection_reason == "Invalid quantity"


class TestConflictResolution:
    def test_no_conflict(self):
        res = ConflictResolution(has_conflict=False)
        assert res.has_conflict is False
        assert res.resolved_signal is None

    def test_with_conflict(self):
        signal = Signal(
            strategy_id="s",
            instrument_token="t",
            action=SignalAction.ENTER_LONG,
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("1"),
        )
        res = ConflictResolution(
            has_conflict=True,
            conflict_reason="Opposing signals",
            rejected_signals=[signal],
        )
        assert res.has_conflict is True
        assert len(res.rejected_signals) == 1


class TestStrategyContext:
    def test_context_creation(self):
        ctx = StrategyContext(
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )
        assert ctx.strategy_id == "test"
        assert ctx.market_snapshots == {}
        assert ctx.portfolio.cash == Decimal("0")
        assert ctx.portfolio.equity == Decimal("0")
        assert ctx.strategy_positions == {}

    def test_context_with_positions(self):
        pos = PositionSnapshot(
            instrument_token="RELIANCE",
            net_quantity=Decimal("100"),
            direction="LONG",
        )
        ctx = StrategyContext(
            strategy_id="test",
            timestamp=datetime.utcnow(),
            strategy_positions={"RELIANCE": pos},
        )
        assert ctx.strategy_positions["RELIANCE"].net_quantity == Decimal("100")
