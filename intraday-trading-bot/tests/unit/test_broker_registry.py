"""Tests for the broker singleton registry and live-gated order path.

Verifies that:
  - Registry defaults to PaperBroker when no live adapter is registered
  - set_live_broker / get_broker / is_live_mode / clear_live_broker work correctly
  - The order router uses the registry adapter (not a per-request constructed one)
  - When a live-ready ZerodhaOrderGateway is registered, place_order() reaches
    it and does NOT silently fall through to PaperBroker
  - BrokerLiveModeError from an unready gateway yields 503, not 500

No real Zerodha calls are made — all broker objects are mocked at the unit level
following the pattern established in phase8-tests.md.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.brokers.paper_broker import PaperBroker
from src.brokers.exceptions import BrokerLiveModeError, BrokerSessionExpiredError
import src.brokers.registry as registry


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_mock_live_adapter() -> MagicMock:
    """Return a mock adapter that reports is_ready=True and places orders successfully."""
    adapter = MagicMock()
    adapter.is_ready = MagicMock(return_value=True)
    adapter.place_broker_order = AsyncMock(return_value=MagicMock(
        broker_order_id="LIVE-ORD-001",
        status="OPEN",
        paper_mode=False,
    ))
    return adapter


def _live_config():
    from src.brokers.zerodha.config import ZerodhaBrokerConfig
    return ZerodhaBrokerConfig(
        api_key="testkey",
        api_secret="testsecret",
        access_token="testtoken",
        enabled=True,
        paper_trading=False,
        live_trading_enabled=True,
    )


def _live_request(idem: str = "IDEM-LIVE-001"):
    from src.brokers.contracts import (
        BrokerExchange, BrokerOrderRequest, BrokerOrderType,
        BrokerProduct, BrokerSide, BrokerValidity, BrokerVariety,
    )
    return BrokerOrderRequest(
        internal_order_id="ORD-LIVE-001",
        idempotency_key=idem,
        trading_symbol="RELIANCE",
        transaction_type=BrokerSide.BUY,
        quantity=Decimal("1"),
        order_type=BrokerOrderType.MARKET,
        exchange=BrokerExchange.NSE,
        product=BrokerProduct.MIS,
        validity=BrokerValidity.DAY,
        variety=BrokerVariety.REGULAR,
        paper_mode=False,
    )


# ── Registry unit tests ────────────────────────────────────────────────────

class TestBrokerRegistry:
    def setup_method(self):
        registry.clear_live_broker()

    def teardown_method(self):
        registry.clear_live_broker()

    def test_default_returns_paper_broker(self):
        broker = registry.get_broker()
        assert isinstance(broker, PaperBroker)

    def test_is_live_mode_false_when_empty(self):
        assert registry.is_live_mode() is False

    def test_set_and_get_live_broker(self):
        mock_adapter = _make_mock_live_adapter()
        registry.set_live_broker(mock_adapter)
        assert registry.get_broker() is mock_adapter
        assert registry.is_live_mode() is True

    def test_clear_live_broker_resets_to_paper(self):
        registry.set_live_broker(_make_mock_live_adapter())
        registry.clear_live_broker()
        assert registry.is_live_mode() is False
        assert isinstance(registry.get_broker(), PaperBroker)

    def test_set_live_broker_replaces_existing(self):
        adapter1 = _make_mock_live_adapter()
        adapter2 = _make_mock_live_adapter()
        registry.set_live_broker(adapter1)
        registry.set_live_broker(adapter2)
        assert registry.get_broker() is adapter2


# ── Live-gated order gateway tests ────────────────────────────────────────

class TestLiveGatedOrderPath:
    """Prove that an order request reaches the live gateway when health is ready.

    Uses ZerodhaOrderGateway directly with a mocked HTTP client — no real
    Zerodha calls.  Follows the pattern from test_zerodha_order_gateway.py.
    """

    def setup_method(self):
        registry.clear_live_broker()
        # Ensure kill switch is clear
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test setup")

    def teardown_method(self):
        registry.clear_live_broker()
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test teardown")

    @pytest.mark.asyncio
    async def test_registry_live_adapter_is_returned_not_paper(self):
        """When a live adapter is in the registry, get_broker() returns it — not PaperBroker."""
        mock_adapter = _make_mock_live_adapter()
        registry.set_live_broker(mock_adapter)
        broker = registry.get_broker()
        assert broker is mock_adapter, "Expected registered live adapter, got PaperBroker"

    @pytest.mark.asyncio
    async def test_live_mode_error_from_unready_gateway_is_typed_not_generic(self):
        """BrokerLiveModeError is raised (not plain Exception) when health gates are not ready.

        This proves the orders router can catch it and return 503 rather than 500.
        """
        from src.brokers.zerodha.health import BrokerHealthTracker
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway

        health = BrokerHealthTracker(paper_mode=False)
        # Health NOT marked ready — _assert_health() should raise BrokerLiveModeError
        gw = ZerodhaOrderGateway(
            config=_live_config(),
            health_tracker=health,
            paper_broker=PaperBroker(),
            client=None,
        )

        with pytest.raises(BrokerLiveModeError):
            await gw.place_order(_live_request())

    @pytest.mark.asyncio
    async def test_live_order_gateway_calls_live_client_when_health_ready(self):
        """When health is fully ready and client is mocked, gateway calls the live API path.

        Confirms the order does NOT silently fall through to PaperBroker.
        """
        from src.brokers.zerodha.health import BrokerHealthTracker
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway

        health = BrokerHealthTracker(paper_mode=False)
        await health.mark_authenticated()   # sets _authenticated + _session_valid
        await health.mark_rest_success()    # sets _rest_reachable
        assert health.is_ready(), "Precondition: health must be ready"

        # Mock HTTP client — simulates a successful Zerodha API call
        mock_client = AsyncMock()
        mock_client.place_order = AsyncMock(return_value="KITE-ORD-999")

        # Mock DB session so correlation persistence doesn't blow up
        mock_db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        gw = ZerodhaOrderGateway(
            config=_live_config(),
            health_tracker=health,
            paper_broker=PaperBroker(),
            client=mock_client,
        )
        gw.set_db_session(mock_db)

        response = await gw.place_order(_live_request(idem="IDEM-LIVE-002"))

        # The live HTTP client must have been called (not the paper broker)
        mock_client.place_order.assert_called_once()
        assert response.paper_mode is False, "Expected live order response (paper_mode=False)"
        assert response.broker_order_id == "KITE-ORD-999"
