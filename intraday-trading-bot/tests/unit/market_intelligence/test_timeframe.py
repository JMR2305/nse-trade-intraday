"""Unit tests for TimeframeAggregator."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from market_data.contracts import CompletedBar
from market_intelligence.timeframe import TimeframeAggregator


def make_bar(
    token: str,
    ts: datetime,
    open_p: str,
    high: str,
    low: str,
    close: str,
    vol: str = "1000",
) -> CompletedBar:
    return CompletedBar(
        instrument_token=token,
        timestamp=ts.isoformat(),
        open=Decimal(open_p),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(vol),
        interval="1m",
    )


class TestTimeframeAggregator5m:
    def test_empty_buffer_returns_none(self) -> None:
        agg = TimeframeAggregator("INFY", "5m")
        bar = make_bar("INFY", datetime(2026, 7, 23, 9, 15), "100", "101", "99", "100")
        result = agg.on_bar(bar)
        assert result is None

    def test_five_minutes_emits_aggregated_bar(self) -> None:
        agg = TimeframeAggregator("INFY", "5m")
        base = datetime(2026, 7, 23, 9, 15)
        results = []
        for i in range(5):
            bar = make_bar("INFY", base + timedelta(minutes=i), "100", "101", "99", str(100 + i))
            r = agg.on_bar(bar)
            if r:
                results.append(r)
        assert len(results) == 1
        assert results[0].open == Decimal("100")
        assert results[0].high == Decimal("101")
        assert results[0].low == Decimal("99")
        assert results[0].close == Decimal("104")
        assert results[0].volume == Decimal("5000")
        assert results[0].interval == "5m"

    def test_ohlcv_computed_correctly(self) -> None:
        agg = TimeframeAggregator("TCS", "5m")
        base = datetime(2026, 7, 23, 10, 0)
        bars = [
            make_bar("TCS", base, "200", "210", "195", "205", "1000"),
            make_bar("TCS", base + timedelta(minutes=1), "205", "215", "200", "210", "2000"),
            make_bar("TCS", base + timedelta(minutes=2), "210", "220", "205", "215", "1500"),
            make_bar("TCS", base + timedelta(minutes=3), "215", "218", "210", "212", "1200"),
            make_bar("TCS", base + timedelta(minutes=4), "212", "214", "208", "210", "800"),
        ]
        result = None
        for b in bars:
            result = agg.on_bar(b)
        assert result is not None
        assert result.open == Decimal("200")
        assert result.high == Decimal("220")
        assert result.low == Decimal("195")
        assert result.close == Decimal("210")
        assert result.volume == Decimal("6500")

    def test_session_boundary_emits_and_starts_new(self) -> None:
        agg = TimeframeAggregator("RELIANCE", "5m")
        bar1 = make_bar("RELIANCE", datetime(2026, 7, 23, 15, 28), "500", "505", "498", "502")
        bar2 = make_bar("RELIANCE", datetime(2026, 7, 23, 15, 29), "502", "503", "499", "501")
        bar3 = make_bar("RELIANCE", datetime(2026, 7, 24, 9, 15), "510", "515", "508", "512")

        agg.on_bar(bar1)
        r = agg.on_bar(bar2)
        assert r is None

        r2 = agg.on_bar(bar3)
        assert r2 is not None
        assert r2.close == Decimal("501")

    def test_15m_aggregation(self) -> None:
        agg = TimeframeAggregator("HDFC", "15m")
        base = datetime(2026, 7, 23, 9, 15)
        results = []
        for i in range(15):
            bar = make_bar("HDFC", base + timedelta(minutes=i), "300", "305", "295", str(300 + i), "100")
            r = agg.on_bar(bar)
            if r:
                results.append(r)
        assert len(results) == 1
        assert results[0].interval == "15m"
        assert results[0].volume == Decimal("1500")

    def test_1h_aggregation(self) -> None:
        agg = TimeframeAggregator("ITC", "1h")
        base = datetime(2026, 7, 23, 9, 15)
        results = []
        for i in range(60):
            bar = make_bar("ITC", base + timedelta(minutes=i), "400", "405", "395", str(400 + i % 10), "50")
            r = agg.on_bar(bar)
            if r:
                results.append(r)
        assert len(results) == 1
        assert results[0].interval == "1h"
        assert results[0].volume == Decimal("3000")

    def test_gap_handling(self) -> None:
        agg = TimeframeAggregator("WIPRO", "5m")
        base = datetime(2026, 7, 23, 9, 15)
        agg.on_bar(make_bar("WIPRO", base, "100", "101", "99", "100"))
        agg.on_bar(make_bar("WIPRO", base + timedelta(minutes=1), "100", "102", "98", "101"))
        agg.on_bar(make_bar("WIPRO", base + timedelta(minutes=2), "101", "103", "100", "102"))
        # Gap of 10 minutes — exceeds 5m interval
        r = agg.on_bar(make_bar("WIPRO", base + timedelta(minutes=12), "110", "112", "108", "111"))
        assert r is not None
        assert r.close == Decimal("102")

    def test_determinism(self) -> None:
        agg1 = TimeframeAggregator("INFY", "5m")
        agg2 = TimeframeAggregator("INFY", "5m")
        base = datetime(2026, 7, 23, 9, 15)
        results1, results2 = [], []
        for i in range(10):
            bar = make_bar("INFY", base + timedelta(minutes=i), "100", "101", "99", str(100 + i))
            r1 = agg1.on_bar(bar)
            r2 = agg2.on_bar(bar)
            if r1:
                results1.append(r1)
            if r2:
                results2.append(r2)
        assert len(results1) == len(results2)
        for a, b in zip(results1, results2):
            assert a.open == b.open
            assert a.high == b.high
            assert a.low == b.low
            assert a.close == b.close
            assert a.volume == b.volume

    def test_reset_clears_buffer(self) -> None:
        agg = TimeframeAggregator("INFY", "5m")
        base = datetime(2026, 7, 23, 9, 15)
        agg.on_bar(make_bar("INFY", base, "100", "101", "99", "100"))
        agg.reset()
        r = agg.on_bar(make_bar("INFY", base + timedelta(days=1), "110", "111", "109", "110"))
        assert r is None

    def test_token_mismatch_returns_none(self) -> None:
        agg = TimeframeAggregator("INFY", "5m")
        bar = make_bar("TCS", datetime(2026, 7, 23, 9, 15), "100", "101", "99", "100")
        result = agg.on_bar(bar)
        assert result is None

    def test_invalid_interval_raises(self) -> None:
        with pytest.raises(ValueError):
            TimeframeAggregator("INFY", "3m")
