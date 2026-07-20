"""
Unit tests for risk/state.py.
"""

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta

from src.risk.state import RiskState
from src.risk.contracts import RiskStateSnapshot


class TestRiskState:
    @pytest.fixture
    def state(self):
        return RiskState("ACC001", initial_equity=Decimal("100000"))

    @pytest.mark.asyncio
    async def test_initial_state(self, state):
        assert state.account_id == "ACC001"
        assert state.daily_realized_pnl == Decimal("0")
        assert state.daily_turnover == Decimal("0")
        assert state.peak_equity == Decimal("100000")
        assert state.kill_switch_active is False
        assert state.message_counts == {}

    @pytest.mark.asyncio
    async def test_record_fill_profit(self, state):
        await state.record_fill(
            realized_pnl=Decimal("500"),
            turnover=Decimal("10000"),
            current_equity=Decimal("100500"),
            fill_timestamp=datetime.utcnow(),
        )
        assert state.daily_realized_pnl == Decimal("500")
        assert state.daily_turnover == Decimal("10000")
        assert state.peak_equity == Decimal("100500")

    @pytest.mark.asyncio
    async def test_record_fill_loss(self, state):
        await state.record_fill(
            realized_pnl=Decimal("-500"),
            turnover=Decimal("10000"),
            current_equity=Decimal("99500"),
            fill_timestamp=datetime.utcnow(),
        )
        assert state.daily_realized_pnl == Decimal("-500")
        assert state.daily_turnover == Decimal("10000")
        assert state.peak_equity == Decimal("100000")

    @pytest.mark.asyncio
    async def test_record_multiple_fills(self, state):
        await state.record_fill(
            realized_pnl=Decimal("1000"),
            turnover=Decimal("10000"),
            current_equity=Decimal("101000"),
            fill_timestamp=datetime.utcnow(),
        )
        await state.record_fill(
            realized_pnl=Decimal("-200"),
            turnover=Decimal("5000"),
            current_equity=Decimal("100800"),
            fill_timestamp=datetime.utcnow(),
        )
        assert state.daily_realized_pnl == Decimal("800")
        assert state.daily_turnover == Decimal("15000")
        assert state.peak_equity == Decimal("101000")

    @pytest.mark.asyncio
    async def test_record_message(self, state):
        now = datetime.utcnow()
        count = await state.record_message("account:ACC001", 60, now)
        assert count == 1

        count = await state.record_message("account:ACC001", 60, now)
        assert count == 2

    @pytest.mark.asyncio
    async def test_record_message_window_expiry(self, state):
        now = datetime.utcnow()
        await state.record_message("account:ACC001", 60, now)

        later = now + timedelta(seconds=61)
        count = await state.record_message("account:ACC001", 60, later)
        assert count == 1

    @pytest.mark.asyncio
    async def test_get_message_count(self, state):
        now = datetime.utcnow()
        await state.record_message("key1", 60, now)

        count = await state.get_message_count("key1", 60, now)
        assert count == 1

    @pytest.mark.asyncio
    async def test_kill_switch(self, state):
        await state.activate_kill_switch("Daily loss limit reached")
        assert state.kill_switch_active is True
        assert state.kill_switch_reason == "Daily loss limit reached"

        await state.deactivate_kill_switch()
        assert state.kill_switch_active is False
        assert state.kill_switch_reason is None

    @pytest.mark.asyncio
    async def test_reset_daily(self, state):
        await state.record_fill(
            realized_pnl=Decimal("500"),
            turnover=Decimal("10000"),
            current_equity=Decimal("100500"),
            fill_timestamp=datetime.utcnow(),
        )
        await state.record_message("key1", 60, datetime.utcnow())
        await state.activate_kill_switch("Test")

        await state.reset_daily(initial_equity=Decimal("100000"))
        assert state.daily_realized_pnl == Decimal("0")
        assert state.daily_turnover == Decimal("0")
        assert state.peak_equity == Decimal("100000")
        assert state.message_counts == {}
        # Kill switch is NOT reset by reset_daily() — it is a separate safety
        # mechanism that must be explicitly deactivated.
        assert state.kill_switch_active is True
        assert state.kill_switch_reason == "Test"

    @pytest.mark.asyncio
    async def test_to_snapshot(self, state):
        now = datetime.utcnow()
        await state.record_fill(
            realized_pnl=Decimal("500"),
            turnover=Decimal("10000"),
            current_equity=Decimal("100500"),
            fill_timestamp=now,
        )

        snapshot = state.to_snapshot(now)
        assert snapshot.account_id == "ACC001"
        assert snapshot.daily_realized_pnl == Decimal("500")
        assert snapshot.daily_turnover == Decimal("10000")
        assert snapshot.peak_equity == Decimal("100500")

    @pytest.mark.asyncio
    async def test_from_snapshot(self, state):
        now = datetime.utcnow()
        snapshot = RiskStateSnapshot(
            account_id="ACC001",
            snapshot_timestamp=now,
            daily_realized_pnl=Decimal("-500"),
            daily_turnover=Decimal("20000"),
            peak_equity=Decimal("95000"),
            message_counts={"account:ACC001": 5},
            kill_switch_active=True,
            kill_switch_reason="Test reason",
        )

        restored = RiskState.from_snapshot(snapshot)
        assert restored.account_id == "ACC001"
        assert restored.daily_realized_pnl == Decimal("-500")
        assert restored.daily_turnover == Decimal("20000")
        assert restored.peak_equity == Decimal("95000")
        assert restored.kill_switch_active is True
        assert restored.kill_switch_reason == "Test reason"

    @pytest.mark.asyncio
    async def test_concurrent_access(self, state):
        async def worker(n):
            for _ in range(10):
                await state.record_fill(
                    realized_pnl=Decimal("1"),
                    turnover=Decimal("100"),
                    current_equity=Decimal("100000"),
                    fill_timestamp=datetime.utcnow(),
                )

        await asyncio.gather(*[worker(i) for i in range(5)])
        assert state.daily_realized_pnl == Decimal("50")
        assert state.daily_turnover == Decimal("5000")
