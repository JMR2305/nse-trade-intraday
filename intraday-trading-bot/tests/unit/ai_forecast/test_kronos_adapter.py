from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest

from ai_forecast.kronos_adapter import ForecastResult, KronosAdapter
from ai_forecast.features import FeatureVector


class TestForecastResult:
    def test_valid_direction(self) -> None:
        result = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.75"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        assert result.direction == "UP"
        assert result.confidence == Decimal("0.75")

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction must be one of"):
            ForecastResult(
                instrument_token="INFY",
                forecast_horizon="15m",
                direction="SIDEWAYS",
                confidence=Decimal("0.75"),
                model_version="v1",
                computed_at=datetime.utcnow().isoformat(),
            )

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            ForecastResult(
                instrument_token="INFY",
                forecast_horizon="15m",
                direction="UP",
                confidence=Decimal("-0.1"),
                model_version="v1",
                computed_at=datetime.utcnow().isoformat(),
            )

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            ForecastResult(
                instrument_token="INFY",
                forecast_horizon="15m",
                direction="UP",
                confidence=Decimal("1.1"),
                model_version="v1",
                computed_at=datetime.utcnow().isoformat(),
            )

    def test_neutral_direction(self) -> None:
        result = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="NEUTRAL",
            confidence=Decimal("0.5"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        assert result.direction == "NEUTRAL"

    def test_down_direction(self) -> None:
        result = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="DOWN",
            confidence=Decimal("0.6"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        assert result.direction == "DOWN"

    def test_optional_price_target(self) -> None:
        result = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.7"),
            price_target=Decimal("1500"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        assert result.price_target == Decimal("1500")

    def test_immutability(self) -> None:
        result = ForecastResult(
            instrument_token="INFY",
            forecast_horizon="15m",
            direction="UP",
            confidence=Decimal("0.7"),
            model_version="v1",
            computed_at=datetime.utcnow().isoformat(),
        )
        with pytest.raises(Exception):
            result.direction = "DOWN"


class TestKronosAdapter:
    def test_fail_open_returns_none(self) -> None:
        """KronosAdapter returns None when server is unreachable (fail-open)."""
        adapter = KronosAdapter(base_url="http://localhost:99999", timeout_ms=100, max_retries=0)
        import asyncio
        features = FeatureVector(
            instrument_token="INFY",
            features=tuple([Decimal("0.5")] * 42),
            schema_version="1.0",
            generated_at=datetime.utcnow().isoformat(),
        )
        result = asyncio.get_event_loop().run_until_complete(
            adapter.forecast("INFY", features)
        )
        assert result is None

    def test_configurable_timeout(self) -> None:
        adapter = KronosAdapter(timeout_ms=500)
        assert adapter._timeout == 500

    def test_configurable_retries(self) -> None:
        adapter = KronosAdapter(max_retries=3)
        assert adapter._max_retries == 3

    def test_default_settings_from_config(self) -> None:
        from core.config import settings
        adapter = KronosAdapter()
        assert adapter._base_url == settings.ai_forecast.kronos_base_url
        assert adapter._timeout == settings.ai_forecast.kronos_timeout_ms
        assert adapter._max_retries == settings.ai_forecast.kronos_max_retries

    def test_close_client(self) -> None:
        adapter = KronosAdapter()
        import asyncio
        asyncio.get_event_loop().run_until_complete(adapter.close())
        assert adapter._client is None
