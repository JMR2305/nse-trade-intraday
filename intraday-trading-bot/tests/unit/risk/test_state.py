"""
Unit tests for RC-8B RiskState.

Tests daily counters, throttle windows, safety mechanisms,
snapshot creation, and state restoration.
"""

import asyncio
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from src.risk.state import RiskState
from src.risk.contracts import RiskStateSnapshot


# ── Initial state ─────────────────────────────────────────────────────────


def test_initial_state_zero_counters():
    state = RiskState("acc_001")
    assert state.account_id == "acc_001"
    assert state.daily_realized_pnl == Decimal("0")
    assert state.daily_turnover == Decimal("0")
    assert state.trade_count == 0
    assert state.order_count == 0
    assert state.peak_equity == Decimal("0")
    assert state.kill_switch_active is False
    assert state.kill_switch_reason is None
    assert state.emergency_halt_active is False
    assert state.circuit_breaker_triggered is False


def test_initial_state_with_equity():
    state = RiskState("acc_001", initial_equity=Decimal("100000"))
    assert state.peak_equity == Decimal("100000")


# ── record_fill ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_fill_increments_trade_count():
    state = RiskState("acc_001")
    ts = datetime.now(timezone.utc)
    await state.record_fill(
        realized_pnl=Decimal("500"),
        turnover=Decimal("50000"),
        current_equity=Decimal("100500"),
        fill_timestamp=ts,
    )
    assert state.trade_count == 1
    assert state.daily_realized_pnl == Decimal("500")
    assert state.daily_turnover == Decimal("50000")


@pytest.mark.asyncio
async def test_record_fill_accumulates():
    state = RiskState("acc_001", initial_equity=Decimal("100000"))
    ts = datetime.now(timezone.utc)
    for i in range(5):
        await state.record_fill(
            realized_pnl=Decimal("100"),
            turnover=Decimal("10000"),
            current_equity=Decimal(str(100000 + (i + 1) * 100)),
            fill_timestamp=ts,
        )
    assert state.trade_count == 5
    assert state.daily_realized_pnl == Decimal("500")
    assert state.daily_turnover == Decimal("50000")


@pytest.mark.asyncio
async def test_record_fill_updates_peak_equity():
    state = RiskState("acc_001", initial_equity=Decimal("100000"))
    ts = datetime.now(timezone.utc)
    await state.record_fill(
        realized_pnl=Decimal("2000"),
        turnover=Decimal("100000"),
        current_equity=Decimal("102000"),
        fill_timestamp=ts,
    )
    assert state.peak_equity == Decimal("102000")


@pytest.mark.asyncio
async def test_record_fill_negative_pnl():
    state = RiskState("acc_001")
    ts = datetime.now(timezone.utc)
    await state.record_fill(
        realized_pnl=Decimal("-3000"),
        turnover=Decimal("100000"),
        current_equity=Decimal("97000"),
        fill_timestamp=ts,
    )
    assert state.daily_realized_pnl == Decimal("-3000")
    assert state.trade_count == 1


# ── record_order ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_order_increments_count():
    state = RiskState("acc_001")
    ts = datetime.now(timezone.utc)
    await state.record_order(ts)
    await state.record_order(ts)
    assert state.order_count == 2


# ── record_message (throttle) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_message_counts_within_window():
    state = RiskState("acc_001")
    now = datetime.now(timezone.utc)
    count1 = await state.record_message("key1", 60, now)
    count2 = await state.record_message("key1", 60, now)
    assert count1 == 1
    assert count2 == 2


@pytest.mark.asyncio
async def test_record_message_resets_after_window():
    state = RiskState("acc_001")
    past = datetime.now(timezone.utc) - timedelta(seconds=61)
    await state.record_message("key1", 60, past)
    now = datetime.now(timezone.utc)
    count = await state.record_message("key1", 60, now)
    assert count == 1  # Reset


@pytest.mark.asyncio
async def test_get_message_count_before_recording():
    state = RiskState("acc_001")
    now = datetime.now(timezone.utc)
    count = await state.get_message_count("no_such_key", 60, now)
    assert count == 0


# ── Kill switch ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_kill_switch():
    state = RiskState("acc_001")
    await state.activate_kill_switch("Testing")
    assert state.kill_switch_active is True
    assert state.kill_switch_reason == "Testing"


