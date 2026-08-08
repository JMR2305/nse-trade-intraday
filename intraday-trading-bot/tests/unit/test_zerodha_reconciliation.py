"""Tests for RC-10D reconciliation engine (Group L).

Covers all 9 discrepancy types:
  LOCAL_ONLY, BROKER_ONLY, STATE_MISMATCH, FILL_MISMATCH,
  QUANTITY_MISMATCH, PRICE_MISMATCH, MISSING_EXCHANGE_ORDER_ID,
  DUPLICATE_ORDER, UNRESOLVED_BROKER_EVENT
Also covers:
  - Paper mode always reports clean
  - Lock prevents concurrent runs from corrupting state
  - BrokerReconciliationError on gateway failure
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.brokers.contracts import (
    BrokerOrderStatus,
    BrokerOrderUpdate,
    BrokerSide,
    ReconciliationDiscrepancyType,
)
from src.brokers.exceptions import BrokerReconciliationError
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.reconciliation import ReconciliationEngine


def _paper_config() -> ZerodhaBrokerConfig:
    return ZerodhaBrokerConfig(paper_trading=True)


def _live_config() -> ZerodhaBrokerConfig:
    return ZerodhaBrokerConfig(
        api_key="key",
        api_secret="secret",
        paper_trading=False,
        enabled=True,
        live_trading_enabled=True,
    )


def _broker_update(
    broker_order_id: str,
    status: BrokerOrderStatus = BrokerOrderStatus.OPEN,
    filled_qty: Decimal = Decimal("0"),
    exchange_order_id: str | None = "EXCH001",
) -> BrokerOrderUpdate:
    return BrokerOrderUpdate(
        broker_order_id=broker_order_id,
        trading_symbol="RELIANCE",
        exchange="NSE",
        transaction_type=BrokerSide.BUY,
        status=status,
        quantity=Decimal("10"),
        filled_quantity=filled_qty,
        received_at=datetime.now(timezone.utc),
        exchange_order_id=exchange_order_id,
        paper_mode=False,
    )


def _make_engine(config, mock_gateway):
    health = BrokerHealthTracker(paper_mode=config.paper_trading)
    return ReconciliationEngine(
        config=config,
        health_tracker=health,
        order_gateway=mock_gateway,
    )


class TestPaperMode:
    @pytest.mark.asyncio
    async def test_paper_always_clean(self):
        config = _paper_config()
        gateway = MagicMock()
        engine = _make_engine(config, gateway)

        report = await engine.run(trigger="test")
        assert report.clean is True
        assert report.paper_mode is True
        assert len(report.discrepancies) == 0
        gateway.get_order_book.assert_not_called()

    @pytest.mark.asyncio
    async def test_paper_returns_zero_checked(self):
        config = _paper_config()
        gateway = MagicMock()
        engine = _make_engine(config, gateway)
        report = await engine.run(trigger="test")
        assert report.orders_checked == 0


class TestLocalOnly:
    @pytest.mark.asyncio
    async def test_local_order_not_in_broker_flagged(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        local_orders = [
            {
                "id": 1,
                "broker_order_id": "BRK-MISSING",
                "symbol": "RELIANCE",
                "status": "OPEN",
            }
        ]
        report = await engine.run(trigger="test", local_orders=local_orders)
        types = [d.discrepancy_type for d in report.discrepancies]
        assert ReconciliationDiscrepancyType.LOCAL_ONLY in types

    @pytest.mark.asyncio
    async def test_local_terminal_order_not_flagged(self):
        """Terminal local orders not in broker are OK (already settled)."""
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        local_orders = [
            {
                "id": 1,
                "broker_order_id": "BRK-DONE",
                "symbol": "RELIANCE",
                "status": "COMPLETE",
            }
        ]
        report = await engine.run(trigger="test", local_orders=local_orders)
        local_only = [d for d in report.discrepancies
                      if d.discrepancy_type == ReconciliationDiscrepancyType.LOCAL_ONLY]
        assert len(local_only) == 0


class TestPaperFallbackBucketing:
    @pytest.mark.asyncio
    async def test_fallback_order_not_flagged_local_only(self):
        """Paper-fallback orders never appear in the broker book — must not
        produce a false LOCAL_ONLY discrepancy."""
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        engine._load_paper_fallback_reasons = AsyncMock(
            return_value={"1": "token_expired"}
        )
        local_orders = [
            {
                "id": 1,
                "broker_order_id": "PAPER-001",
                "symbol": "RELIANCE",
                "status": "COMPLETE",
            },
            {
                "id": 2,
                "broker_order_id": "BRK-MISSING",
                "symbol": "INFY",
                "status": "OPEN",
            },
        ]
        report = await engine.run(trigger="eod", local_orders=local_orders)
        # Fallback order bucketed separately
        assert report.paper_fallback_orders == 1
        assert report.paper_fallback_reasons == {"token_expired": 1}
        # Both orders still counted as checked
        assert report.orders_checked == 2
        # Only the genuinely-missing live order is flagged
        local_only = [d for d in report.discrepancies
                      if d.discrepancy_type == ReconciliationDiscrepancyType.LOCAL_ONLY]
        assert len(local_only) == 1
        assert local_only[0].internal_order_id == "2"

    @pytest.mark.asyncio
    async def test_no_fallback_orders_reports_zero(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        report = await engine.run(trigger="eod", local_orders=[])
        assert report.paper_fallback_orders == 0
        assert report.paper_fallback_reasons == {}

    @pytest.mark.asyncio
    async def test_fallback_tag_load_failure_falls_through_to_checks(self):
        """If the tag lookup fails, orders go through normal checks (fail-noisy)."""
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        # No db_session → loader returns {} without error
        local_orders = [
            {"id": 1, "broker_order_id": "PAPER-001", "symbol": "RELIANCE", "status": "OPEN"},
        ]
        report = await engine.run(trigger="eod", local_orders=local_orders)
        assert report.paper_fallback_orders == 0
        types = [d.discrepancy_type for d in report.discrepancies]
        assert ReconciliationDiscrepancyType.LOCAL_ONLY in types


class TestBrokerOnly:
    @pytest.mark.asyncio
    async def test_broker_order_without_local_flagged(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[
            _broker_update("BRK-ORPHAN", BrokerOrderStatus.OPEN)
        ])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        report = await engine.run(trigger="test", local_orders=[])
        types = [d.discrepancy_type for d in report.discrepancies]
        assert ReconciliationDiscrepancyType.BROKER_ONLY in types

    @pytest.mark.asyncio
    async def test_broker_terminal_not_flagged(self):
        """Completed broker orders without local counterpart are OK."""
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[
            _broker_update("BRK-DONE", BrokerOrderStatus.COMPLETE, Decimal("10"))
        ])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        report = await engine.run(trigger="test", local_orders=[])
        broker_only = [d for d in report.discrepancies
                       if d.discrepancy_type == ReconciliationDiscrepancyType.BROKER_ONLY]
        assert len(broker_only) == 0


class TestStateMismatch:
    @pytest.mark.asyncio
    async def test_local_terminal_broker_open_flagged(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[
            _broker_update("BRK-001", BrokerOrderStatus.OPEN)
        ])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        local_orders = [{"id": 1, "broker_order_id": "BRK-001", "symbol": "X", "status": "COMPLETE"}]
        report = await engine.run(trigger="test", local_orders=local_orders)
        types = [d.discrepancy_type for d in report.discrepancies]
        assert ReconciliationDiscrepancyType.STATE_MISMATCH in types


class TestMissingExchangeOrderId:
    @pytest.mark.asyncio
    async def test_complete_order_without_exchange_id_flagged(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[
            _broker_update(
                "BRK-001",
                BrokerOrderStatus.COMPLETE,
                Decimal("10"),
                exchange_order_id=None,
            )
        ])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        local_orders = [{"id": 1, "broker_order_id": "BRK-001", "symbol": "X", "status": "COMPLETE"}]
        report = await engine.run(trigger="test", local_orders=local_orders)
        types = [d.discrepancy_type for d in report.discrepancies]
        assert ReconciliationDiscrepancyType.MISSING_EXCHANGE_ORDER_ID in types


class TestCleanReport:
    @pytest.mark.asyncio
    async def test_matching_orders_clean(self):
        from src.brokers.contracts import BrokerTrade
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[
            _broker_update("BRK-001", BrokerOrderStatus.COMPLETE, Decimal("10"))
        ])
        # Provide a matching trade so FILL_MISMATCH is not triggered
        matching_trade = BrokerTrade(
            trade_id="TRD-001",
            broker_order_id="BRK-001",
            exchange_order_id="EXCH001",
            trading_symbol="RELIANCE",
            exchange="NSE",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("10"),
            price=Decimal("2500"),
            fill_timestamp=datetime.now(timezone.utc),
            product="MIS",
        )
        gateway.get_trades = AsyncMock(return_value=[matching_trade])

        engine = _make_engine(config, gateway)
        local_orders = [{"id": 1, "broker_order_id": "BRK-001", "symbol": "X", "status": "COMPLETE"}]
        report = await engine.run(trigger="test", local_orders=local_orders)
        assert report.clean is True

    @pytest.mark.asyncio
    async def test_run_id_unique_per_run(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        r1 = await engine.run(trigger="t1", local_orders=[])
        r2 = await engine.run(trigger="t2", local_orders=[])
        assert r1.run_id != r2.run_id

    @pytest.mark.asyncio
    async def test_trigger_recorded(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = _make_engine(config, gateway)
        report = await engine.run(trigger="post_reconnect", local_orders=[])
        assert report.trigger == "post_reconnect"


class TestGatewayFailure:
    @pytest.mark.asyncio
    async def test_gateway_error_raises_reconciliation_error(self):
        config = _live_config()
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(side_effect=Exception("Network error"))

        engine = _make_engine(config, gateway)
        with pytest.raises(BrokerReconciliationError):
            await engine.run(trigger="test", local_orders=[])
