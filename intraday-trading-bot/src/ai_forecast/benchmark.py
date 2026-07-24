from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkEntry:
    instrument_token: str
    forecast_direction: str
    actual_direction: str
    correct: bool
    confidence: Decimal
    timestamp: str


class BenchmarkReport(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True)

    total_predictions: int = 0
    correct_predictions: int = 0
    accuracy: Decimal = Decimal("0")
    avg_confidence: Decimal = Decimal("0")
    by_instrument: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    by_direction: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    report_period: str = ""


class ForecastBenchmark:
    """Tracks forecast accuracy against actual outcomes.

    Records every forecast and can evaluate after the forecast horizon passes.
    """

    def __init__(self, accuracy_threshold: Optional[float] = None) -> None:
        self._threshold = (
            accuracy_threshold
            if accuracy_threshold is not None
            else settings.ai_forecast.benchmark_accuracy_alert_threshold
        )
        self._entries: List[BenchmarkEntry] = []
        self._pending: Dict[str, Dict[str, str]] = {}  # instrument -> {forecast_data}

    def record_forecast(
        self,
        instrument_token: str,
        forecast_direction: str,
        confidence: Decimal,
        timestamp: str,
    ) -> None:
        """Record a forecast for later evaluation."""
        self._pending[instrument_token] = {
            "direction": forecast_direction,
            "confidence": str(confidence),
            "timestamp": timestamp,
        }
        logger.debug(
            "Forecast recorded for benchmark",
            extra={
                "instrument_token": instrument_token,
                "direction": forecast_direction,
                "confidence": str(confidence),
            },
        )

    def evaluate(
        self,
        instrument_token: str,
        actual_direction: str,
        timestamp: str,
    ) -> None:
        """Evaluate a pending forecast against actual outcome."""
        pending = self._pending.pop(instrument_token, None)
        if pending is None:
            return

        correct = pending["direction"] == actual_direction
        entry = BenchmarkEntry(
            instrument_token=instrument_token,
            forecast_direction=pending["direction"],
            actual_direction=actual_direction,
            correct=correct,
            confidence=Decimal(pending["confidence"]),
            timestamp=timestamp,
        )
        self._entries.append(entry)

        if not correct:
            logger.warning(
                "Forecast mismatch: expected %s, got %s",
                pending["direction"],
                actual_direction,
                extra={
                    "instrument_token": instrument_token,
                    "expected": pending["direction"],
                    "actual": actual_direction,
                },
            )

    def generate_report(self, period: str = "daily") -> BenchmarkReport:
        """Generate accuracy report from recorded entries."""
        if not self._entries:
            return BenchmarkReport(report_period=period)

        total = len(self._entries)
        correct = sum(1 for e in self._entries if e.correct)
        accuracy = Decimal(str(correct)) / Decimal(str(total)) if total > 0 else Decimal("0")
        avg_conf = (
            sum(e.confidence for e in self._entries) / Decimal(str(total))
            if total > 0
            else Decimal("0")
        )

        by_inst: Dict[str, Dict[str, int]] = {}
        for e in self._entries:
            if e.instrument_token not in by_inst:
                by_inst[e.instrument_token] = {"total": 0, "correct": 0}
            by_inst[e.instrument_token]["total"] += 1
            if e.correct:
                by_inst[e.instrument_token]["correct"] += 1

        by_dir: Dict[str, Dict[str, int]] = {}
        for e in self._entries:
            d = e.forecast_direction
            if d not in by_dir:
                by_dir[d] = {"total": 0, "correct": 0}
            by_dir[d]["total"] += 1
            if e.correct:
                by_dir[d]["correct"] += 1

        if float(accuracy) < self._threshold:
            logger.warning(
                "Forecast accuracy %.4f below threshold %.4f",
                float(accuracy),
                self._threshold,
                extra={
                    "accuracy": str(accuracy),
                    "threshold": str(self._threshold),
                    "total_predictions": total,
                },
            )

        return BenchmarkReport(
            total_predictions=total,
            correct_predictions=correct,
            accuracy=accuracy.quantize(Decimal("0.0001")),
            avg_confidence=avg_conf.quantize(Decimal("0.0001")),
            by_instrument=by_inst,
            by_direction=by_dir,
            report_period=period,
        )

    def clear(self) -> None:
        """Clear all entries (e.g., at session end)."""
        self._entries.clear()
        self._pending.clear()
