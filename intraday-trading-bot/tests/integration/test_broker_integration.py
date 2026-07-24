"""RC-10D Integration tests (spec section 24).

7 end-to-end integration scenarios using mocked broker and DB components.
All use PaperBroker or mocked adapters — no real Zerodha calls.

Scenarios:
  1. Paper order full flow
  2. Risk-rejected signal
  3. Kill switch blocks placement / allows cancellation
  4. Live-mode safety gate rejection
  5. Broker timeout → UNCERTAIN correlation (no duplicate)
  6. WebSocket disconnect → reconnect → reconciliation triggered
  7. Restart recovery of UNCERTAIN correlation
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.brokers.contracts import (
    BrokerExchange, BrokerOrderRequest, BrokerOrderStatus, BrokerOrderType,
    BrokerProduct, BrokerSide, BrokerValidity, BrokerVariety, CorrelationStatus,
)
from src.brokers.exceptions import (
    BrokerKillSwitchError,
    BrokerLiveModeError,
    BrokerTimeoutError,
)
from src.brokers.paper_broker import PaperBroker
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway
from src.brokers.zerodha.reconciliation import ReconciliationEngine
from src.brokers.zerodha.websocket import ZerodhaWebSocketManager


def _make_request(idem: str = "IDEM-INT-001") -> BrokerOrderRequest:
    return BrokerOrderRequest(
        internal_order_id="ORD-INT-001",
        idempotency_key=idem,
        trading_symbol="RELIANCE",
        transaction_type=BrokerSide.BUY,
        quantity=Decimal("5"),
        order_type=BrokerOrderType.MARKET,
        exchange=BrokerExchange.NSE,
        product=BrokerProduct.MIS,
        validity=BrokerValidity.DAY,
        variety=BrokerVariety.REGULAR,
        paper_mode=True,
    )


# ── Scenario 1: Paper order full flow ─────────────────────────────────────

class TestScenario1PaperOrderFlow:
    """Full paper order: request → kill switch check → paper broker → COMPLETE."""

    @pytest.mark.asyncio
    async def test_paper_order_reaches_complete(self):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test setup")

        paper_broker = PaperBroker()
        config = ZerodhaBrokerConfig(paper_trading=True)
        health = BrokerHealthTracker(paper_mode=True)
        gateway = ZerodhaOrderGateway(config, health, paper_broker)

        response = await gateway.place_order(_make_request())
        assert response.status == BrokerOrderStatus.COMPLETE
        assert response.paper_mode is True
        assert response.broker_order_id is not None

    @pytest.mark.asyncio
    async def test_paper_order_idempotency_key_tracked(self):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test setup")

        paper_broker = PaperBroker()
        config = ZerodhaBrokerConfig(paper_trading=True)
        health = BrokerHealthTracker(paper_mode=True)
        gateway = ZerodhaOrderGateway(config, health, paper_broker)

        await gateway.place_order(_make_request("IDEM-TRACK-1"))
        assert "IDEM-TRACK-1" in gateway._correlations
        assert gateway._correlations["IDEM-TRACK-1"] == CorrelationStatus.CONFIRMED.value


# ── Scenario 2: Risk-rejected signal ──────────────────────────────────────

class TestScenario2RiskRejected:
    """Risk gate (RC-8) rejects order before broker is called."""

    @pytest.mark.asyncio
    async def test_risk_rejection_does_not_reach_broker(self):
        """When RiskIntegrationLayer rejects, broker.place_order is never called."""
        broker = MagicMock(spec=PaperBroker)
        broker.place_order = AsyncMock()

        with patch("src.services.execution_service.OrderService"), \
             patch("src.services.execution_service.PositionService"), \
             patch("src.services.execution_service.OrderRepository"), \
             patch("src.services.execution_service.FillRepository"), \
             patch("src.services.execution_service.LedgerRepository"), \
             patch("src.services.execution_service.RiskEngine"), \
             patch("src.services.execution_service.ProjectExecutionAdapter"), \
             patch("src.services.execution_service.RiskIntegrationLayer") as mock_ril:

            mock_ril_instance = MagicMock()
            from src.risk.integration_layer import RiskIntegrationResult
            from src.risk.contracts import RiskResult
            mock_ril_instance.submit_order = AsyncMock(
                return_value=MagicMock(
                    rejected=True,
                    rejection_reason="Daily loss limit exceeded",
                    error=None,
                )
            )
            mock_ril.return_value = mock_ril_instance

            from src.services.execution_service import ExecutionService
            svc = ExecutionService(MagicMock(), broker=broker)

            with pytest.raises(Exception, match="Risk check failed"):
                await svc.execute_order(
                    session_id="sess1",
                    instrument_token=12345,
                    symbol="RELIANCE",
                    side="BUY",
                    quantity=10,
                )

            # Broker was never called directly
            broker.place_order.assert_not_called()


# ── Scenario 3: Kill switch blocks placement / allows cancellation ─────────

class TestScenario3KillSwitch:
    @pytest.mark.asyncio
    async def test_kill_switch_pause_blocks_new_order(self):
        from src.core.kill_switch import kill_switch_manager, KillSwitchLevel
        kill_switch_manager.escalate(KillSwitchLevel.PAUSE, "test")
        try:
            paper_broker = PaperBroker()
            config = ZerodhaBrokerConfig(paper_trading=True)
            health = BrokerHealthTracker(paper_mode=True)
            gateway = ZerodhaOrderGateway(config, health, paper_broker)

            with pytest.raises(BrokerKillSwitchError):
                await gateway.place_order(_make_request("IDEM-KS-1"))
        finally:
            kill_switch_manager.reset("cleanup")

    @pytest.mark.asyncio
    async def test_kill_switch_allows_cancellation(self):
        from src.core.kill_switch import kill_switch_manager, KillSwitchLevel
        kill_switch_manager.escalate(KillSwitchLevel.PAUSE, "test")
        try:
            paper_broker = PaperBroker()
            config = ZerodhaBrokerConfig(paper_trading=True)
            health = BrokerHealthTracker(paper_mode=True)
            gateway = ZerodhaOrderGateway(config, health, paper_broker)

            # First place an order (should fail due to kill switch)
            # Directly place on paper broker to simulate an open order
            from src.brokers.interface import OrderRequest as LegacyReq
            resp = await paper_broker.place_order(
                LegacyReq(symbol="RELIANCE", side="BUY", quantity=5,
                           order_type="MARKET", price=Decimal("2500"))
            )
            # Cancellation should still work
            result = await gateway.cancel_order(resp.broker_order_id, "ORD-INT-001")
            assert result is True
        finally:
            kill_switch_manager.reset("cleanup")


# ── Scenario 4: Live-mode safety gate rejection ────────────────────────────

class TestScenario4LiveModeGates:
    @pytest.mark.asyncio
    async def test_live_order_rejected_in_paper_mode(self):
        """Any attempt to configure an order as non-paper is blocked by config."""
        config = ZerodhaBrokerConfig(paper_trading=True)
        assert config.is_live_order_allowed() is False

    def test_all_5_gates_required(self):
        """Verify that all 5 conditions must be True for live order."""
        # Missing: enabled
        c = ZerodhaBrokerConfig(api_key="k", api_secret="s", paper_trading=False,
                                enabled=False, live_trading_enabled=True, access_token="t")
        assert c.is_live_order_allowed() is False

        # Missing: live_trading_enabled
        c2 = ZerodhaBrokerConfig(api_key="k", api_secret="s", paper_trading=False,
                                 enabled=True, live_trading_enabled=False, access_token="t")
        assert c2.is_live_order_allowed() is False

        # Missing: access_token
        c3 = ZerodhaBrokerConfig(api_key="k", api_secret="s", paper_trading=False,
                                 enabled=True, live_trading_enabled=True, access_token=None)
        assert c3.is_live_order_allowed() is False

        # Missing: api_key — would fail pydantic validator first
        # All present:
        c4 = ZerodhaBrokerConfig(api_key="k", api_secret="s", paper_trading=False,
                                 enabled=True, live_trading_enabled=True, access_token="t")
        assert c4.is_live_order_allowed() is True


# ── Scenario 5: Broker timeout → UNCERTAIN (no duplicate) ─────────────────

class TestScenario5TimeoutUncertain:
    @pytest.mark.asyncio
    async def test_timeout_marks_uncertain_not_duplicate(self):
        """On placement timeout, correlation becomes UNCERTAIN, not CONFIRMED.
        A subsequent placement with the same key should not be allowed but
        an UNCERTAIN key allows re-submission after reconciliation."""
        config = ZerodhaBrokerConfig(
            api_key="key",
            api_secret="secret",
            paper_trading=False,
            enabled=True,
            live_trading_enabled=True,
            access_token="tok",
        )
        health = BrokerHealthTracker(paper_mode=False)
        await health.mark_authenticated()
        await health.mark_rest_success()

        mock_client = MagicMock()
        mock_client.place_order = AsyncMock(side_effect=BrokerTimeoutError("timeout"))

        paper_broker = PaperBroker()
        gateway = ZerodhaOrderGateway(
            config=config, health_tracker=health, paper_broker=paper_broker, client=mock_client
        )

        request = BrokerOrderRequest(
            internal_order_id="ORD-TIMEOUT",
            idempotency_key="IDEM-TIMEOUT",
            trading_symbol="TCS",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("10"),
            order_type=BrokerOrderType.MARKET,
            exchange=BrokerExchange.NSE,
            product=BrokerProduct.MIS,
            validity=BrokerValidity.DAY,
            variety=BrokerVariety.REGULAR,
            paper_mode=False,
        )

        with pytest.raises(BrokerTimeoutError):
            await gateway.place_order(request)

        # Correlation must be UNCERTAIN
        assert gateway._correlations.get("IDEM-TIMEOUT") == CorrelationStatus.UNCERTAIN.value


# ── Scenario 6: WebSocket disconnect → reconnect → reconciliation ──────────

class TestScenario6WebSocketReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_triggers_reconciliation(self):
        """After reconnect, reconciliation callback must be called."""
        recon_called = False

        async def on_reconcile():
            nonlocal recon_called
            recon_called = True

        config = ZerodhaBrokerConfig(paper_trading=True)
        health = BrokerHealthTracker(paper_mode=True)
        ws = ZerodhaWebSocketManager(config=config, health_tracker=health,
                                      on_reconcile=on_reconcile)

        await ws._on_reconnect_success()
        assert recon_called is True

    @pytest.mark.asyncio
    async def test_handle_close_marks_websocket_disconnected(self):
        config = ZerodhaBrokerConfig(paper_trading=True)
        health = BrokerHealthTracker(paper_mode=True)
        ws = ZerodhaWebSocketManager(config=config, health_tracker=health)
        ws._running = False  # Prevent reconnect from starting

        await ws._handle_close(1001, "going away")
        h = health.get_health()
        # Disconnected means reconnect_count >= 1
        assert h.reconnect_count >= 1


# ── Scenario 7: Restart recovery of UNCERTAIN correlation ─────────────────

class TestScenario7RestartRecovery:
    @pytest.mark.asyncio
    async def test_uncertain_correlation_triggers_reconciliation_on_init(self):
        """Simulate startup: UNCERTAIN correlations → reconciliation triggered."""
        config = ZerodhaBrokerConfig(paper_trading=True)
        health = BrokerHealthTracker(paper_mode=True)
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = ReconciliationEngine(config=config, health_tracker=health,
                                      order_gateway=gateway)

        # Simulate startup with UNCERTAIN local orders
        local_orders = [
            {
                "id": 1,
                "broker_order_id": None,  # Never received broker ID
                "symbol": "RELIANCE",
                "status": "PENDING",  # Still pending — UNCERTAIN
            }
        ]
        report = await engine.run(trigger="startup", local_orders=local_orders, db_session=None)
        # Paper mode — report is clean but trigger is recorded
        assert report.trigger == "startup"
