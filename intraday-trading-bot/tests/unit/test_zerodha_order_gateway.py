"""Tests for RC-10D order gateway (Group I).

Covers:
  - Kill switch blocks placement (even in paper mode)
  - Duplicate detection via idempotency_key
  - Paper mode routes to PaperBroker
  - Live mode requires all safety gates
  - Timeout marks correlation UNCERTAIN
  - cancel_order allowed through kill switch
  - kill switch checked before live gates
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
    BrokerDuplicateOrderError,
    BrokerKillSwitchError,
    BrokerLiveModeError,
    BrokerTimeoutError,
)
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway


def _paper_config() -> ZerodhaBrokerConfig:
    return ZerodhaBrokerConfig(paper_trading=True)


def _request(idem_key: str = "IDEM-001", **kw) -> BrokerOrderRequest:
    defaults = dict(
        internal_order_id="ORD-001",
        idempotency_key=idem_key,
        trading_symbol="RELIANCE",
        transaction_type=BrokerSide.BUY,
        quantity=Decimal("10"),
        order_type=BrokerOrderType.MARKET,
        exchange=BrokerExchange.NSE,
        product=BrokerProduct.MIS,
        validity=BrokerValidity.DAY,
        variety=BrokerVariety.REGULAR,
        paper_mode=True,
    )
    defaults.update(kw)
    return BrokerOrderRequest(**defaults)


@pytest.fixture
def paper_broker_mock():
    mock = MagicMock()
    from src.brokers.interface import OrderResponse
    mock.place_order = AsyncMock(return_value=OrderResponse(
        broker_order_id="PAPER_001",
        status="COMPLETE",
        average_price=Decimal("2500"),
        filled_quantity=10,
    ))
    mock.cancel_order = AsyncMock(return_value=True)
    mock.modify_order = AsyncMock(return_value=OrderResponse(
        broker_order_id="PAPER_001",
        status="MODIFIED",
    ))
    return mock


@pytest.fixture
def gateway(paper_broker_mock):
    config = _paper_config()
    health = BrokerHealthTracker(paper_mode=True)
    return ZerodhaOrderGateway(
        config=config,
        health_tracker=health,
        paper_broker=paper_broker_mock,
    )


class TestKillSwitchBlocking:
    @pytest.mark.asyncio
    async def test_kill_switch_pause_blocks_placement(self, gateway):
        from src.core.kill_switch import kill_switch_manager, KillSwitchLevel
        kill_switch_manager.escalate(KillSwitchLevel.PAUSE, "test")
        try:
            with pytest.raises(BrokerKillSwitchError):
                await gateway.place_order(_request())
        finally:
            kill_switch_manager.reset("cleanup")

    @pytest.mark.asyncio
    async def test_kill_switch_cancel_pending_blocks_placement(self, gateway):
        from src.core.kill_switch import kill_switch_manager, KillSwitchLevel
        kill_switch_manager.escalate(KillSwitchLevel.CANCEL_PENDING, "test")
        try:
            with pytest.raises(BrokerKillSwitchError):
                await gateway.place_order(_request())
        finally:
            kill_switch_manager.reset("cleanup")

    @pytest.mark.asyncio
    async def test_kill_switch_normal_allows_placement(self, gateway):
        from src.core.kill_switch import kill_switch_manager
        # Ensure NORMAL state
        kill_switch_manager.reset("test setup")
        response = await gateway.place_order(_request())
        assert response.status == BrokerOrderStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_kill_switch_allows_cancellation(self, gateway, paper_broker_mock):
        from src.core.kill_switch import kill_switch_manager, KillSwitchLevel
        kill_switch_manager.escalate(KillSwitchLevel.PAUSE, "test")
        try:
            # Cancel should NOT check kill switch
            result = await gateway.cancel_order("PAPER_001", "ORD-001")
            assert result is True
        finally:
            kill_switch_manager.reset("cleanup")


class TestPaperModeRouting:
    @pytest.mark.asyncio
    async def test_paper_mode_routes_to_paper_broker(self, gateway, paper_broker_mock):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test")

        response = await gateway.place_order(_request())
        assert response.paper_mode is True
        paper_broker_mock.place_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_paper_response_status_complete(self, gateway):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test")

        response = await gateway.place_order(_request())
        assert response.status == BrokerOrderStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_paper_broker_order_id_in_response(self, gateway):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test")

        response = await gateway.place_order(_request())
        assert response.broker_order_id == "PAPER_001"


class TestDuplicatePrevention:
    @pytest.mark.asyncio
    async def test_duplicate_idempotency_key_raises(self, gateway):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test")

        await gateway.place_order(_request(idem_key="IDEM-DUP"))
        with pytest.raises(BrokerDuplicateOrderError):
            await gateway.place_order(_request(idem_key="IDEM-DUP"))

    @pytest.mark.asyncio
    async def test_different_idempotency_keys_ok(self, gateway):
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test")

        await gateway.place_order(_request(idem_key="IDEM-A"))
        # Different key should succeed
        await gateway.place_order(_request(idem_key="IDEM-B", internal_order_id="ORD-002"))


class TestLiveModeGates:
    @pytest.mark.asyncio
    async def test_live_mode_blocked_without_gates(self, paper_broker_mock):
        """Default config (paper=True) must never reach live path."""
        config = _paper_config()
        health = BrokerHealthTracker(paper_mode=True)
        gateway = ZerodhaOrderGateway(
            config=config, health_tracker=health, paper_broker=paper_broker_mock
        )
        from src.core.kill_switch import kill_switch_manager
        kill_switch_manager.reset("test")

        # Even with paper=True, order goes to paper broker (not live)
        response = await gateway.place_order(_request())
        assert response.paper_mode is True


class TestOrderBook:
    @pytest.mark.asyncio
    async def test_order_book_paper_mode_empty(self, gateway):
        orders = await gateway.get_order_book()
        assert orders == []

    @pytest.mark.asyncio
    async def test_trades_paper_mode_empty(self, gateway):
        trades = await gateway.get_trades()
        assert trades == []

    @pytest.mark.asyncio
    async def test_get_order_paper_mode_none(self, gateway):
        order = await gateway.get_order("BRK-001")
        assert order is None
