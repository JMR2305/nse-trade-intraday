from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from ai_forecast.kronos_adapter import ForecastResult

logger = logging.getLogger(__name__)


class ForecastConfidenceGate(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True)

    min_confidence: Decimal = Decimal("0.55")
    enforce_direction_mandatory: bool = True

    def apply(self, forecast: ForecastResult) -> Optional[ForecastResult]:
        """Filter forecast through confidence gate. Returns None if rejected."""
        if forecast.confidence < self.min_confidence:
            logger.info(
                "Forecast rejected: confidence %.4f < threshold %.4f",
                float(forecast.confidence),
                float(self.min_confidence),
                extra={
                    "instrument_token": forecast.instrument_token,
                    "confidence": str(forecast.confidence),
                    "threshold": str(self.min_confidence),
                },
            )
            return None

        if forecast.direction == "NEUTRAL":
            if self.enforce_direction_mandatory:
                logger.info(
                    "Forecast rejected: direction is NEUTRAL",
                    extra={
                        "instrument_token": forecast.instrument_token,
                        "direction": forecast.direction,
                    },
                )
                return None
            return forecast

        logger.info(
            "Forecast passed gate: %s %.4f",
            forecast.direction,
            float(forecast.confidence),
            extra={
                "instrument_token": forecast.instrument_token,
                "direction": forecast.direction,
                "confidence": str(forecast.confidence),
            },
        )
        return forecast
