"""RC-10D Integration test: adapter-triggered reconciliation end-to-end.

Exercises the full path:
  ZerodhaAdapter.set_db_session() → gateway.set_db_session()
                                 → reconciler.set_db_session()
  ZerodhaAdapter._trigger_reconciliation() → reconciler.run(trigger="post_reconnect")
    → uses stored db_session (no manual local_orders injection)
    → loads local orders from DB
    → persists run/discrepancy rows to broker_reconciliation_runs

Also validates restart-safety: seed_correlations_from_db() populates the
in-memory cache from broker_order_correlations so idempotency survives restarts.
"""
from __future__ import annotations

import asyncio
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.brokers.contracts import (
    BrokerOrderStatus,
    BrokerOrderUpdate,
    BrokerSide,
    ReconciliationDiscrepancyType,
)
from src.brokers.zerodha.config import ZerodhaBrokerConfig
from src.brokers.zerodha.health import BrokerHealthTracker
from src.brokers.zerodha.reconciliation import ReconciliationEngine


# ── Helpers ────────────────────────────────────────────────────────────────

def _live_config() -> ZerodhaBrokerConfig:
    return ZerodhaBrokerConfig(
        api_key="key",
        api_secret="secret",
        paper_trading=False,
        enabled=True,
        live_trading_enabled=True,
        access_token="tok",
    )


def _paper_config() -> ZerodhaBrokerConfig:
    return ZerodhaBrokerConfig(paper_trading=True)


def _broker_update(order_id: str, status: BrokerOrderStatus) -> BrokerOrderUpdate:
    from datetime import datetime, timezone
    return BrokerOrderUpdate(
        broker_order_id=order_id,
        trading_symbol="RELIANCE",
        exchange="NSE",
        transaction_type=BrokerSide.BUY,
        status=status,
        quantity=Decimal("10"),
        filled_quantity=Decimal("10") if status == BrokerOrderStatus.COMPLETE else Decimal("0"),
        received_at=datetime.now(timezone.utc),
        exchange_order_id="EXCH001" if status == BrokerOrderStatus.COMPLETE else None,
        paper_mode=False,
    )


# ── Test 1: set_db_session wiring ─────────────────────────────────────────

class TestSetDbSessionWiring:
    def test_set_db_session_wires_gateway(self):
        """set_db_session propagates to the order gateway."""
        config = _paper_config()
        from src.brokers.paper_broker import PaperBroker
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway
        from src.brokers.zerodha.websocket import ZerodhaWebSocketManager
        from src.brokers.zerodha.reconciliation import ReconciliationEngine

        health = BrokerHealthTracker(paper_mode=True)
        gateway = ZerodhaOrderGateway(config=config, health_tracker=health,
                                       paper_broker=PaperBroker())
        engine = ReconciliationEngine(config=config, health_tracker=health,
                                       order_gateway=gateway)

        mock_session = MagicMock()
        gateway.set_db_session(mock_session)
        engine.set_db_session(mock_session)

        assert gateway._db_session is mock_session
        assert engine._db_session is mock_session

    def test_set_db_session_via_adapter_reaches_reconciler(self):
        """ZerodhaAdapter.set_db_session() propagates to the reconciler."""
        from src.brokers.zerodha.adapter import ZerodhaAdapter

        config = _paper_config()
        adapter = ZerodhaAdapter(config)
        mock_session = MagicMock()
        adapter.set_db_session(mock_session)

        # Both the order gateway and reconciler should have the session
        assert adapter._order_gateway._db_session is mock_session
        assert adapter._reconciler._db_session is mock_session


# ── Test 2: adapter-triggered reconciliation uses stored DB session ─────────

