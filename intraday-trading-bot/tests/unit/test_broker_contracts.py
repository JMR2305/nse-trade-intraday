"""Tests for RC-10D broker contracts (Group A).

Covers:
  - All Pydantic models are frozen (immutable after construction)
  - Monetary/quantity fields use Decimal
  - All timestamps are timezone-aware
  - Serialization round-trips (model_dump → re-parse)
  - BrokerHealth.is_ready property
  - ReconciliationReport.has_discrepancies property
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from src.brokers.contracts import (
    BrokerCapabilities,
    BrokerExchange,
    BrokerFunds,
    BrokerHealth,
    BrokerHealthStatus,
    BrokerHolding,
    BrokerInstrument,
    BrokerMargins,
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerOrderUpdate,
    BrokerPosition,
    BrokerProduct,
    BrokerSide,
    BrokerSession,
    BrokerTrade,
    BrokerValidity,
    BrokerVariety,
    CorrelationStatus,
    ReconciliationDiscrepancy,
    ReconciliationDiscrepancyType,
    ReconciliationReport,
)


NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# BrokerOrderRequest
# ---------------------------------------------------------------------------

class TestBrokerOrderRequest:
    def _make(self, **kw) -> BrokerOrderRequest:
        defaults = dict(
            internal_order_id="ORD-001",
            idempotency_key="IDEM-001",
            trading_symbol="RELIANCE",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("10"),
            order_type=BrokerOrderType.MARKET,
            paper_mode=True,
        )
        return BrokerOrderRequest(**{**defaults, **kw})

    def test_frozen(self):
        req = self._make()
        with pytest.raises(Exception):
            req.trading_symbol = "INFY"  # frozen model must raise

    def test_quantity_is_decimal(self):
        req = self._make(quantity=Decimal("100"))
        assert isinstance(req.quantity, Decimal)

    def test_price_is_decimal_when_provided(self):
        req = self._make(price=Decimal("2500.50"))
        assert isinstance(req.price, Decimal)
        assert req.price == Decimal("2500.50")

    def test_paper_mode_default(self):
        req = self._make()
        assert req.paper_mode is True

    def test_exchange_default(self):
        req = self._make()
        assert req.exchange == BrokerExchange.NSE

    def test_product_default(self):
        req = self._make()
        assert req.product == BrokerProduct.MIS

    def test_validity_default(self):
        req = self._make()
        assert req.validity == BrokerValidity.DAY

    def test_serialization_round_trip(self):
        req = self._make(price=Decimal("100.5"))
        data = req.model_dump()
        restored = BrokerOrderRequest(**data)
        assert restored.internal_order_id == req.internal_order_id
        assert restored.trading_symbol == req.trading_symbol

    def test_sl_order_type(self):
        req = self._make(
            order_type=BrokerOrderType.SL,
            price=Decimal("2500"),
            trigger_price=Decimal("2480"),
        )
        assert req.order_type == BrokerOrderType.SL
        assert req.trigger_price == Decimal("2480")


# ---------------------------------------------------------------------------
# BrokerOrderResponse
# ---------------------------------------------------------------------------

class TestBrokerOrderResponse:
    def _make(self, **kw) -> BrokerOrderResponse:
        defaults = dict(
            internal_order_id="ORD-001",
            status=BrokerOrderStatus.COMPLETE,
            paper_mode=True,
        )
        return BrokerOrderResponse(**{**defaults, **kw})

    def test_frozen(self):
        resp = self._make()
        with pytest.raises(Exception):
            resp.status = BrokerOrderStatus.CANCELLED

    def test_placed_at_timezone_aware(self):
        resp = self._make(placed_at=NOW)
        assert resp.placed_at.tzinfo is not None

    def test_status_enum_values(self):
        for status in BrokerOrderStatus:
            resp = self._make(status=status)
            assert resp.status == status

    def test_paper_mode_default(self):
        resp = self._make()
        assert resp.paper_mode is True

    def test_broker_order_id_optional(self):
        resp = self._make()
        assert resp.broker_order_id is None


# ---------------------------------------------------------------------------
# BrokerOrderUpdate
# ---------------------------------------------------------------------------

class TestBrokerOrderUpdate:
    def _make(self, **kw) -> BrokerOrderUpdate:
        defaults = dict(
            broker_order_id="BRK-001",
            trading_symbol="INFY",
            exchange="NSE",
            transaction_type=BrokerSide.SELL,
            status=BrokerOrderStatus.COMPLETE,
            quantity=Decimal("5"),
            received_at=NOW,
            paper_mode=True,
        )
        return BrokerOrderUpdate(**{**defaults, **kw})

    def test_frozen(self):
        upd = self._make()
        with pytest.raises(Exception):
            upd.status = BrokerOrderStatus.OPEN

    def test_received_at_timezone_aware(self):
        upd = self._make()
        assert upd.received_at.tzinfo is not None

    def test_filled_quantity_decimal(self):
        upd = self._make(filled_quantity=Decimal("5"))
        assert isinstance(upd.filled_quantity, Decimal)

    def test_default_source(self):
        upd = self._make()
        assert upd.source == "websocket"

    def test_rest_source(self):
        upd = self._make(source="rest")
        assert upd.source == "rest"


# ---------------------------------------------------------------------------
# BrokerSession
# ---------------------------------------------------------------------------

class TestBrokerSession:
    def test_frozen(self):
        sess = BrokerSession(created_at=NOW, is_valid=True)
        with pytest.raises(Exception):
            sess.is_valid = False

    def test_repr_does_not_leak_secrets(self):
        sess = BrokerSession(created_at=NOW, user_id="XY1234", is_valid=True)
        r = repr(sess)
        assert "XY1234" in r
        assert "token" not in r.lower()
        assert "secret" not in r.lower()

    def test_session_id_auto_generated(self):
        s1 = BrokerSession(created_at=NOW)
        s2 = BrokerSession(created_at=NOW)
        assert s1.session_id != s2.session_id

    def test_created_at_timezone_aware(self):
        sess = BrokerSession(created_at=NOW)
        assert sess.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# BrokerHealth
# ---------------------------------------------------------------------------

class TestBrokerHealth:
    def _healthy(self) -> BrokerHealth:
        return BrokerHealth(
            status=BrokerHealthStatus.HEALTHY,
            authenticated=True,
            session_valid=True,
            paper_mode=False,
            checked_at=NOW,
        )

    def test_frozen(self):
        h = self._healthy()
        with pytest.raises(Exception):
            h.status = BrokerHealthStatus.DOWN

    def test_is_ready_healthy(self):
        h = self._healthy()
        assert h.is_ready is True

    def test_is_ready_not_authenticated(self):
        h = BrokerHealth(
            status=BrokerHealthStatus.HEALTHY,
            authenticated=False,
            session_valid=True,
            paper_mode=False,
            checked_at=NOW,
        )
        assert h.is_ready is False

    def test_is_ready_session_invalid(self):
        h = BrokerHealth(
            status=BrokerHealthStatus.HEALTHY,
            authenticated=True,
            session_valid=False,
            paper_mode=False,
            checked_at=NOW,
        )
        assert h.is_ready is False

    def test_is_ready_degraded_counts(self):
        h = BrokerHealth(
            status=BrokerHealthStatus.DEGRADED,
            authenticated=True,
            session_valid=True,
            paper_mode=False,
            checked_at=NOW,
        )
        assert h.is_ready is True  # DEGRADED still accepts orders

    def test_is_ready_down(self):
        h = BrokerHealth(
            status=BrokerHealthStatus.DOWN,
            authenticated=True,
            session_valid=True,
            paper_mode=False,
            checked_at=NOW,
        )
        assert h.is_ready is False

    def test_is_live_paper_mode(self):
        h = BrokerHealth(
            status=BrokerHealthStatus.HEALTHY,
            paper_mode=True,
            checked_at=NOW,
        )
        assert h.is_live is False

    def test_is_live_live_mode(self):
        h = self._healthy()
        assert h.is_live is True

    def test_checked_at_timezone_aware(self):
        h = self._healthy()
        assert h.checked_at.tzinfo is not None


# ---------------------------------------------------------------------------
# BrokerMargins / BrokerFunds
# ---------------------------------------------------------------------------

class TestBrokerMargins:
    def test_frozen(self):
        m = BrokerMargins(
            available_cash=Decimal("100000"),
            available_margin=Decimal("100000"),
            used_margin=Decimal("0"),
        )
        with pytest.raises(Exception):
            m.available_cash = Decimal("0")

    def test_all_decimal(self):
        m = BrokerMargins(
            available_cash=Decimal("500000"),
            available_margin=Decimal("500000"),
            used_margin=Decimal("50000"),
            payin_amount=Decimal("1000"),
        )
        assert isinstance(m.available_cash, Decimal)
        assert isinstance(m.used_margin, Decimal)


class TestBrokerFunds:
    def test_frozen(self):
        equity = BrokerMargins(
            available_cash=Decimal("1"),
            available_margin=Decimal("1"),
            used_margin=Decimal("0"),
        )
        funds = BrokerFunds(equity=equity)
        with pytest.raises(Exception):
            funds.equity = equity


# ---------------------------------------------------------------------------
# ReconciliationReport
# ---------------------------------------------------------------------------

class TestReconciliationReport:
    def test_has_discrepancies_false_when_empty(self):
        r = ReconciliationReport(
            trigger="test",
            started_at=NOW,
            discrepancies=[],
            clean=True,
            paper_mode=True,
        )
        assert r.has_discrepancies is False

    def test_has_discrepancies_true_when_present(self):
        d = ReconciliationDiscrepancy(
            discrepancy_type=ReconciliationDiscrepancyType.STATE_MISMATCH,
            description="test mismatch",
        )
        r = ReconciliationReport(
            trigger="test",
            started_at=NOW,
            discrepancies=[d],
            clean=False,
            paper_mode=True,
        )
        assert r.has_discrepancies is True

    def test_frozen(self):
        r = ReconciliationReport(trigger="test", started_at=NOW)
        with pytest.raises(Exception):
            r.clean = False


# ---------------------------------------------------------------------------
# BrokerTrade
# ---------------------------------------------------------------------------

class TestBrokerTrade:
    def test_frozen(self):
        t = BrokerTrade(
            trade_id="T1",
            broker_order_id="B1",
            trading_symbol="TCS",
            exchange="NSE",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("10"),
            price=Decimal("3500"),
            fill_timestamp=NOW,
            product="MIS",
        )
        with pytest.raises(Exception):
            t.quantity = Decimal("5")

    def test_price_is_decimal(self):
        t = BrokerTrade(
            trade_id="T1",
            broker_order_id="B1",
            trading_symbol="TCS",
            exchange="NSE",
            transaction_type=BrokerSide.BUY,
            quantity=Decimal("10"),
            price=Decimal("3500.25"),
            fill_timestamp=NOW,
            product="MIS",
        )
        assert isinstance(t.price, Decimal)


# ---------------------------------------------------------------------------
# CorrelationStatus enum
# ---------------------------------------------------------------------------

class TestCorrelationStatus:
    def test_all_values(self):
        expected = {"PENDING", "SUBMITTED", "CONFIRMED", "UNCERTAIN", "RECONCILED", "FAILED"}
        actual = {s.value for s in CorrelationStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# BrokerCapabilities
# ---------------------------------------------------------------------------

class TestBrokerCapabilities:
    def test_paper_mode_only_default(self):
        caps = BrokerCapabilities(broker_name="test")
        assert caps.paper_mode_only is True

    def test_supports_live_false_by_default(self):
        caps = BrokerCapabilities(broker_name="test")
        assert caps.supports_live_orders is False
