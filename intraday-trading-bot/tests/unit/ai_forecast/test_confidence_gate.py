from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest

from ai_forecast.kronos_adapter import ForecastResult
from ai_forecast.confidence_gate import ForecastConfidenceGate


class TestForecastConfidenceGate:
    def test_passes_above_threshold(self) -> None:
        gate = ForecastConfidenceGate(min_confidence=Decimal("0.55"))
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.60"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is not None
        assert result.direction == "UP"

    def test_rejects_below_threshold(self) -> None:
        gate = ForecastConfidenceGate(min_confidence=Decimal("0.55"))
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.50"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is None

    def test_rejects_neutral_when_mandatory(self) -> None:
        gate = ForecastConfidenceGate(enforce_direction_mandatory=True)
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="NEUTRAL",
            confidence=Decimal("0.70"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is None

    def test_allows_neutral_when_not_mandatory(self) -> None:
        gate = ForecastConfidenceGate(enforce_direction_mandatory=False)
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="NEUTRAL",
            confidence=Decimal("0.70"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is not None
        assert result.direction == "NEUTRAL"

    def test_exactly_at_threshold_passes(self) -> None:
        gate = ForecastConfidenceGate(min_confidence=Decimal("0.55"))
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.55"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is not None

    def test_down_direction_passes(self) -> None:
        gate = ForecastConfidenceGate(min_confidence=Decimal("0.55"))
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="DOWN",
            confidence=Decimal("0.60"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is not None
        assert result.direction == "DOWN"

    def test_default_min_confidence(self) -> None:
        gate = ForecastConfidenceGate()
        assert gate.min_confidence == Decimal("0.55")

    def test_default_enforce_mandatory(self) -> None:
        gate = ForecastConfidenceGate()
        assert gate.enforce_direction_mandatory is True

    def test_returns_original_when_passed(self) -> None:
        gate = ForecastConfidenceGate()
        forecast = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.70"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        result = gate.apply(forecast)
        assert result is forecast
