"""Unit tests for P&L calculator."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution.contracts import ExecutionOrderSide
from src.execution.pnl import PnLCalculator
from src.execution.portfolio import PositionDirection, PositionSnapshot


# ==================================================================
# Helpers
# ==================================================================

def _empty_position(instrument_token: int = 123456) -> PositionSnapshot:
    return PositionSnapshot(
        instrument_token=instrument_token,
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


# ==================================================================
# FLAT → LONG (OPEN)
# ==================================================================

class TestFlatToLong:
    def test_buy_opens_long(self):
        pos = _empty_position()
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.BUY, 100, Decimal("150"),
        )
        assert pnl == Decimal("0")
        assert impact == "OPEN"
        assert new_pos.is_long
        assert new_pos.net_quantity == 100
        assert new_pos.average_buy_price == Decimal("150")
        assert new_pos.total_buy_value == Decimal("15000")


# ==================================================================
# LONG → LONG (ADD)
# ==================================================================

class TestLongToLong:
    def test_buy_adds_to_long(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.BUY, 50, Decimal("160"),
        )
        assert pnl == Decimal("0")
        assert impact == "ADD"
        assert new_pos.net_quantity == 150
        # Weighted average: (100*150 + 50*160) / 150 = 23000/150 = 153.333...
        assert new_pos.average_buy_price == Decimal("23000") / Decimal("150")
        # Verify it equals 153.333... (repeating decimal handled by Decimal)


# ==================================================================
# LONG → FLAT (CLOSE)
# ==================================================================

class TestLongToFlat:
    def test_sell_closes_long(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.SELL, 100, Decimal("160"),
        )
        assert pnl == Decimal("1000")  # (160 - 150) * 100
        assert impact == "CLOSE"
        assert new_pos.is_flat
        assert new_pos.net_quantity == 0


# ==================================================================
# LONG → SHORT (REVERSE)
# ==================================================================

class TestLongToShort:
    def test_oversell_reverses_to_short(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.SELL, 150, Decimal("160"),
        )
        # Close 100 at profit 10 each = 1000, then open short 50 at 160
        assert pnl == Decimal("1000")
        assert impact == "REVERSE"
        assert new_pos.is_short
        assert new_pos.net_quantity == -50
        assert new_pos.average_sell_price == Decimal("160")


# ==================================================================
# FLAT → SHORT (OPEN)
# ==================================================================

class TestFlatToShort:
    def test_sell_opens_short(self):
        pos = _empty_position()
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.SELL, 50, Decimal("200"),
        )
        assert pnl == Decimal("0")
        assert impact == "OPEN"
        assert new_pos.is_short
        assert new_pos.net_quantity == -50
        assert new_pos.average_sell_price == Decimal("200")


# ==================================================================
# SHORT → SHORT (ADD)
# ==================================================================

class TestShortToShort:
    def test_sell_adds_to_short(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.SELL, 50, Decimal("210"),
        )
        assert pnl == Decimal("0")
        assert impact == "ADD"
        assert new_pos.net_quantity == -100
        # Weighted average: (50*200 + 50*210) / 100 = 205
        assert new_pos.average_sell_price == Decimal("205")


# ==================================================================
# SHORT → FLAT (CLOSE)
# ==================================================================

class TestShortToFlat:
    def test_buy_closes_short(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.BUY, 50, Decimal("190"),
        )
        assert pnl == Decimal("500")  # (200 - 190) * 50
        assert impact == "CLOSE"
        assert new_pos.is_flat


# ==================================================================
# SHORT → LONG (REVERSE)
# ==================================================================

class TestShortToLong:
    def test_overbuy_reverses_to_long(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.BUY, 100, Decimal("190"),
        )
        # Close 50 short at profit 10 each = 500, then open long 50 at 190
        assert pnl == Decimal("500")
        assert impact == "REVERSE"
        assert new_pos.is_long
        assert new_pos.net_quantity == 50
        assert new_pos.average_buy_price == Decimal("190")


# ==================================================================
# Partial Exits
# ==================================================================

class TestPartialExits:
    def test_long_partial_reduce(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.SELL, 40, Decimal("160"),
        )
        assert pnl == Decimal("400")  # (160 - 150) * 40
        assert impact == "REDUCE"
        assert new_pos.is_long
        assert new_pos.net_quantity == 60
        assert new_pos.average_buy_price == Decimal("150")  # unchanged

    def test_short_partial_reduce(self):
        pos = PositionSnapshot(
            instrument_token=123456,
            net_quantity=-100,
            direction=PositionDirection.SHORT,
            average_buy_price=Decimal("0"),
            average_sell_price=Decimal("200"),
            total_buy_quantity=0,
            total_sell_quantity=100,
            total_buy_value=Decimal("0"),
            total_sell_value=Decimal("20000"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        pnl, new_pos, impact = PnLCalculator.compute_realized_pnl(
            pos, ExecutionOrderSide.BUY, 30, Decimal("190"),
        )
        assert pnl == Decimal("300")  # (200 - 190) * 30
        assert impact == "REDUCE"
        assert new_pos.is_short
        assert new_pos.net_quantity == -70


# ==================================================================
# Unrealized P&L
# ==================================================================

class TestUnrealizedPnL:
    def test_long_unrealized(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        unrealized = PnLCalculator.compute_unrealized_pnl(pos, Decimal("160"))
        assert unrealized == Decimal("1000")  # (160 - 150) * 100

    def test_short_unrealized(self):
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
            unrealized_pnl=Decimal("0"),
            market_price=None,
            market_timestamp=None,
        )
        unrealized = PnLCalculator.compute_unrealized_pnl(pos, Decimal("190"))
        assert unrealized == Decimal("500")  # (200 - 190) * 50

    def test_flat_unrealized_is_zero(self):
        pos = _empty_position()
        unrealized = PnLCalculator.compute_unrealized_pnl(pos, Decimal("100"))
        assert unrealized == Decimal("0")


# ==================================================================
# Edge Cases
# ==================================================================

class TestEdgeCases:
    def test_zero_quantity_raises(self):
        pos = _empty_position()
        with pytest.raises(ValueError, match="fill_quantity must be positive"):
            PnLCalculator.compute_realized_pnl(
                pos, ExecutionOrderSide.BUY, 0, Decimal("100"),
            )

    def test_zero_price_raises(self):
        pos = _empty_position()
        with pytest.raises(ValueError, match="fill_price must be positive"):
            PnLCalculator.compute_realized_pnl(
                pos, ExecutionOrderSide.BUY, 100, Decimal("0"),
            )
