"""Unit tests for PositionManager (position_manager.py).

Covers:
  - open_position: creates lot, correct average_entry_price
  - open_position: duplicate open instrument (non-closed) → InvalidPositionTransitionError
  - increase_position: weighted average recalculation
  - reduce_position: FIFO P&L correct (long close: sell > buy → profit)
  - reduce_position: partial (status=REDUCING)
  - reduce_position: full (status=CLOSED)
  - reduce_position: overshoot → InvalidPositionTransitionError
  - close_position via reduce_position: sets closed_at
  - update_unrealised_pnl: LONG profit when price rises
  - update_unrealised_pnl: SHORT profit when price falls
  - duplicate fill_id → is_fill_duplicate returns True
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.portfolio.contracts import PositionSide, PositionStatus
from src.portfolio.exceptions import InvalidPositionTransitionError
from src.portfolio.position_manager import PositionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)
_TOKEN = 738561
_SYMBOL = "RELIANCE"


def _pm() -> PositionManager:
    return PositionManager()


def _open_long(pm: PositionManager, qty: int = 10, price: Decimal = Decimal("2500")) -> None:
    pm.open_position(
        instrument_token=_TOKEN,
        instrument_symbol=_SYMBOL,
        side=PositionSide.LONG,
        quantity=qty,
        price=price,
        fill_id="fill-001",
        filled_at=_NOW,
    )


# ===========================================================================
# open_position
# ===========================================================================

class TestOpenPosition:
    def test_open_creates_position(self):
        """open_position creates a position with correct fields."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-001",
            filled_at=_NOW,
        )
        assert pos.instrument_token == _TOKEN
        assert pos.instrument_symbol == _SYMBOL
        assert pos.side == PositionSide.LONG
        assert pos.open_quantity == 10
        assert pos.status == PositionStatus.OPEN

    def test_open_creates_one_lot(self):
        """open_position creates exactly one lot."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("100"),
            fill_id="fill-a",
            filled_at=_NOW,
        )
        assert len(pos.lots) == 1
        assert pos.lots[0].fill_id == "fill-a"
        assert pos.lots[0].quantity == 5

    def test_open_average_entry_price(self):
        """average_entry_price equals the fill price after open_position."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-001",
            filled_at=_NOW,
        )
        assert pos.average_entry_price == Decimal("2500.0000")

    def test_open_invalid_quantity_raises(self):
        """open_position with qty <= 0 → InvalidPositionTransitionError."""
        pm = _pm()
        with pytest.raises(InvalidPositionTransitionError):
            pm.open_position(
                instrument_token=_TOKEN,
                instrument_symbol=_SYMBOL,
                side=PositionSide.LONG,
                quantity=0,
                price=Decimal("2500"),
                fill_id="fill-001",
                filled_at=_NOW,
            )

    def test_open_short(self):
        """Can open a SHORT position."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-s01",
            filled_at=_NOW,
        )
        assert pos.side == PositionSide.SHORT
        assert pos.open_quantity == 10

    def test_fill_id_registered_in_lot(self):
        """fill_id is stored in the lot after open_position."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-001",
            filled_at=_NOW,
        )
        assert pm.is_fill_duplicate(pos, "fill-001") is True

    def test_different_fill_not_duplicate(self):
        """A different fill_id is not a duplicate."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("2500"),
            fill_id="fill-001",
            filled_at=_NOW,
        )
        assert pm.is_fill_duplicate(pos, "fill-999") is False


# ===========================================================================
# increase_position
# ===========================================================================

class TestIncreasePosition:
    def test_increase_weighted_average(self):
        """Weighted average entry price recalculated correctly after increase."""
        pm = _pm()
        _open_long(pm, qty=100, price=Decimal("100"))
        pos = pm.increase_position(
            instrument_token=_TOKEN,
            quantity=100,
            price=Decimal("120"),
            fill_id="fill-002",
            filled_at=_NOW,
        )
        # avg = (100*100 + 100*120) / 200 = 110
        assert pos.average_entry_price == Decimal("110.0000")
        assert pos.open_quantity == 200

    def test_increase_adds_lot(self):
        """increase_position appends a new lot."""
        pm = _pm()
        _open_long(pm, qty=10)
        pos = pm.increase_position(
            instrument_token=_TOKEN,
            quantity=5,
            price=Decimal("2600"),
            fill_id="fill-002",
            filled_at=_NOW,
        )
        assert len(pos.lots) == 2

    def test_increase_no_open_position_raises(self):
        """increase_position on missing position → InvalidPositionTransitionError."""
        pm = _pm()
        with pytest.raises(InvalidPositionTransitionError):
            pm.increase_position(
                instrument_token=99999,
                quantity=5,
                price=Decimal("100"),
                fill_id="fill-x",
                filled_at=_NOW,
            )

    def test_increase_fees_accumulated(self):
        """Fees are accumulated across open and increase."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-a",
            filled_at=_NOW,
            fees=Decimal("20"),
        )
        pos = pm.increase_position(
            instrument_token=_TOKEN,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-b",
            filled_at=_NOW,
            fees=Decimal("20"),
        )
        assert pos.total_fees == Decimal("40.00")

    def test_increase_duplicate_fill_id_raises(self):
        """increase_position with duplicate fill_id → InvalidPositionTransitionError."""
        pm = _pm()
        _open_long(pm)
        with pytest.raises(InvalidPositionTransitionError):
            pm.increase_position(
                instrument_token=_TOKEN,
                quantity=5,
                price=Decimal("2600"),
                fill_id="fill-001",  # same as open fill
                filled_at=_NOW,
            )


