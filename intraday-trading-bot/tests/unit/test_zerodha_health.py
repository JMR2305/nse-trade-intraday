"""Tests for RC-10D broker health tracker (Group G).

Covers:
  - Health starts UNKNOWN/DOWN in live mode
  - Paper mode always HEALTHY and is_ready=True
  - is_ready reflects combined state
  - Status degrades correctly
  - Concurrent updates safe with asyncio.Lock
  - Metrics exposed via get_health()
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone

from src.brokers.contracts import BrokerHealthStatus
from src.brokers.zerodha.health import BrokerHealthTracker


@pytest.fixture
def paper_tracker():
    return BrokerHealthTracker(paper_mode=True)


@pytest.fixture
def live_tracker():
    return BrokerHealthTracker(paper_mode=False)


class TestPaperMode:
    @pytest.mark.asyncio
    async def test_paper_always_healthy(self, paper_tracker):
        health = paper_tracker.get_health()
        assert health.status == BrokerHealthStatus.HEALTHY

    def test_paper_is_ready(self, paper_tracker):
        assert paper_tracker.is_ready() is True

    def test_paper_not_live(self, paper_tracker):
        assert paper_tracker.is_live() is False

    @pytest.mark.asyncio
    async def test_paper_healthy_even_without_auth(self, paper_tracker):
        health = paper_tracker.get_health()
        assert health.status == BrokerHealthStatus.HEALTHY


class TestLiveMode:
    def test_live_starts_down(self, live_tracker):
        assert live_tracker.is_ready() is False

    @pytest.mark.asyncio
    async def test_live_after_auth_and_rest_healthy(self, live_tracker):
        await live_tracker.mark_authenticated()
        await live_tracker.mark_rest_success()
        await live_tracker.mark_websocket_connected()
        assert live_tracker.is_ready() is True
        health = live_tracker.get_health()
        assert health.status == BrokerHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_live_degraded_without_websocket(self, live_tracker):
        await live_tracker.mark_authenticated()
        await live_tracker.mark_rest_success()
        # No websocket
        health = live_tracker.get_health()
        assert health.status == BrokerHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_live_down_after_session_invalid(self, live_tracker):
        await live_tracker.mark_authenticated()
        await live_tracker.mark_session_invalid("Token expired")
        assert live_tracker.is_ready() is False
        health = live_tracker.get_health()
        assert health.status == BrokerHealthStatus.DOWN

    @pytest.mark.asyncio
    async def test_live_down_after_rest_failure(self, live_tracker):
        await live_tracker.mark_authenticated()
        await live_tracker.mark_rest_failure("Connection refused")
        assert live_tracker.is_ready() is False
        health = live_tracker.get_health()
        assert health.status == BrokerHealthStatus.DOWN

    @pytest.mark.asyncio
    async def test_reconnect_count_increments(self, live_tracker):
        await live_tracker.mark_websocket_disconnected()
        await live_tracker.mark_websocket_disconnected()
        health = live_tracker.get_health()
        assert health.reconnect_count == 2

    @pytest.mark.asyncio
    async def test_rate_limited_flag(self, live_tracker):
        await live_tracker.mark_authenticated()
        await live_tracker.mark_rest_success()
        await live_tracker.mark_websocket_connected()
        await live_tracker.mark_rate_limited()
        health = live_tracker.get_health()
        assert health.rate_limited is True
        assert health.status == BrokerHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_unresolved_orders_degrade(self, live_tracker):
        await live_tracker.mark_authenticated()
        await live_tracker.mark_rest_success()
        await live_tracker.mark_websocket_connected()
        await live_tracker.set_unresolved_orders(3)
        health = live_tracker.get_health()
        assert health.unresolved_orders == 3
        assert health.status == BrokerHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_reconciliation_status_set(self, live_tracker):
        await live_tracker.set_reconciliation_status("DISCREPANCIES:2")
        health = live_tracker.get_health()
        assert health.reconciliation_status == "DISCREPANCIES:2"

    @pytest.mark.asyncio
    async def test_last_successful_request_updated(self, live_tracker):
        health_before = live_tracker.get_health()
        assert health_before.last_successful_request is None
        await live_tracker.mark_rest_success()
        health_after = live_tracker.get_health()
        assert health_after.last_successful_request is not None

    @pytest.mark.asyncio
    async def test_last_broker_event_updated(self, live_tracker):
        await live_tracker.mark_broker_event()
        health = live_tracker.get_health()
        assert health.last_broker_event is not None

    @pytest.mark.asyncio
    async def test_concurrent_updates_safe(self, live_tracker):
        """Concurrent mark_rest_success calls should not corrupt state."""
        async def update():
            await live_tracker.mark_rest_success()

        await asyncio.gather(*[update() for _ in range(20)])
        health = live_tracker.get_health()
        assert health.last_successful_request is not None

    def test_checked_at_timezone_aware(self, live_tracker):
        health = live_tracker.get_health()
        assert health.checked_at.tzinfo is not None
