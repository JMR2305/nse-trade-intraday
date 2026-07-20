"""
Unit tests for risk/rules.py.
"""

import pytest
from decimal import Decimal
from datetime import datetime

from src.risk.contracts import (
    RiskCheckContext,
    RiskStateSnapshot,
    OrderSizeLimit,
    PriceToleranceLimit,
    PositionLimit,
    PortfolioExposureLimit,
    DailyLossLimit,
    MessageThrottleLimit,
    DuplicateOrderLimit,
    SelfTradeLimit,
    PortfolioHeatLimit,
    DrawdownLimit,
    TurnoverVelocityLimit,
    RiskSeverity,
    RiskCheckType,
)
from src.risk.rules import (
    OrderSizeRule,
    PriceToleranceRule,
    PositionLimitRule,
    PortfolioExposureRule,
    DailyLossLimitRule,
    MessageThrottleRule,
    DuplicateOrderRule,
    SelfTradeRule,
    PortfolioHeatRule,
    DrawdownRule,
    TurnoverVelocityRule,
)


@pytest.fixture
def base_context():
    return RiskCheckContext(
        account_id="ACC001",
        check_timestamp=datetime.utcnow(),
    )


@pytest.fixture
def base_state():
    return RiskStateSnapshot(
        account_id="ACC001",
        snapshot_timestamp=datetime.utcnow(),
    )


class TestOrderSizeRule:
    def test_pass(self, base_context, base_state):
        rule = OrderSizeRule()
        limit = OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100"))
        order = {"instrument_token": "INFY", "quantity": Decimal("50")}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_fail(self, base_context, base_state):
        rule = OrderSizeRule()
        limit = OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100"))
        order = {"instrument_token": "INFY", "quantity": Decimal("150")}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.ORDER_SIZE
        assert result.actual_value == Decimal("150")

    def test_instrument_specific_match(self, base_context, base_state):
        rule = OrderSizeRule()
        limit = OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100"), instrument_token="INFY")
        order = {"instrument_token": "INFY", "quantity": Decimal("150")}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None

    def test_instrument_specific_no_match(self, base_context, base_state):
        rule = OrderSizeRule()
        limit = OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100"), instrument_token="TCS")
        order = {"instrument_token": "INFY", "quantity": Decimal("150")}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_disabled(self, base_context, base_state):
        rule = OrderSizeRule()
        limit = OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100"), enabled=False)
        order = {"instrument_token": "INFY", "quantity": Decimal("150")}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_no_order(self, base_context, base_state):
        rule = OrderSizeRule()
        limit = OrderSizeLimit(rule_id="os_001", max_quantity=Decimal("100"))
        result = rule.evaluate(base_context, limit, base_state)
        assert result is None


