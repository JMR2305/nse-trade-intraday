"""Tests for RC-10D Zerodha status mapper (Group C).

Covers:
  - All 12+ known Zerodha status strings map to canonical BrokerOrderStatus
  - Unknown statuses → BrokerOrderStatus.UNKNOWN (never crash)
  - Case-insensitive mapping
  - Out-of-order update detection via state machine
  - Illegal transition rejection
  - BrokerOrderUpdate mapping from raw dicts
  - BrokerTrade mapping from raw dicts
  - to_zerodha_order_params conversion
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from src.brokers.contracts import (
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerProduct,
    BrokerSide,
    BrokerExchange,
    BrokerVariety,
    BrokerValidity,
    BrokerOrderRequest,
)
from src.brokers.zerodha.mapper import ZerodhaStatusMapper


# ---------------------------------------------------------------------------
# Known status mappings
# ---------------------------------------------------------------------------

class TestStatusMapping:
    KNOWN_MAPPINGS = [
        ("OPEN", BrokerOrderStatus.OPEN),
        ("OPEN PENDING", BrokerOrderStatus.OPEN),
        ("VALIDATION PENDING", BrokerOrderStatus.VALIDATION_PENDING),
        ("TRIGGER PENDING", BrokerOrderStatus.TRIGGER_PENDING),
        ("MODIFY PENDING", BrokerOrderStatus.MODIFICATION_PENDING),
        ("MODIFY VALIDATION PENDING", BrokerOrderStatus.MODIFICATION_PENDING),
        ("CANCEL PENDING", BrokerOrderStatus.CANCELLATION_PENDING),
        ("UPDATE", BrokerOrderStatus.PARTIALLY_FILLED),
        ("COMPLETE", BrokerOrderStatus.COMPLETE),
        ("CANCELLED", BrokerOrderStatus.CANCELLED),
        ("REJECTED", BrokerOrderStatus.REJECTED),
        ("AMO REQ RECEIVED", BrokerOrderStatus.PENDING),
    ]

    @pytest.mark.parametrize("raw,expected", KNOWN_MAPPINGS)
    def test_known_status(self, raw, expected):
        result = ZerodhaStatusMapper.map_status(raw)
        assert result == expected, f"{raw!r} → expected {expected}, got {result}"

    @pytest.mark.parametrize("raw,expected", KNOWN_MAPPINGS)
    def test_case_insensitive(self, raw, expected):
        result = ZerodhaStatusMapper.map_status(raw.lower())
        assert result == expected

    def test_unknown_status_returns_unknown(self):
        result = ZerodhaStatusMapper.map_status("SOME_FUTURE_STATUS_12345")
        assert result == BrokerOrderStatus.UNKNOWN

    def test_empty_string_returns_unknown(self):
        result = ZerodhaStatusMapper.map_status("")
        assert result == BrokerOrderStatus.UNKNOWN

    def test_none_like_returns_unknown(self):
        # Simulate None being passed as empty str
        result = ZerodhaStatusMapper.map_status("")
        assert result == BrokerOrderStatus.UNKNOWN

    def test_whitespace_only_returns_unknown(self):
        result = ZerodhaStatusMapper.map_status("   ")
        # strip() in map_status means this maps to ""
        assert result == BrokerOrderStatus.UNKNOWN


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------

class TestIsTerminal:
    def test_complete_is_terminal(self):
        assert ZerodhaStatusMapper.is_terminal(BrokerOrderStatus.COMPLETE) is True

    def test_cancelled_is_terminal(self):
        assert ZerodhaStatusMapper.is_terminal(BrokerOrderStatus.CANCELLED) is True

    def test_rejected_is_terminal(self):
        assert ZerodhaStatusMapper.is_terminal(BrokerOrderStatus.REJECTED) is True

    def test_open_not_terminal(self):
        assert ZerodhaStatusMapper.is_terminal(BrokerOrderStatus.OPEN) is False

    def test_pending_not_terminal(self):
        assert ZerodhaStatusMapper.is_terminal(BrokerOrderStatus.PENDING) is False

    def test_partially_filled_not_terminal(self):
        assert ZerodhaStatusMapper.is_terminal(BrokerOrderStatus.PARTIALLY_FILLED) is False


# ---------------------------------------------------------------------------
# State transition validation
# ---------------------------------------------------------------------------

class TestTransitions:
    def test_idempotent_same_state(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.OPEN, BrokerOrderStatus.OPEN
        ) is True

    def test_pending_to_open(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.PENDING, BrokerOrderStatus.OPEN
        ) is True

    def test_open_to_complete(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.OPEN, BrokerOrderStatus.COMPLETE
        ) is True

    def test_open_to_partial(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.OPEN, BrokerOrderStatus.PARTIALLY_FILLED
        ) is True

    def test_partial_to_complete(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.PARTIALLY_FILLED, BrokerOrderStatus.COMPLETE
        ) is True

    def test_complete_to_anything_rejected(self):
        """COMPLETE → any other state is illegal."""
        for status in BrokerOrderStatus:
            if status != BrokerOrderStatus.COMPLETE:
                assert ZerodhaStatusMapper.is_transition_allowed(
                    BrokerOrderStatus.COMPLETE, status
                ) is False

    def test_cancelled_to_open_rejected(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.CANCELLED, BrokerOrderStatus.OPEN
        ) is False

    def test_rejected_to_open_rejected(self):
        assert ZerodhaStatusMapper.is_transition_allowed(
            BrokerOrderStatus.REJECTED, BrokerOrderStatus.OPEN
        ) is False


# ---------------------------------------------------------------------------
# map_order_update
# ---------------------------------------------------------------------------

class TestMapOrderUpdate:
    def _raw(self, **overrides) -> dict:
        base = {
            "order_id": "220101000001234",
            "tradingsymbol": "RELIANCE",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "status": "COMPLETE",
            "quantity": 10,
            "filled_quantity": 10,
            "pending_quantity": 0,
            "average_price": "2500.50",
            "price": "2500.00",
        }
        base.update(overrides)
        return base

    def test_basic_mapping(self):
        upd = ZerodhaStatusMapper.map_order_update(self._raw(), source="rest")
        assert upd.broker_order_id == "220101000001234"
        assert upd.trading_symbol == "RELIANCE"
        assert upd.exchange == "NSE"
        assert upd.transaction_type == BrokerSide.BUY
        assert upd.status == BrokerOrderStatus.COMPLETE
        assert upd.quantity == Decimal("10")
        assert upd.filled_quantity == Decimal("10")

    def test_sell_side(self):
        upd = ZerodhaStatusMapper.map_order_update(
            self._raw(transaction_type="SELL")
        )
        assert upd.transaction_type == BrokerSide.SELL

    def test_unknown_status_maps_to_unknown(self):
        upd = ZerodhaStatusMapper.map_order_update(
            self._raw(status="FUTURE_STATUS")
        )
        assert upd.status == BrokerOrderStatus.UNKNOWN

    def test_received_at_is_tz_aware(self):
        upd = ZerodhaStatusMapper.map_order_update(self._raw())
        assert upd.received_at.tzinfo is not None

    def test_rejected_reason_from_status_message(self):
        upd = ZerodhaStatusMapper.map_order_update(
            self._raw(
                status="REJECTED",
                status_message="Insufficient margin"
            )
        )
        assert upd.rejected_reason == "Insufficient margin"

    def test_missing_fields_dont_crash(self):
        upd = ZerodhaStatusMapper.map_order_update({"status": "OPEN"})
        assert upd.status == BrokerOrderStatus.OPEN
        assert upd.quantity == Decimal("0")

    def test_paper_mode_flag(self):
        upd = ZerodhaStatusMapper.map_order_update(self._raw(), paper_mode=True)
        assert upd.paper_mode is True

    def test_source_rest(self):
        upd = ZerodhaStatusMapper.map_order_update(self._raw(), source="rest")
        assert upd.source == "rest"


# ---------------------------------------------------------------------------
# map_trade
# ---------------------------------------------------------------------------

class TestMapTrade:
    def _raw(self) -> dict:
        return {
            "trade_id": "TRD001",
            "order_id": "ORD001",
            "exchange_order_id": "EXCH001",
            "tradingsymbol": "TCS",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "quantity": 5,
            "average_price": "3500.25",
            "product": "MIS",
        }

    def test_basic_trade_mapping(self):
        t = ZerodhaStatusMapper.map_trade(self._raw())
        assert t.trade_id == "TRD001"
        assert t.trading_symbol == "TCS"
        assert t.quantity == Decimal("5")
        assert t.price == Decimal("3500.25")
        assert t.transaction_type == BrokerSide.BUY

    def test_fill_timestamp_tz_aware(self):
        t = ZerodhaStatusMapper.map_trade(self._raw())
        assert t.fill_timestamp.tzinfo is not None

    def test_sell_side(self):
        raw = self._raw()
        raw["transaction_type"] = "SELL"
        t = ZerodhaStatusMapper.map_trade(raw)
        assert t.transaction_type == BrokerSide.SELL


# ---------------------------------------------------------------------------
# to_zerodha_order_params
# ---------------------------------------------------------------------------

class TestToZerodhaOrderParams:
    def _request(self, **kw) -> BrokerOrderRequest:
        defaults = dict(
            internal_order_id="ORD-001",
            idempotency_key="IDEM-001",
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

    def test_basic_params_present(self):
        req = self._request()
        params = ZerodhaStatusMapper.to_zerodha_order_params(req)
        assert params["tradingsymbol"] == "RELIANCE"
        assert params["exchange"] == "NSE"
        assert params["transaction_type"] == "BUY"
        assert params["quantity"] == 10
        assert params["order_type"] == "MARKET"
        assert params["product"] == "MIS"
        assert params["validity"] == "DAY"

    def test_price_included_when_limit(self):
        req = self._request(
            order_type=BrokerOrderType.LIMIT,
            price=Decimal("2500.50"),
        )
        params = ZerodhaStatusMapper.to_zerodha_order_params(req)
        assert "price" in params
        assert params["price"] == pytest.approx(2500.50)

    def test_sl_order_type(self):
        req = self._request(
            order_type=BrokerOrderType.SL,
            price=Decimal("2500"),
            trigger_price=Decimal("2480"),
        )
        params = ZerodhaStatusMapper.to_zerodha_order_params(req)
        assert params["order_type"] == "SL"
        assert "trigger_price" in params

    def test_sl_m_order_type(self):
        req = self._request(
            order_type=BrokerOrderType.SL_M,
            trigger_price=Decimal("2480"),
        )
        params = ZerodhaStatusMapper.to_zerodha_order_params(req)
        assert params["order_type"] == "SL-M"

    def test_tag_truncated_to_20_chars(self):
        req = self._request(tag=None)
        params = ZerodhaStatusMapper.to_zerodha_order_params(req)
        assert len(params["tag"]) <= 20

    def test_price_not_included_for_market(self):
        req = self._request(price=None)
        params = ZerodhaStatusMapper.to_zerodha_order_params(req)
        assert "price" not in params
