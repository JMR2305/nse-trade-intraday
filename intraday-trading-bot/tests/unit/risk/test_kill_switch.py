"""
Unit tests for RC-8B KillSwitch.

Tests activation/deactivation lifecycle, audit trail,
and async safety. No account_id — KillSwitch is now
account-agnostic; account state is managed at RiskEngine level.
"""

import pytest
from datetime import datetime, timezone

from src.risk.kill_switch import KillSwitch, KillSwitchEvent
from src.risk.contracts import RiskSeverity


class TestKillSwitch:
    @pytest.fixture
    def ks(self):
        return KillSwitch()

    # ── Initial state ─────────────────────────────────────────────────────

    def test_initial_state(self, ks):
        assert ks.active is False
        assert ks.is_active() is False
        assert ks.reason is None
        assert ks.events == []

    # ── Activation ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_activate(self, ks):
        await ks.activate("Test reason", triggered_by="admin")
        assert ks.active is True
        assert ks.is_active() is True
        assert ks.reason == "Test reason"
        assert ks.triggered_by == "admin"

    @pytest.mark.asyncio
    async def test_activate_records_event(self, ks):
        await ks.activate("Market crash", triggered_by="risk_engine")
        events = ks.events
        assert len(events) == 1
        assert events[0].event_type == "ACTIVATED"
        assert events[0].reason == "Market crash"
        assert events[0].triggered_by == "risk_engine"
        assert isinstance(events[0].timestamp, datetime)

    @pytest.mark.asyncio
    async def test_activate_idempotent(self, ks):
        """Activating an already-active kill switch does not add a second event."""
        await ks.activate("First", triggered_by="a")
        await ks.activate("Second", triggered_by="b")  # Already active; ignored
        assert len(ks.events) == 1  # Only first activation recorded

    # ── Deactivation ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_deactivate(self, ks):
        await ks.activate("Testing")
        await ks.deactivate(triggered_by="admin")
        assert ks.active is False
        assert ks.reason is None

    @pytest.mark.asyncio
    async def test_deactivate_records_event(self, ks):
        await ks.activate("Test")
        await ks.deactivate(triggered_by="admin")
        events = ks.events
        assert len(events) == 2
        assert events[0].event_type == "ACTIVATED"
        assert events[1].event_type == "DEACTIVATED"
        assert events[1].triggered_by == "admin"

    @pytest.mark.asyncio
    async def test_deactivate_inactive_no_op(self, ks):
        """Deactivating an inactive kill switch is a no-op."""
        await ks.deactivate()
        assert len(ks.events) == 0

    # ── Audit trail ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_events_are_immutable_copy(self, ks):
        """events property returns a copy; mutation does not affect internal state."""
        await ks.activate("Test")
        events = ks.events
        events.clear()
        assert len(ks.events) == 1  # Internal list unchanged

    @pytest.mark.asyncio
    async def test_full_lifecycle_history(self, ks):
        await ks.activate("First", triggered_by="system")
        await ks.deactivate(triggered_by="admin")
        await ks.activate("Second", triggered_by="system")

        events = ks.events
        assert len(events) == 3
        assert events[0].event_type == "ACTIVATED"
        assert events[1].event_type == "DEACTIVATED"
        assert events[2].event_type == "ACTIVATED"

    # ── reset_events ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_reset_events_clears_audit_trail(self, ks):
        await ks.activate("Test")
        await ks.deactivate()
        ks.reset_events()
        assert ks.events == []
        # State (active/reason) is NOT affected by reset_events
        # (kill switch was deactivated before reset, so it's still inactive)
        assert ks.active is False

    # ── Concurrent safety ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_concurrent_activate_deactivate(self, ks):
        """Multiple concurrent activations only register once."""
        import asyncio
        await asyncio.gather(
            ks.activate("concurrent_1"),
            ks.activate("concurrent_2"),
            ks.activate("concurrent_3"),
        )
        # Kill switch is active (first write wins)
        assert ks.active is True
        # Due to the idempotency guard, only 1 event is recorded
        assert len(ks.events) == 1