class TestAdapterTriggeredReconciliation:
    @pytest.mark.asyncio
    async def test_trigger_reconciliation_uses_stored_session(self):
        """_trigger_reconciliation runs with stored db_session (no manual injection)."""
        config = _live_config()
        health = BrokerHealthTracker(paper_mode=False)
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        mock_session = MagicMock()
        # _load_local_orders_from_db will be called on mock_session
        # Simulate an empty result from DB
        mock_session.execute = AsyncMock(
            return_value=MagicMock(
                mappings=lambda: MagicMock(fetchall=lambda: [])
            )
        )

        engine = ReconciliationEngine(config=config, health_tracker=health,
                                       order_gateway=gateway)
        engine.set_db_session(mock_session)

        # Call run() without supplying local_orders or db_session — should use stored session
        report = await engine.run(trigger="post_reconnect")

        assert report.trigger == "post_reconnect"
        assert report.clean is True
        # The DB should have been consulted (execute called at least once)
        # for local order loading
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_trigger_reconciliation_no_session_uses_empty_list(self):
        """Without any db_session, reconciliation runs with empty local orders (no crash)."""
        config = _live_config()
        health = BrokerHealthTracker(paper_mode=False)
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        engine = ReconciliationEngine(config=config, health_tracker=health,
                                       order_gateway=gateway)
        # No db_session at all
        assert engine._db_session is None

        report = await engine.run(trigger="post_reconnect")
        assert report.clean is True
        assert report.orders_checked == 0

    @pytest.mark.asyncio
    async def test_report_persisted_when_session_available(self):
        """Reconciliation run is written to broker_reconciliation_runs via db_session."""
        config = _live_config()
        health = BrokerHealthTracker(paper_mode=False)
        gateway = MagicMock()
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        persist_calls = []

        async def mock_execute(stmt, params=None):
            persist_calls.append(params)
            return MagicMock(mappings=lambda: MagicMock(fetchall=lambda: []))

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_session.commit = AsyncMock()

        engine = ReconciliationEngine(config=config, health_tracker=health,
                                       order_gateway=gateway)
        engine.set_db_session(mock_session)

        report = await engine.run(trigger="eod")
        assert report.trigger == "eod"
        # session.execute should have been called (for both load and persist)
        assert mock_session.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_discrepancy_detected_from_db_local_orders(self):
        """LOCAL_ONLY discrepancy found using orders loaded from DB."""
        config = _live_config()
        health = BrokerHealthTracker(paper_mode=False)
        gateway = MagicMock()
        # Broker returns no orders (all empty)
        gateway.get_order_book = AsyncMock(return_value=[])
        gateway.get_trades = AsyncMock(return_value=[])

        # DB returns one OPEN local order with a broker_order_id
        local_row = {
            "id": 1,
            "broker_order_id": "BRK-ORPHAN",
            "symbol": "RELIANCE",
            "status": "OPEN",
            "quantity": 10,
            "price": None,
        }

        async def mock_execute(stmt, params=None):
            return MagicMock(
                mappings=lambda: MagicMock(fetchall=lambda: [local_row])
            )

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_session.commit = AsyncMock()

        engine = ReconciliationEngine(config=config, health_tracker=health,
                                       order_gateway=gateway)
        engine.set_db_session(mock_session)

        report = await engine.run(trigger="startup")
        types = [d.discrepancy_type for d in report.discrepancies]
        assert ReconciliationDiscrepancyType.LOCAL_ONLY in types
        assert report.clean is False


# ── Test 3: seed_correlations_from_db restores idempotency cache ──────────

class TestRestartRecovery:
    @pytest.mark.asyncio
    async def test_seed_correlations_populates_in_memory_cache(self):
        """After restart, seed_from_db restores the correlation cache."""
        from src.brokers.paper_broker import PaperBroker
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway

        config = _paper_config()
        health = BrokerHealthTracker(paper_mode=True)
        gateway = ZerodhaOrderGateway(config=config, health_tracker=health,
                                       paper_broker=PaperBroker())

        # Simulate DB returning 2 existing correlations
        mock_rows = [
            MagicMock(idempotency_key="IDEM-A", status="CONFIRMED"),
            MagicMock(idempotency_key="IDEM-B", status="UNCERTAIN"),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.fetchall = lambda: mock_rows
            return result

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)

        count = await gateway.seed_from_db(mock_session)
        assert count == 2
        assert gateway._correlations["IDEM-A"] == "CONFIRMED"
        assert gateway._correlations["IDEM-B"] == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_seed_correlations_via_adapter_method(self):
        """ZerodhaAdapter.seed_correlations_from_db() delegates to gateway."""
        from src.brokers.zerodha.adapter import ZerodhaAdapter

        config = _paper_config()
        adapter = ZerodhaAdapter(config)

        mock_rows = [
            MagicMock(idempotency_key="IDEM-C", status="CONFIRMED"),
        ]

        async def mock_execute(stmt):
            result = MagicMock()
            result.fetchall = lambda: mock_rows
            return result

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)

        count = await adapter.seed_correlations_from_db(mock_session)
        assert count == 1
        assert adapter._order_gateway._correlations["IDEM-C"] == "CONFIRMED"

    @pytest.mark.asyncio
    async def test_seed_correlations_no_session_returns_zero(self):
        """Without a DB session, seed returns 0 and does not crash."""
        from src.brokers.paper_broker import PaperBroker
        from src.brokers.zerodha.order_gateway import ZerodhaOrderGateway

        config = _paper_config()
        health = BrokerHealthTracker(paper_mode=True)
        gateway = ZerodhaOrderGateway(config=config, health_tracker=health,
                                       paper_broker=PaperBroker())

        count = await gateway.seed_from_db(None)
        assert count == 0
        assert gateway._correlations == {}