@pytest.mark.asyncio
async def test_deactivate_kill_switch():
    state = RiskState("acc_001")
    await state.activate_kill_switch("Testing")
    await state.deactivate_kill_switch()
    assert state.kill_switch_active is False
    assert state.kill_switch_reason is None


# ── Emergency halt ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_emergency_halt():
    state = RiskState("acc_001")
    await state.activate_emergency_halt("Market crash")
    assert state.emergency_halt_active is True


@pytest.mark.asyncio
async def test_deactivate_emergency_halt():
    state = RiskState("acc_001")
    await state.activate_emergency_halt("Market crash")
    await state.deactivate_emergency_halt()
    assert state.emergency_halt_active is False


# ── Circuit breaker ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_circuit_breaker():
    state = RiskState("acc_001")
    await state.trigger_circuit_breaker()
    assert state.circuit_breaker_triggered is True


@pytest.mark.asyncio
async def test_reset_circuit_breaker():
    state = RiskState("acc_001")
    await state.trigger_circuit_breaker()
    await state.reset_circuit_breaker()
    assert state.circuit_breaker_triggered is False


# ── Snapshot ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_to_snapshot_captures_all_fields():
    state = RiskState("acc_001", initial_equity=Decimal("100000"))
    ts = datetime.now(timezone.utc)
    await state.record_fill(
        realized_pnl=Decimal("500"),
        turnover=Decimal("50000"),
        current_equity=Decimal("100500"),
        fill_timestamp=ts,
    )
    await state.record_order(ts)
    await state.activate_kill_switch("test")
    await state.activate_emergency_halt("test halt")
    await state.trigger_circuit_breaker()

    snap = state.to_snapshot(ts)
    assert isinstance(snap, RiskStateSnapshot)
    assert snap.trade_count == 1
    assert snap.order_count == 1
    assert snap.daily_realized_pnl == Decimal("500")
    assert snap.daily_turnover == Decimal("50000")
    assert snap.kill_switch_active is True
    assert snap.emergency_halt_active is True
    assert snap.circuit_breaker_triggered is True
    assert snap.peak_equity == Decimal("100500")


@pytest.mark.asyncio
async def test_from_snapshot_restores_state():
    ts = datetime.now(timezone.utc)
    snap = RiskStateSnapshot(
        account_id="acc_001",
        snapshot_timestamp=ts,
        daily_realized_pnl=Decimal("1000"),
        daily_turnover=Decimal("80000"),
        trade_count=3,
        order_count=5,
        peak_equity=Decimal("101000"),
        kill_switch_active=True,
        kill_switch_reason="Restored from snapshot",
        emergency_halt_active=False,
        circuit_breaker_triggered=True,
    )
    state = RiskState.from_snapshot(snap)
    assert state.account_id == "acc_001"
    assert state.trade_count == 3
    assert state.order_count == 5
    assert state.daily_realized_pnl == Decimal("1000")
    assert state.kill_switch_active is True
    assert state.circuit_breaker_triggered is True
    assert state.emergency_halt_active is False


# ── Daily reset ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_daily_clears_counters():
    state = RiskState("acc_001")
    ts = datetime.now(timezone.utc)
    await state.record_fill(
        realized_pnl=Decimal("500"),
        turnover=Decimal("50000"),
        current_equity=Decimal("100500"),
        fill_timestamp=ts,
    )
    await state.record_order(ts)
    await state.reset_daily(initial_equity=Decimal("100000"))
    assert state.daily_realized_pnl == Decimal("0")
    assert state.daily_turnover == Decimal("0")
    assert state.trade_count == 0
    assert state.order_count == 0
    assert state.peak_equity == Decimal("100000")


@pytest.mark.asyncio
async def test_reset_daily_does_not_clear_safety_state():
    """Kill switch, emergency halt, and circuit breaker survive daily reset."""
    state = RiskState("acc_001")
    await state.activate_kill_switch("test")
    await state.activate_emergency_halt("test")
    await state.trigger_circuit_breaker()
    await state.reset_daily()
    assert state.kill_switch_active is True
    assert state.emergency_halt_active is True
    assert state.circuit_breaker_triggered is True
