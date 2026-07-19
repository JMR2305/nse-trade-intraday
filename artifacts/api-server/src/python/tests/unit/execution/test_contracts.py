"""Unit tests for execution contracts.

Covers:
  - valid order construction for all order types and sides
  - invalid quantity (zero, negative)
  - invalid prices (zero, negative)
  - required fields by order type
  - timezone-aware timestamp enforcement
  - immutability of Pydantic models
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.execution.contracts import (
    ExecutionOrder,
    ExecutionOrderSide,
    ExecutionOrderStatus,
    ExecutionOrderType,
    ExecutionAuditEvent,
    ExecutionOrderAction,
    FillRecord,
)


# ==================================================================
# Helpers
# ==================================================================

def _make_order(**overrides) -> ExecutionOrder:
    defaults = {
        "client_order_id": "test-001",
        "instrument_token": 123456,
        "side": ExecutionOrderSide.BUY,
        "order_type": ExecutionOrderType.MARKET,
        "quantity": 100,
    }
    defaults.update(overrides)
    return ExecutionOrder(**defaults)


# ==================================================================
# Valid Construction
# ==================================================================

class TestValidOrderConstruction:
    def test_market_buy(self):
        order = _make_order(side=ExecutionOrderSide.BUY, order_type=ExecutionOrderType.MARKET)
        assert order.side == ExecutionOrderSide.BUY
        assert order.order_type == ExecutionOrderType.MARKET
        assert order.quantity == 100
        assert order.limit_price is None
        assert order.trigger_price is None

    def test_market_sell(self):
        order = _make_order(side=ExecutionOrderSide.SELL, order_type=ExecutionOrderType.MARKET)
        assert order.side == ExecutionOrderSide.SELL

    def test_limit_buy(self):
        order = _make_order(
            order_type=ExecutionOrderType.LIMIT,
            limit_price=Decimal("150.50"),
        )
        assert order.order_type == ExecutionOrderType.LIMIT
        assert order.limit_price == Decimal("150.50")

    def test_limit_sell(self):
        order = _make_order(
            side=ExecutionOrderSide.SELL,
            order_type=ExecutionOrderType.LIMIT,
            limit_price=Decimal("200.00"),
        )
        assert order.side == ExecutionOrderSide.SELL
        assert order.limit_price == Decimal("200.00")

    def test_stop_market_buy(self):
        order = _make_order(
            order_type=ExecutionOrderType.STOP_MARKET,
            trigger_price=Decimal("145.00"),
        )
        assert order.order_type == ExecutionOrderType.STOP_MARKET
        assert order.trigger_price == Decimal("145.00")
        assert order.limit_price is None

    def test_stop_limit_buy(self):
        order = _make_order(
            order_type=ExecutionOrderType.STOP_LIMIT,
            trigger_price=Decimal("145.00"),
            limit_price=Decimal("146.00"),
        )
        assert order.order_type == ExecutionOrderType.STOP_LIMIT
        assert order.trigger_price == Decimal("145.00")
        assert order.limit_price == Decimal("146.00")

    def test_all_sides_and_types(self):
        """Exhaustive: 2 sides x 4 types = 8 valid combinations."""
        for side in ExecutionOrderSide:
            for otype in ExecutionOrderType:
                kwargs = {"side": side, "order_type": otype}
                if otype == ExecutionOrderType.LIMIT:
                    kwargs["limit_price"] = Decimal("100")
                elif otype == ExecutionOrderType.STOP_MARKET:
                    kwargs["trigger_price"] = Decimal("100")
                elif otype == ExecutionOrderType.STOP_LIMIT:
                    kwargs["trigger_price"] = Decimal("100")
                    kwargs["limit_price"] = Decimal("101")
                order = _make_order(**kwargs)
                assert order.side == side
                assert order.order_type == otype


# ==================================================================
# Invalid Quantity
# ==================================================================

class TestInvalidQuantity:
    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(quantity=0)

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(quantity=-10)


# ==================================================================
# Invalid Instrument Token
# ==================================================================

class TestInvalidInstrumentToken:
    def test_zero_token_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(instrument_token=0)

    def test_negative_token_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(instrument_token=-1)


# ==================================================================
# Invalid Prices
# ==================================================================

class TestInvalidPrices:
    def test_limit_zero_price_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(order_type=ExecutionOrderType.LIMIT, limit_price=Decimal("0"))

    def test_limit_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(order_type=ExecutionOrderType.LIMIT, limit_price=Decimal("-10"))

    def test_stop_market_zero_trigger_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(order_type=ExecutionOrderType.STOP_MARKET, trigger_price=Decimal("0"))

    def test_stop_limit_zero_trigger_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(
                order_type=ExecutionOrderType.STOP_LIMIT,
                trigger_price=Decimal("0"),
                limit_price=Decimal("100"),
            )

    def test_stop_limit_zero_limit_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(
                order_type=ExecutionOrderType.STOP_LIMIT,
                trigger_price=Decimal("100"),
                limit_price=Decimal("0"),
            )


# ==================================================================
# Required Fields by Order Type
# ==================================================================

class TestRequiredFieldsByOrderType:
    def test_limit_missing_limit_price(self):
        with pytest.raises(ValidationError, match="require limit_price"):
            _make_order(order_type=ExecutionOrderType.LIMIT)

    def test_market_with_limit_price_rejected(self):
        with pytest.raises(ValidationError, match="must not specify limit_price"):
            _make_order(order_type=ExecutionOrderType.MARKET, limit_price=Decimal("100"))

    def test_stop_market_missing_trigger_price(self):
        with pytest.raises(ValidationError, match="require trigger_price"):
            _make_order(order_type=ExecutionOrderType.STOP_MARKET)

    def test_stop_market_with_limit_price_rejected(self):
        with pytest.raises(ValidationError, match="must not specify limit_price"):
            _make_order(
                order_type=ExecutionOrderType.STOP_MARKET,
                trigger_price=Decimal("100"),
                limit_price=Decimal("101"),
            )

    def test_stop_limit_missing_trigger_price(self):
        with pytest.raises(ValidationError, match="require trigger_price"):
            _make_order(order_type=ExecutionOrderType.STOP_LIMIT, limit_price=Decimal("100"))

    def test_stop_limit_missing_limit_price(self):
        with pytest.raises(ValidationError, match="require limit_price"):
            _make_order(order_type=ExecutionOrderType.STOP_LIMIT, trigger_price=Decimal("100"))


# ==================================================================
# Client Order ID
# ==================================================================

class TestClientOrderId:
    def test_empty_client_order_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_order(client_order_id="")

    def test_valid_client_order_id(self):
        order = _make_order(client_order_id="ext-12345")
        assert order.client_order_id == "ext-12345"


# ==================================================================
# Timezone-Aware Timestamps
# ==================================================================

class TestTimezoneAwareTimestamps:
    def test_naive_created_at_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            ExecutionOrder(
                client_order_id="test",
                instrument_token=1,
                side=ExecutionOrderSide.BUY,
                order_type=ExecutionOrderType.MARKET,
                quantity=1,
                created_at=datetime(2026, 7, 20, 9, 15, 0),  # naive
            )

    def test_utc_created_at_accepted(self):
        order = ExecutionOrder(
            client_order_id="test",
            instrument_token=1,
            side=ExecutionOrderSide.BUY,
            order_type=ExecutionOrderType.MARKET,
            quantity=1,
            created_at=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert order.created_at.tzinfo is not None

    def test_fill_record_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            FillRecord(
                quantity=10,
                price=Decimal("100"),
                filled_at=datetime(2026, 7, 20, 9, 15, 0),  # naive
            )

    def test_audit_event_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            ExecutionAuditEvent(
                order_id=__import__("uuid").uuid4(),
                client_order_id="test",
                sequence_number=1,
                previous_state=ExecutionOrderStatus.CREATED,
                new_state=ExecutionOrderStatus.VALIDATED,
                action=ExecutionOrderAction.VALIDATE,
                event_timestamp=datetime(2026, 7, 20, 9, 15, 0),  # naive
            )


# ==================================================================
# Immutability
# ==================================================================

class TestImmutability:
    def test_order_immutable(self):
        order = _make_order()
        with pytest.raises(ValidationError):
            order.quantity = 200

    def test_audit_event_immutable(self):
        from uuid import uuid4
        event = ExecutionAuditEvent(
            order_id=uuid4(),
            client_order_id="test",
            sequence_number=1,
            previous_state=ExecutionOrderStatus.CREATED,
            new_state=ExecutionOrderStatus.VALIDATED,
            action=ExecutionOrderAction.VALIDATE,
        )
        with pytest.raises(ValidationError):
            event.sequence_number = 2

    def test_fill_record_immutable(self):
        fr = FillRecord(
            quantity=10,
            price=Decimal("100"),
            filled_at=datetime.now(timezone.utc),
        )
        with pytest.raises(ValidationError):
            fr.quantity = 20


# ==================================================================
# Terminal States
# ==================================================================

class TestTerminalStates:
    def test_terminal_states_frozen_set(self):
        from src.execution.contracts import TERMINAL_STATES
        assert ExecutionOrderStatus.FILLED in TERMINAL_STATES
        assert ExecutionOrderStatus.CANCELLED in TERMINAL_STATES
        assert ExecutionOrderStatus.REJECTED in TERMINAL_STATES
        assert ExecutionOrderStatus.EXPIRED in TERMINAL_STATES
        assert ExecutionOrderStatus.FAILED in TERMINAL_STATES
        assert ExecutionOrderStatus.CREATED not in TERMINAL_STATES
        assert ExecutionOrderStatus.OPEN not in TERMINAL_STATES
