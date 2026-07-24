from __future__ import annotations

from decimal import Decimal
from datetime import datetime
import datetime as dt

import pytest

from ai_forecast.volatility import VolatilityForecast, VolatilityForecaster
from market_data.contracts import CompletedBar


def make_bars(count: int, start_price: Decimal = Decimal("100"), volatility: Decimal = Decimal("1")) -> list:
    bars = []
    base = datetime(2026, 7, 24, 9, 15)
    price = start_price
    for i in range(count):
        o = price
        c = price + (Decimal(str(i % 3 - 1)) * volatility)
        h = max(o, c) + volatility
        l = min(o, c) - volatility
        bars.append(CompletedBar(
            instrument_token="INFY",
            timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=Decimal("1000"),
            interval="1m",
        ))
        price = c
    return bars


class TestVolatilityForecaster:
    def test_forecast_returns_result(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(30)
        result = forecaster.forecast("INFY", bars)
        assert isinstance(result, VolatilityForecast)
        assert result.instrument_token == "INFY"
        assert result.forecast_window == "15m"

    def test_expected_range_positive(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(30)
        result = forecaster.forecast("INFY", bars)
        assert result.expected_range > Decimal("0")

    def test_expected_range_pct(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(30)
        result = forecaster.forecast("INFY", bars)
        assert result.expected_range_pct >= Decimal("0")

    def test_confidence_in_range(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(30)
        result = forecaster.forecast("INFY", bars)
        assert Decimal("0") <= result.confidence <= Decimal("1")

    def test_empty_bars_fallback(self) -> None:
        forecaster = VolatilityForecaster()
        result = forecaster.forecast("INFY", [])
        assert result.expected_range > Decimal("0")
        assert result.confidence == Decimal("0.3")

    def test_insufficient_data_uses_std(self) -> None:
        """With fewer bars than ATR period but >= 2, STD path is used (confidence 0.5)."""
        forecaster = VolatilityForecaster()
        bars = make_bars(10)
        result = forecaster.forecast("INFY", bars)
        assert result.confidence == Decimal("0.5")

    def test_update_adds_bar(self) -> None:
        forecaster = VolatilityForecaster()
        bar = make_bars(1)[0]
        forecaster.update(bar)
        assert len(forecaster.get_buffer("INFY")) == 1

    def test_buffer_bounded(self) -> None:
        forecaster = VolatilityForecaster()
        for i in range(60):
            bar = make_bars(1, start_price=Decimal(str(100 + i)))[0]
            forecaster.update(bar)
        assert len(forecaster.get_buffer("INFY")) == 50

    def test_custom_window(self) -> None:
        forecaster = VolatilityForecaster(default_window="1h")
        bars = make_bars(30)
        result = forecaster.forecast("INFY", bars, window="1h")
        assert result.forecast_window == "1h"

    def test_determinism(self) -> None:
        forecaster1 = VolatilityForecaster()
        forecaster2 = VolatilityForecaster()
        bars = make_bars(30)
        r1 = forecaster1.forecast("INFY", bars)
        r2 = forecaster2.forecast("INFY", bars)
        assert r1.expected_range == r2.expected_range
        assert r1.confidence == r2.confidence
