"""
paper_analytics/preopen_analytics.py — Phase 8.2
Pre-open validation analytics derived from preopen_accuracy module.

REAL preopen_accuracy symbol row fields (confirmed from live get_accuracy()):
  symbol, indicative_price, actual_open, price_at_0920, price_at_0930,
  error_pct, direction_correct, was_in_watchlist, watchlist_confirmed

UNAVAILABLE fields (NOT emitted by the upstream module):
  opening_reversal, opening_continuation, session_minutes,
  session_high, session_low, trend_day.

Consequently:
  gap_and_go    — available  (derived from direction_correct)
  gap_fill      — UNAVAILABLE (requires opening_reversal field)
  early_reversal— UNAVAILABLE (requires session_minutes field)
  late_reversal — UNAVAILABLE (requires opening_reversal field)
  range_day     — UNAVAILABLE (requires intraday OHLC)
  trend_day     — UNAVAILABLE (requires intraday OHLC)

MFE/MAE: intraday high/low not in source; we expose:
  mae_open_vs_indicative_pct — mean |error_pct| (open vs indicative only)
  max_abs_error_pct          — max |error_pct| observed
  mfe_available: False       — explicitly marked unavailable

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations

import statistics as _stats
from typing import Any, Dict, List


def _score_band_accuracy(symbols: List[dict]) -> List[Dict[str, Any]]:
    """Group symbols by pre-open score band and compute per-band accuracy."""
    bands: Dict[str, list] = {}
    for s in symbols:
        score = s.get("preopen_score") or s.get("score")
        if score is None:
            band = "No Score"
        elif score >= 80:
            band = "80–100 (Strong)"
        elif score >= 60:
            band = "60–79 (Moderate)"
        elif score >= 40:
            band = "40–59 (Weak)"
        else:
            band = "0–39 (Very Weak)"
        bands.setdefault(band, []).append(s)

    rows = []
    for band, syms in bands.items():
        correct = sum(1 for s in syms if s.get("direction_correct") is True)
        n       = len(syms)
        rows.append({
            "band":     band,
            "count":    n,
            "accuracy": round(correct / n * 100, 2) if n > 0 else 0.0,
        })
    return sorted(rows, key=lambda r: -r["accuracy"])


def _classify_trends(symbols: List[dict]) -> Dict[str, Any]:
    """
    Classify opening outcomes from available preopen_accuracy symbol data.

    The upstream get_accuracy() emits direction_correct per symbol but NOT
    opening_reversal, opening_continuation, or session_minutes.  Only
    gap_and_go can be computed from the available fields.  All other
    sub-classifications (gap_fill, early/late reversal, range-day,
    trend-day) require fields not present in the data source and are
    explicitly marked unavailable to prevent silent misreporting.
    """
    total = len(symbols)

    # Fields we would need but do NOT have from get_accuracy() symbol rows
    has_opening_reversal = any("opening_reversal" in s for s in symbols)
    has_session_minutes  = any("session_minutes"  in s for s in symbols)

    gap_go = sum(1 for s in symbols if s.get("direction_correct") is True)

    result: Dict[str, Any] = {
        "gap_and_go_count": gap_go,
        "gap_and_go_rate":  round(gap_go / total * 100, 2) if total > 0 else 0.0,
        # Reversal sub-classifications — unavailable from current upstream data
        "gap_fill_available":       has_opening_reversal,
        "early_reversal_available": has_opening_reversal and has_session_minutes,
        "late_reversal_available":  has_opening_reversal,
        "range_day_available":      False,  # requires intraday OHLC
        "trend_day_available":      False,  # requires intraday OHLC
        "intraday_ohlc_required":   True,
        "note": (
            "gap_fill, early/late reversal, range-day, and trend-day "
            "classifications require opening_reversal, session_minutes, or "
            "intraday OHLC fields not emitted by the pre-open accuracy module. "
            "Only gap_and_go (from direction_correct) is computed."
        ),
    }

    # If the upstream ever gains these fields, compute them
    if has_opening_reversal:
        gap_fill = sum(1 for s in symbols if s.get("opening_reversal") is True)
        late_rev = gap_fill
        early_rev = 0
        if has_session_minutes:
            early_rev = sum(
                1 for s in symbols
                if s.get("opening_reversal") is True
                and (s.get("session_minutes") or 999) < 30
            )
            late_rev = max(0, gap_fill - early_rev)
        result.update({
            "gap_fill_count":       gap_fill,
            "gap_fill_rate":        round(gap_fill  / total * 100, 2) if total > 0 else 0.0,
            "early_reversal_count": early_rev,
            "early_reversal_rate":  round(early_rev / total * 100, 2) if total > 0 else 0.0,
            "late_reversal_count":  late_rev,
            "late_reversal_rate":   round(late_rev  / total * 100, 2) if total > 0 else 0.0,
        })

    return result


def _mae_from_symbols(symbols: List[dict]) -> Dict[str, Any]:
    """
    Compute mean and max absolute indicative-to-open error from symbol list.

    Clearly labelled: open-price vs indicative-price error only.
    NOT intraday MAE/MFE (which require session_high/session_low).
    """
    errors = []
    for s in symbols:
        ep = s.get("error_pct")
        if ep is not None:
            try:
                errors.append(abs(float(ep)))
            except (TypeError, ValueError):
                pass

    if not errors:
        return {
            "mae_open_vs_indicative_pct": None,
            "max_abs_error_pct":          None,
            "mfe_available":              False,
            "mfe_note": (
                "MFE (maximum favourable excursion) requires intraday high/low "
                "price per symbol — not available from the pre-open data source."
            ),
        }

    return {
        "mae_open_vs_indicative_pct": round(_stats.mean(errors), 4),
        "max_abs_error_pct":          round(max(errors), 4),
        "mfe_available":              False,
        "mfe_note": (
            "MFE (maximum favourable excursion) requires intraday high/low "
            "price per symbol — not available from the pre-open data source."
        ),
    }


def get_preopen_analytics() -> Dict[str, Any]:
    """
    Pre-open analytics integrating preopen_accuracy session and history data.
    """
    try:
        from preopen_accuracy import get_accuracy, get_accuracy_history
    except ImportError:
        return {
            "available":     False,
            "advisory_only": True,
            "message":       "preopen_accuracy module not available.",
        }

    # Latest session
    acc  = get_accuracy()
    hist = get_accuracy_history(n_sessions=10)

    symbols       = acc.get("symbols", [])
    score_bands   = _score_band_accuracy(symbols)
    trend_class   = _classify_trends(symbols)
    error_metrics = _mae_from_symbols(symbols)

    # History
    session_history = hist.get("sessions", [])
    history_series  = [
        {
            "trading_date":     s.get("trading_date"),
            "hit_rate_pct":     s.get("hit_rate_pct"),
            "mae_pct":          s.get("avg_indicative_to_open_error_pct"),
            "symbols_count":    s.get("symbols_reconciled"),
            "continuation_pct": s.get("continuation_rate_pct"),
            "reversal_pct":     s.get("reversal_rate_pct"),
            "grade":            s.get("grade"),
        }
        for s in session_history
    ]

    return {
        "available":     True,
        "advisory_only": True,
        "latest_session": {
            "trading_date":            acc.get("trading_date"),
            "symbols_reconciled":      acc.get("symbols_reconciled", 0),
            "hit_rate_pct":            acc.get("hit_rate_pct"),
            "continuation_rate_pct":   acc.get("continuation_rate_pct"),
            "reversal_rate_pct":       acc.get("reversal_rate_pct"),
            "confirmation_rate_pct":   acc.get("confirmation_rate_pct"),
            "false_positive_rate_pct": acc.get("false_positive_rate_pct"),
            "mae_pct":                 acc.get("avg_indicative_to_open_error_pct"),
            "grade":                   acc.get("grade"),
            "grade_label":             acc.get("grade_label"),
        },
        # Error metrics (open vs indicative only — NOT intraday excursion)
        **error_metrics,
        "score_band_accuracy":  score_bands,
        "trend_classification": trend_class,
        "history_sessions":     len(session_history),
        "history":              history_series,
        "symbols":              symbols,
    }
