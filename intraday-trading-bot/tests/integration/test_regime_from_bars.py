"""Integration tests: Regime detection from real bar sequences."""
from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal

from market_data.contracts import CompletedBar
from market_intelligence.indicator_engine import IndicatorEngine
from market_intelligence.regime import MarketRegimeDetector
from market_intelligence.multi_timeframe_context import MarketRegime


def make_trending_bars(count: int, uptrend: bool = True, token: str = "INFY") -> list:
    bars = []
    base = datetime(2026, 7, 23, 9, 15)
    price = Decimal("100")
    for i in range(count):
        delta = Decimal("1") if uptrend else Decimal("-1")
        o = price
        c = price + delta
        h = max(o, c) + Decimal("0.5")
        lo = min(o, c) - Decimal("0.3")
        bars.append(CompletedBar(
            instrument_token=token,
            timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=Decimal("1000"),
            interval="1m",
        ))
        price = c
    return bars


class TestRegimeFromBars:
    def test_strong_uptrend_from_trending_bars(self) -> None:
        engine = IndicatorEngine(max_bars=50)
        for b in make_trending_bars(40, uptrend=True):
            engine.update(b, "1m")
        indicators = engine.get_indicators("INFY", "1m")
        result = MarketRegimeDetector().detect("INFY", indicators)
        assert result.regime in (MarketRegime.STRONG_UPTREND, MarketRegime.UPTREND)

    def test_downtrend_from_falling_bars(self) -> None:
        engine = IndicatorEngine(max_bars=50)
        for b in make_trending_bars(40, uptrend=False):
            engine.update(b, "1m")
        indicators = engine.get_indicators("INFY", "1m")
        result = MarketRegimeDetector().detect("INFY", indicators)
        assert result.regime in (MarketRegime.STRONG_DOWNTREND, MarketRegime.DOWNTREND)
