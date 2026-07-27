"""
preopen_validation_outcomes.py — Phase 5B outcome classifier.

Classifies each pre-open candidate after post-open prices are collected.
Thresholds are transparent and documented here; they are NOT optimised on
a single day of data and must not be changed without multiple sessions of
evidence.

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists in this module.
"""
from __future__ import annotations

from typing import Optional, Tuple
from preopen_validation_model import ValidationRecord, OutcomeClass, DataQualityStatus, ValidationStatus


# ── Threshold constants (documented, not tuned) ───────────────────────────────

# A "strong continuation" requires this minimum return at 09:30 relative to open.
STRONG_CONTINUATION_RETURN_PCT   = 1.0    # ≥ 1.0% at 09:30
MODERATE_CONTINUATION_RETURN_PCT = 0.0    # > 0% but < strong threshold
FLAT_BAND_PCT                    = 0.25   # within ±0.25% considered flat

# Early reversal: price moves against pre-open direction within first 15 min.
# We use price_0920 as the 15-min proxy.
EARLY_REVERSAL_THRESHOLD_PCT     = -0.3   # at least 0.3% against direction within 15 min

# Max adverse excursion allowed while still calling STRONG_CONTINUATION.
STRONG_CONTINUATION_MAX_MAE_PCT  = 1.0    # MAE must be within 1.0%

# No-liquidity: post-open volume too thin to form a reliable outcome.
# Without volume data we use a proxy: if executed_quantity was 0 and
# intraday range is microscopic.
NO_LIQUIDITY_RANGE_PCT           = 0.1    # intraday range (H-L)/open < 0.1%


def _is_bullish(record: ValidationRecord) -> bool:
    """True when the pre-open signal was a gap-up or buy-imbalance candidate."""
    gap = record.gap_percent or 0.0
    imp = record.imbalance_percent or 0.0
    return gap > 0 or imp > 0


def _check_data_quality(record: ValidationRecord) -> Tuple[str, str]:
    """
    Return (data_quality_status, reason).
    Called before classification — poor data is flagged and excluded.
    """
    if record.actual_open is None:
        return DataQualityStatus.MISSING, "actual_open missing"
    if record.validation_status == ValidationStatus.EXCLUDED:
        return DataQualityStatus.INVALID, "record excluded"
    # Count available checkpoints
    checkpoints = [record.price_0920, record.price_0930,
                   record.price_1000, record.price_1030, record.closing_price]
    present = sum(1 for p in checkpoints if p is not None)
    if present == 0:
        return DataQualityStatus.MISSING, "no post-open checkpoints"
    if present < 3:
        return DataQualityStatus.PARTIAL, f"only {present}/5 checkpoints present"
    return DataQualityStatus.COMPLETE, "ok"


