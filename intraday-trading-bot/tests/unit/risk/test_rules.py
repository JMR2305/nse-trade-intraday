"""
Unit tests for RC-8B risk rules.

Each rule's evaluate() is tested directly with crafted RiskRequest,
RiskContext, RiskConfiguration, and RiskStateSnapshot objects.
No engine is involved — pure unit tests for rule logic.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from src.risk.contracts import (
    RiskCheckType,
    RiskSeverity,
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
    DailyProfitTargetLock,
    MaxTradesPerDayLimit,
    CashAvailabilityLimit,
    PortfolioExposureLimit,
    ConcentrationLimit,
)
from src.risk.rules import (
    KillSwitchRule,
    EmergencyHaltRule,
    CircuitBreakerRule,
    OrderQuantityRule,
    PriceBandRule,
    MaxPositionSizeRule,
    DailyLossLimitRule,
    MaxOrdersPerMinuteRule,
    DrawdownRule,
    TurnoverVelocityRule,
    DailyProfitTargetRule,
    MaxTradesPerDayRule,
    CashAvailabilityRule,
    PortfolioExposureRule,
    ConcentrationRule,
    get_rule,
    RULE_REGISTRY,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

TS = datetime.now(timezone.utc)
ACCOUNT = "acc_001"


def make_state(
    kill_switch_active: bool = False,
    kill_switch_reason: str = None,
    emergency_halt_active: bool = False,
    circuit_breaker_triggered: bool = False,
    daily_realized_pnl: Decimal = Decimal("0"),
    daily_turnover: Decimal = Decimal("0"),
    trade_count: int = 0,
    order_count: int = 0,
    peak_equity: Decimal = Decimal("100000"),
    message_counts: dict = None,
) -> RiskStateSnapshot:
    return RiskStateSnapshot(
        account_id=ACCOUNT,
        snapshot_timestamp=TS,
        kill_switch_active=kill_switch_active,
        kill_switch_reason=kill_switch_reason,
        emergency_halt_active=emergency_halt_active,
        circuit_breaker_triggered=circuit_breaker_triggered,
        daily_realized_pnl=daily_realized_pnl,
        daily_turnover=daily_turnover,
        trade_count=trade_count,
        order_count=order_count,
        peak_equity=peak_equity,
        message_counts=message_counts or {},
    )


def make_request(order: dict = None) -> RiskRequest:
    return RiskRequest(
        account_id=ACCOUNT,
        order=order or {"side": "BUY", "quantity": 10, "instrument_token": "738561"},
        check_timestamp=TS,
    )


def make_context(order: dict = None, portfolio: dict = None, positions: dict = None, prices: dict = None) -> RiskContext:
    return RiskContext(
        account_id=ACCOUNT,
        order=order or {"side": "BUY", "quantity": 10, "instrument_token": "738561"},
        portfolio_snapshot=portfolio,
        position_snapshots=positions or {},
        market_prices={k: Decimal(str(v)) for k, v in (prices or {}).items()},
    )


# ── Safety rules ──────────────────────────────────────────────────────────


def test_kill_switch_rule_inactive_allows():
    rule = KillSwitchRule()
    state = make_state(kill_switch_active=False)
    result = rule.evaluate(make_request(), make_context(), KillSwitchLimit(rule_id="ks_001"), state)
    assert result is None


def test_kill_switch_rule_active_blocks():
    rule = KillSwitchRule()
    state = make_state(kill_switch_active=True, kill_switch_reason="Testing")
    result = rule.evaluate(make_request(), make_context(), KillSwitchLimit(rule_id="ks_001"), state)
    assert result is not None
    assert result.severity == RiskSeverity.FATAL
    assert "Testing" in result.message
    assert result.check_type == RiskCheckType.KILL_SWITCH


def test_emergency_halt_rule_inactive_allows():
    rule = EmergencyHaltRule()
    state = make_state(emergency_halt_active=False)
    result = rule.evaluate(make_request(), make_context(), EmergencyHaltLimit(rule_id="eh_001"), state)
    assert result is None


def test_emergency_halt_rule_active_blocks():
    rule = EmergencyHaltRule()
    state = make_state(emergency_halt_active=True)
    result = rule.evaluate(make_request(), make_context(), EmergencyHaltLimit(rule_id="eh_001"), state)
    assert result is not None
    assert result.severity == RiskSeverity.FATAL
    assert result.check_type == RiskCheckType.EMERGENCY_HALT


def test_circuit_breaker_rule_not_triggered_allows():
    rule = CircuitBreakerRule()
    state = make_state(circuit_breaker_triggered=False)
    from src.risk.contracts import CircuitBreakerLimit
    result = rule.evaluate(
        make_request(), make_context(),
        CircuitBreakerLimit(rule_id="cb_001", max_decline_percent=Decimal("5")),
        state
    )
    assert result is None


def test_circuit_breaker_rule_triggered_blocks():
    rule = CircuitBreakerRule()
    state = make_state(circuit_breaker_triggered=True)
    from src.risk.contracts import CircuitBreakerLimit
    result = rule.evaluate(
        make_request(), make_context(),
        CircuitBreakerLimit(rule_id="cb_001", max_decline_percent=Decimal("5")),
        state
    )
    assert result is not None
    assert result.severity == RiskSeverity.FATAL


# ── Order quantity rule ───────────────────────────────────────────────────


def test_order_quantity_within_limit():
    rule = OrderQuantityRule()
    order = {"side": "BUY", "quantity": 100, "instrument_token": "738561"}
    config = OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("500"))
    state = make_state()
    result = rule.evaluate(make_request(order), make_context(order), config, state)
    assert result is None


def test_order_quantity_exceeds_limit():
    rule = OrderQuantityRule()
    order = {"side": "BUY", "quantity": 600, "instrument_token": "738561"}
    config = OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("500"))
    state = make_state()
    result = rule.evaluate(make_request(order), make_context(order), config, state)
    assert result is not None
    assert result.check_type == RiskCheckType.ORDER_QUANTITY
    assert result.limit_value == Decimal("500")
    assert result.actual_value == Decimal("600")


def test_order_quantity_at_limit_allowed():
    rule = OrderQuantityRule()
    order = {"side": "BUY", "quantity": 500, "instrument_token": "738561"}
    config = OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("500"))
    state = make_state()
    result = rule.evaluate(make_request(order), make_context(order), config, state)
    assert result is None


def test_order_quantity_instrument_filter_skips():
    """Rule with instrument_token filter skips orders for other instruments."""
    rule = OrderQuantityRule()
    order = {"side": "BUY", "quantity": 600, "instrument_token": "OTHER"}
    config = OrderQuantityLimit(
        rule_id="oq_001", max_quantity=Decimal("500"), instrument_token="738561"
    )
    state = make_state()
    result = rule.evaluate(make_request(order), make_context(order), config, state)
    assert result is None  # Different instrument; rule skipped


# ── Price band rule ───────────────────────────────────────────────────────


def test_price_band_within_allowed():
    rule = PriceBandRule()
    order = {"side": "BUY", "quantity": 10, "instrument_token": "738561", "price": 100}
    config = PriceBandLimit(rule_id="pb_001", max_deviation_percent=Decimal("2.0"))
    state = make_state()
    ctx = make_context(order=order, prices={"738561": 100})
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None


def test_price_band_outside_allowed():
    rule = PriceBandRule()
    order = {"side": "BUY", "quantity": 10, "instrument_token": "738561", "price": 105}
    config = PriceBandLimit(rule_id="pb_001", max_deviation_percent=Decimal("2.0"))
    state = make_state()
    ctx = make_context(order=order, prices={"738561": 100})
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is not None
    assert result.check_type == RiskCheckType.PRICE_BAND


def test_price_band_no_ltp_skips():
    """PriceBandRule skips gracefully when no market price is available."""
    rule = PriceBandRule()
    order = {"side": "BUY", "quantity": 10, "instrument_token": "738561", "price": 105}
    config = PriceBandLimit(rule_id="pb_001", max_deviation_percent=Decimal("2.0"))
    state = make_state()
    ctx = make_context(order=order, prices={})  # No LTP
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None  # No LTP → rule skipped


def test_price_band_market_order_skips():
    """PriceBandRule skips MARKET orders (no price field)."""
    rule = PriceBandRule()
    order = {"side": "BUY", "quantity": 10, "instrument_token": "738561"}  # No price
    config = PriceBandLimit(rule_id="pb_001", max_deviation_percent=Decimal("2.0"))
    state = make_state()
    ctx = make_context(order=order, prices={"738561": 100})
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None


# ── Max position size rule ────────────────────────────────────────────────


def test_max_position_size_buy_within_limit():
    rule = MaxPositionSizeRule()
    order = {"side": "BUY", "quantity": 100, "instrument_token": "738561"}
    config = MaxPositionSizeLimit(
        rule_id="mp_001",
        max_long_quantity=Decimal("500"),
        max_short_quantity=Decimal("500"),
        instrument_token="738561",
    )
    state = make_state()
    positions = {"738561": {"net_quantity": Decimal("300"), "direction": "LONG", "market_value": Decimal("30000")}}
    ctx = make_context(order=order, positions=positions)
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None  # 300 + 100 = 400 ≤ 500


def test_max_position_size_buy_exceeds_limit():
    rule = MaxPositionSizeRule()
    order = {"side": "BUY", "quantity": 250, "instrument_token": "738561"}
    config = MaxPositionSizeLimit(
        rule_id="mp_001",
        max_long_quantity=Decimal("500"),
        max_short_quantity=Decimal("500"),
        instrument_token="738561",
    )
    state = make_state()
    positions = {"738561": {"net_quantity": Decimal("300"), "direction": "LONG", "market_value": Decimal("30000")}}
    ctx = make_context(order=order, positions=positions)
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is not None  # 300 + 250 = 550 > 500


def test_max_position_size_sell_within_limit():
    rule = MaxPositionSizeRule()
    order = {"side": "SELL", "quantity": 100, "instrument_token": "738561"}
    config = MaxPositionSizeLimit(
        rule_id="mp_001",
        max_long_quantity=Decimal("500"),
        max_short_quantity=Decimal("200"),
        instrument_token="738561",
    )
    state = make_state()
    positions = {"738561": {"net_quantity": Decimal("50"), "direction": "LONG", "market_value": Decimal("5000")}}
    ctx = make_context(order=order, positions=positions)
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None  # 50 - 100 = -50 → short 50 ≤ 200


# ── Daily loss limit rule ─────────────────────────────────────────────────


def test_daily_loss_no_loss_allows():
    rule = DailyLossLimitRule()
    config = DailyLossLimit(rule_id="dll_001", max_daily_loss=Decimal("5000"))
    state = make_state(daily_realized_pnl=Decimal("100"))
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is None


def test_daily_loss_at_warning_threshold():
    rule = DailyLossLimitRule()
    config = DailyLossLimit(
        rule_id="dll_001",
        max_daily_loss=Decimal("5000"),
        warning_threshold_percent=Decimal("80"),
    )
    # Loss = 4000 = 80% of 5000 → WARNING
    state = make_state(daily_realized_pnl=Decimal("-4000"))
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is not None
    assert result.severity == RiskSeverity.WARNING


def test_daily_loss_at_limit_is_fatal():
    rule = DailyLossLimitRule()
    config = DailyLossLimit(rule_id="dll_001", max_daily_loss=Decimal("5000"))
    # Loss = 5000 = 100% of limit → FATAL
    state = make_state(daily_realized_pnl=Decimal("-5000"))
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is not None
    assert result.severity == RiskSeverity.FATAL


def test_daily_loss_exceeds_limit_is_fatal():
    rule = DailyLossLimitRule()
    config = DailyLossLimit(rule_id="dll_001", max_daily_loss=Decimal("5000"))
    state = make_state(daily_realized_pnl=Decimal("-6000"))
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is not None
    assert result.severity == RiskSeverity.FATAL


# ── Max orders per minute rule ────────────────────────────────────────────


def test_max_orders_within_limit():
    rule = MaxOrdersPerMinuteRule()
    config = MaxOrdersPerMinuteLimit(rule_id="mt_001", max_orders=10, window_seconds=60)
    throttle_key = f"orders_per_minute:{ACCOUNT}"
    state = make_state(message_counts={throttle_key: 5})
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is None  # 5 < 10


def test_max_orders_at_limit_blocked():
    rule = MaxOrdersPerMinuteRule()
    config = MaxOrdersPerMinuteLimit(rule_id="mt_001", max_orders=10, window_seconds=60)
    throttle_key = f"orders_per_minute:{ACCOUNT}"
    state = make_state(message_counts={throttle_key: 10})
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is not None
    assert result.check_type == RiskCheckType.MAX_ORDERS_PER_MINUTE


def test_max_orders_zero_count_allows():
    rule = MaxOrdersPerMinuteRule()
    config = MaxOrdersPerMinuteLimit(rule_id="mt_001", max_orders=10, window_seconds=60)
    state = make_state(message_counts={})
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is None


# ── Daily profit target ───────────────────────────────────────────────────


def test_profit_target_not_reached():
    rule = DailyProfitTargetRule()
    config = DailyProfitTargetLock(rule_id="pt_001", profit_target=Decimal("10000"))
    state = make_state(daily_realized_pnl=Decimal("5000"))
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is None


def test_profit_target_reached_blocks():
    rule = DailyProfitTargetRule()
    config = DailyProfitTargetLock(rule_id="pt_001", profit_target=Decimal("10000"))
    state = make_state(daily_realized_pnl=Decimal("10000"))
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is not None
    assert result.severity == RiskSeverity.CRITICAL


# ── Max trades per day ────────────────────────────────────────────────────


def test_max_trades_within_limit():
    rule = MaxTradesPerDayRule()
    config = MaxTradesPerDayLimit(rule_id="mt_001", max_trades=50)
    state = make_state(trade_count=30)
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is None


def test_max_trades_at_limit_blocked():
    rule = MaxTradesPerDayRule()
    config = MaxTradesPerDayLimit(rule_id="mt_001", max_trades=50)
    state = make_state(trade_count=50)
    result = rule.evaluate(make_request(), make_context(), config, state)
    assert result is not None


# ── Drawdown rule ─────────────────────────────────────────────────────────


def test_drawdown_within_limit():
    rule = DrawdownRule()
    config = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10"))
    portfolio = {"equity": Decimal("95000")}
    state = make_state(peak_equity=Decimal("100000"))
    ctx = make_context(portfolio=portfolio)
    result = rule.evaluate(make_request(), ctx, config, state)
    assert result is None  # 5% drawdown < 10%


def test_drawdown_exceeds_limit():
    rule = DrawdownRule()
    config = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10"))
    portfolio = {"equity": Decimal("85000")}
    state = make_state(peak_equity=Decimal("100000"))
    ctx = make_context(portfolio=portfolio)
    result = rule.evaluate(make_request(), ctx, config, state)
    assert result is not None  # 15% drawdown > 10%
    assert result.check_type == RiskCheckType.DRAWDOWN


def test_drawdown_zero_peak_skips():
    rule = DrawdownRule()
    config = DrawdownLimit(rule_id="dd_001", max_drawdown_percent=Decimal("10"))
    portfolio = {"equity": Decimal("100000")}
    state = make_state(peak_equity=Decimal("0"))  # No peak yet
    ctx = make_context(portfolio=portfolio)
    result = rule.evaluate(make_request(), ctx, config, state)
    assert result is None


# ── Cash availability rule ────────────────────────────────────────────────


def test_cash_availability_sufficient():
    rule = CashAvailabilityRule()
    config = CashAvailabilityLimit(rule_id="ca_001")
    order = {"side": "BUY", "quantity": 10, "price": 100, "instrument_token": "738561"}
    portfolio = {"cash": Decimal("10000")}
    ctx = make_context(order=order, portfolio=portfolio)
    state = make_state()
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None  # 10 * 100 = 1000 ≤ 10000


def test_cash_availability_insufficient():
    rule = CashAvailabilityRule()
    config = CashAvailabilityLimit(rule_id="ca_001")
    order = {"side": "BUY", "quantity": 200, "price": 100, "instrument_token": "738561"}
    portfolio = {"cash": Decimal("5000")}
    ctx = make_context(order=order, portfolio=portfolio)
    state = make_state()
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is not None  # 200 * 100 = 20000 > 5000


def test_cash_availability_sell_skipped():
    """Cash check only applies to BUY orders."""
    rule = CashAvailabilityRule()
    config = CashAvailabilityLimit(rule_id="ca_001")
    order = {"side": "SELL", "quantity": 200, "price": 100, "instrument_token": "738561"}
    portfolio = {"cash": Decimal("0")}  # Zero cash
    ctx = make_context(order=order, portfolio=portfolio)
    state = make_state()
    result = rule.evaluate(make_request(order), ctx, config, state)
    assert result is None  # SELL orders skip cash check


# ── Rule registry ─────────────────────────────────────────────────────────


def test_get_rule_all_registered_types():
    registered_types = list(RULE_REGISTRY.keys())
    assert len(registered_types) >= 10  # At least the core rules are registered
    for check_type in registered_types:
        rule = get_rule(check_type)
        assert rule is not None


def test_get_rule_unknown_type_raises():
    with pytest.raises(KeyError):
        get_rule("NONEXISTENT_TYPE")  # type: ignore