# ===========================================================================
# reduce_position
# ===========================================================================

class TestReducePosition:
    def test_full_close_profit(self):
        """FIFO P&L: long close at higher price → profit."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=100,
            price=Decimal("100"),
            fill_id="fill-open",
            filled_at=_NOW,
        )
        pos, pnl = pm.reduce_position(
            instrument_token=_TOKEN,
            quantity=100,
            price=Decimal("110"),
            fill_id="fill-close",
            filled_at=_NOW,
        )
        assert pnl == Decimal("1000.00")  # (110-100)*100
        assert pos.status == PositionStatus.CLOSED
        assert pos.open_quantity == 0

    def test_partial_close_status_reducing(self):
        """Partial reduce → status=REDUCING."""
        pm = _pm()
        _open_long(pm, qty=100, price=Decimal("100"))
        pos, _ = pm.reduce_position(
            instrument_token=_TOKEN,
            quantity=50,
            price=Decimal("110"),
            fill_id="fill-partial",
            filled_at=_NOW,
        )
        assert pos.status == PositionStatus.REDUCING
        assert pos.open_quantity == 50

    def test_full_close_status_closed(self):
        """Full reduce → status=CLOSED."""
        pm = _pm()
        _open_long(pm, qty=10)
        pos, _ = pm.reduce_position(
            instrument_token=_TOKEN,
            quantity=10,
            price=Decimal("2600"),
            fill_id="fill-close",
            filled_at=_NOW,
        )
        assert pos.status == PositionStatus.CLOSED

    def test_overshoot_raises(self):
        """Reducing more than open_quantity → InvalidPositionTransitionError."""
        pm = _pm()
        _open_long(pm, qty=10)
        with pytest.raises(InvalidPositionTransitionError):
            pm.reduce_position(
                instrument_token=_TOKEN,
                quantity=15,
                price=Decimal("2600"),
                fill_id="fill-over",
                filled_at=_NOW,
            )

    def test_loss_close(self):
        """Close at lower price → negative P&L (loss)."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=100,
            price=Decimal("100"),
            fill_id="fill-open",
            filled_at=_NOW,
        )
        _, pnl = pm.reduce_position(
            instrument_token=_TOKEN,
            quantity=100,
            price=Decimal("90"),
            fill_id="fill-loss",
            filled_at=_NOW,
        )
        assert pnl == Decimal("-1000.00")  # (90-100)*100

    def test_fifo_multi_lot(self):
        """FIFO: oldest lot consumed first when reducing."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-1",
            filled_at=_NOW,
        )
        pm.increase_position(
            instrument_token=_TOKEN,
            quantity=10,
            price=Decimal("200"),
            fill_id="fill-2",
            filled_at=_NOW,
        )
        # Close 10 shares — should consume the first lot (price=100)
        _, pnl = pm.reduce_position(
            instrument_token=_TOKEN,
            quantity=10,
            price=Decimal("150"),
            fill_id="fill-close",
            filled_at=_NOW,
        )
        # P&L = (150 - 100) * 10 = 500
        assert pnl == Decimal("500.00")

    def test_closed_at_set_on_full_close(self):
        """closed_at is set when position is fully closed."""
        pm = _pm()
        _open_long(pm, qty=10, price=Decimal("100"))
        pos, _ = pm.reduce_position(
            instrument_token=_TOKEN,
            quantity=10,
            price=Decimal("110"),
            fill_id="fill-close",
            filled_at=_NOW,
        )
        assert pos.closed_at == _NOW
        assert pos.status == PositionStatus.CLOSED


# ===========================================================================
# update_unrealised_pnl
# ===========================================================================

class TestUpdateUnrealisedPnl:
    def test_long_profit_when_price_rises(self):
        """LONG: unrealised P&L positive when price rises above entry."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-x",
            filled_at=_NOW,
        )
        pos = pm.update_unrealised_pnl(_TOKEN, Decimal("110"))
        assert pos.unrealised_pnl == Decimal("100.00")  # (110-100)*10

    def test_long_loss_when_price_falls(self):
        """LONG: unrealised P&L negative when price falls."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-x",
            filled_at=_NOW,
        )
        pos = pm.update_unrealised_pnl(_TOKEN, Decimal("90"))
        assert pos.unrealised_pnl == Decimal("-100.00")

    def test_short_profit_when_price_falls(self):
        """SHORT: unrealised P&L positive when price falls."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.SHORT,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-s",
            filled_at=_NOW,
        )
        pos = pm.update_unrealised_pnl(_TOKEN, Decimal("80"))
        assert pos.unrealised_pnl == Decimal("200.00")  # (100-80)*10

    def test_unrealised_pnl_updates_market_price(self):
        """update_unrealised_pnl stores last_market_price."""
        pm = _pm()
        pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=5,
            price=Decimal("100"),
            fill_id="fill-y",
            filled_at=_NOW,
        )
        pos = pm.update_unrealised_pnl(_TOKEN, Decimal("120"))
        assert pos.last_market_price == Decimal("120")

    def test_unknown_instrument_returns_none(self):
        """update_unrealised_pnl for unknown token returns None."""
        pm = _pm()
        result = pm.update_unrealised_pnl(99999, Decimal("100"))
        assert result is None