def classify_outcome(record: ValidationRecord) -> Tuple[str, str, bool, bool]:
    """
    Apply outcome classification to a ValidationRecord.

    Returns:
        (outcome, reason, continuation_flag, reversal_flag)

    Thresholds are fixed; do not adjust based on single-session results.
    """
    # ── Guard: stale or invalid pre-open data ─────────────────────────────────
    if record.data_quality_status in (DataQualityStatus.STALE,):
        return OutcomeClass.INVALID_SIGNAL, "Pre-open snapshot was stale", False, False

    dq, dq_reason = _check_data_quality(record)
    if dq in (DataQualityStatus.MISSING, DataQualityStatus.INVALID):
        return OutcomeClass.DATA_INCOMPLETE, dq_reason, False, False

    base = record.actual_open
    bullish = _is_bullish(record)
    gap = record.gap_percent or 0.0

    # ── No-liquidity check ────────────────────────────────────────────────────
    if record.intraday_high is not None and record.intraday_low is not None and base and base > 0:
        intraday_range_pct = (record.intraday_high - record.intraday_low) / base * 100
        if intraday_range_pct < NO_LIQUIDITY_RANGE_PCT and record.executed_quantity == 0:
            return OutcomeClass.NO_LIQUIDITY, "Intraday range too narrow and zero executed qty", False, False

    # ── Early reversal (within first 15 min, proxy = 09:20) ──────────────────
    if record.price_0920 is not None and base and base > 0:
        r0920 = (record.price_0920 - base) / base * 100
        if bullish and r0920 <= EARLY_REVERSAL_THRESHOLD_PCT:
            return OutcomeClass.EARLY_REVERSAL, f"Bearish at 09:20: {r0920:.2f}% (threshold {EARLY_REVERSAL_THRESHOLD_PCT}%)", False, True
        if not bullish and r0920 >= -EARLY_REVERSAL_THRESHOLD_PCT:
            return OutcomeClass.EARLY_REVERSAL, f"Bullish reversal at 09:20: {r0920:.2f}%", False, True

    # ── Use 09:30 as the primary verdict checkpoint ───────────────────────────
    r0930 = record.return_0930
    if r0930 is None and record.price_0930 is not None and base and base > 0:
        r0930 = (record.price_0930 - base) / base * 100

    if r0930 is None:
        # Fall back to 10:00 if 09:30 unavailable
        if record.price_1000 is not None and base and base > 0:
            r0930 = (record.price_1000 - base) / base * 100
        else:
            return OutcomeClass.DATA_INCOMPLETE, "09:30 and 10:00 prices both missing", False, False

    mae = record.max_adverse_excursion or 0.0

    # ── Bullish candidate outcome paths ──────────────────────────────────────
    # FLAT is evaluated before MODERATE so that returns inside ±0.25% do not
    # incorrectly trigger MODERATE_CONTINUATION.
    if bullish:
        if r0930 >= STRONG_CONTINUATION_RETURN_PCT and mae <= STRONG_CONTINUATION_MAX_MAE_PCT:
            return OutcomeClass.STRONG_CONTINUATION, (
                f"09:30 return {r0930:.2f}% ≥ {STRONG_CONTINUATION_RETURN_PCT}%, "
                f"MAE {mae:.2f}% within limit"
            ), True, False

        if abs(r0930) <= FLAT_BAND_PCT:
            # False breakout: meaningful gap-up but price stays flat at 09:30
            if gap >= 1.0:
                return OutcomeClass.FALSE_BREAKOUT, f"Gap-up {gap:.2f}% failed to continue, flat at 09:30 ({r0930:.2f}%)", False, False
            return OutcomeClass.FLAT, f"09:30 return {r0930:.2f}% within flat band ±{FLAT_BAND_PCT}%", False, False

        if r0930 > FLAT_BAND_PCT:
            # Check late reversal — did it close negative?
            if record.closing_return is not None and record.closing_return < 0:
                return OutcomeClass.LATE_REVERSAL, (
                    f"Initial continuation ({r0930:.2f}% at 09:30) reversed by close "
                    f"({record.closing_return:.2f}%)"
                ), False, True
            return OutcomeClass.MODERATE_CONTINUATION, f"09:30 return {r0930:.2f}% (positive, below strong threshold)", True, False

        # Negative beyond flat band at 09:30 → gap-up continuation failed
        if r0930 < -FLAT_BAND_PCT:
            return OutcomeClass.EARLY_REVERSAL, f"Gap-up reversed by 09:30: {r0930:.2f}%", False, True

    # ── Bearish candidate outcome paths ──────────────────────────────────────
    else:
        if r0930 <= -STRONG_CONTINUATION_RETURN_PCT and mae <= STRONG_CONTINUATION_MAX_MAE_PCT:
            return OutcomeClass.STRONG_CONTINUATION, (
                f"09:30 return {r0930:.2f}% ≤ -{STRONG_CONTINUATION_RETURN_PCT}%, "
                f"MAE {mae:.2f}% within limit"
            ), True, False

        if abs(r0930) <= FLAT_BAND_PCT:
            if gap <= -1.0:
                return OutcomeClass.FALSE_BREAKOUT, f"Gap-down {gap:.2f}% failed to continue, flat at 09:30 ({r0930:.2f}%)", False, False
            return OutcomeClass.FLAT, f"09:30 return {r0930:.2f}% within flat band ±{FLAT_BAND_PCT}%", False, False

        if r0930 < -FLAT_BAND_PCT:
            if record.closing_return is not None and record.closing_return > 0:
                return OutcomeClass.LATE_REVERSAL, (
                    f"Initial continuation ({r0930:.2f}% at 09:30) reversed by close "
                    f"({record.closing_return:.2f}%)"
                ), False, True
            return OutcomeClass.MODERATE_CONTINUATION, f"09:30 return {r0930:.2f}% (negative, below strong threshold)", True, False

        if r0930 > FLAT_BAND_PCT:
            return OutcomeClass.EARLY_REVERSAL, f"Gap-down reversed by 09:30: {r0930:.2f}%", False, True

    return OutcomeClass.FLAT, f"09:30 return {r0930:.2f}% — no clear outcome", False, False


def classify_and_update(record: ValidationRecord) -> ValidationRecord:
    """
    Classify the record in-place and update all outcome fields.
    Returns the modified record.
    """
    dq, _ = _check_data_quality(record)
    record.data_quality_status = dq

    outcome, reason, cont, rev = classify_outcome(record)
    record.prediction_result = outcome
    record.continuation_flag = cont
    record.reversal_flag = rev

    if dq in (DataQualityStatus.MISSING, DataQualityStatus.INVALID):
        record.validation_status = ValidationStatus.EXCLUDED
    elif dq == DataQualityStatus.PARTIAL:
        record.validation_status = ValidationStatus.PARTIAL
    else:
        record.validation_status = ValidationStatus.COMPLETE

    from preopen_validation_model import now_utc
    record.updated_at = now_utc()
    return record
