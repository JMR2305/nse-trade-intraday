"""RC-10B ForecastConfidenceGate — async, per-strategy, fail-open.

Public interface (plan-aligned):

    gate = ForecastConfidenceGate(adapter, generator)
    should_route, forecast = await gate.should_route(
        signal, context, min_confidence, prefetched_forecast=None
    )

Behaviour matrix:
  min_confidence is None         → (True, None)   — fail-open, no threshold
  forecast unavailable or error  → (True, None)   — fail-open
  confidence < min_confidence    → (False, forecast)
  confidence ≥ min_confidence    → (True, forecast)

Filtering ONLY occurs when the caller explicitly passes a non-None
min_confidence threshold (sourced from StrategyConfig.parameters).
A gate instance with no threshold is operationally inert.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from ai_forecast.kronos_adapter import ForecastResult, KronosAdapter
    from ai_forecast.features import FeatureGenerator, FeatureVector
    from strategy.contracts import Signal, StrategyContext
    from market_intelligence.multi_timeframe_context import MultiTimeframeContext

logger = logging.getLogger(__name__)


class ForecastConfidenceGate:
    """Async AI forecast gate.

    Coordinates FeatureGenerator + KronosAdapter + confidence threshold.
    Does not hold mutable state beyond its injected dependencies.
    Safe for concurrent use once constructed.
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
    ) -> Tuple[bool, Optional["ForecastResult"]]:
        """Determine whether to route a signal.

        Args:
            signal:              The trading signal being evaluated.
            context:             StrategyContext produced by ContextBuilder.
            min_confidence:      Threshold from StrategyConfig.parameters
                                 ["min_forecast_confidence"]. None → pass-through.
            prefetched_forecast: A pre-fetched ForecastResult (e.g. from
                                 asyncio.create_task prefetch). When provided,
                                 the adapter is not called again.

        Returns:
            (should_route: bool, forecast: Optional[ForecastResult])
        """
        # No threshold configured → always route, no forecast needed
        if min_confidence is None:
            return True, None

        # Obtain forecast
        forecast = prefetched_forecast
        if forecast is None:
            forecast = await self._fetch_forecast(signal, context)

        # Adapter failure or no MTF context → fail-open
        if forecast is None:
            return True, None

        # Apply threshold
        if forecast.confidence < min_confidence:
            logger.info(
                "Signal suppressed by forecast gate: instrument=%s "
                "confidence=%.4f threshold=%.4f direction=%s",
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
            return False, forecast

        logger.info(
            "Signal approved by forecast gate: instrument=%s "
            "confidence=%.4f threshold=%.4f direction=%s",
            signal.instrument_token,
            float(forecast.confidence),
            float(min_confidence),
            forecast.direction,
            extra={
                "instrument_token": signal.instrument_token,
                "confidence": str(forecast.confidence),
                "direction": forecast.direction,
                "model_version": forecast.model_version,
            },
        )
        return True, forecast

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
                "Forecast fetch failed (fail-open): %s", exc,
                extra={"instrument_token": signal.instrument_token},
            )
            return None

    # ------------------------------------------------------------------
    # Synchronous utility (backward-compatible with audit-era apply())
    # ------------------------------------------------------------------

    @staticmethod
    def apply(
        forecast: "ForecastResult",
        min_confidence: Optional[Decimal] = None,
    ) -> Optional["ForecastResult"]:
        """Synchronous filter for a pre-obtained forecast.

        Returns the forecast if it passes min_confidence, else None.
        When min_confidence is None, always returns the forecast.
        This is a utility; it does not call the adapter.
        """
        if min_confidence is None:
            return forecast
        return forecast if forecast.confidence >= min_confidence else None