class TestPriceToleranceRule:
    def test_pass(self, base_context, base_state):
        rule = PriceToleranceRule()
        limit = PriceToleranceLimit(rule_id="pt_001", max_deviation_percent=Decimal("5"))
        order = {"instrument_token": "INFY", "price": Decimal("1575"), "order_type": "LIMIT"}
        ctx = base_context.copy(update={"order": order, "market_prices": {"INFY": Decimal("1500")}})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_fail(self, base_context, base_state):
        rule = PriceToleranceRule()
        limit = PriceToleranceLimit(rule_id="pt_001", max_deviation_percent=Decimal("5"))
        order = {"instrument_token": "INFY", "price": Decimal("1700"), "order_type": "LIMIT"}
        ctx = base_context.copy(update={"order": order, "market_prices": {"INFY": Decimal("1500")}})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.PRICE_TOLERANCE

    def test_market_order_skipped(self, base_context, base_state):
        rule = PriceToleranceRule()
        limit = PriceToleranceLimit(rule_id="pt_001", max_deviation_percent=Decimal("5"))
        order = {"instrument_token": "INFY", "price": Decimal("1000000"), "order_type": "MARKET"}
        ctx = base_context.copy(update={"order": order, "market_prices": {"INFY": Decimal("1500")}})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_no_ltp(self, base_context, base_state):
        rule = PriceToleranceRule()
        limit = PriceToleranceLimit(rule_id="pt_001", max_deviation_percent=Decimal("5"))
        order = {"instrument_token": "INFY", "price": Decimal("1700"), "order_type": "LIMIT"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None


class TestPositionLimitRule:
    def test_pass_within_limit(self, base_context, base_state):
        rule = PositionLimitRule()
        limit = PositionLimit(rule_id="pl_001", max_long_quantity=Decimal("1000"), max_short_quantity=Decimal("500"), instrument_token="INFY")
        order = {"instrument_token": "INFY", "quantity": Decimal("100"), "side": "BUY"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_fail_long_limit(self, base_context, base_state):
        rule = PositionLimitRule()
        limit = PositionLimit(rule_id="pl_001", max_long_quantity=Decimal("100"), max_short_quantity=Decimal("500"), instrument_token="INFY")
        order = {"instrument_token": "INFY", "quantity": Decimal("150"), "side": "BUY"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.POSITION_LIMIT

    def test_fail_short_limit(self, base_context, base_state):
        rule = PositionLimitRule()
        limit = PositionLimit(rule_id="pl_001", max_long_quantity=Decimal("1000"), max_short_quantity=Decimal("100"), instrument_token="INFY")
        order = {"instrument_token": "INFY", "quantity": Decimal("150"), "side": "SELL"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.POSITION_LIMIT

    def test_with_existing_position(self, base_context, base_state):
        rule = PositionLimitRule()
        limit = PositionLimit(rule_id="pl_001", max_long_quantity=Decimal("100"), max_short_quantity=Decimal("500"), instrument_token="INFY")
        order = {"instrument_token": "INFY", "quantity": Decimal("50"), "side": "BUY"}
        positions = {"INFY": {"net_quantity": Decimal("60"), "direction": "LONG"}}
        ctx = base_context.copy(update={"order": order, "position_snapshots": positions})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None

    def test_wrong_instrument(self, base_context, base_state):
        rule = PositionLimitRule()
        limit = PositionLimit(rule_id="pl_001", max_long_quantity=Decimal("100"), max_short_quantity=Decimal("500"), instrument_token="TCS")
        order = {"instrument_token": "INFY", "quantity": Decimal("150"), "side": "BUY"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None


class TestPortfolioExposureRule:
    def test_pass(self, base_context, base_state):
        rule = PortfolioExposureRule()
        limit = PortfolioExposureLimit(rule_id="pe_001", max_exposure_percent=Decimal("100"))
        portfolio = {"equity": Decimal("100000"), "total_market_value": Decimal("80000")}
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_fail(self, base_context, base_state):
        rule = PortfolioExposureRule()
        limit = PortfolioExposureLimit(rule_id="pe_001", max_exposure_percent=Decimal("50"))
        portfolio = {"equity": Decimal("100000"), "total_market_value": Decimal("80000")}
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.PORTFOLIO_EXPOSURE

    def test_zero_equity(self, base_context, base_state):
        rule = PortfolioExposureRule()
        limit = PortfolioExposureLimit(rule_id="pe_001", max_exposure_percent=Decimal("100"))
        portfolio = {"equity": Decimal("0"), "total_market_value": Decimal("80000")}
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None


class TestDailyLossLimitRule:
    def test_no_loss(self, base_context, base_state):
        rule = DailyLossLimitRule()
        limit = DailyLossLimit(rule_id="dl_001", max_daily_loss=Decimal("10000"))
        state = base_state.copy(update={"daily_realized_pnl": Decimal("500")})
        result = rule.evaluate(base_context, limit, state)
        assert result is None

    def test_warning_threshold(self, base_context, base_state):
        rule = DailyLossLimitRule()
        limit = DailyLossLimit(rule_id="dl_001", max_daily_loss=Decimal("10000"))
        state = base_state.copy(update={"daily_realized_pnl": Decimal("-8500")})
        result = rule.evaluate(base_context, limit, state)
        assert result is not None
        assert result.severity.value == "WARNING"

    def test_fatal_threshold(self, base_context, base_state):
        rule = DailyLossLimitRule()
        limit = DailyLossLimit(rule_id="dl_001", max_daily_loss=Decimal("10000"))
        state = base_state.copy(update={"daily_realized_pnl": Decimal("-10000")})
        result = rule.evaluate(base_context, limit, state)
        assert result is not None
        assert result.severity.value == "FATAL"

    def test_exceeds_limit(self, base_context, base_state):
        rule = DailyLossLimitRule()
        limit = DailyLossLimit(rule_id="dl_001", max_daily_loss=Decimal("10000"))
        state = base_state.copy(update={"daily_realized_pnl": Decimal("-15000")})
        result = rule.evaluate(base_context, limit, state)
        assert result is not None
        assert result.severity.value == "FATAL"


class TestMessageThrottleRule:
    def test_pass(self, base_context, base_state):
        rule = MessageThrottleRule()
        limit = MessageThrottleLimit(rule_id="mt_001", max_messages=10, window_seconds=60)
        state = base_state.copy(update={"message_counts": {"account:ACC001": 5}})
        result = rule.evaluate(base_context, limit, state)
        assert result is None

    def test_fail(self, base_context, base_state):
        rule = MessageThrottleRule()
        limit = MessageThrottleLimit(rule_id="mt_001", max_messages=10, window_seconds=60)
        state = base_state.copy(update={"message_counts": {"account:ACC001": 10}})
        result = rule.evaluate(base_context, limit, state)
        assert result is not None
        assert result.check_type == RiskCheckType.MESSAGE_THROTTLE

    def test_instrument_scope(self, base_context, base_state):
        rule = MessageThrottleRule()
        limit = MessageThrottleLimit(rule_id="mt_001", max_messages=5, window_seconds=60, scope="instrument", instrument_token="INFY")
        order = {"instrument_token": "INFY"}
        ctx = base_context.copy(update={"order": order})
        state = base_state.copy(update={"message_counts": {"instrument:INFY": 5}})
        result = rule.evaluate(ctx, limit, state)
        assert result is not None


class TestDuplicateOrderRule:
    def test_no_duplicate(self, base_context, base_state):
        rule = DuplicateOrderRule()
        limit = DuplicateOrderLimit(rule_id="dup_001", window_seconds=5)
        order = {"instrument_token": "INFY", "side": "BUY", "quantity": "100", "price": "1500"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_duplicate_detected(self, base_context, base_state):
        rule = DuplicateOrderRule()
        rule.reset()
        limit = DuplicateOrderLimit(rule_id="dup_001", window_seconds=5)
        order = {"instrument_token": "INFY", "side": "BUY", "quantity": "100", "price": "1500"}

        ctx1 = base_context.copy(update={"order": order, "check_timestamp": datetime(2024, 1, 1, 12, 0, 0)})
        result1 = rule.evaluate(ctx1, limit, base_state)
        assert result1 is None

        ctx2 = base_context.copy(update={"order": order, "check_timestamp": datetime(2024, 1, 1, 12, 0, 2)})
        result2 = rule.evaluate(ctx2, limit, base_state)
        assert result2 is not None
        assert result2.check_type == RiskCheckType.DUPLICATE_ORDER

    def test_duplicate_after_window(self, base_context, base_state):
        rule = DuplicateOrderRule()
        rule.reset()
        limit = DuplicateOrderLimit(rule_id="dup_001", window_seconds=5)
        order = {"instrument_token": "INFY", "side": "BUY", "quantity": "100", "price": "1500"}

        ctx1 = base_context.copy(update={"order": order, "check_timestamp": datetime(2024, 1, 1, 12, 0, 0)})
        result1 = rule.evaluate(ctx1, limit, base_state)
        assert result1 is None

        ctx2 = base_context.copy(update={"order": order, "check_timestamp": datetime(2024, 1, 1, 12, 0, 6)})
        result2 = rule.evaluate(ctx2, limit, base_state)
        assert result2 is None

    def test_reset(self, base_context, base_state):
        rule = DuplicateOrderRule()
        limit = DuplicateOrderLimit(rule_id="dup_001", window_seconds=5)
        order = {"instrument_token": "INFY", "side": "BUY", "quantity": "100", "price": "1500"}
        ctx = base_context.copy(update={"order": order})
        rule.evaluate(ctx, limit, base_state)
        rule.reset()
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None


class TestSelfTradeRule:
    def test_no_open_orders(self, base_context, base_state):
        rule = SelfTradeRule()
        limit = SelfTradeLimit(rule_id="st_001")
        order = {"instrument_token": "INFY", "side": "BUY", "price": "1500"}
        ctx = base_context.copy(update={"order": order})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_no_cross(self, base_context, base_state):
        rule = SelfTradeRule()
        limit = SelfTradeLimit(rule_id="st_001")
        order = {"instrument_token": "INFY", "side": "BUY", "price": "1500"}
        open_orders = [{"instrument_token": "INFY", "side": "SELL", "price": "1600"}]
        ctx = base_context.copy(update={"order": order, "open_orders": open_orders})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_cross_detected(self, base_context, base_state):
        rule = SelfTradeRule()
        limit = SelfTradeLimit(rule_id="st_001")
        order = {"instrument_token": "INFY", "side": "BUY", "price": "1500"}
        open_orders = [{"instrument_token": "INFY", "side": "SELL", "price": "1490"}]
        ctx = base_context.copy(update={"order": order, "open_orders": open_orders})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.SELF_TRADE

    def test_same_side_no_cross(self, base_context, base_state):
        rule = SelfTradeRule()
        limit = SelfTradeLimit(rule_id="st_001")
        order = {"instrument_token": "INFY", "side": "BUY", "price": "1500"}
        open_orders = [{"instrument_token": "INFY", "side": "BUY", "price": "1490"}]
        ctx = base_context.copy(update={"order": order, "open_orders": open_orders})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None


class TestPortfolioHeatRule:
    def test_pass(self, base_context, base_state):
        rule = PortfolioHeatRule()
        limit = PortfolioHeatLimit(rule_id="ph_001", max_concentration_percent=Decimal("50"))
        portfolio = {"equity": Decimal("100000")}
        positions = {"INFY": {"market_value": Decimal("40000")}}
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio, "position_snapshots": positions})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is None

    def test_fail(self, base_context, base_state):
        rule = PortfolioHeatRule()
        limit = PortfolioHeatLimit(rule_id="ph_001", max_concentration_percent=Decimal("30"))
        portfolio = {"equity": Decimal("100000")}
        positions = {"INFY": {"market_value": Decimal("40000")}}
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio, "position_snapshots": positions})
        result = rule.evaluate(ctx, limit, base_state)
        assert result is not None
        assert result.check_type == RiskCheckType.PORTFOLIO_HEAT


class TestDrawdownRule:
    def test_no_drawdown(self, base_context, base_state):
        rule = DrawdownRule()
        limit = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10"))
        portfolio = {"equity": Decimal("100000")}
        state = base_state.copy(update={"peak_equity": Decimal("100000")})
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, state)
        assert result is None

    def test_warning(self, base_context, base_state):
        rule = DrawdownRule()
        limit = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10"))
        portfolio = {"equity": Decimal("93000")}
        state = base_state.copy(update={"peak_equity": Decimal("100000")})
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, state)
        assert result is not None
        assert result.severity.value == "WARNING"

    def test_fatal(self, base_context, base_state):
        rule = DrawdownRule()
        limit = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10"))
        portfolio = {"equity": Decimal("90000")}
        state = base_state.copy(update={"peak_equity": Decimal("100000")})
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, state)
        assert result is not None
        assert result.severity.value == "FATAL"


class TestTurnoverVelocityRule:
    def test_pass(self, base_context, base_state):
        rule = TurnoverVelocityRule()
        limit = TurnoverVelocityLimit(rule_id="tv_001", max_velocity=Decimal("5"))
        portfolio = {"equity": Decimal("100000")}
        state = base_state.copy(update={"daily_turnover": Decimal("300000")})
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, state)
        assert result is None

    def test_fail(self, base_context, base_state):
        rule = TurnoverVelocityRule()
        limit = TurnoverVelocityLimit(rule_id="tv_001", max_velocity=Decimal("5"))
        portfolio = {"equity": Decimal("100000")}
        state = base_state.copy(update={"daily_turnover": Decimal("600000")})
        ctx = base_context.copy(update={"portfolio_snapshot": portfolio})
        result = rule.evaluate(ctx, limit, state)
        assert result is not None
        assert result.check_type == RiskCheckType.TURNOVER_VELOCITY
