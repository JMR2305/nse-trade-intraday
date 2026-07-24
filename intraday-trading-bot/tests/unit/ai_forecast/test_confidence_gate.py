"""Tests for RC-10B ForecastConfidenceGate — GateDecision API, fail-open, static utility."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_forecast.confidence_gate import ForecastConfidenceGate, GateDecision
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
# GateDecision model
# ---------------------------------------------------------------------------

class TestGateDecision:
    def test_immutable(self) -> None:
        d = GateDecision(allowed=True, reason="APPROVED")
        with pytest.raises(Exception):  # frozen Pydantic
            d.allowed = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        d = GateDecision(allowed=True, reason="FAIL_OPEN_NO_THRESHOLD")
        assert d.raw_confidence is None
        assert d.calibrated_confidence is None
        assert d.threshold is None
        assert d.model_version is None
        assert d.forecast_horizon is None
        assert d.degraded is False
        assert d.forecast is None

    def test_reason_constants(self) -> None:
        d = GateDecision(allowed=True, reason="X")
        assert d.REASON_APPROVED == "APPROVED"
        assert d.REASON_SUPPRESSED == "SUPPRESSED_LOW_CONFIDENCE"
        assert d.REASON_NO_THRESHOLD == "FAIL_OPEN_NO_THRESHOLD"
        assert d.REASON_NO_FORECAST == "FAIL_OPEN_NO_FORECAST"

    def test_full_population(self) -> None:
        fc = make_forecast("0.75")
        d = GateDecision(
            allowed=True,
            reason="APPROVED",
            raw_confidence=Decimal("0.75"),
            calibrated_confidence=Decimal("0.75"),
            threshold=Decimal("0.60"),
            model_version="v1",
            forecast_horizon="15m",
            degraded=False,
            forecast=fc,
        )
        assert d.allowed is True
        assert d.raw_confidence == Decimal("0.75")
        assert d.forecast is fc


# ---------------------------------------------------------------------------
# should_route() — GateDecision return type
# ---------------------------------------------------------------------------

class TestShouldRoute:
    @pytest.mark.asyncio
    async def test_no_threshold_always_routes(self) -> None:
        """min_confidence=None → FAIL_OPEN_NO_THRESHOLD, allowed=True."""
        gate = make_gate(forecast=make_forecast("0.2"))
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, min_confidence=None)
        assert decision.allowed is True
        assert decision.reason == "FAIL_OPEN_NO_THRESHOLD"
        assert decision.raw_confidence is None
        assert decision.forecast is None
        # Adapter must NOT be called when no threshold
        gate._adapter.forecast.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_threshold_approved(self) -> None:
        forecast = make_forecast("0.75")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert decision.allowed is True
        assert decision.reason == "APPROVED"
        assert decision.raw_confidence == Decimal("0.75")
        assert decision.calibrated_confidence == Decimal("0.75")
        assert decision.threshold == Decimal("0.60")
        assert decision.model_version == "v1"
        assert decision.forecast_horizon == "15m"
        assert decision.degraded is False
        assert decision.forecast is forecast

    @pytest.mark.asyncio
    async def test_below_threshold_suppressed(self) -> None:
        forecast = make_forecast("0.40")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert decision.allowed is False
        assert decision.reason == "SUPPRESSED_LOW_CONFIDENCE"
        assert decision.raw_confidence == Decimal("0.40")
        assert decision.threshold == Decimal("0.60")
        # forecast NOT attached when suppressed (prevent accidental use)
        assert decision.forecast is None

    @pytest.mark.asyncio
    async def test_exact_threshold_approved(self) -> None:
        forecast = make_forecast("0.60")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert decision.allowed is True
        assert decision.reason == "APPROVED"

    @pytest.mark.asyncio
    async def test_adapter_error_fail_open(self) -> None:
        """Adapter exception → FAIL_OPEN_NO_FORECAST, allowed=True, degraded=True."""
        gate = make_gate(adapter_raises=RuntimeError("Kronos unavailable"))
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert decision.allowed is True
        assert decision.reason == "FAIL_OPEN_NO_FORECAST"
        assert decision.degraded is True
        assert decision.forecast is None
        assert decision.raw_confidence is None

    @pytest.mark.asyncio
    async def test_missing_mtf_context_fail_open(self) -> None:
        """No MultiTimeframeContext for instrument → FAIL_OPEN_NO_FORECAST."""
        gate = make_gate(forecast=make_forecast("0.80"))
        signal = make_signal()
        ctx = make_context(with_mtf=False)
        decision = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert decision.allowed is True
        assert decision.reason == "FAIL_OPEN_NO_FORECAST"
        assert decision.degraded is True

    @pytest.mark.asyncio
    async def test_adapter_returns_none_fail_open(self) -> None:
        gate = make_gate(forecast=None)
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, Decimal("0.60"))
        assert decision.allowed is True
        assert decision.reason == "FAIL_OPEN_NO_FORECAST"
        assert decision.degraded is True

    @pytest.mark.asyncio
    async def test_prefetched_forecast_bypasses_adapter(self) -> None:
        """When prefetched_forecast is provided, the adapter must NOT be called."""
        prefetched = make_forecast("0.80")
        gate = make_gate(forecast=make_forecast("0.20"))  # adapter would suppress
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(
            signal, ctx, Decimal("0.60"), prefetched_forecast=prefetched
        )
        assert decision.allowed is True
        assert decision.reason == "APPROVED"
        assert decision.forecast is prefetched
        gate._adapter.forecast.assert_not_called()

    @pytest.mark.asyncio
    async def test_down_direction_routed_when_above_threshold(self) -> None:
        forecast = make_forecast("0.72", direction="DOWN")
        gate = make_gate(forecast=forecast)
        signal = make_signal()
        ctx = make_context()
        decision = await gate.should_route(signal, ctx, Decimal("0.65"))
        assert decision.allowed is True
        assert decision.forecast is not None
        assert decision.forecast.direction == "DOWN"

    @pytest.mark.asyncio
    async def test_decision_is_immutable(self) -> None:
        """GateDecision must be a frozen Pydantic model."""
        gate = make_gate(forecast=make_forecast("0.70"))
        decision = await gate.should_route(make_signal(), make_context(), Decimal("0.60"))
        with pytest.raises(Exception):
            decision.allowed = False  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_degraded_false_on_approval(self) -> None:
        """When forecast is available and threshold met, degraded must be False."""
        gate = make_gate(forecast=make_forecast("0.80"))
        decision = await gate.should_route(make_signal(), make_context(), Decimal("0.60"))
        assert decision.degraded is False

    @pytest.mark.asyncio
    async def test_all_required_fields_populated_on_approval(self) -> None:
        """All 7 structured fields must be non-None when approved with a forecast."""
        forecast = make_forecast("0.75")
        gate = make_gate(forecast=forecast)
        decision = await gate.should_route(make_signal(), make_context(), Decimal("0.60"))
        assert decision.allowed is True
        assert decision.raw_confidence is not None
        assert decision.calibrated_confidence is not None
        assert decision.threshold is not None
        assert decision.reason is not None
        assert decision.model_version is not None
        assert decision.forecast_horizon is not None


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

    def test_exact_threshold_passes(self) -> None:
        forecast = make_forecast("0.60")
        result = ForecastConfidenceGate.apply(forecast, Decimal("0.60"))
        assert result is forecast
