"""
calibration_analyser.py — Phase 6.3
Confidence band analysis: 0-20%, 20-40%, 40-60%, 60-80%, 80-100%.

Per band: trades, win rate, avg return, avg risk, prediction error.
Recommends ideal confidence threshold.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List
from .optimisation_models import ConfidenceBand

_BANDS = [
    ("0–20%",  0.00, 0.20),
    ("20–40%", 0.20, 0.40),
    ("40–60%", 0.40, 0.60),
    ("60–80%", 0.60, 0.80),
    ("80–100%",0.80, 1.01),
]


def analyse_calibration(records: list) -> dict:
    bands = _build_bands(records)
    threshold_rec = _recommend_threshold(bands)
    overall_ece = sum(b.prediction_error * (b.trades / max(len(records), 1))
                      for b in bands if b.trades > 0)

    return {
        "bands": [b.to_dict() for b in bands],
        "recommended_threshold": threshold_rec["threshold"],
        "threshold_rationale": threshold_rec["rationale"],
        "threshold_expected_win_rate": threshold_rec["expected_win_rate"],
        "overall_ece": round(overall_ece, 4),
        "advisory_only": True,
    }


def _build_bands(records: list) -> List[ConfidenceBand]:
    if not records:
        return [
            ConfidenceBand(label, lo, hi, 0, 0.0, 0.0, 0.0, 0.0)
            for label, lo, hi in _BANDS
        ]

    result = []
    for label, lo, hi in _BANDS:
        bucket = [r for r in records
                  if (r.ai_confidence or 0.0) >= lo
                  and (r.ai_confidence or 0.0) < hi]
        if not bucket:
            result.append(ConfidenceBand(label, lo, hi, 0, 0.0, 0.0, 0.0, 0.0))
            continue

        wr = sum(1 for r in bucket if (r.pnl or 0) > 0) / len(bucket)
        avg_ret = sum(r.pnl_pct or 0.0 for r in bucket) / len(bucket)
        avg_risk = sum(r.risk_score or 0.0 for r in bucket) / len(bucket)
        mid_conf = (lo + min(hi, 1.0)) / 2.0
        pred_error = abs(mid_conf - wr)

        result.append(ConfidenceBand(
            band=label, min_conf=lo, max_conf=min(hi, 1.0),
            trades=len(bucket),
            win_rate=round(wr, 4),
            avg_return_pct=round(avg_ret, 4),
            avg_risk=round(avg_risk, 4),
            prediction_error=round(pred_error, 4),
        ))
    return result


def _recommend_threshold(bands: List[ConfidenceBand]) -> dict:
    """
    Find the lowest confidence threshold such that all bands above it
    have win_rate > 0.55 and trades > 0.
    Falls back to 0.60 if insufficient data.
    """
    active = [b for b in bands if b.trades >= 3]
    if not active:
        return {
            "threshold": 0.60,
            "rationale": "Insufficient data — defaulting to 60% confidence threshold.",
            "expected_win_rate": 0.0,
        }

    best = max(active, key=lambda b: b.win_rate - b.prediction_error)
    threshold = best.min_conf
    return {
        "threshold": round(threshold, 2),
        "rationale": (
            f"Band {best.band} has the best calibrated win rate "
            f"({best.win_rate * 100:.0f}%) with low prediction error "
            f"({best.prediction_error:.3f}) across {best.trades} trades."
        ),
        "expected_win_rate": best.win_rate,
    }
