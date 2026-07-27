"""
preopen_validation_metrics.py — Phase 5B accuracy metrics calculator.

Computes all 20 accuracy metrics, 6 score bands, 8 factor analyses,
and multi-dimension breakdowns from a list of ValidationRecord objects.

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists in this module.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from preopen_validation_model import (
    ValidationRecord, OutcomeClass, DataQualityStatus, ValidationStatus
)


# ── Score band definitions ────────────────────────────────────────────────────

SCORE_BANDS = [
    ("90-100", 90, 100),
    ("80-89",  80,  89),
    ("70-79",  70,  79),
    ("60-69",  60,  69),
    ("50-59",  50,  59),
    ("below-50", 0, 49),
]


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0:
        return default
    return round(num / den, 4)


def _avg(values: list) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _pct(count: int, total: int) -> float:
    return round(_safe_div(count, total) * 100, 2)


def _is_valid(r: ValidationRecord) -> bool:
    """A record is valid for metrics if not EXCLUDED and has actual_open."""
    return (
        r.validation_status != ValidationStatus.EXCLUDED
        and r.data_quality_status not in (DataQualityStatus.MISSING, DataQualityStatus.INVALID)
        and r.actual_open is not None
    )


def _is_continuation(r: ValidationRecord) -> bool:
    return r.prediction_result in (OutcomeClass.STRONG_CONTINUATION, OutcomeClass.MODERATE_CONTINUATION)


def _is_reversal(r: ValidationRecord) -> bool:
    return r.prediction_result in (OutcomeClass.EARLY_REVERSAL, OutcomeClass.LATE_REVERSAL)


def _is_false_positive(r: ValidationRecord) -> bool:
    """False positive: had an opportunity score but did not continue."""
    return r.opportunity_score >= 50 and not _is_continuation(r)


def _top_n_accuracy(records: List[ValidationRecord], n: int) -> Optional[float]:
    """Accuracy rate for the top-N ranked candidates."""
    ranked = sorted([r for r in records if r.preopen_rank is not None
                     and _is_valid(r)],
                    key=lambda r: r.preopen_rank or 999)[:n]
    if not ranked:
        return None
    cont = sum(1 for r in ranked if _is_continuation(r))
    return round(cont / len(ranked) * 100, 2)


# ── Main metrics calculator ───────────────────────────────────────────────────

def calculate_session_metrics(records: List[ValidationRecord]) -> Dict[str, Any]:
    """
    Compute all 20 accuracy metrics for one trading session.
    Returns a dict safe for JSON serialisation.

    Stale and incomplete records are excluded from accuracy metrics.
    Raw counts are always shown alongside valid counts.
    """
    total = len(records)
    valid = [r for r in records if _is_valid(r)]
    excluded = [r for r in records if not _is_valid(r)]
    confirmed = [r for r in valid if r.prediction_result not in (
        OutcomeClass.DATA_INCOMPLETE, OutcomeClass.INVALID_SIGNAL)]

    cont_records   = [r for r in confirmed if _is_continuation(r)]
    rev_records    = [r for r in confirmed if _is_reversal(r)]
    fp_records     = [r for r in valid if _is_false_positive(r)]

    n_valid = len(valid)
    n_conf  = len(confirmed)

    metrics: Dict[str, Any] = {
        # Counts
        "total_candidates":   total,
        "valid_candidates":   n_valid,
        "confirmed_candidates": n_conf,
        "excluded_candidates": len(excluded),

        # Core rates
        "continuation_rate":   _pct(len(cont_records), n_conf),
        "reversal_rate":       _pct(len(rev_records),  n_conf),
        "false_positive_rate": _pct(len(fp_records),   n_valid),

        # Average returns
        "avg_return_0930":  _avg([r.return_0930 for r in valid]),
        "avg_return_1000":  _avg([r.return_1000 for r in valid]),
        "avg_return_1030":  _avg([r.return_1030 for r in valid]),
        "avg_closing_return": _avg([r.closing_return for r in valid]),
        "avg_mfe":          _avg([r.max_favourable_excursion for r in valid]),
        "avg_mae":          _avg([r.max_adverse_excursion for r in valid]),

        # Rank accuracy
        "top5_accuracy":    _top_n_accuracy(valid, 5),
        "top10_accuracy":   _top_n_accuracy(valid, 10),

        # Gap direction accuracy
        "gap_up_continuation_rate":   _pct(
            sum(1 for r in cont_records if (r.gap_percent or 0) > 0),
            max(1, sum(1 for r in confirmed if (r.gap_percent or 0) > 0))
        ),
        "gap_down_continuation_rate": _pct(
            sum(1 for r in cont_records if (r.gap_percent or 0) < 0),
            max(1, sum(1 for r in confirmed if (r.gap_percent or 0) < 0))
        ),

        # Imbalance accuracy
        "buy_imbalance_success_rate":  _pct(
            sum(1 for r in cont_records if (r.imbalance_percent or 0) > 20),
            max(1, sum(1 for r in confirmed if (r.imbalance_percent or 0) > 20))
        ),
        "sell_imbalance_success_rate": _pct(
            sum(1 for r in cont_records if (r.imbalance_percent or 0) < -20),
            max(1, sum(1 for r in confirmed if (r.imbalance_percent or 0) < -20))
        ),

        # Sector / volume helpers
        "sector_confirmed_success_rate": _pct(
            sum(1 for r in cont_records if (r.sector_score or 0) >= 8),
            max(1, sum(1 for r in confirmed if (r.sector_score or 0) >= 8))
        ),
        "high_volume_success_rate": _pct(
            sum(1 for r in cont_records if r.executed_quantity > 50000),
            max(1, sum(1 for r in confirmed if r.executed_quantity > 50000))
        ),
        "low_liquidity_failure_rate": _pct(
            sum(1 for r in valid if r.prediction_result == OutcomeClass.NO_LIQUIDITY),
            max(1, sum(1 for r in valid if r.liquidity_score < 20))
        ),

        # Sample size warning
        "sample_size_warning": n_conf < 10,
        "data_completeness_pct": _pct(n_valid, total) if total else 0,
    }
    return metrics


# ── Score-band analysis ───────────────────────────────────────────────────────

def calculate_score_bands(records: List[ValidationRecord]) -> List[Dict[str, Any]]:
    """
    Return per-band statistics for the 6 score bands defined by the spec.
    Bands that contain 0 valid records still appear (with null metrics).
    """
    valid = [r for r in records if _is_valid(r)]
    result = []
    for band_label, lo, hi in SCORE_BANDS:
        band = [r for r in valid if lo <= r.opportunity_score <= hi]
        cont  = [r for r in band if _is_continuation(r)]
        rev   = [r for r in band if _is_reversal(r)]
        n = len(band)
        result.append({
            "band":              band_label,
            "score_min":         lo,
            "score_max":         hi,
            "candidates":        n,
            "continuation_rate": _pct(len(cont), n) if n else None,
            "reversal_rate":     _pct(len(rev),  n) if n else None,
            "avg_return_0930":   _avg([r.return_0930 for r in band]),
            "avg_return_1030":   _avg([r.return_1030 for r in band]),
            "avg_closing_return": _avg([r.closing_return for r in band]),
            "avg_mfe":           _avg([r.max_favourable_excursion for r in band]),
            "avg_mae":           _avg([r.max_adverse_excursion for r in band]),
            "sample_size_warning": n < 5,
            "inconclusive":      n < 3,
        })
    return result


# ── Factor contribution analysis ──────────────────────────────────────────────

_FACTORS = [
    "gap_strength",
    "order_imbalance",
    "executed_quantity",
    "liquidity",
    "sector_confirmation",
    "index_direction",
    "data_freshness",
    "volatility_risk",
]


def _get_factor_score(record: ValidationRecord, factor: str) -> Optional[float]:
    """Extract per-factor score from record. Records store factor_scores as dict in DB."""
    # ValidationRecord doesn't directly hold factor_scores — they live in the
    # Phase 5A snapshot. We proxy via the available scalar fields.
    proxies = {
        "gap_strength":       abs(record.gap_percent or 0),
        "order_imbalance":    abs(record.imbalance_percent or 0),
        "executed_quantity":  record.executed_quantity,
        "liquidity":          record.liquidity_score,
        "sector_confirmation": record.sector_score,
        "index_direction":    abs(record.index_context or 0),
        "data_freshness":     None,   # not available post-hoc
        "volatility_risk":    record.vix_context,
    }
    return proxies.get(factor)


def calculate_factor_metrics(records: List[ValidationRecord]) -> List[Dict[str, Any]]:
    """
    For each of the 8 Phase 5A factors, compute:
      factor_success_rate, factor_avg_return, factor_failure_rate,
      factor_reliability_score, sample_size
    """
    valid = [r for r in records if _is_valid(r)]
    result = []
    for factor in _FACTORS:
        # Split into high/low factor presence using a simple median split
        with_factor = [r for r in valid if _get_factor_score(r, factor) is not None
                       and _get_factor_score(r, factor) > 0]
        n = len(with_factor)
        cont = [r for r in with_factor if _is_continuation(r)]
        fail = [r for r in with_factor if _is_reversal(r) or
                r.prediction_result == OutcomeClass.NO_LIQUIDITY]

        success_rate = _pct(len(cont), n) if n else None
        failure_rate = _pct(len(fail), n) if n else None
        avg_ret      = _avg([r.return_0930 for r in with_factor])

        # Reliability score: success_rate - failure_rate (0-100), None if inconclusive
        reliability = None
        if success_rate is not None and failure_rate is not None:
            reliability = round(max(0.0, success_rate - failure_rate), 2)

        result.append({
            "factor":             factor,
            "sample_size":        n,
            "factor_success_rate": success_rate,
            "factor_avg_return":  avg_ret,
            "factor_failure_rate": failure_rate,
            "factor_reliability_score": reliability,
            "inconclusive":       n < 5,
            "note": "Insufficient data — treat as inconclusive" if n < 5 else None,
        })
    return result


# ── Multi-dimension breakdowns ────────────────────────────────────────────────

def calculate_sector_breakdown(records: List[ValidationRecord]) -> List[Dict[str, Any]]:
    valid = [r for r in records if _is_valid(r)]
    sectors: Dict[str, list] = {}
    for r in valid:
        sectors.setdefault(r.sector or "Unknown", []).append(r)
    result = []
    for sec, recs in sorted(sectors.items()):
        cont = [r for r in recs if _is_continuation(r)]
        result.append({
            "sector":            sec,
            "candidates":        len(recs),
            "continuation_rate": _pct(len(cont), len(recs)),
            "avg_return_0930":   _avg([r.return_0930 for r in recs]),
            "avg_return_1030":   _avg([r.return_1030 for r in recs]),
            "inconclusive":      len(recs) < 3,
        })
    return result


def calculate_gap_breakdown(records: List[ValidationRecord]) -> List[Dict[str, Any]]:
    valid = [r for r in records if _is_valid(r)]
    bands = [
        ("gap_up_strong",    lambda r: (r.gap_percent or 0) >= 2.0),
        ("gap_up_moderate",  lambda r: 0.5 <= (r.gap_percent or 0) < 2.0),
        ("flat",             lambda r: abs(r.gap_percent or 0) < 0.5),
        ("gap_down_moderate",lambda r: -2.0 < (r.gap_percent or 0) <= -0.5),
        ("gap_down_strong",  lambda r: (r.gap_percent or 0) <= -2.0),
    ]
    result = []
    for label, fn in bands:
        recs = [r for r in valid if fn(r)]
        cont = [r for r in recs if _is_continuation(r)]
        result.append({
            "band":            label,
            "candidates":      len(recs),
            "continuation_rate": _pct(len(cont), len(recs)) if recs else None,
            "avg_return_0930": _avg([r.return_0930 for r in recs]),
            "inconclusive":    len(recs) < 3,
        })
    return result


def calculate_vix_breakdown(records: List[ValidationRecord]) -> List[Dict[str, Any]]:
    valid = [r for r in records if _is_valid(r) and r.vix_context is not None]
    bands = [
        ("low_vix_<15",    lambda r: (r.vix_context or 0) < 15),
        ("normal_15-20",   lambda r: 15 <= (r.vix_context or 0) < 20),
        ("elevated_20-25", lambda r: 20 <= (r.vix_context or 0) < 25),
        ("high_vix_>=25",  lambda r: (r.vix_context or 0) >= 25),
    ]
    result = []
    for label, fn in bands:
        recs = [r for r in valid if fn(r)]
        cont = [r for r in recs if _is_continuation(r)]
        result.append({
            "regime":          label,
            "candidates":      len(recs),
            "continuation_rate": _pct(len(cont), len(recs)) if recs else None,
            "avg_return_0930": _avg([r.return_0930 for r in recs]),
            "inconclusive":    len(recs) < 3,
        })
    return result
