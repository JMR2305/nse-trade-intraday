"""Tests for tick-to-bar aggregation.

All tests use deterministic timestamps.  No system-clock dependency.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.market_data.bar_builder import BarBuilder
from src.market_data.contracts import Tick

# Asia/Kolkata for NSE session tests
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")


def make_tick(
    token: int = 123,
    hour: int = 9,
    minute: int = 15,
    second: int = 0,
    price: str = "100.00",
    volume: int = 1000,
    last_qty: int = 10,
) -> Tick:
    """Helper to create ticks within the NSE session."""
    ts = datetime(2026, 7, 20, hour, minute, second, tzinfo=IST)
    return Tick(
        instrument_token=token,
        exchange_timestamp=ts,
        received_at=ts.astimezone(timezone.utc),
        last_price=Decimal(price),
        last_quantity=last_qty,
        cumulative_volume=volume,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
    )


class TestBarBuilder:
    @pytest.fixture
    def builder(self):
        return BarBuilder()

    def test_first_bar_at_session_open(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        builder.process(tick)
        assert len(bars) == 0  # bar is still open
        current = builder.current_bar(123)
        assert current is not None
        assert current.timestamp.minute == 15
        assert current.open == Decimal("100.00")

    def test_bar_rollover_at_next_minute(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick1 = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        tick2 = make_tick(hour=9, minute=16, second=0, price="101.00", volume=200)
        builder.process(tick1)
        builder.process(tick2)
        assert len(bars) == 1
        bar = bars[0]
        assert bar.timestamp.minute == 15
        assert bar.close == Decimal("100.00")
        assert bar.volume == 100
        current = builder.current_bar(123)
        assert current.timestamp.minute == 16
        assert current.open == Decimal("101.00")

    def test_session_close_flush(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick = make_tick(hour=15, minute=30, second=0, price="100.00", volume=100)
        builder.process(tick)
        builder.flush_session_close(123)
        assert len(bars) == 1
        assert bars[0].timestamp.minute == 30

    def test_volume_delta_calculation(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick1 = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        tick2 = make_tick(hour=9, minute=15, second=30, price="101.00", volume=250)
        tick3 = make_tick(hour=9, minute=16, second=0, price="102.00", volume=250)
        builder.process(tick1)
        builder.process(tick2)
        builder.process(tick3)
        assert len(bars) == 1
        # First bar of session: cumvol goes 0→100→250. Bar volume = 250 (all shares traded).
        assert bars[0].volume == 250

    def test_volume_reset_on_new_day(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick1 = make_tick(hour=9, minute=15, second=0, price="100.00", volume=500)
        # Simulate a reset: cumulative volume drops
        tick2 = make_tick(hour=9, minute=16, second=0, price="101.00", volume=50)
        builder.process(tick1)
        builder.process(tick2)
        assert len(bars) == 1
        # Reset detected: use cumulative directly = 50
        assert bars[0].volume == 500  # first bar uses cumulative directly
        current = builder.current_bar(123)
        assert current.volume == 50  # new bar uses reset value

    def test_duplicate_tick_ignored(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        builder.process(tick)
        builder.process(tick)  # exact duplicate
        builder.process(make_tick(hour=9, minute=16, second=0, price="101.00", volume=200))
        assert len(bars) == 1
        assert bars[0].volume == 100  # not doubled

    def test_out_of_order_tick_classified(self, builder):
        ooo_ticks = []
        builder.on_out_of_order(lambda t: ooo_ticks.append(t))
        tick1 = make_tick(hour=9, minute=16, second=0, price="101.00", volume=200)
        tick2 = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        builder.process(tick1)
        builder.process(tick2)
        assert len(ooo_ticks) == 1
        assert ooo_ticks[0].exchange_timestamp.minute == 15

    def test_gap_emitted_for_missing_minute(self, builder):
        bars = []
        gaps = []
        builder.on_bar(lambda b: bars.append(b))
        builder.on_gap(lambda g: gaps.append(g))
        tick1 = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        tick2 = make_tick(hour=9, minute=17, second=0, price="102.00", volume=300)
        builder.process(tick1)
        builder.process(tick2)
        assert len(bars) == 1
        assert len(gaps) == 1
        assert gaps[0].start.minute == 16
        assert gaps[0].end.minute == 17

    def test_ohlc_updates_within_minute(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick1 = make_tick(hour=9, minute=15, second=0, price="100.00", volume=100)
        tick2 = make_tick(hour=9, minute=15, second=30, price="105.00", volume=200)
        tick3 = make_tick(hour=9, minute=15, second=45, price="98.00", volume=300)
        tick4 = make_tick(hour=9, minute=16, second=0, price="102.00", volume=300)
        builder.process(tick1)
        builder.process(tick2)
        builder.process(tick3)
        builder.process(tick4)
        assert len(bars) == 1
        bar = bars[0]
        assert bar.open == Decimal("100.00")
        assert bar.high == Decimal("105.00")
        assert bar.low == Decimal("98.00")
        assert bar.close == Decimal("98.00")

    def test_tick_outside_session_rejected(self, builder):
        oos_ticks = []
        builder.on_out_of_session(lambda t: oos_ticks.append(t))
        tick = make_tick(hour=8, minute=30, second=0, price="100.00", volume=100)
        builder.process(tick)
        assert len(oos_ticks) == 1
        assert builder.current_bar(123) is None

    def test_weekend_tick_rejected(self, builder):
        oos_ticks = []
        builder.on_out_of_session(lambda t: oos_ticks.append(t))
        # Saturday, July 18 2026
        ts = datetime(2026, 7, 18, 10, 0, 0, tzinfo=IST)
        tick = Tick(
            instrument_token=123,
            exchange_timestamp=ts,
            received_at=ts.astimezone(timezone.utc),
            last_price=Decimal("100"),
            last_quantity=1,
            cumulative_volume=1,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
        builder.process(tick)
        assert len(oos_ticks) == 1

    def test_multiple_instruments_isolated(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        tick_a = make_tick(token=111, hour=9, minute=15, price="100.00", volume=100)
        tick_b = make_tick(token=222, hour=9, minute=15, price="200.00", volume=50)
        builder.process(tick_a)
        builder.process(tick_b)
        assert builder.current_bar(111).open == Decimal("100.00")
        assert builder.current_bar(222).open == Decimal("200.00")

    def test_flush_all_instruments(self, builder):
        bars = []
        builder.on_bar(lambda b: bars.append(b))
        builder.process(make_tick(token=111, hour=9, minute=15, price="100.00", volume=100))
        builder.process(make_tick(token=222, hour=9, minute=15, price="200.00", volume=50))
        builder.flush_session_close()
        assert len(bars) == 2
