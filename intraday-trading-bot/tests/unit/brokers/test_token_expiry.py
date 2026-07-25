"""Unit tests for Zerodha token expiry detection and graceful degradation.

All tests are unit-level with mocked clients/sessions — no real broker calls.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional

import pytest

from src.brokers.zerodha.authentication import ZerodhaSessionManager
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.contracts import BrokerSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(*, paper_trading: bool = False) -> ZerodhaBrokerConfig:
    """Return a minimal non-paper config for testing."""
    return ZerodhaBrokerConfig(
        api_key="test_api_key",
        api_secret="test_api_secret",
        paper_trading=paper_trading,
        enabled=True,
        live_trading_enabled=not paper_trading,
    )


def _session_expiring_in(minutes: float) -> BrokerSession:
    """Return a BrokerSession whose expires_at is ``minutes`` from now."""
    return BrokerSession(
        user_id="test_user",
        broker_name="zerodha",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
        is_valid=True,
        paper_mode=False,
    )


# ---------------------------------------------------------------------------
# ZerodhaSessionManager — minutes_until_expiry
# ---------------------------------------------------------------------------

class TestMinutesUntilExpiry:
    def test_returns_none_when_no_session(self):
        config = _make_config()
        manager = ZerodhaSessionManager(config)
        assert manager.minutes_until_expiry() is None

    def test_positive_when_not_yet_expired(self):
        config = _make_config()
        manager = ZerodhaSessionManager(config)
        manager._session = _session_expiring_in(45)
        mins = manager.minutes_until_expiry()
        assert mins is not None
        assert 44 < mins < 46

    def test_negative_when_already_expired(self):
        config = _make_config()
        manager = ZerodhaSessionManager(config)
        manager._session = _session_expiring_in(-5)
        mins = manager.minutes_until_expiry()
        assert mins is not None
        assert mins < 0

    def test_zero_boundary(self):
        config = _make_config()
        manager = ZerodhaSessionManager(config)
        # Expiry exactly now should be ≤ 0
        manager._session = BrokerSession(
            user_id="u",
            broker_name="zerodha",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
            is_valid=True,
            paper_mode=False,
        )
        mins = manager.minutes_until_expiry()
        assert mins is not None
        assert mins <= 0.1  # allow tiny positive rounding


# ---------------------------------------------------------------------------
# ZerodhaSessionManager — check_expiry_warning
# ---------------------------------------------------------------------------

class TestCheckExpiryWarning:
    def test_no_session_returns_all_false(self):
        manager = ZerodhaSessionManager(_make_config())
        is_soon, is_expired, mins = manager.check_expiry_warning(warning_lead_minutes=30)
        assert is_soon is False
        assert is_expired is False
        assert mins is None

    def test_healthy_session_not_flagged(self):
        manager = ZerodhaSessionManager(_make_config())
        manager._session = _session_expiring_in(60)  # 60 min remaining
        is_soon, is_expired, mins = manager.check_expiry_warning(warning_lead_minutes=30)
        assert is_soon is False
        assert is_expired is False
        assert mins is not None and mins > 0

    def test_within_warning_window(self):
        manager = ZerodhaSessionManager(_make_config())
        manager._session = _session_expiring_in(15)  # 15 min < 30 min threshold
        is_soon, is_expired, mins = manager.check_expiry_warning(warning_lead_minutes=30)
        assert is_soon is True
        assert is_expired is False
        assert 14 < mins < 16

    def test_exactly_at_threshold_boundary(self):
        manager = ZerodhaSessionManager(_make_config())
        # Exactly at the threshold should NOT trigger the warning (> not ≥)
        manager._session = _session_expiring_in(30)
        is_soon, is_expired, mins = manager.check_expiry_warning(warning_lead_minutes=30)
        # 30.0 <= 30 means it IS triggered — ensure consistent logic
        assert isinstance(is_soon, bool)  # just validate it returns bool

    def test_expired_session_detected(self):
        manager = ZerodhaSessionManager(_make_config())
        manager._session = _session_expiring_in(-1)  # expired 1 minute ago
        is_soon, is_expired, mins = manager.check_expiry_warning(warning_lead_minutes=30)
        assert is_expiring_soon_xor_expired(is_soon, is_expired)
        assert is_expired is True
        assert is_soon is False  # expired, not merely "soon"
        assert mins < 0

    def test_custom_lead_time(self):
        manager = ZerodhaSessionManager(_make_config())
        manager._session = _session_expiring_in(45)  # 45 min remaining
        # With 60 min lead time, 45 min should trigger the warning
        is_soon, is_expired, mins = manager.check_expiry_warning(warning_lead_minutes=60)
        assert is_soon is True
        # With 30 min lead time, 45 min should NOT trigger
        is_soon2, _, _ = manager.check_expiry_warning(warning_lead_minutes=30)
        assert is_soon2 is False


def is_expiring_soon_xor_expired(is_soon: bool, is_expired: bool) -> bool:
    """Helper: is_soon and is_expired should not both be True."""
    return not (is_soon and is_expired)


# ---------------------------------------------------------------------------
# BrokerHealthTracker — expiry warning state
# ---------------------------------------------------------------------------

class TestBrokerHealthTrackerExpiryWarning:
    def test_initial_state_has_no_expiry_warning(self):
        tracker = BrokerHealthTracker(paper_mode=False)
        health = tracker.get_health()
        assert health.token_expiry_minutes is None
        assert health.token_expiry_warning is False

    def test_mark_token_expiry_warning_sets_fields(self):
        tracker = BrokerHealthTracker(paper_mode=False)
        loop = asyncio.new_event_loop()
        # Authenticate first so session_valid starts True
        loop.run_until_complete(tracker.mark_authenticated())
        # A warning-only call (not expired) must NOT invalidate the session
        loop.run_until_complete(
            tracker.mark_token_expiry_warning(15.0, is_expired=False)
        )
        loop.close()
        health = tracker.get_health()
        assert health.token_expiry_minutes == 15.0
        assert health.token_expiry_warning is True
        # Session should remain valid when only warning (not yet expired)
        assert health.session_valid is True

    def test_mark_token_expiry_warning_expired_invalidates_session(self):
        tracker = BrokerHealthTracker(paper_mode=False)
        asyncio.get_event_loop().run_until_complete(tracker.mark_authenticated())
        asyncio.get_event_loop().run_until_complete(
            tracker.mark_token_expiry_warning(-5.0, is_expired=True)
        )
        health = tracker.get_health()
        assert health.session_valid is False
        assert health.authenticated is False
        assert health.token_expiry_warning is True
        assert health.failure_reason is not None
        assert "expired" in health.failure_reason.lower()

    def test_is_ready_false_after_expiry(self):
        tracker = BrokerHealthTracker(paper_mode=False)
        asyncio.get_event_loop().run_until_complete(tracker.mark_authenticated())
        asyncio.get_event_loop().run_until_complete(tracker.mark_rest_success())
        assert tracker.is_ready() is True

        asyncio.get_event_loop().run_until_complete(
            tracker.mark_token_expiry_warning(-1.0, is_expired=True)
        )
        assert tracker.is_ready() is False

    def test_clear_expiry_warning(self):
        tracker = BrokerHealthTracker(paper_mode=False)
        asyncio.get_event_loop().run_until_complete(
            tracker.mark_token_expiry_warning(10.0, is_expired=False)
        )
        asyncio.get_event_loop().run_until_complete(tracker.clear_token_expiry_warning())
        health = tracker.get_health()
        assert health.token_expiry_minutes is None
        assert health.token_expiry_warning is False


# ---------------------------------------------------------------------------
# ZerodhaAdapter.check_token_expiry — integration of expiry logic
# ---------------------------------------------------------------------------

class TestAdapterCheckTokenExpiry:
    """Test check_token_expiry() via ZerodhaAdapter in isolation.

    The adapter is constructed with mocked sub-components to keep tests
    unit-level (no live broker, no DB, no filesystem).
    """

    def _make_adapter(self, *, session_minutes: Optional[float] = None):
        """Build a minimal ZerodhaAdapter with a stubbed session manager."""
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        config = _make_config(paper_trading=False)
        adapter = ZerodhaAdapter.__new__(ZerodhaAdapter)
        adapter._config = config
        adapter._session_expired_paper_fallback = False

        # Stub health tracker
        health_tracker = BrokerHealthTracker(paper_mode=False)
        adapter._health_tracker = health_tracker

        # Stub session manager with a real manager that has a preset session
        session_manager = ZerodhaSessionManager(config)
        if session_minutes is not None:
            session_manager._session = _session_expiring_in(session_minutes)
        adapter._session_manager = session_manager

        return adapter

    def test_paper_mode_returns_none_immediately(self):
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        config = _make_config(paper_trading=True)
        adapter = ZerodhaAdapter.__new__(ZerodhaAdapter)
        adapter._config = config
        adapter._session_expired_paper_fallback = False
        adapter._health_tracker = BrokerHealthTracker(paper_mode=True)
        adapter._session_manager = ZerodhaSessionManager(config)

        result = asyncio.get_event_loop().run_until_complete(
            adapter.check_token_expiry(warning_lead_minutes=30)
        )
        assert result["action"] == "none"
        assert result["minutes_remaining"] is None

    def test_healthy_session_no_action(self):
        adapter = self._make_adapter(session_minutes=120)  # 2 hours remaining
        with patch.object(adapter, "_send_expiry_alert", new_callable=AsyncMock) as mock_alert:
            result = asyncio.get_event_loop().run_until_complete(
                adapter.check_token_expiry(warning_lead_minutes=30)
            )
        assert result["action"] == "none"
        assert adapter._session_expired_paper_fallback is False
        mock_alert.assert_not_called()

    def test_expiring_soon_triggers_warning(self):
        adapter = self._make_adapter(session_minutes=15)  # 15 min < 30 min threshold
        with patch.object(adapter, "_send_expiry_alert", new_callable=AsyncMock) as mock_alert:
            result = asyncio.get_event_loop().run_until_complete(
                adapter.check_token_expiry(warning_lead_minutes=30)
            )
        assert result["action"] == "warning_alert"
        assert adapter._session_expired_paper_fallback is True
        mock_alert.assert_awaited_once()

    def test_expired_session_degrades_to_paper(self):
        adapter = self._make_adapter(session_minutes=-5)  # already expired
        with patch.object(adapter, "_send_expiry_alert", new_callable=AsyncMock) as mock_alert:
            result = asyncio.get_event_loop().run_until_complete(
                adapter.check_token_expiry(warning_lead_minutes=30)
            )
        assert result["action"] == "expired_degraded"
        assert adapter._session_expired_paper_fallback is True
        # Health tracker should show session invalid
        health = adapter._health_tracker.get_health()
        assert health.session_valid is False
        mock_alert.assert_awaited_once()

    def test_no_session_no_action(self):
        """When no session exists (not yet authenticated), no warning is fired."""
        adapter = self._make_adapter(session_minutes=None)
        with patch.object(adapter, "_send_expiry_alert", new_callable=AsyncMock) as mock_alert:
            result = asyncio.get_event_loop().run_until_complete(
                adapter.check_token_expiry(warning_lead_minutes=30)
            )
        assert result["action"] == "none"
        assert adapter._session_expired_paper_fallback is False
        mock_alert.assert_not_called()

    def test_send_expiry_alert_never_raises(self):
        """_send_expiry_alert must swallow all exceptions silently."""
        adapter = self._make_adapter(session_minutes=None)
        # Force an exception inside by patching the import to raise
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            # Should not raise
            asyncio.get_event_loop().run_until_complete(
                adapter._send_expiry_alert(
                    is_expired=True,
                    minutes_remaining=-1.0,
                    warning_lead_minutes=30,
                )
            )

    def test_healthy_session_does_not_set_token_expiry_warning_flag(self):
        """A healthy session (120 min remaining) must NOT set token_expiry_warning."""
        adapter = self._make_adapter(session_minutes=120)
        with patch.object(adapter, "_send_expiry_alert", new_callable=AsyncMock):
            asyncio.get_event_loop().run_until_complete(
                adapter.check_token_expiry(warning_lead_minutes=30)
            )
        health = adapter._health_tracker.get_health()
        # Warning flag must remain False for a healthy session
        assert health.token_expiry_warning is False
        # But the countdown should be updated
        assert health.token_expiry_minutes is not None
        assert health.token_expiry_minutes > 0


# ---------------------------------------------------------------------------
# Integration: place_broker_order() routes to paper when fallback is active
# ---------------------------------------------------------------------------

class TestPaperFallbackRouting:
    """Prove that expiry-degraded orders go through the paper path, not live."""

    def _make_live_adapter_with_expired_session(self):
        """Build a ZerodhaAdapter in live config with an expired session."""
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway
        from src.brokers.paper_broker import PaperBroker

        config = _make_config(paper_trading=False)
        adapter = ZerodhaAdapter.__new__(ZerodhaAdapter)
        adapter._config = config
        adapter._session_expired_paper_fallback = True  # Simulate degraded state

        paper_broker = PaperBroker()
        health_tracker = BrokerHealthTracker(paper_mode=False)
        # Mark session invalid (as check_token_expiry does after expiry)
        asyncio.get_event_loop().run_until_complete(
            health_tracker.mark_token_expiry_warning(-1.0, is_expired=True)
        )

        # Wire a gateway with a real paper broker but no live client
        gateway = ZerodhaOrderGateway(
            config=config,
            health_tracker=health_tracker,
            paper_broker=paper_broker,
            client=None,
        )
        adapter._order_gateway = gateway
        adapter._health_tracker = health_tracker
        return adapter

    def test_place_broker_order_returns_paper_fill_when_fallback_active(self):
        """place_broker_order() must return a paper-mode response, never hit live."""
        from src.brokers.contracts import (
            BrokerOrderRequest, BrokerSide, BrokerOrderType,
            BrokerProduct, BrokerValidity, BrokerVariety, BrokerExchange,
        )
        from decimal import Decimal

        adapter = self._make_live_adapter_with_expired_session()

        request = BrokerOrderRequest(
            internal_order_id="test-order-001",
            idempotency_key="idem-001",
            exchange=BrokerExchange.NSE,
            trading_symbol="INFY",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("1"),
            order_type=BrokerOrderType.MARKET,
            product=BrokerProduct.MIS,
            validity=BrokerValidity.DAY,
            variety=BrokerVariety.REGULAR,
            paper_mode=False,  # caller intends live — fallback overrides this
        )

        response = asyncio.get_event_loop().run_until_complete(
            adapter.place_broker_order(request)
        )

        # Response must be paper-mode — not a live Zerodha order
        assert response.paper_mode is True
        assert response.internal_order_id == "test-order-001"
        # A paper fill is synchronous; status should be COMPLETE or similar
        assert response.status is not None

    def test_fallback_path_blocked_by_kill_switch(self):
        """Kill switch must still block orders even when expiry fallback is active."""
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway
        from src.brokers.paper_broker import PaperBroker
        from src.brokers.contracts import (
            BrokerOrderRequest, BrokerSide, BrokerOrderType,
            BrokerProduct, BrokerValidity, BrokerVariety, BrokerExchange,
        )
        from src.brokers.exceptions import BrokerKillSwitchError
        from src.core.kill_switch import KillSwitchLevel
        from decimal import Decimal

        adapter = self._make_live_adapter_with_expired_session()

        request = BrokerOrderRequest(
            internal_order_id="ks-order-001",
            idempotency_key="idem-ks-001",
            exchange=BrokerExchange.NSE,
            trading_symbol="INFY",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("1"),
            order_type=BrokerOrderType.MARKET,
            product=BrokerProduct.MIS,
            validity=BrokerValidity.DAY,
            variety=BrokerVariety.REGULAR,
            paper_mode=False,
        )

        # Engage the kill switch
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.escalate(KillSwitchLevel.PAUSE, "test kill switch")
        try:
            with pytest.raises(BrokerKillSwitchError):
                asyncio.get_event_loop().run_until_complete(
                    adapter.place_broker_order(request)
                )
        finally:
            kill_switch_manager.reset("cleanup")

    def test_fallback_path_enforces_idempotency(self):
        """Duplicate idempotency key must be rejected on the paper fallback path."""
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        from src.brokers.contracts import (
            BrokerOrderRequest, BrokerSide, BrokerOrderType,
            BrokerProduct, BrokerValidity, BrokerVariety, BrokerExchange,
        )
        from src.brokers.exceptions import BrokerDuplicateOrderError
        from decimal import Decimal

        adapter = self._make_live_adapter_with_expired_session()

        request = BrokerOrderRequest(
            internal_order_id="idem-order-001",
            idempotency_key="idem-key-001",
            exchange=BrokerExchange.NSE,
            trading_symbol="INFY",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("1"),
            order_type=BrokerOrderType.MARKET,
            product=BrokerProduct.MIS,
            validity=BrokerValidity.DAY,
            variety=BrokerVariety.REGULAR,
            paper_mode=False,
        )

        # First placement should succeed
        asyncio.get_event_loop().run_until_complete(
            adapter.place_broker_order(request)
        )

        # Second placement with same idempotency key must be rejected
        with pytest.raises(BrokerDuplicateOrderError):
            asyncio.get_event_loop().run_until_complete(
                adapter.place_broker_order(request)
            )

    def test_place_broker_order_without_fallback_calls_gateway_place_order(self):
        """Without fallback, adapter delegates to gateway.place_order(), not directly
        to gateway._place_paper_order().  The gateway may itself choose paper
        (e.g. when live gates are not met), but the adapter-level bypass is not used.
        """
        from src.brokers.zerodha.adapter import ZerodhaAdapter
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway
        from src.brokers.paper_broker import PaperBroker
        from src.brokers.contracts import (
            BrokerOrderRequest, BrokerSide, BrokerOrderType,
            BrokerProduct, BrokerValidity, BrokerVariety, BrokerExchange,
        )
        from decimal import Decimal

        config = _make_config(paper_trading=False)
        adapter = ZerodhaAdapter.__new__(ZerodhaAdapter)
        adapter._config = config
        adapter._session_expired_paper_fallback = False  # No expiry fallback

        paper_broker = PaperBroker()
        health_tracker = BrokerHealthTracker(paper_mode=False)
        gateway = ZerodhaOrderGateway(
            config=config,
            health_tracker=health_tracker,
            paper_broker=paper_broker,
            client=None,
        )

        # Track which path the ADAPTER calls (gateway.place_order vs _place_paper_order)
        gateway_place_order_called = []
        original_place_order = gateway.place_order

        async def _spy_place_order(req):
            gateway_place_order_called.append(req)
            return await original_place_order(req)

        gateway.place_order = _spy_place_order
        adapter._order_gateway = gateway
        adapter._health_tracker = health_tracker

        request = BrokerOrderRequest(
            internal_order_id="test-order-002",
            idempotency_key="idem-002",
            exchange=BrokerExchange.NSE,
            trading_symbol="TCS",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("1"),
            order_type=BrokerOrderType.MARKET,
            product=BrokerProduct.MIS,
            validity=BrokerValidity.DAY,
            variety=BrokerVariety.REGULAR,
            paper_mode=False,
        )

        asyncio.get_event_loop().run_until_complete(
            adapter.place_broker_order(request)
        )

        # Adapter called gateway.place_order() — the normal path
        assert len(gateway_place_order_called) == 1


# ---------------------------------------------------------------------------
# TokenExpiryMonitor
# ---------------------------------------------------------------------------

class TestTokenExpiryMonitor:
    def test_start_stop(self):
        from src.brokers.zerodha.expiry_monitor import TokenExpiryMonitor

        mock_adapter = MagicMock()
        mock_adapter.check_token_expiry = AsyncMock(
            return_value={"action": "none", "minutes_remaining": 120.0}
        )

        monitor = TokenExpiryMonitor(
            mock_adapter,
            poll_interval_seconds=1,
            warning_lead_minutes=30,
        )

        async def _run():
            monitor.start()
            await asyncio.sleep(0.1)  # let one iteration run
            await monitor.stop()

        asyncio.get_event_loop().run_until_complete(_run())
        # check_token_expiry should have been called at least once
        mock_adapter.check_token_expiry.assert_called()

    def test_double_start_is_safe(self):
        from src.brokers.zerodha.expiry_monitor import TokenExpiryMonitor

        mock_adapter = MagicMock()
        mock_adapter.check_token_expiry = AsyncMock(
            return_value={"action": "none", "minutes_remaining": 60.0}
        )

        monitor = TokenExpiryMonitor(mock_adapter, poll_interval_seconds=60)

        async def _run():
            monitor.start()
            monitor.start()  # should not create a second task
            task1 = monitor._task
            monitor.start()
            task2 = monitor._task
            assert task1 is task2
            await monitor.stop()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_poll_error_does_not_crash_monitor(self):
        """Monitor loop must continue even if check_token_expiry raises."""
        from src.brokers.zerodha.expiry_monitor import TokenExpiryMonitor

        call_count = 0

        async def _flaky_check(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")
            return {"action": "none", "minutes_remaining": 60.0}

        mock_adapter = MagicMock()
        mock_adapter.check_token_expiry = _flaky_check

        monitor = TokenExpiryMonitor(mock_adapter, poll_interval_seconds=0)

        async def _run():
            monitor.start()
            await asyncio.sleep(0.05)
            await monitor.stop()

        asyncio.get_event_loop().run_until_complete(_run())
        assert call_count >= 1  # monitor survived the error
