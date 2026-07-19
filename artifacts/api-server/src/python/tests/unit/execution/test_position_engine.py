"""Unit tests for the position engine.

Covers end-to-end integration: FillEvent → positions → P&L → portfolio.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.execution.contracts import ExecutionOrderSide
from src.execution.fills import FillEvent
from src.execution.position_engine import PositionEngine
from src.execution.portfolio import PositionDirection


# ==================================================================
# Helpers
# ==================================================================

def _make_fill(
    instrument_token: int = 123456,
    side: ExecutionOrderSide = ExecutionOrderSide.BUY,
    quantity: int = 100,
    price: Decimal = Decimal("150"),
    fill_id: str = "F-001",
    order_id: str | None = None,
    market_event_id: str = "evt-001",
) -> FillEvent:
    gross = Decimal(quantity) * price
    return FillEvent(
        fill_id=fill_id,
        order_id=uuid4() if order_id is None else uuid4(),
        client_order_id="test-001",
        instrument_token=instrument_token,
        side=side,
        quantity=quantity,
        price=price,
        gross_value=gross,
        market_event_id=market_event_id,
        market_timestamp=datetime(2026, 7, 20, 9, 15, 0, tzinfo=timezone.utc),
        cumulative_filled_quantity=quantity,
        remaining_quantity=0,
    )


@pytest.fixture
def engine() -> PositionEngine:
    return PositionEngine(initial_cash=Decimal("1000000"))


# ==================================================================
# Basic Fill Processing
# ==================================================================

class TestBasicFillProcessing:
    @pytest.mark.asyncio
    async def test_buy_opens_long_position(self, engine: PositionEngine):
        fill = _make_fill(side=ExecutionOrderSide.BUY, quantity=100, price=Decimal("150"))
        result = await engine.on_fill(fill)

        assert result.position_impact == "OPEN"
        assert result.realized_pnl == Decimal("0")
        assert result.new_position.is_long
        assert result.new_position.net_quantity == 100
        assert result.trade_recorded is True

        # Cash decreased by gross value
        assert engine.get_cash() == Decimal("1000000") - Decimal("15000")

    @pytest.mark.asyncio
    async def test_sell_opens_short_position(self, engine: PositionEngine):
        fill = _make_fill(side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200"))
        result = await engine.on_fill(fill)

        assert result.position_impact == "OPEN"
        assert result.realized_pnl == Decimal("0")
        assert result.new_position.is_short
        assert result.new_position.net_quantity == -50

        # Cash increased by gross value
        assert engine.get_cash() == Decimal("1000000") + Decimal("10000")


# ==================================================================
# Position Lifecycle
# ==================================================================

class TestPositionLifecycle:
    @pytest.mark.asyncio
    async def test_long_add(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", quantity=50, price=Decimal("160")))

        assert result.position_impact == "ADD"
        assert result.new_position.net_quantity == 150
        # Weighted avg: (100*150 + 50*160) / 150 = 153.33...
        expected_avg = Decimal("23000") / Decimal("150")
        assert result.new_position.average_buy_price == expected_avg

    @pytest.mark.asyncio
    async def test_long_close(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")))

        assert result.position_impact == "CLOSE"
        assert result.realized_pnl == Decimal("1000")  # (160 - 150) * 100
        assert result.new_position.is_flat

        # Position removed from internal dict
        assert engine.get_position(123456) is None

    @pytest.mark.asyncio
    async def test_long_partial_reduce(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=40, price=Decimal("160")))

        assert result.position_impact == "REDUCE"
        assert result.realized_pnl == Decimal("400")  # (160 - 150) * 40
        assert result.new_position.is_long
        assert result.new_position.net_quantity == 60

    @pytest.mark.asyncio
    async def test_long_reverse_to_short(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=150, price=Decimal("160")))

        assert result.position_impact == "REVERSE"
        assert result.realized_pnl == Decimal("1000")  # (160 - 150) * 100
        assert result.new_position.is_short
        assert result.new_position.net_quantity == -50
        assert result.new_position.average_sell_price == Decimal("160")

    @pytest.mark.asyncio
    async def test_short_add(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("210")))

        assert result.position_impact == "ADD"
        assert result.new_position.net_quantity == -100
        assert result.new_position.average_sell_price == Decimal("205")

    @pytest.mark.asyncio
    async def test_short_close(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.BUY, quantity=50, price=Decimal("190")))

        assert result.position_impact == "CLOSE"
        assert result.realized_pnl == Decimal("500")  # (200 - 190) * 50
        assert result.new_position.is_flat

    @pytest.mark.asyncio
    async def test_short_reverse_to_long(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200")))
        result = await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.BUY, quantity=100, price=Decimal("190")))

        assert result.position_impact == "REVERSE"
        assert result.realized_pnl == Decimal("500")  # (200 - 190) * 50
        assert result.new_position.is_long
        assert result.new_position.net_quantity == 50
        assert result.new_position.average_buy_price == Decimal("190")


# ==================================================================
# Portfolio Snapshot
# ==================================================================

class TestPortfolioSnapshot:
    @pytest.mark.asyncio
    async def test_empty_portfolio(self, engine: PositionEngine):
        snap = engine.snapshot()
        assert snap.cash == Decimal("1000000")
        assert snap.equity == Decimal("1000000")
        assert len(snap.positions) == 0
        assert snap.realized_pnl == Decimal("0")
        assert snap.unrealized_pnl == Decimal("0")
        assert snap.total_pnl == Decimal("0")
        assert snap.trade_count == 0

    @pytest.mark.asyncio
    async def test_portfolio_with_long_position(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))

        snap = engine.snapshot()
        assert snap.cash == Decimal("985000")  # 1M - 15K
        assert len(snap.positions) == 1
        assert snap.trade_count == 1
        assert snap.turnover == Decimal("15000")

    @pytest.mark.asyncio
    async def test_portfolio_after_close(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        await engine.on_fill(_make_fill(fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")))

        snap = engine.snapshot()
        assert snap.cash == Decimal("1001000")  # 1M + 1K profit
        assert len(snap.positions) == 0
        assert snap.realized_pnl == Decimal("1000")
        assert snap.total_pnl == Decimal("1000")


# ==================================================================
# Idempotency
# ==================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_fill_ignored(self, engine: PositionEngine):
        fill = _make_fill(fill_id="F-001", quantity=100, price=Decimal("150"))

        result1 = await engine.on_fill(fill)
        assert result1.position_impact == "OPEN"

        result2 = await engine.on_fill(fill)
        assert result2.position_impact == "DUPLICATE"
        assert result2.trade_recorded is False

        # Cash should not change on duplicate
        assert engine.get_cash() == Decimal("985000")

        # Only one trade recorded
        assert engine.get_trade_ledger().trade_count == 1

    @pytest.mark.asyncio
    async def test_multiple_instruments_independent(self, engine: PositionEngine):
        fill1 = _make_fill(fill_id="F-001", instrument_token=123456, quantity=100, price=Decimal("150"))
        fill2 = _make_fill(fill_id="F-002", instrument_token=789012, side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200"))

        await engine.on_fill(fill1)
        await engine.on_fill(fill2)

        pos1 = engine.get_position(123456)
        pos2 = engine.get_position(789012)

        assert pos1 is not None
        assert pos1.net_quantity == 100
        assert pos2 is not None
        assert pos2.net_quantity == -50


# ==================================================================
# Concurrency
# ==================================================================

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_fills_same_instrument(self, engine: PositionEngine):
        fill1 = _make_fill(fill_id="F-001", quantity=50, price=Decimal("150"))
        fill2 = _make_fill(fill_id="F-002", quantity=50, price=Decimal("151"))

        results = await asyncio.gather(
            engine.on_fill(fill1),
            engine.on_fill(fill2),
        )

        # Both should succeed (first OPEN, second ADD — order may vary due to async)
        impacts = [r.position_impact for r in results]
        assert all(i in ("OPEN", "ADD") for i in impacts)
        assert "OPEN" in impacts  # at least one must be OPEN

        # Total position should be 100
        pos = engine.get_position(123456)
        assert pos is not None
        assert pos.net_quantity == 100

    @pytest.mark.asyncio
    async def test_concurrent_fills_different_instruments(self, engine: PositionEngine):
        fill1 = _make_fill(fill_id="F-001", instrument_token=123456, quantity=100, price=Decimal("150"))
        fill2 = _make_fill(fill_id="F-002", instrument_token=789012, side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200"))

        results = await asyncio.gather(
            engine.on_fill(fill1),
            engine.on_fill(fill2),
        )

        assert results[0].position_impact == "OPEN"
        assert results[1].position_impact == "OPEN"

        assert engine.get_position(123456).net_quantity == 100
        assert engine.get_position(789012).net_quantity == -50


# ==================================================================
# Market Price Update
# ==================================================================

class TestMarketPriceUpdate:
    @pytest.mark.asyncio
    async def test_unrealized_pnl_update(self, engine: PositionEngine):
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))

        updated = await engine.update_market_price(
            instrument_token=123456,
            market_price=Decimal("160"),
            market_timestamp=datetime(2026, 7, 20, 9, 20, 0, tzinfo=timezone.utc),
        )

        assert updated is not None
        assert updated.unrealized_pnl == Decimal("1000")  # (160 - 150) * 100

        snap = engine.snapshot()
        assert snap.unrealized_pnl == Decimal("1000")
        assert snap.total_pnl == Decimal("1000")  # only unrealized so far

    @pytest.mark.asyncio
    async def test_no_position_no_update(self, engine: PositionEngine):
        updated = await engine.update_market_price(
            instrument_token=123456,
            market_price=Decimal("160"),
            market_timestamp=datetime(2026, 7, 20, 9, 20, 0, tzinfo=timezone.utc),
        )
        assert updated is None


# ==================================================================
# Deterministic Replay
# ==================================================================

class TestDeterministicReplay:
    @pytest.mark.asyncio
    async def test_same_fills_same_state(self):
        engine1 = PositionEngine(initial_cash=Decimal("1000000"))
        engine2 = PositionEngine(initial_cash=Decimal("1000000"))

        fills = [
            _make_fill(fill_id="F-001", quantity=100, price=Decimal("150")),
            _make_fill(fill_id="F-002", quantity=50, price=Decimal("160")),
            _make_fill(fill_id="F-003", side=ExecutionOrderSide.SELL, quantity=80, price=Decimal("155")),
        ]

        for fill in fills:
            await engine1.on_fill(fill)
            await engine2.on_fill(fill)

        snap1 = engine1.snapshot()
        snap2 = engine2.snapshot()

        assert snap1.cash == snap2.cash
        assert snap1.realized_pnl == snap2.realized_pnl
        assert len(snap1.positions) == len(snap2.positions)

        if len(snap1.positions) > 0:
            assert snap1.positions[0].net_quantity == snap2.positions[0].net_quantity
            assert snap1.positions[0].average_buy_price == snap2.positions[0].average_buy_price

    @pytest.mark.asyncio
    async def test_reset_and_replay(self, engine: PositionEngine):
        fill = _make_fill(fill_id="F-001", quantity=100, price=Decimal("150"))
        await engine.on_fill(fill)

        assert engine.get_position(123456) is not None
        assert engine.get_trade_ledger().trade_count == 1

        engine.reset()

        assert engine.get_position(123456) is None
        assert engine.get_trade_ledger().trade_count == 0
        assert engine.get_cash() == Decimal("1000000")

        # Replay same fill
        await engine.on_fill(fill)
        assert engine.get_position(123456).net_quantity == 100
        assert engine.get_trade_ledger().trade_count == 1


# ==================================================================
# Regression: Cumulative Realized P&L
# ==================================================================

class TestCumulativeRealizedPnLRegression:
    """Regression tests for the cumulative realized P&L bug (BATCH 7CA).

    Before the fix, cumulative_realized_pnl on trades and portfolio
    snapshots was incorrect after a position was completely closed,
    because the closed position was removed from the internal positions
    dict before the cumulative P&L was computed.
    """

    @pytest.mark.asyncio
    async def test_long_partial_exit_accumulates_realized_pnl(self, engine: PositionEngine):
        """Partial close of a LONG position must accumulate realized P&L correctly."""
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=40, price=Decimal("160")
        ))

        # Realized on this trade: (160 - 150) * 40 = 400
        assert result.realized_pnl == Decimal("400")
        # Cumulative on trade must equal 400
        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert trade is not None
        assert trade.cumulative_realized_pnl == Decimal("400")

        # Portfolio snapshot must show 400 realized
        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("400")

    @pytest.mark.asyncio
    async def test_long_full_exit_preserves_realized_pnl(self, engine: PositionEngine):
        """Complete close of a LONG position must preserve accumulated realized P&L."""
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")
        ))

        # Realized on this trade: (160 - 150) * 100 = 1000
        assert result.realized_pnl == Decimal("1000")
        assert result.new_position.is_flat

        # Cumulative on trade must equal 1000
        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert trade is not None
        assert trade.cumulative_realized_pnl == Decimal("1000")

        # Portfolio snapshot must still show 1000 realized after position removal
        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("1000")
        assert len(snap.positions) == 0  # position was removed

    @pytest.mark.asyncio
    async def test_short_partial_exit_accumulates_realized_pnl(self, engine: PositionEngine):
        """Partial close of a SHORT position must accumulate realized P&L correctly."""
        await engine.on_fill(_make_fill(fill_id="F-001", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.BUY, quantity=40, price=Decimal("150")
        ))

        # Realized on this trade: (160 - 150) * 40 = 400
        assert result.realized_pnl == Decimal("400")

        # Cumulative on trade must equal 400
        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert trade is not None
        assert trade.cumulative_realized_pnl == Decimal("400")

        # Portfolio snapshot must show 400 realized
        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("400")

    @pytest.mark.asyncio
    async def test_short_full_exit_preserves_realized_pnl(self, engine: PositionEngine):
        """Complete close of a SHORT position must preserve accumulated realized P&L."""
        await engine.on_fill(_make_fill(fill_id="F-001", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.BUY, quantity=100, price=Decimal("150")
        ))

        # Realized on this trade: (160 - 150) * 100 = 1000
        assert result.realized_pnl == Decimal("1000")
        assert result.new_position.is_flat

        # Cumulative on trade must equal 1000
        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert trade is not None
        assert trade.cumulative_realized_pnl == Decimal("1000")

        # Portfolio snapshot must still show 1000 realized after position removal
        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("1000")
        assert len(snap.positions) == 0  # position was removed

    @pytest.mark.asyncio
    async def test_multiple_sequential_closes_accumulate(self, engine: PositionEngine):
        """Multiple sequential partial closes must accumulate realized P&L correctly."""
        # Open long 100 @ 150
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))

        # Close 30 @ 160 → realized 300
        await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=30, price=Decimal("160")
        ))

        # Close 40 @ 165 → realized 600
        await engine.on_fill(_make_fill(
            fill_id="F-003", side=ExecutionOrderSide.SELL, quantity=40, price=Decimal("165")
        ))

        # Close remaining 30 @ 170 → realized 600
        await engine.on_fill(_make_fill(
            fill_id="F-004", side=ExecutionOrderSide.SELL, quantity=30, price=Decimal("170")
        ))

        # Total realized: 300 + 600 + 600 = 1500
        ledger = engine.get_trade_ledger()
        trade2 = ledger.get_trade_by_fill_id("F-002")
        trade3 = ledger.get_trade_by_fill_id("F-003")
        trade4 = ledger.get_trade_by_fill_id("F-004")

        assert trade2.cumulative_realized_pnl == Decimal("300")
        assert trade3.cumulative_realized_pnl == Decimal("900")   # 300 + 600
        assert trade4.cumulative_realized_pnl == Decimal("1500")  # 300 + 600 + 600

        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("1500")
        assert len(snap.positions) == 0

    @pytest.mark.asyncio
    async def test_reopen_after_flat_preserves_historical_realized_pnl(self, engine: PositionEngine):
        """Reopening a position after complete close must not corrupt historical realized P&L."""
        # Trade 1: open long 100 @ 150
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))

        # Trade 2: close all @ 160 → realized 1000
        await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")
        ))

        # Trade 3: reopen long 50 @ 155 (new position)
        result3 = await engine.on_fill(_make_fill(fill_id="F-003", quantity=50, price=Decimal("155")))

        # The new open should have zero realized P&L
        assert result3.position_impact == "OPEN"
        assert result3.realized_pnl == Decimal("0")

        # Historical cumulative must still be 1000
        ledger = engine.get_trade_ledger()
        trade3 = ledger.get_trade_by_fill_id("F-003")
        assert trade3.cumulative_realized_pnl == Decimal("1000")

        # Portfolio snapshot must show 1000 realized, new position has 0 realized
        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("1000")
        assert len(snap.positions) == 1
        assert snap.positions[0].realized_pnl == Decimal("0")  # new position
        assert snap.positions[0].net_quantity == 50

    @pytest.mark.asyncio
    async def test_reopen_and_close_again_accumulates(self, engine: PositionEngine):
        """Close, reopen, close again — cumulative must keep growing."""
        # Round 1: open 100 @ 150, close @ 160 → +1000
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160")
        ))

        # Round 2: reopen 50 @ 155, close @ 165 → +500
        await engine.on_fill(_make_fill(fill_id="F-003", quantity=50, price=Decimal("155")))
        await engine.on_fill(_make_fill(
            fill_id="F-004", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("165")
        ))

        # Total realized: 1000 + 500 = 1500
        ledger = engine.get_trade_ledger()
        trade2 = ledger.get_trade_by_fill_id("F-002")
        trade4 = ledger.get_trade_by_fill_id("F-004")

        assert trade2.cumulative_realized_pnl == Decimal("1000")
        assert trade4.cumulative_realized_pnl == Decimal("1500")

        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("1500")
        assert len(snap.positions) == 0

    @pytest.mark.asyncio
    async def test_cumulative_does_not_affect_unrealized_pnl(self, engine: PositionEngine):
        """Realized P&L accumulation must not corrupt unrealized P&L."""
        # Open long 100 @ 150
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))

        # Partial close 50 @ 160 → realized 500, remaining position avg still 150
        await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("160")
        ))

        # Update market price to 170
        await engine.update_market_price(
            instrument_token=123456,
            market_price=Decimal("170"),
            market_timestamp=datetime(2026, 7, 20, 9, 20, 0, tzinfo=timezone.utc),
        )

        # Unrealized on remaining 50: (170 - 150) * 50 = 1000
        snap = engine.snapshot()
        assert snap.realized_pnl == Decimal("500")
        assert snap.unrealized_pnl == Decimal("1000")
        assert snap.total_pnl == Decimal("1500")

        # Average buy price of remaining position must still be 150
        pos = engine.get_position(123456)
        assert pos.average_buy_price == Decimal("150")

    @pytest.mark.asyncio
    async def test_decimal_arithmetic_preserved(self, engine: PositionEngine):
        """All P&L calculations must use Decimal, not float."""
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150.25")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=100, price=Decimal("160.50")
        ))

        # (160.50 - 150.25) * 100 = 10.25 * 100 = 1025.00
        assert result.realized_pnl == Decimal("1025.00")

        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert isinstance(trade.cumulative_realized_pnl, Decimal)
        assert trade.cumulative_realized_pnl == Decimal("1025.00")

        snap = engine.snapshot()
        assert isinstance(snap.realized_pnl, Decimal)
        assert snap.realized_pnl == Decimal("1025.00")


# ==================================================================
# Regression: Reversal Accounting (documented limitation)
# ==================================================================

class TestReversalAccountingLimitation:
    """Documented limitation: reversal accounting does not separately
    track realized P&L for the closed portion vs. the new reversed
    portion in a single atomic trade.

    This test captures current behaviour so any future change is
    explicitly detectable.
    """

    @pytest.mark.asyncio
    async def test_long_to_short_reversal_current_behaviour(self, engine: PositionEngine):
        """LONG 100 @ 150, then SELL 150 @ 160 (reversal).

        Current behaviour:
          - realized_pnl on trade = (160 - 150) * 100 = 1000  (closed portion)
          - cumulative_realized_pnl = 1000
          - new short position starts with realized_pnl = 0
          - average_sell_price = 160 (weighted avg of all 150 sell shares)
        """
        await engine.on_fill(_make_fill(fill_id="F-001", quantity=100, price=Decimal("150")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.SELL, quantity=150, price=Decimal("160")
        ))

        assert result.position_impact == "REVERSE"
        assert result.realized_pnl == Decimal("1000")

        # Trade cumulative must be 1000
        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert trade.cumulative_realized_pnl == Decimal("1000")

        # New short position has zero realized_pnl (documented limitation)
        assert result.new_position.is_short
        assert result.new_position.realized_pnl == Decimal("0")
        assert result.new_position.net_quantity == -50

        # Average sell price includes all 150 shares (closed + reversed)
        # (100 * 160 + 50 * 160) / 150 = 160
        assert result.new_position.average_sell_price == Decimal("160")

    @pytest.mark.asyncio
    async def test_short_to_long_reversal_current_behaviour(self, engine: PositionEngine):
        """SHORT 50 @ 200, then BUY 100 @ 190 (reversal).

        Current behaviour:
          - realized_pnl on trade = (200 - 190) * 50 = 500  (closed portion)
          - cumulative_realized_pnl = 500
          - new long position starts with realized_pnl = 0
          - average_buy_price = 190 (weighted avg of all 100 buy shares)
        """
        await engine.on_fill(_make_fill(fill_id="F-001", side=ExecutionOrderSide.SELL, quantity=50, price=Decimal("200")))
        result = await engine.on_fill(_make_fill(
            fill_id="F-002", side=ExecutionOrderSide.BUY, quantity=100, price=Decimal("190")
        ))

        assert result.position_impact == "REVERSE"
        assert result.realized_pnl == Decimal("500")

        # Trade cumulative must be 500
        ledger = engine.get_trade_ledger()
        trade = ledger.get_trade_by_fill_id("F-002")
        assert trade.cumulative_realized_pnl == Decimal("500")

        # New long position has zero realized_pnl (documented limitation)
        assert result.new_position.is_long
        assert result.new_position.realized_pnl == Decimal("0")
        assert result.new_position.net_quantity == 50

        # Average buy price includes all 100 shares (closed + reversed)
        # (50 * 190 + 50 * 190) / 100 = 190
        assert result.new_position.average_buy_price == Decimal("190")
