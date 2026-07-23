"""Integration tests: TimeframeAggregator pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from market_data.contracts import CompletedBar
from market_intelligence.timeframe import TimeframeAggregator


def make_bar(token: str, ts: datetime, close: str) -> CompletedBar:
    return CompletedBar(
        instrument_token=token,
        timestamp=ts.isoformat(),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("1000"),
        interval="1m",
    )


class TestTimeframePipeline:
    def test_75_bars_produce_15_five_minute_bars(self) -> None:
        agg = TimeframeAggregator("INFY", "5m")
        base = datetime(2026, 7, 23, 9, 15)
        emitted = []
        for i in range(75):
            bar = make_bar("INFY", base + timedelta(minutes=i), str(100 + i))
            r = agg.on_bar(bar)
            if r:
                emitted.append(r)
        assert len(emitted) == 15
        for e in emitted:
            assert e.interval == "5m"
            assert e.volume == Decimal("5000")

    def test_pipeline_determinism(self) -> None:
        agg1 = TimeframeAggregator("INFY", "5m")
        agg2 = TimeframeAggregator("INFY", "5m")
        base = datetime(2026, 7, 23, 9, 15)
        for i in range(20):
            bar = make_bar("INFY", base + timedelta(minutes=i), str(100 + i))
            r1 = agg1.on_bar(bar)
            r2 = agg2.on_bar(bar)
            if r1 and r2:
                assert r1.open == r2.open
                assert r1.close == r2.close
                assert r1.volume == r2.volume
