"""Tests for strategy/built_in/sma_crossover.py."""
import pytest
from decimal import Decimal
from datetime import datetime

from strategy.built_in.sma_crossover import SmaCrossoverStrategy
from strategy.contracts import StrategyConfig, StrategyContext, SignalAction
from execution.contracts import ExecutionOrderSide
from market_data.contracts import CompletedBar


@pytest.fixture
def base_config():
    return StrategyConfig(
        strategy_id="sma_test",
        strategy_type="sma_crossover",
        name="SMA Crossover",
        instrument_tokens=["RELIANCE"],
        parameters={
            "short_period": 3,
            "long_period": 5,
            "quantity": 100,
        },
    )


class TestSmaCrossoverStrategy:
    def test_strategy_type(self):
        strat = SmaCrossoverStrategy()
        assert strat.strategy_type == "sma_crossover"

    def test_validate_config_valid(self, base_config):
        strat = SmaCrossoverStrategy()
        errors = strat.validate_config(base_config)
        assert errors == []

    def test_validate_config_invalid_periods(self, base_config):
        config = base_config.model_copy(update={"parameters": {"short_period": 10, "long_period": 5}})
        strat = SmaCrossoverStrategy()
        errors = strat.validate_config(config)
        assert any("short_period" in e for e in errors)

    def test_validate_config_invalid_quantity(self, base_config):
        config = base_config.model_copy(update={"parameters": {"quantity": -10}})
        strat = SmaCrossoverStrategy()
        errors = strat.validate_config(config)
        assert any("quantity" in e for e in errors)

    def test_not_enough_bars_no_signal(self, base_config):
        strat = SmaCrossoverStrategy()
        strat.validate_config(base_config)

        ctx = StrategyContext(strategy_id="sma_test", timestamp=datetime.utcnow())

        for i in range(4):
            bar = CompletedBar(
                instrument_token="RELIANCE",
                timestamp=datetime.utcnow(),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("95"),
                close=Decimal(f"{100 + i}"),
                volume=Decimal("1000"),
                interval="1m",
            )
            signal = strat.on_bar(bar, ctx)
            assert signal is None

    def test_golden_cross_signal(self, base_config):
        strat = SmaCrossoverStrategy()
        strat.validate_config(base_config)

        ctx = StrategyContext(strategy_id="sma_test", timestamp=datetime.utcnow())

        # Falling-then-rising series: short SMA drops below long SMA during the
        # decline, then crosses back above on the recovery — golden cross fires
        # at bar 9 (price=106) with short_period=3, long_period=5.
        prices = [110, 108, 106, 104, 102, 100, 101, 103, 106, 110]
        signal = None
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
            result = strat.on_bar(bar, ctx)
            if result is not None:
                signal = result

        assert signal is not None
        assert signal.action == SignalAction.ENTER_LONG
        assert signal.side == ExecutionOrderSide.BUY
        assert signal.quantity == Decimal("100")

    def test_death_cross_signal(self, base_config):
        strat = SmaCrossoverStrategy()
        strat.validate_config(base_config)

        ctx = StrategyContext(strategy_id="sma_test", timestamp=datetime.utcnow())

        rising = [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]
        falling = [109, 108, 107, 106, 105, 104, 103, 102, 101, 100]

        for price in rising:
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
            strat.on_bar(bar, ctx)

        signal = None
        for price in falling:
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
            result = strat.on_bar(bar, ctx)
            if result is not None:
                signal = result

        assert signal is not None
        assert signal.action == SignalAction.ENTER_SHORT
        assert signal.side == ExecutionOrderSide.SELL

    def test_tick_returns_none(self, base_config):
        strat = SmaCrossoverStrategy()
        ctx = StrategyContext(strategy_id="sma_test", timestamp=datetime.utcnow())

        from market_data.contracts import Tick
        tick = Tick(
            instrument_token="RELIANCE",
            timestamp=datetime.utcnow(),
            last_price=Decimal("100"),
            last_quantity=Decimal("10"),
            volume=Decimal("1000"),
            buy_price=Decimal("99"),
            buy_quantity=Decimal("5"),
            sell_price=Decimal("101"),
            sell_quantity=Decimal("5"),
        )
        signal = strat.on_tick(tick, ctx)
        assert signal is None

    def test_fill_returns_none(self, base_config):
        strat = SmaCrossoverStrategy()
        ctx = StrategyContext(strategy_id="sma_test", timestamp=datetime.utcnow())

        from execution.fills import FillEvent
        fill = FillEvent(
            fill_id="f1",
            order_id="o1",
            client_order_id="c1",
            instrument_token="RELIANCE",
            side=ExecutionOrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("100"),
            fill_timestamp=datetime.utcnow(),
        )
        signal = strat.on_fill(fill, ctx)
        assert signal is None

    def test_determinism(self, base_config):
        strat1 = SmaCrossoverStrategy()
        strat2 = SmaCrossoverStrategy()

        ctx = StrategyContext(strategy_id="sma_test", timestamp=datetime.utcnow())

        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]
        signals1 = []
        signals2 = []

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
            s1 = strat1.on_bar(bar, ctx)
            s2 = strat2.on_bar(bar, ctx)
            if s1:
                signals1.append(s1.action.value)
            if s2:
                signals2.append(s2.action.value)

        assert signals1 == signals2
