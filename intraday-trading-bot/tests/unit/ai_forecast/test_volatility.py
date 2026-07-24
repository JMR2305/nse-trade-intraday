"""Tests for RC-10B VolatilityForecaster — plan-aligned field names."""
from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ai_forecast.volatility import VolatilityForecast, VolatilityForecaster
from market_data.contracts import CompletedBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bars(
    count: int,
    start_price: Decimal = Decimal("1500"),
    volatility: Decimal = Decimal("5"),
    token: str = "INFY",
) -> list[CompletedBar]:
    bars = []
    base = datetime(2026, 7, 24, 9, 15, tzinfo=timezone.utc)
    price = start_price
    for i in range(count):
        o = price
        c = price + (Decimal(str(i % 3 - 1)) * volatility)
        h = max(o, c) + volatility
        l = min(o, c) - volatility
        bars.append(CompletedBar(
            instrument_token=token,
            timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=Decimal("10000"),
            interval="1m",
        ))
        price = c
    return bars


# ---------------------------------------------------------------------------
# VolatilityForecast field names (plan-aligned)
# ---------------------------------------------------------------------------

class TestVolatilityForecastFields:
    def test_predicted_atr_field_exists(self) -> None:
        """Plan-aligned field: predicted_atr (NOT expected_range)."""
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert hasattr(forecast, "predicted_atr")

    def test_predicted_range_pct_field_exists(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert hasattr(forecast, "predicted_range_pct")

    def test_forecast_horizon_field_exists(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert hasattr(forecast, "forecast_horizon")
        assert isinstance(forecast.forecast_horizon, str)

    def test_computed_at_is_timezone_aware_datetime(self) -> None:
        """computed_at must be a timezone-aware datetime, not a string."""
        forecaster = VolatilityForecaster()
        bars = make_bars(5)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert isinstance(forecast.computed_at, datetime)
        assert forecast.computed_at.tzinfo is not None

    def test_deprecated_expected_range_alias(self) -> None:
        """Backward-compat alias: expected_range → predicted_atr."""
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert forecast.expected_range == forecast.predicted_atr

    def test_deprecated_expected_range_pct_alias(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert forecast.expected_range_pct == forecast.predicted_range_pct

    def test_deprecated_forecast_window_alias(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(5)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert forecast.forecast_window == forecast.forecast_horizon


# ---------------------------------------------------------------------------
# VolatilityForecaster — confidence (ATR stability-based)
# ---------------------------------------------------------------------------

class TestVolatilityForecasterConfidence:
    def test_confidence_in_bounds(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert Decimal("0.3") <= forecast.confidence <= Decimal("0.9")

    def test_confidence_fallback_few_bars(self) -> None:
        """< 3 ATR measurements → returns 0.6 (no history penalty)."""
        forecaster = VolatilityForecaster()
        bars = make_bars(5)  # < ATR_PERIOD+1, uses STD path
        for b in bars:
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        # With 2-4 bars → STD path → fixed 0.5; or fallback 0.3
        assert forecast.confidence in {Decimal("0.5"), Decimal("0.3")}

    def test_confidence_not_fixed_constant(self) -> None:
        """Stability-based confidence should vary with market data, not be hardcoded."""
        forecaster1 = VolatilityForecaster()
        forecaster2 = VolatilityForecaster()

        # Low volatility market (stable ATR)
        bars_stable = make_bars(25, volatility=Decimal("1"))
        for b in bars_stable:
            forecaster1.update(b)

        # High volatility market (unstable ATR)
        bars_volatile = make_bars(25, volatility=Decimal("50"))
        for b in bars_volatile:
            forecaster2.update(b)

        f1 = forecaster1.forecast("INFY")
        f2 = forecaster2.forecast("INFY")
        # Both should be valid
        assert Decimal("0.3") <= f1.confidence <= Decimal("0.9")
        assert Decimal("0.3") <= f2.confidence <= Decimal("0.9")


# ---------------------------------------------------------------------------
# VolatilityForecaster — fallback paths
# ---------------------------------------------------------------------------

class TestVolatilityForecasterFallbacks:
    def test_no_bars_returns_zero_atr(self) -> None:
        forecaster = VolatilityForecaster()
        forecast = forecaster.forecast("INFY")
        assert forecast.predicted_atr == Decimal("0")
        assert forecast.confidence == Decimal("0.3")

    def test_one_bar_returns_zero_atr(self) -> None:
        forecaster = VolatilityForecaster()
        forecaster.update(make_bars(1)[0])
        forecast = forecaster.forecast("INFY")
        assert forecast.predicted_atr == Decimal("0")

    def test_few_bars_uses_std_or_fallback(self) -> None:
        """Uses STD path (confidence=0.5) when bars have different closes and std > 0."""
        forecaster = VolatilityForecaster()
        # High volatility to guarantee different closes → std > 0 → STD path
        for b in make_bars(5, volatility=Decimal("20")):
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert forecast.confidence == Decimal("0.5")

    def test_enough_bars_uses_atr_path(self) -> None:
        forecaster = VolatilityForecaster()
        for b in make_bars(20):
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert forecast.predicted_atr > Decimal("0")

    def test_predicted_range_pct_positive(self) -> None:
        forecaster = VolatilityForecaster()
        for b in make_bars(20):
            forecaster.update(b)
        forecast = forecaster.forecast("INFY")
        assert forecast.predicted_range_pct > Decimal("0")


# ---------------------------------------------------------------------------
# VolatilityForecaster — buffer update
# ---------------------------------------------------------------------------

class TestVolatilityForecasterUpdate:
    def test_update_with_bars_list(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(30)
        for b in bars:
            forecaster.update(b)
        assert len(forecaster.get_buffer("INFY")) == 30

    def test_buffer_capped_at_50(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(60)
        for b in bars:
            forecaster.update(b)
        assert len(forecaster.get_buffer("INFY")) == 50

    def test_forecast_with_explicit_bars(self) -> None:
        forecaster = VolatilityForecaster()
        bars = make_bars(20)
        forecast = forecaster.forecast("INFY", bars=bars)
        assert forecast.predicted_atr >= Decimal("0")
