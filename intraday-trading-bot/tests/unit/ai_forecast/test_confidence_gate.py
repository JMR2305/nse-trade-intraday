"""Tests for RC-10B ForecastConfidenceGate (async, class-based, fail-open)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_forecast.confidence_gate import ForecastConfidenceGate
from ai_forecast.kronos_adapter import ForecastResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_forecast(confidence: str, direction: str = "UP") -> ForecastResult:
    return ForecastResult(
        instrument_token="INFY",
        forecast_horizon="15m",
        direction=direction,
        confidence=Decimal(confidence),
        model_version="v1",
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def make_gate(
    forecast: ForecastResult | None = None,
    adapter_raises: Exception | None = None,
) -> ForecastConfidenceGate:
    adapter = AsyncMock()
    if adapter_raises is not None:
        adapter.forecast.side_effect = adapter_raises
    else:
        adapter.forecast.return_value = forecast

    generator = MagicMock()
    generator.generate.return_value = MagicMock(
        features=(Decimal("0.1"),) * 25, schema_version="1.0"
    )

    return ForecastConfidenceGate(adapter=adapter, generator=generator)


def make_signal(instrument_token: str = "INFY") -> MagicMock:
    s = MagicMock()
    s.instrument_token = instrument_token
    s.signal_id = "test-signal-1"
    s.metadata = {}
    return s


def make_context(instrument_token: str = "INFY", with_mtf: bool = True) -> MagicMock:
    from market_intelligence.multi_timeframe_context import MultiTimeframeContext
    ctx = MagicMock()
    if with_mtf:
        mtf = MagicMock(spec=MultiTimeframeContext)
        mtf.timeframes = {"1m": {"close": Decimal("1500")}}
        mtf.regime = None
        ctx.market_snapshots = {instrument_token: mtf}
    else:
        ctx.market_snapshots = {}
    return ctx


# ---------------------------------------------------------------------------
# should_route() — async API
# ---------------------------------------------------------------------------

class TestShouldRoute:
    @pytest.mark.asyncio
    async def test_no_threshold_always_routes(self) -> None:
        """min_confidence=None → fail-open (True, None) regardless of forecast."""
        gate = make_gate(forecast=make_forecast("0.2"))
        signal = make_signal()
        ctx = make_context()
        should_route, forecast = await gate.should_route(signal, ctx, min_confidence=None)
        assert should_route is True
        assert forecast is None
        # Adapter must NOT be called when no threshold
        gate._adapter.forecast.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_threshold_routes_with_forecast(self) -> None:
        forecast = make_forecast("0.75")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        should_route, returned = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert should_route is True
        assert returned is forecast

    @pytest.mark.asyncio
    async def test_below_threshold_suppresses(self) -> None:
        forecast = make_forecast("0.40")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        should_route, returned = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert should_route is False
        assert returned is forecast

    @pytest.mark.asyncio
    async def test_exact_threshold_routes(self) -> None:
        forecast = make_forecast("0.60")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        should_route, _ = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert should_route is True

    @pytest.mark.asyncio
    async def test_adapter_error_fail_open(self) -> None:
        """Adapter exception → fail-open (True, None)."""
        gate = make_gate(adapter_raises=RuntimeError("Kronos unavailable"))
        signal = make_signal()
        ctx = make_context()
        should_route, forecast = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert should_route is True
        assert forecast is None

    @pytest.mark.asyncio
    async def test_missing_mtf_context_fail_open(self) -> None:
        """No MultiTimeframeContext for instrument → fail-open."""
        gate = make_gate(forecast=make_forecast("0.80"))
        signal = make_signal()
        ctx = make_context(with_mtf=False)
        should_route, forecast = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert should_route is True
        assert forecast is None

    @pytest.mark.asyncio
    async def test_adapter_returns_none_fail_open(self) -> None:
        gate = make_gate(forecast=None)
        signal = make_signal()
        ctx = make_context()
        should_route, forecast = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert should_route is True
        assert forecast is None

    @pytest.mark.asyncio
    async def test_prefetched_forecast_bypasses_adapter(self) -> None:
        """When prefetched_forecast is provided, the adapter must NOT be called."""
        prefetched = make_forecast("0.80")
        gate = make_gate(forecast=make_forecast("0.20"))  # adapter would suppress
        signal = make_signal()
        ctx = make_context()
        should_route, returned = await gate.should_route(
            signal, ctx, Decimal("0.60"), prefetched_forecast=prefetched
        )
        assert should_route is True
        assert returned is prefetched
        gate._adapter.forecast.assert_not_called()

    @pytest.mark.asyncio
    async def test_down_direction_routed_when_above_threshold(self) -> None:
        forecast = make_forecast("0.72", direction="DOWN")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        should_route, returned = await gate.should_route(signal, ctx, Decimal("0.65"))
        assert should_route is True
        assert returned.direction == "DOWN"


# ---------------------------------------------------------------------------
# apply() — static sync utility (backward compatibility)
# ---------------------------------------------------------------------------

class TestApplyStaticUtility:
    def test_passes_above_threshold(self) -> None:
        forecast = make_forecast("0.75")
        result = ForecastConfidenceGate.apply(forecast, Decimal("0.60"))
        assert result is forecast

    def test_rejects_below_threshold(self) -> None:
        forecast = make_forecast("0.40")
        result = ForecastConfidenceGate.apply(forecast, Decimal("0.60"))
        assert result is None

    def test_no_threshold_returns_forecast(self) -> None:
        forecast = make_forecast("0.10")
        result = ForecastConfidenceGate.apply(forecast, None)
        assert result is forecast
