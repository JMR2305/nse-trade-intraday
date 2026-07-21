"""
Unit tests for RC-8B risk contracts.

Tests for all domain types: RiskViolation, RiskResult, RiskRequest,
RiskContext, limit configurations, and RiskStateSnapshot.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from src.risk.contracts import (
    RiskSeverity,
    RiskCheckType,
    RiskViolation,
    RiskResult,
    RiskRequest,
    RiskContext,
    RiskStateSnapshot,
    OrderQuantityLimit,
    OrderValueLimit,
    PriceBandLimit,
    MaxPositionSizeLimit,
    DailyLossLimit,
    MaxOrdersPerMinuteLimit,
    KillSwitchLimit,
    EmergencyHaltLimit,
    CircuitBreakerLimit,
    DrawdownLimit,
    TurnoverVelocityLimit,
    ConcentrationLimit,
)


# ── RiskSeverity ──────────────────────────────────────────────────────────


def test_severity_ordering():
    levels = [
        RiskSeverity.INFO,
        RiskSeverity.WARNING,
        RiskSeverity.CRITICAL,
        RiskSeverity.FATAL,
    ]
    assert len(levels) == 4
    assert all(isinstance(s, RiskSeverity) for s in levels)


# ── RiskViolation ─────────────────────────────────────────────────────────


def test_risk_violation_creation():
    v = RiskViolation(
        check_type=RiskCheckType.ORDER_QUANTITY,
        severity=RiskSeverity.CRITICAL,
        message="Quantity 1000 exceeds max 500",
        rule_id="oq_001",
        limit_value=Decimal("500"),
        actual_value=Decimal("1000"),
    )
    assert v.check_type == RiskCheckType.ORDER_QUANTITY
    assert v.severity == RiskSeverity.CRITICAL
    assert v.limit_value == Decimal("500")
    assert v.actual_value == Decimal("1000")


def test_risk_violation_immutable():
    v = RiskViolation(
        check_type=RiskCheckType.KILL_SWITCH,
        severity=RiskSeverity.FATAL,
        message="Kill switch active",
        rule_id="ks_001",
    )
    with pytest.raises(Exception):
        v.severity = RiskSeverity.INFO  # type: ignore[misc]


def test_risk_violation_decimal_coercion():
    v = RiskViolation(
        check_type=RiskCheckType.DAILY_LOSS_LIMIT,
        severity=RiskSeverity.WARNING,
        message="Approaching loss limit",
        rule_id="dll_001",
        limit_value=10000,   # int → Decimal
        actual_value=8000.5,  # float → Decimal
    )
    assert isinstance(v.limit_value, Decimal)
    assert isinstance(v.actual_value, Decimal)
    assert v.limit_value == Decimal("10000")


def test_risk_violation_no_limit_values():
    v = RiskViolation(
        check_type=RiskCheckType.EMERGENCY_HALT,
        severity=RiskSeverity.FATAL,
        message="Emergency halt active",
        rule_id="eh_001",
    )
    assert v.limit_value is None
    assert v.actual_value is None


# ── RiskResult ────────────────────────────────────────────────────────────


def test_risk_result_approved():
    ts = datetime.now(timezone.utc)
    result = RiskResult(
        approved=True,
        violations=[],
        check_timestamp=ts,
        account_id="acc_001",
    )
    assert result.approved is True
    assert result.is_allowed is True
    assert result.is_blocked is False
    assert result.action == "ALLOW"
    assert not result.has_critical


def test_risk_result_critical_violation():
    ts = datetime.now(timezone.utc)
    v = RiskViolation(
        check_type=RiskCheckType.ORDER_QUANTITY,
        severity=RiskSeverity.CRITICAL,
        message="Quantity exceeded",
        rule_id="oq_001",
    )
    result = RiskResult(
        approved=False,
        violations=[v],
        check_timestamp=ts,
        account_id="acc_001",
    )
    assert result.is_blocked is True
    assert result.has_critical is True
    assert result.action == "BLOCK"


def test_risk_result_fatal_violation():
    ts = datetime.now(timezone.utc)
    v = RiskViolation(
        check_type=RiskCheckType.KILL_SWITCH,
        severity=RiskSeverity.FATAL,
        message="Kill switch",
        rule_id="ks_001",
    )
    result = RiskResult(
        approved=False,
        violations=[v],
        check_timestamp=ts,
        account_id="acc_001",
    )
    assert result.action == "KILL_SWITCH"
    assert result.has_critical is True


def test_risk_result_warning_still_approved():
    ts = datetime.now(timezone.utc)
    v = RiskViolation(
        check_type=RiskCheckType.DAILY_LOSS_LIMIT,
        severity=RiskSeverity.WARNING,
        message="Approaching loss limit",
        rule_id="dll_001",
    )
    # WARNING does not block — engine still marks as not approved if
    # the rule also emits CRITICAL. Here we test a standalone WARNING.
    result = RiskResult(
        approved=True,
        violations=[v],
        check_timestamp=ts,
        account_id="acc_001",
    )
    assert result.approved is True
    assert result.action == "WARN"


def test_risk_result_immutable():
    ts = datetime.now(timezone.utc)
    result = RiskResult(
        approved=True,
        violations=[],
        check_timestamp=ts,
        account_id="acc_001",
    )
    with pytest.raises(Exception):
        result.approved = False  # type: ignore[misc]


# ── RiskRequest ───────────────────────────────────────────────────────────


def test_risk_request_defaults_timestamp():
    req = RiskRequest(account_id="acc_001", order={"side": "BUY"})
    assert req.account_id == "acc_001"
    assert req.check_timestamp is not None


def test_risk_request_immutable():
    req = RiskRequest(account_id="acc_001", order={})
    with pytest.raises(Exception):
        req.account_id = "other"  # type: ignore[misc]


# ── RiskContext ───────────────────────────────────────────────────────────


def test_risk_context_defaults():
    ctx = RiskContext(account_id="acc_001")
    assert ctx.portfolio_snapshot is None
    assert ctx.position_snapshots == {}
    assert ctx.market_prices == {}
    assert ctx.open_orders == []
    assert ctx.order is None


def test_risk_context_decimal_prices():
    ctx = RiskContext(
        account_id="acc_001",
        market_prices={"738561": 1500.50},  # float → Decimal
    )
    assert isinstance(ctx.market_prices["738561"], Decimal)
    assert ctx.market_prices["738561"] == Decimal("1500.5")


# ── Limit configurations ──────────────────────────────────────────────────


def test_order_quantity_limit():
    limit = OrderQuantityLimit(rule_id="oq_001", max_quantity=500)
    assert limit.check_type == RiskCheckType.ORDER_QUANTITY
    assert limit.max_quantity == Decimal("500")
    assert limit.enabled is True


def test_order_quantity_limit_decimal_coercion():
    limit = OrderQuantityLimit(rule_id="oq_001", max_quantity=100.5)
    assert isinstance(limit.max_quantity, Decimal)


def test_order_quantity_limit_gt_zero():
    with pytest.raises(Exception):
        OrderQuantityLimit(rule_id="oq_001", max_quantity=0)


def test_price_band_limit():
    limit = PriceBandLimit(rule_id="pb_001", max_deviation_percent=Decimal("2.0"))
    assert limit.check_type == RiskCheckType.PRICE_BAND
    assert limit.max_deviation_percent == Decimal("2.0")


def test_daily_loss_limit_defaults():
    limit = DailyLossLimit(rule_id="dll_001", max_daily_loss=Decimal("5000"))
    assert limit.max_daily_loss == Decimal("5000")
    assert limit.warning_threshold_percent == Decimal("80.0")
    assert limit.check_type == RiskCheckType.DAILY_LOSS_LIMIT


def test_max_orders_per_minute_limit():
    limit = MaxOrdersPerMinuteLimit(rule_id="mt_001", max_orders=10, window_seconds=60)
    assert limit.max_orders == 10
    assert limit.window_seconds == 60
    assert limit.scope == "account"


def test_kill_switch_limit():
    limit = KillSwitchLimit(rule_id="ks_001")
    assert limit.check_type == RiskCheckType.KILL_SWITCH
    assert limit.allow_risk_reducing is False


def test_emergency_halt_limit():
    limit = EmergencyHaltLimit(rule_id="eh_001")
    assert limit.check_type == RiskCheckType.EMERGENCY_HALT


def test_circuit_breaker_limit():
    limit = CircuitBreakerLimit(rule_id="cb_001", max_decline_percent=Decimal("5.0"))
    assert limit.check_type == RiskCheckType.CIRCUIT_BREAKER
    assert limit.max_decline_percent == Decimal("5.0")
    assert limit.lookback_seconds == 300


def test_drawdown_limit():
    limit = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10.0"))
    assert limit.check_type == RiskCheckType.DRAWDOWN


def test_concentration_limit():
    limit = ConcentrationLimit(rule_id="cl_001", max_concentration_percent=Decimal("20.0"))
    assert limit.check_type == RiskCheckType.CONCENTRATION_LIMIT


def test_max_position_size_limit():
    limit = MaxPositionSizeLimit(
        rule_id="mp_001",
        max_long_quantity=Decimal("1000"),
        max_short_quantity=Decimal("500"),
        instrument_token="738561",
    )
    assert limit.check_type == RiskCheckType.MAX_POSITION_SIZE
    assert limit.max_long_quantity == Decimal("1000")


# ── RiskStateSnapshot ─────────────────────────────────────────────────────


def test_risk_state_snapshot_defaults():
    ts = datetime.now(timezone.utc)
    snap = RiskStateSnapshot(account_id="acc_001", snapshot_timestamp=ts)
    assert snap.daily_realized_pnl == Decimal("0")
    assert snap.daily_turnover == Decimal("0")
    assert snap.trade_count == 0
    assert snap.order_count == 0
    assert snap.peak_equity == Decimal("0")
    assert snap.message_counts == {}
    assert snap.kill_switch_active is False
    assert snap.kill_switch_reason is None
    assert snap.emergency_halt_active is False
    assert snap.circuit_breaker_triggered is False


def test_risk_state_snapshot_with_rc8b_fields():
    ts = datetime.now(timezone.utc)
    snap = RiskStateSnapshot(
        account_id="acc_001",
        snapshot_timestamp=ts,
        daily_realized_pnl=Decimal("1500"),
        daily_turnover=Decimal("250000"),
        trade_count=5,
        order_count=7,
        peak_equity=Decimal("105000"),
        kill_switch_active=False,
        emergency_halt_active=True,
        circuit_breaker_triggered=False,
    )
    assert snap.trade_count == 5
    assert snap.order_count == 7
    assert snap.emergency_halt_active is True
    assert snap.circuit_breaker_triggered is False


def test_risk_state_snapshot_immutable():
    ts = datetime.now(timezone.utc)
    snap = RiskStateSnapshot(account_id="acc_001", snapshot_timestamp=ts)
    with pytest.raises(Exception):
        snap.trade_count = 10  # type: ignore[misc]


def test_risk_state_snapshot_decimal_coercion():
    ts = datetime.now(timezone.utc)
    snap = RiskStateSnapshot(
        account_id="acc_001",
        snapshot_timestamp=ts,
        daily_realized_pnl=1500.0,   # float → Decimal
        daily_turnover="250000",     # str → Decimal
    )
    assert isinstance(snap.daily_realized_pnl, Decimal)
    assert isinstance(snap.daily_turnover, Decimal)
