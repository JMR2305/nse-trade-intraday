"""
Unit tests for RC-8B RiskEngine.

Tests engine orchestration: state management, rule evaluation,
throttle recording, fill recording (with dedup), and snapshot/restore.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from src.risk.engine import RiskEngine
from src.risk.contracts import (
    RiskCheckType,
    RiskRequest,
    RiskContext,
    RiskStateSnapshot,
    OrderQuantityLimit,
    DailyLossLimit,
    MaxOrdersPerMinuteLimit,
    KillSwitchLimit,
    EmergencyHaltLimit,
    CircuitBreakerLimit,
    RiskSeverity,
)

ACCOUNT = "test_account"
TS = datetime.now(timezone.utc)


def make_request(order: dict = None) -> RiskRequest:
    return RiskRequest(
        account_id=ACCOUNT,
        order=order or {"side": "BUY", "quantity": 10, "instrument_token": "738561"},
        check_timestamp=TS,
    )


def make_context(order: dict = None) -> RiskContext:
    return RiskContext(
        account_id=ACCOUNT,
        order=order or {"side": "BUY", "quantity": 10, "instrument_token": "738561"},
    )


# ── Basic evaluation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_no_limits_always_approved():
    engine = RiskEngine()
    result = await engine.evaluate(make_request(), make_context(), limits=[])
    assert result.approved is True
    assert result.violations == []


@pytest.mark.asyncio
async def test_engine_approved_order_within_limits():
    engine = RiskEngine()
    order = {"side": "BUY", "quantity": 50, "instrument_token": "738561"}
    limits = [OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("500"))]
    result = await engine.evaluate(make_request(order), make_context(order), limits)
    assert result.approved is True


@pytest.mark.asyncio
async def test_engine_rejected_order_exceeds_quantity():
    engine = RiskEngine()
    order = {"side": "BUY", "quantity": 600, "instrument_token": "738561"}
    limits = [OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("500"))]
    result = await engine.evaluate(make_request(order), make_context(order), limits)
    assert result.approved is False
    assert len(result.violations) == 1
    assert result.violations[0].check_type == RiskCheckType.ORDER_QUANTITY


# ── Safety rule short-circuit ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_kill_switch_short_circuits():
    engine = RiskEngine()
    await engine.activate_kill_switch(ACCOUNT, "Testing")
    limits = [
        KillSwitchLimit(rule_id="ks_001"),
        OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("500")),
    ]
    order = {"side": "BUY", "quantity": 10, "instrument_token": "738561"}
    result = await engine.evaluate(make_request(order), make_context(order), limits)
    assert result.approved is False
    # Only kill switch violation — short-circuited before other rules
    assert any(v.check_type == RiskCheckType.KILL_SWITCH for v in result.violations)


@pytest.mark.asyncio
async def test_engine_emergency_halt_blocks():
    engine = RiskEngine()
    await engine.activate_emergency_halt(ACCOUNT, "Market crashed")
    limits = [EmergencyHaltLimit(rule_id="eh_001")]
    result = await engine.evaluate(make_request(), make_context(), limits)
    assert result.approved is False
    assert any(v.check_type == RiskCheckType.EMERGENCY_HALT for v in result.violations)


@pytest.mark.asyncio
async def test_engine_circuit_breaker_blocks():
    engine = RiskEngine()
    await engine.trigger_circuit_breaker(ACCOUNT)
    limits = [CircuitBreakerLimit(rule_id="cb_001", max_decline_percent=Decimal("5"))]
    result = await engine.evaluate(make_request(), make_context(), limits)
    assert result.approved is False
    assert any(v.check_type == RiskCheckType.CIRCUIT_BREAKER for v in result.violations)


# ── Kill switch lifecycle ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_deactivate_kill_switch_allows():
    engine = RiskEngine()
    await engine.activate_kill_switch(ACCOUNT, "Testing")
    await engine.deactivate_kill_switch(ACCOUNT)
    limits = [KillSwitchLimit(rule_id="ks_001")]
    result = await engine.evaluate(make_request(), make_context(), limits)
    assert result.approved is True


# ── Daily loss limit ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_daily_loss_at_limit_blocks():
    engine = RiskEngine()
    # Record a fill that puts the account at the loss limit
    await engine.record_fill(
        account_id=ACCOUNT,
        fill_id="fill_001",
        realized_pnl=Decimal("-5000"),
        turnover=Decimal("100000"),
        current_equity=Decimal("95000"),
    )
    limits = [DailyLossLimit(rule_id="dll_001", max_daily_loss=Decimal("5000"))]
    result = await engine.evaluate(make_request(), make_context(), limits)
    assert result.approved is False
    assert any(v.severity == RiskSeverity.FATAL for v in result.violations)


@pytest.mark.asyncio
async def test_engine_daily_loss_warning_still_approved():
    engine = RiskEngine()
    # At 80% of limit (warning threshold)
    await engine.record_fill(
        account_id=ACCOUNT,
        fill_id="fill_001",
        realized_pnl=Decimal("-4000"),
        turnover=Decimal("100000"),
        current_equity=Decimal("96000"),
    )
    limits = [
        DailyLossLimit(
            rule_id="dll_001",
            max_daily_loss=Decimal("5000"),
            warning_threshold_percent=Decimal("80"),
        )
    ]
    result = await engine.evaluate(make_request(), make_context(), limits)
    # WARNING violation does not block
    assert result.approved is True
    assert any(v.severity == RiskSeverity.WARNING for v in result.violations)


# ── Throttle recording ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_throttle_records_after_approved_orders():
    engine = RiskEngine()
    limits = [
        MaxOrdersPerMinuteLimit(rule_id="mt_001", max_orders=10, window_seconds=60)
    ]
    # Submit 10 orders — all should be approved
    for i in range(10):
        order = {"side": "BUY", "quantity": 10, "instrument_token": "738561"}
        result = await engine.evaluate(make_request(order), make_context(order), limits)
        assert result.approved is True, f"Order {i} should be approved; was rejected"

    # 11th order should be blocked
    order = {"side": "BUY", "quantity": 10, "instrument_token": "738561"}
    result = await engine.evaluate(make_request(order), make_context(order), limits)
    assert result.approved is False
    assert any(v.check_type == RiskCheckType.MAX_ORDERS_PER_MINUTE for v in result.violations)


@pytest.mark.asyncio
async def test_engine_throttle_not_recorded_on_rejected_order():
    """Throttle count must not increment when the order is rejected by another rule."""
    engine = RiskEngine()
    limits = [
        OrderQuantityLimit(rule_id="oq_001", max_quantity=Decimal("5")),
        MaxOrdersPerMinuteLimit(rule_id="mt_001", max_orders=2, window_seconds=60),
    ]
    order = {"side": "BUY", "quantity": 100, "instrument_token": "738561"}

    # Order is rejected by quantity rule — throttle count should not increment
    result = await engine.evaluate(make_request(order), make_context(order), limits)
    assert result.approved is False

    # Verify throttle count is still 0 by submitting 2 valid orders
    valid_order = {"side": "BUY", "quantity": 1, "instrument_token": "738561"}
    r1 = await engine.evaluate(make_request(valid_order), make_context(valid_order), limits)
    r2 = await engine.evaluate(make_request(valid_order), make_context(valid_order), limits)
    assert r1.approved is True
    assert r2.approved is True  # Would fail if throttle was incremented by rejected order


# ── Fill recording ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_fill_recording():
    engine = RiskEngine()
    recorded = await engine.record_fill(
        account_id=ACCOUNT,
        fill_id="fill_001",
        realized_pnl=Decimal("500"),
        turnover=Decimal("50000"),
        current_equity=Decimal("100500"),
    )
    assert recorded is True
    snap = await engine.get_state_snapshot(ACCOUNT, TS)
    assert snap.trade_count == 1
    assert snap.daily_realized_pnl == Decimal("500")


@pytest.mark.asyncio
async def test_engine_fill_dedup_ignores_duplicate():
    """Duplicate fill_id must not double-count the fill."""
    engine = RiskEngine()
    r1 = await engine.record_fill(
        account_id=ACCOUNT,
        fill_id="fill_dup",
        realized_pnl=Decimal("500"),
        turnover=Decimal("50000"),
        current_equity=Decimal("100500"),
    )
    r2 = await engine.record_fill(
        account_id=ACCOUNT,
        fill_id="fill_dup",  # Same ID
        realized_pnl=Decimal("500"),
        turnover=Decimal("50000"),
        current_equity=Decimal("101000"),
    )
    assert r1 is True
    assert r2 is False  # Duplicate ignored
    snap = await engine.get_state_snapshot(ACCOUNT, TS)
    assert snap.trade_count == 1  # Only counted once
    assert snap.daily_realized_pnl == Decimal("500")  # Not doubled


# ── State snapshot & restore ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_snapshot_captures_state():
    engine = RiskEngine()
    await engine.record_fill(
        account_id=ACCOUNT,
        fill_id="fill_001",
        realized_pnl=Decimal("1000"),
        turnover=Decimal("80000"),
        current_equity=Decimal("101000"),
    )
    await engine.activate_kill_switch(ACCOUNT, "snapshot test")
    snap = await engine.get_state_snapshot(ACCOUNT, TS)
    assert snap.account_id == ACCOUNT
    assert snap.trade_count == 1
    assert snap.daily_realized_pnl == Decimal("1000")
    assert snap.kill_switch_active is True


@pytest.mark.asyncio
async def test_engine_restore_state_from_snapshot():
    engine = RiskEngine()
    snap = RiskStateSnapshot(
        account_id=ACCOUNT,
        snapshot_timestamp=TS,
        daily_realized_pnl=Decimal("2000"),
        daily_turnover=Decimal("100000"),
        trade_count=4,
        order_count=6,
        peak_equity=Decimal("105000"),
        kill_switch_active=True,
        kill_switch_reason="Restored",
    )
    await engine.restore_state(snap)

    restored_snap = await engine.get_state_snapshot(ACCOUNT, TS)
    assert restored_snap.trade_count == 4
    assert restored_snap.daily_realized_pnl == Decimal("2000")
    assert restored_snap.kill_switch_active is True


# ── Disabled rule skipped ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_disabled_limit_skipped():
    engine = RiskEngine()
    order = {"side": "BUY", "quantity": 600, "instrument_token": "738561"}
    limits = [
        OrderQuantityLimit(
            rule_id="oq_001", max_quantity=Decimal("500"), enabled=False
        )
    ]
    result = await engine.evaluate(make_request(order), make_context(order), limits)
    # Disabled rule → approved even though quantity exceeds limit
    assert result.approved is True


# ── Multiple accounts independent ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_multiple_accounts_independent():
    engine = RiskEngine()
    acc_a = "account_A"
    acc_b = "account_B"

    await engine.activate_kill_switch(acc_a, "Account A only")
    limits = [KillSwitchLimit(rule_id="ks_001")]

    req_a = RiskRequest(account_id=acc_a, order={"side": "BUY", "quantity": 10, "instrument_token": "t"}, check_timestamp=TS)
    req_b = RiskRequest(account_id=acc_b, order={"side": "BUY", "quantity": 10, "instrument_token": "t"}, check_timestamp=TS)
    ctx_a = RiskContext(account_id=acc_a, order={"side": "BUY", "quantity": 10, "instrument_token": "t"})
    ctx_b = RiskContext(account_id=acc_b, order={"side": "BUY", "quantity": 10, "instrument_token": "t"})

    result_a = await engine.evaluate(req_a, ctx_a, limits)
    result_b = await engine.evaluate(req_b, ctx_b, limits)

    assert result_a.approved is False  # Kill switch active for A
    assert result_b.approved is True   # No kill switch for B
