"""Unit tests for portfolio and position contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution.portfolio import (
    CashLedger,
    PortfolioSnapshot,
    PositionDirection,
    PositionSnapshot,
)


# ==================================================================
# PositionSnapshot
# ==================================================================

class TestPositionSnapshot:
    def test_flat_position(self):
        pos = PositionSnapshot(
            instrument_token=123456,
            net_quantity=0,
            direction=PositionDirection.FLAT,
            average_buy_price=Decimal("0"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=0,
            total_sell_quantity=0,
            total_buy_value=Decimal("0"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        assert pos.is_flat
        assert not pos.is_long
        assert not pos.is_short
        assert pos.market_value == Decimal("0")
        assert pos.exposure == Decimal("0")

    def test_long_position(self):
        pos = PositionSnapshot(
            instrument_token=123456,
            net_quantity=100,
            direction=PositionDirection.LONG,
            average_buy_price=Decimal("150"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=100,
            total_sell_quantity=0,
            total_buy_value=Decimal("15000"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("500"),
            market_price=Decimal("155"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert pos.is_long
        assert pos.market_value == Decimal("15500")
        assert pos.exposure == Decimal("15000")

    def test_short_position(self):
        pos = PositionSnapshot(
            instrument_token=123456,
            net_quantity=-50,
            direction=PositionDirection.SHORT,
            average_buy_price=Decimal("0"),
            average_sell_price=Decimal("200"),
            total_buy_quantity=0,
            total_sell_quantity=50,
            total_buy_value=Decimal("0"),
            total_sell_value=Decimal("10000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("250"),
            market_price=Decimal("195"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert pos.is_short
        assert pos.market_value == Decimal("-9750")
        assert pos.exposure == Decimal("10000")

    def test_inconsistent_direction_raises(self):
        with pytest.raises(ValueError):
            PositionSnapshot(
                instrument_token=123456,
                net_quantity=100,
                direction=PositionDirection.SHORT,  # inconsistent
                average_buy_price=Decimal("150"),
                average_sell_price=Decimal("0"),
                total_buy_quantity=100,
                total_sell_quantity=0,
                total_buy_value=Decimal("15000"),
                total_sell_value=Decimal("0"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                market_price=None,
                market_timestamp=None,
            )


# ==================================================================
# CashLedger
# ==================================================================

class TestCashLedger:
    def test_initial_state(self):
        ledger = CashLedger()
        assert ledger.balance == Decimal("0")
        assert ledger.transaction_count == 0

    def test_credit(self):
        ledger = CashLedger()
        ledger.credit(Decimal("10000"))
        assert ledger.balance == Decimal("10000")
        assert ledger.total_credits == Decimal("10000")
        assert ledger.transaction_count == 1

    def test_debit(self):
        ledger = CashLedger()
        ledger.credit(Decimal("20000"))
        ledger.debit(Decimal("5000"))
        assert ledger.balance == Decimal("15000")
        assert ledger.total_debits == Decimal("5000")
        assert ledger.transaction_count == 2

    def test_credit_negative_raises(self):
        ledger = CashLedger()
        with pytest.raises(ValueError):
            ledger.credit(Decimal("-100"))

    def test_debit_negative_raises(self):
        ledger = CashLedger()
        with pytest.raises(ValueError):
            ledger.debit(Decimal("-100"))

    def test_reset(self):
        ledger = CashLedger()
        ledger.credit(Decimal("10000"))
        ledger.debit(Decimal("3000"))
        ledger.reset()
        assert ledger.balance == Decimal("0")
        assert ledger.total_credits == Decimal("0")
        assert ledger.total_debits == Decimal("0")
        assert ledger.transaction_count == 0


# ==================================================================
# PortfolioSnapshot
# ==================================================================

class TestPortfolioSnapshot:
    def test_empty_portfolio(self):
        snap = PortfolioSnapshot(
            cash=Decimal("1000000"),
            equity=Decimal("1000000"),
            positions=(),
            market_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("0"),
            buying_power=Decimal("1000000"),
            margin_used=Decimal("0"),
            trade_count=0,
            turnover=Decimal("0"),
        )
        assert snap.cash == Decimal("1000000")
        assert snap.total_pnl == Decimal("0")

    def test_portfolio_with_positions(self):
        pos1 = PositionSnapshot(
            instrument_token=123456,
            net_quantity=100,
            direction=PositionDirection.LONG,
            average_buy_price=Decimal("150"),
            average_sell_price=Decimal("0"),
            total_buy_quantity=100,
            total_sell_quantity=0,
            total_buy_value=Decimal("15000"),
            total_sell_value=Decimal("0"),
            realized_pnl=Decimal("500"),
            unrealized_pnl=Decimal("200"),
            market_price=Decimal("152"),
            market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        )
        snap = PortfolioSnapshot(
            cash=Decimal("985000"),
            equity=Decimal("1000200"),
            positions=(pos1,),
            market_value=Decimal("15200"),
            realized_pnl=Decimal("500"),
            unrealized_pnl=Decimal("200"),
            total_pnl=Decimal("700"),
            buying_power=Decimal("985000"),
            margin_used=Decimal("15000"),
            trade_count=1,
            turnover=Decimal("15000"),
        )
        assert snap.total_pnl == Decimal("700")
        assert len(snap.positions) == 1
