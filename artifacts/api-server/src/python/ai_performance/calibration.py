"""
ai_performance/calibration.py — Calibration / reliability analysis.

Measures how well the AI's stated confidence matches actual success rates.

A perfectly calibrated AI: if it says 80% confidence → 80% of those signals win.

Metrics produced:
  • ECE (Expected Calibration Error) — weighted mean |predicted – actual|
  • Reliability score — (1 – ECE) * 100
  • Confidence bias — mean(predicted) – mean(actual); positive = overconfident
  • Overconfidence score — % of non-empty buckets where predicted > actual
  • Underconfidence score — % of non-empty buckets where predicted < actual
  • Calibration curve — one point per confidence bucket

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import List, Dict, Any

from .ai_models import AISignalRecord, CalibrationPoint, CalibrationMetrics, CONFIDENCE_BUCKETS


def compute_calibration(signals: List[AISignalRecord]) -> CalibrationMetrics:
    """Compute full calibration analysis from AISignalRecord list."""
    result = CalibrationMetrics()

    if not signals:
        return result

    # Group by confidence bucket
    bucket_groups: Dict[str, List[AISignalRecord]] = {}
    for s in signals:
        bucket_groups.setdefault(s.confidence_bucket, []).append(s)

    curve: List[CalibrationPoint] = []
    ece_numerator = 0.0
    total = len(signals)

    predicted_confs: List[float] = []
    actual_rates:    List[float] = []

    for label, lo, hi in CONFIDENCE_BUCKETS:
        group = bucket_groups.get(label, [])
        if not group:
            continue

        # Predicted confidence: mean of actual signal_confidence values in bucket
        predicted = _stats.mean(g.signal_confidence for g in group)
        actual    = sum(1 for g in group if g.is_winner) / len(group)
        error     = abs(predicted - actual)

        point = CalibrationPoint(
            bucket              = label,
            predicted_confidence = predicted,
            actual_success_rate  = actual,
            sample_count         = len(group),
            calibration_error    = error,
        )
        curve.append(point)

        # Weighted contribution to ECE
        ece_numerator += (len(group) / total) * error

        predicted_confs.append(predicted)
        actual_rates.append(actual)

    result.calibration_curve = curve
    result.ece = round(ece_numerator, 4)
    result.reliability_score = round((1.0 - min(ece_numerator, 1.0)) * 100, 2)

    if predicted_confs and actual_rates:
        result.confidence_bias = round(
            _stats.mean(predicted_confs) - _stats.mean(actual_rates), 4
        )

        non_empty = len(curve)
        overconf  = sum(1 for p in curve if p.predicted_confidence > p.actual_success_rate)
        underconf = sum(1 for p in curve if p.predicted_confidence < p.actual_success_rate)

        result.overconfidence_score  = round(overconf  / non_empty * 100, 2) if non_empty > 0 else 0.0
        result.underconfidence_score = round(underconf / non_empty * 100, 2) if non_empty > 0 else 0.0

    return result
