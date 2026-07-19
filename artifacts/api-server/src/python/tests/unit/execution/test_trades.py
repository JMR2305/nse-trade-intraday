"""Unit tests for trade ledger and execution trade contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.contracts import ExecutionOrderSide
from src.execution.trades import ExecutionTrade, TradeLedger


# ==================================================================
# ExecutionTrade
# ==================================================================

class TestExecutionTrade:
    def test_trade_construction(self):
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert trade.trade_id == "T-001"
        assert trade.fill_id == "F-001"
        assert trade.position_impact == "OPEN"
        assert trade.realized_pnl == Decimal("0")

    def test_trade_immutable(self):
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            trade.quantity = 200

    def test_invalid_position_impact(self):
        with pytest.raises(ValueError):
            ExecutionTrade(
                trade_id="T-001",
                fill_id="F-001",
                order_id=uuid4(),
                client_order_id="test-001",
                instrument_token=123456,
                side=ExecutionOrderSide.BUY,
                quantity=100,
                price=Decimal("150"),
                gross_value=Decimal("15000"),
                position_impact="INVALID",  # invalid
                realized_pnl=Decimal("0"),
                cumulative_realized_pnl=Decimal("0"),
                market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
            )


# ==================================================================
# TradeLedger
# ==================================================================

class TestTradeLedger:
    def test_record_trade(self):
        ledger = TradeLedger()
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert ledger.record(trade) is True
        assert ledger.trade_count == 1
        assert ledger.total_turnover == Decimal("15000")

    def test_duplicate_fill_id_ignored(self):
        ledger = TradeLedger()
        order_id = uuid4()
        trade1 = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=order_id,
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        trade2 = ExecutionTrade(
            trade_id="T-002",
            fill_id="F-001",  # same fill_id
            order_id=order_id,
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert ledger.record(trade1) is True
        assert ledger.record(trade2) is False
        assert ledger.trade_count == 1

    def test_get_trades_by_instrument(self):
        ledger = TradeLedger()
        trade1 = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        trade2 = ExecutionTrade(
            trade_id="T-002",
            fill_id="F-002",
            order_id=uuid4(),
            client_order_id="test-002",
            instrument_token=789012,
            side=ExecutionOrderSide.BUY,
            quantity=50,
            price=Decimal("200"),
            gross_value=Decimal("10000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        ledger.record(trade1)
        ledger.record(trade2)

        trades_123456 = ledger.get_trades(instrument_token=123456)
        assert len(trades_123456) == 1
        assert trades_123456[0].instrument_token == 123456

        all_trades = ledger.get_trades()
        assert len(all_trades) == 2

    def test_get_trade_by_fill_id(self):
        ledger = TradeLedger()
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        ledger.record(trade)

        found = ledger.get_trade_by_fill_id("F-001")
        assert found is not None
        assert found.trade_id == "T-001"

        not_found = ledger.get_trade_by_fill_id("F-999")
        assert not_found is None

    def test_reset(self):
        ledger = TradeLedger()
        trade = ExecutionTrade(
            trade_id="T-001",
            fill_id="F-001",
            order_id=uuid4(),
            client_order_id="test-001",
            instrument_token=123456,
            side=ExecutionOrderSide.BUY,
            quantity=100,
            price=Decimal("150"),
            gross_value=Decimal("15000"),
            position_impact="OPEN",
            realized_pnl=Decimal("0"),
            cumulative_realized_pnl=Decimal("0"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        ledger.record(trade)
        assert ledger.trade_count == 1

        ledger.reset()
        assert ledger.trade_count == 0
        assert ledger.total_turnover == Decimal("0")

        # After reset, same fill_id can be recorded again
        assert ledger.record(trade) is True