# ===========================================================================
# Fill deduplication
# ===========================================================================

class TestFillDeduplication:
    def test_fill_not_duplicate_for_new_id(self):
        """A new fill_id is not a duplicate."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-001",
            filled_at=_NOW,
        )
        assert pm.is_fill_duplicate(pos, "fill-new") is False

    def test_fill_duplicate_after_open(self):
        """fill_id is duplicate after open_position uses it."""
        pm = _pm()
        pos = pm.open_position(
            instrument_token=_TOKEN,
            instrument_symbol=_SYMBOL,
            side=PositionSide.LONG,
            quantity=10,
            price=Decimal("100"),
            fill_id="fill-001",
            filled_at=_NOW,
        )
        assert pm.is_fill_duplicate(pos, "fill-001") is True

    def test_fill_duplicate_after_increase(self):
        """fill_id from increase_position is tracked in lots."""
        pm = _pm()
        _open_long(pm)
        pos = pm.increase_position(
            instrument_token=_TOKEN,
            quantity=5,
            price=Decimal("2600"),
            fill_id="fill-002",
            filled_at=_NOW,
        )
        assert pm.is_fill_duplicate(pos, "fill-002") is True

    def test_position_count_after_open(self):
        """position_count returns 1 after one open."""
        pm = _pm()
        _open_long(pm)
        assert pm.position_count() == 1

    def test_all_open_positions_returns_list(self):
        """all_open_positions returns all tracked positions."""
        pm = _pm()
        _open_long(pm)
        positions = pm.all_open_positions()
        assert len(positions) == 1
        assert positions[0].instrument_symbol == _SYMBOL
