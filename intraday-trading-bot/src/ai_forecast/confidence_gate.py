"""RC-10B ForecastConfidenceGate — async, per-strategy, fail-open.

Public interface (plan-aligned):

    gate = ForecastConfidenceGate(adapter, generator)
    decision = await gate.should_route(
        signal, context, min_confidence, prefetched_forecast=None
    )
    # decision.allowed: bool — whether to route the signal
    # decision.reason:  str  — APPROVED | SUPPRESSED_LOW_CONFIDENCE |
    #                          FAIL_OPEN_NO_THRESHOLD | FAIL_OPEN_NO_FORECAST
    # decision.forecast: ForecastResult | None — attached when approved with data

GateDecision.reason values:
    APPROVED                  confidence ≥ threshold
    SUPPRESSED_LOW_CONFIDENCE confidence < threshold
    FAIL_OPEN_NO_THRESHOLD    no min_confidence configured (inert gate)
    FAIL_OPEN_NO_FORECAST     forecast unavailable (error or no MTF context)

Behaviour matrix:
  min_confidence is None         → allowed=True,  reason=FAIL_OPEN_NO_THRESHOLD
  forecast unavailable or error  → allowed=True,  reason=FAIL_OPEN_NO_FORECAST
  confidence < min_confidence    → allowed=False, reason=SUPPRESSED_LOW_CONFIDENCE
  confidence ≥ min_confidence    → allowed=True,  reason=APPROVED

Filtering ONLY occurs when the caller explicitly passes a non-None
min_confidence threshold (sourced from StrategyConfig.parameters).
A gate instance with no threshold is operationally inert.

AI output never directly creates or executes orders.  The gate result
is advisory: it determines whether the signal proceeds to RC-8 → RC-7,
never bypassing those layers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ai_forecast.kronos_adapter import ForecastResult, KronosAdapter
    from ai_forecast.features import FeatureGenerator, FeatureVector
    from strategy.contracts import Signal, StrategyContext
    from market_intelligence.multi_timeframe_context import MultiTimeframeContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured decision model
# ---------------------------------------------------------------------------

class GateDecision(BaseModel, frozen=True):
    """Immutable, structured result from ForecastConfidenceGate.should_route().

    Downstream callers use decision.allowed to decide whether to route the
    signal.  The remaining fields provide full audit context for structured
    logging and signal metadata enrichment.

    Fields:
        allowed                whether the signal should be routed.
        raw_confidence         model-reported confidence (None if unavailable).
        calibrated_confidence  post-calibration confidence.  Currently identical
                               to raw_confidence (calibration model is planned
                               for RC-10D but the field is reserved here to
                               avoid a breaking schema change later).
        threshold              the min_confidence value applied.
        reason                 one of the REASON_* class constants.
        model_version          model identifier from the forecast.
        forecast_horizon       forecast horizon label (e.g. "15m").
        degraded               True when the gate is fail-open due to missing/
                               errored forecast data.
        forecast               the underlying ForecastResult (populated when
                               allowed=True and a forecast was obtained;
                               None for fail-open and suppressed cases where
                               we do not want to expose partial data).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # -- routing outcome --
    allowed: bool
    reason: str

    # -- confidence detail --
    raw_confidence: Optional[Decimal] = None
    calibrated_confidence: Optional[Decimal] = None
    threshold: Optional[Decimal] = None

    # -- provenance --
    model_version: Optional[str] = None
    forecast_horizon: Optional[str] = None

    # -- health --
    degraded: bool = False

    # -- payload (for metadata enrichment) --
    forecast: Optional[Any] = None  # ForecastResult; Any avoids circular import

    # -- reason constants (ClassVar: not Pydantic fields; accessible as GateDecision.REASON_*) --
    REASON_APPROVED: ClassVar[str] = "APPROVED"
    REASON_SUPPRESSED: ClassVar[str] = "SUPPRESSED_LOW_CONFIDENCE"
    REASON_NO_THRESHOLD: ClassVar[str] = "FAIL_OPEN_NO_THRESHOLD"
    REASON_NO_FORECAST: ClassVar[str] = "FAIL_OPEN_NO_FORECAST"


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class ForecastConfidenceGate:
    """Async AI forecast gate.

    Coordinates FeatureGenerator + KronosAdapter + confidence threshold.
    Does not hold mutable state beyond its injected dependencies.
    Safe for concurrent use once constructed.

    AI output is strictly advisory and enriches signal metadata only.
    It does NOT create orders, modify risk limits, or bypass RC-8/RC-7.
    """

    def __init__(
        self,
        adapter: "KronosAdapter",
        generator: "FeatureGenerator",
    ) -> None:
        self._adapter = adapter
        self._generator = generator

    async def should_route(
        self,
        signal: "Signal",
        context: "StrategyContext",
        min_confidence: Optional[Decimal],
        prefetched_forecast: Optional["ForecastResult"] = None,
    ) -> GateDecision:
        """Determine whether to route a signal through the AI forecast gate.

        Args:
            signal:              The trading signal being evaluated.
            context:             StrategyContext produced by ContextBuilder.
            min_confidence:      Threshold from StrategyConfig.parameters
                                 ["min_forecast_confidence"]. None → pass-through.
            prefetched_forecast: A pre-fetched ForecastResult (e.g. from
                                 asyncio.create_task prefetch). When provided,
                                 the adapter is not called again.

        Returns:
            GateDecision with allowed, reason, and full confidence context.
        """
        # No threshold configured → gate is inert; always route
        if min_confidence is None:
            return GateDecision(
                allowed=True,
                reason=GateDecision.REASON_NO_THRESHOLD,
            )

        # Obtain forecast (use prefetch if available, else fetch inline)
        forecast = prefetched_forecast
        if forecast is None:
            forecast = await self._fetch_forecast(signal, context)

        # Adapter failure or no MTF context → fail-open (degraded mode)
        if forecast is None:
            logger.debug(
                "No forecast available for %s — failing open (degraded)",
                signal.instrument_token,
            )
            return GateDecision(
                allowed=True,
                reason=GateDecision.REASON_NO_FORECAST,
                threshold=min_confidence,
                degraded=True,
            )

        # Apply threshold
        allowed = forecast.confidence >= min_confidence
        reason = (
            GateDecision.REASON_APPROVED
            if allowed
            else GateDecision.REASON_SUPPRESSED
        )

        if allowed:
            logger.info(
                "Gate APPROVED: instrument=%s confidence=%.4f threshold=%.4f "
                "direction=%s model=%s",
                signal.instrument_token,
                float(forecast.confidence),
                float(min_confidence),
                forecast.direction,
                forecast.model_version,
                extra={
                    "instrument_token": signal.instrument_token,
                    "confidence": str(forecast.confidence),
                    "threshold": str(min_confidence),
                    "direction": forecast.direction,
                    "model_version": forecast.model_version,
                },
            )
        else:
            logger.info(
                "Gate SUPPRESSED: instrument=%s confidence=%.4f threshold=%.4f "
                "direction=%s",
                signal.instrument_token,
                float(forecast.confidence),
                float(min_confidence),
                forecast.direction,
                extra={
                    "instrument_token": signal.instrument_token,
                    "confidence": str(forecast.confidence),
                    "threshold": str(min_confidence),
                    "direction": forecast.direction,
                    "signal_id": str(signal.signal_id),
                },
            )

        return GateDecision(
            allowed=allowed,
            reason=reason,
            raw_confidence=forecast.confidence,
            # calibrated_confidence = raw until RC-10D calibration model
            calibrated_confidence=forecast.confidence,
            threshold=min_confidence,
            model_version=forecast.model_version,
            forecast_horizon=forecast.forecast_horizon,
            degraded=False,
            # Attach forecast to GateDecision only when approved so downstream
            # callers do not accidentally use suppressed forecast data.
            forecast=forecast if allowed else None,
        )

    async def _fetch_forecast(
        self,
        signal: "Signal",
        context: "StrategyContext",
    ) -> Optional["ForecastResult"]:
        """Generate features and call Kronos. Fail-open on any error."""
        from market_intelligence.multi_timeframe_context import MultiTimeframeContext

        try:
            mtf_context = context.market_snapshots.get(signal.instrument_token)
            if mtf_context is None or not isinstance(mtf_context, MultiTimeframeContext):
                logger.debug(
                    "No MultiTimeframeContext for %s — skipping forecast",
                    signal.instrument_token,
                )
                return None

            generated_at = datetime.now(timezone.utc).isoformat()
            features = self._generator.generate(
                signal.instrument_token, mtf_context, generated_at
            )
            return await self._adapter.forecast(signal.instrument_token, features)

        except Exception as exc:
            logger.warning(
                "Forecast fetch failed (fail-open): %s",
                exc,
                extra={"instrument_token": signal.instrument_token},
            )
            return None

    # ------------------------------------------------------------------
    # Synchronous utility (backward-compatible with pre-RC-10B apply())
    # ------------------------------------------------------------------

    @staticmethod
    def apply(
        forecast: "ForecastResult",
        min_confidence: Optional[Decimal] = None,
    ) -> Optional["ForecastResult"]:
        """Synchronous filter for a pre-obtained forecast.

        Returns the forecast if it passes min_confidence, else None.
        When min_confidence is None, always returns the forecast.
        This is a utility for tests and non-runtime callers; it does not
        invoke the adapter or produce a GateDecision.
        """
        if min_confidence is None:
            return forecast
        return forecast if forecast.confidence >= min_confidence else None
