"""
Unit tests for risk/contracts.py.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from pydantic import ValidationError

from src.risk.contracts import (
    RiskSeverity,
    RiskAction,
    RiskCheckType,
    RiskViolation,
    RiskDecision,
    OrderSizeLimit,
    PriceToleranceLimit,
    PositionLimit,
    PortfolioExposureLimit,
    DailyLossLimit,
    MessageThrottleLimit,
    RiskStateSnapshot,
    RiskCheckContext,
)


class TestRiskSeverity:
    def test_enum_values(self):
        assert RiskSeverity.INFO == "INFO"
        assert RiskSeverity.WARNING == "WARNING"
        assert RiskSeverity.CRITICAL == "CRITICAL"
        assert RiskSeverity.FATAL == "FATAL"


class TestRiskAction:
    def test_enum_values(self):
        assert RiskAction.ALLOW == "ALLOW"
        assert RiskAction.WARN == "WARN"
        assert RiskAction.BLOCK == "BLOCK"
        assert RiskAction.KILL_SWITCH == "KILL_SWITCH"


class TestRiskViolation:
    def test_create_basic(self):
        v = RiskViolation(
            check_type=RiskCheckType.ORDER_SIZE,
            severity=RiskSeverity.CRITICAL,
            message="Quantity too large",
            rule_id="rule_001",
            limit_value=Decimal("100"),
            actual_value=Decimal("150"),
        )
        assert v.check_type == RiskCheckType.ORDER_SIZE
        assert v.severity == RiskSeverity.CRITICAL
        assert v.limit_value == Decimal("100")
        assert v.actual_value == Decimal("150")

    def test_decimal_conversion_from_string(self):
        v = RiskViolation(
            check_type=RiskCheckType.ORDER_SIZE,
            severity=RiskSeverity.CRITICAL,
            message="Test",
            rule_id="rule_001",
            limit_value="100.50",
            actual_value="200.75",
        )
        assert isinstance(v.limit_value, Decimal)
        assert v.limit_value == Decimal("100.50")
        assert v.actual_value == Decimal("200.75")

    def test_decimal_conversion_from_int(self):
        v = RiskViolation(
            check_type=RiskCheckType.ORDER_SIZE,
            severity=RiskSeverity.CRITICAL,
            message="Test",
            rule_id="rule_001",
            limit_value=100,
            actual_value=200,
        )
        assert isinstance(v.limit_value, Decimal)
        assert v.limit_value == Decimal("100")

    def test_none_values(self):
        v = RiskViolation(
            check_type=RiskCheckType.ORDER_SIZE,
            severity=RiskSeverity.CRITICAL,
            message="Test",
            rule_id="rule_001",
        )
        assert v.limit_value is None
        assert v.actual_value is None


class TestRiskDecision:
    def test_allow_no_violations(self):
        d = RiskDecision(
            action=RiskAction.ALLOW,
            check_timestamp=datetime.utcnow(),
            account_id="ACC001",
        )
        assert d.is_allowed is True
        assert d.is_blocked is False
        assert d.has_critical is False

    def test_block_with_critical(self):
        v = RiskViolation(
            check_type=RiskCheckType.ORDER_SIZE,
            severity=RiskSeverity.CRITICAL,
            message="Too big",
            rule_id="rule_001",
        )
        d = RiskDecision(
            action=RiskAction.BLOCK,
            violations=[v],
            check_timestamp=datetime.utcnow(),
            account_id="ACC001",
        )
        assert d.is_allowed is False
        assert d.is_blocked is True
        assert d.has_critical is True

    def test_kill_switch_with_fatal(self):
        v = RiskViolation(
            check_type=RiskCheckType.DAILY_LOSS_LIMIT,
            severity=RiskSeverity.FATAL,
            message="Loss limit reached",
            rule_id="rule_002",
        )
        d = RiskDecision(
            action=RiskAction.KILL_SWITCH,
            violations=[v],
            check_timestamp=datetime.utcnow(),
            account_id="ACC001",
        )
        assert d.is_allowed is False
        assert d.is_blocked is True
        assert d.has_critical is True

    def test_warn_with_warning_only(self):
        v = RiskViolation(
            check_type=RiskCheckType.DAILY_LOSS_LIMIT,
            severity=RiskSeverity.WARNING,
            message="Near limit",
            rule_id="rule_003",
        )
        d = RiskDecision(
            action=RiskAction.WARN,
            violations=[v],
            check_timestamp=datetime.utcnow(),
            account_id="ACC001",
        )
        assert d.is_allowed is False
        assert d.is_blocked is False
        assert d.has_critical is False


class TestOrderSizeLimit:
    def test_valid(self):
        limit = OrderSizeLimit(rule_id="max_qty_001", max_quantity=Decimal("500"))
        assert limit.max_quantity == Decimal("500")
        assert limit.enabled is True

    def test_string_conversion(self):
        limit = OrderSizeLimit(rule_id="max_qty_001", max_quantity="500")
        assert isinstance(limit.max_quantity, Decimal)
        assert limit.max_quantity == Decimal("500")

    def test_invalid_zero(self):
        with pytest.raises(ValidationError):
            OrderSizeLimit(rule_id="max_qty_001", max_quantity=Decimal("0"))

    def test_invalid_negative(self):
        with pytest.raises(ValidationError):
            OrderSizeLimit(rule_id="max_qty_001", max_quantity=Decimal("-1"))


class TestPriceToleranceLimit:
    def test_valid(self):
        limit = PriceToleranceLimit(rule_id="price_tol_001", max_deviation_percent=Decimal("5.0"))
        assert limit.max_deviation_percent == Decimal("5.0")

    def test_invalid_zero(self):
        with pytest.raises(ValidationError):
            PriceToleranceLimit(rule_id="price_tol_001", max_deviation_percent=Decimal("0"))


class TestPositionLimit:
    def test_valid(self):
        limit = PositionLimit(
            rule_id="pos_limit_001",
            max_long_quantity=Decimal("1000"),
            max_short_quantity=Decimal("500"),
            instrument_token="INFY",
        )
        assert limit.max_long_quantity == Decimal("1000")
        assert limit.max_short_quantity == Decimal("500")

    def test_invalid_negative(self):
        with pytest.raises(ValidationError):
            PositionLimit(
                rule_id="pos_limit_001",
                max_long_quantity=Decimal("-1"),
                max_short_quantity=Decimal("500"),
                instrument_token="INFY",
            )


class TestPortfolioExposureLimit:
    def test_valid(self):
        limit = PortfolioExposureLimit(rule_id="exp_001", max_exposure_percent=Decimal("80.0"))
        assert limit.max_exposure_percent == Decimal("80.0")

    def test_invalid_over_100(self):
        with pytest.raises(ValidationError):
            PortfolioExposureLimit(rule_id="exp_001", max_exposure_percent=Decimal("101.0"))


class TestDailyLossLimit:
    def test_valid(self):
        limit = DailyLossLimit(rule_id="loss_001", max_daily_loss=Decimal("10000"))
        assert limit.max_daily_loss == Decimal("10000")
        assert limit.warning_threshold_percent == Decimal("80.0")

    def test_custom_warning(self):
        limit = DailyLossLimit(
            rule_id="loss_001",
            max_daily_loss=Decimal("10000"),
            warning_threshold_percent=Decimal("50.0"),
        )
        assert limit.warning_threshold_percent == Decimal("50.0")


class TestMessageThrottleLimit:
    def test_valid(self):
        limit = MessageThrottleLimit(rule_id="throttle_001", max_messages=10, window_seconds=60)
        assert limit.max_messages == 10
        assert limit.window_seconds == 60


class TestRiskStateSnapshot:
    def test_create(self):
        snapshot = RiskStateSnapshot(
            account_id="ACC001",
            snapshot_timestamp=datetime.utcnow(),
            daily_realized_pnl=Decimal("-500"),
            daily_turnover=Decimal("10000"),
            peak_equity=Decimal("100000"),
        )
        assert snapshot.daily_realized_pnl == Decimal("-500")
        assert snapshot.kill_switch_active is False

    def test_decimal_conversion(self):
        snapshot = RiskStateSnapshot(
            account_id="ACC001",
            snapshot_timestamp=datetime.utcnow(),
            daily_realized_pnl="-500",
            daily_turnover="10000",
            peak_equity="100000",
        )
        assert isinstance(snapshot.daily_realized_pnl, Decimal)


class TestRiskCheckContext:
    def test_create(self):
        ctx = RiskCheckContext(
            account_id="ACC001",
            check_timestamp=datetime.utcnow(),
            market_prices={"INFY": Decimal("1500.50")},
        )
        assert ctx.market_prices["INFY"] == Decimal("1500.50")

    def test_price_decimal_conversion(self):
        ctx = RiskCheckContext(
            account_id="ACC001",
            check_timestamp=datetime.utcnow(),
            market_prices={"INFY": "1500.50"},
        )
        assert isinstance(ctx.market_prices["INFY"], Decimal)
        assert ctx.market_prices["INFY"] == Decimal("1500.50")
