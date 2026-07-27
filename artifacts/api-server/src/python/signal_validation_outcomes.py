"""
signal_validation_outcomes.py — Phase 5C outcome classification.

Classifies each completed signal into one of 18 outcome classes.
Uses configurable thresholds (does NOT modify strategy thresholds).

Supports:
  - Long signals (BUY, STRONG_BUY)
  - Short signals (SELL, STRONG_SELL) — where supported
  - Signals that never became trades (risk-rejected, expired, stale)
  - Hypothetical outcomes for missed/rejected signals

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from signal_validation_model import OutcomeClass, LifecycleState, SignalValidationRecord

# ── Configurable thresholds (analysis only — never strategy thresholds) ────────

STRONG_SUCCESS_PCT   = Decimal("2.0")
MODERATE_SUCCESS_PCT = Decimal("0.75")
SMALL_SUCCESS_PCT    = Decimal("0.25")
FLAT_BAND_PCT        = Decimal("0.25")   # ±0.25% = FLAT
SMALL_FAILURE_PCT    = Decimal("-0.5")
MODERATE_FAILURE_PCT = Decimal("-1.5")

EARLY_REVERSAL_MINUTES = 15   # Reversal within 15min of entry = EARLY_REVERSAL


def classify(rec: SignalValidationRecord) -> str:
    """
    Classify a signal into one of 18 outcome classes.
    Returns an OutcomeClass constant.
    """
    status = rec.validation_status

    # Terminal non-trade states
    if status == LifecycleState.INVALID_DATA:
        return OutcomeClass.INVALID_SIGNAL
    if status == LifecycleState.STALE_DATA:
        return OutcomeClass.INVALID_SIGNAL
    if status in (LifecycleState.EXPIRED, LifecycleState.SIGNAL_EXPIRED
                  if hasattr(LifecycleState, "SIGNAL_EXPIRED") else "SIGNAL_EXPIRED"):
        return OutcomeClass.SIGNAL_EXPIRED

    # Risk-rejected signals
    if status == LifecycleState.RISK_REJECTED:
        return _classify_risk_rejected(rec)

    # Signals that never reached trade (no paper order)
    if status in (LifecycleState.MISSED, LifecycleState.NO_TRADE, LifecycleState.CANCELLED):
        return OutcomeClass.DATA_INCOMPLETE

    # Active/open positions — incomplete data
    if status in (LifecycleState.OPEN_POSITION, LifecycleState.PAPER_ORDER_FILLED,
                  LifecycleState.PAPER_ORDER_CREATED, LifecycleState.APPROVED):
        return OutcomeClass.DATA_INCOMPLETE

    # Closed position — main classification path
    if status == LifecycleState.CLOSED_POSITION:
        return _classify_closed(rec)

    return OutcomeClass.DATA_INCOMPLETE


def _classify_risk_rejected(rec: SignalValidationRecord) -> str:
    """For risk-rejected signals, check hypothetical outcome."""
    # Need hypothetical price data to judge whether rejection was valid
    hyp = _hyp_return(rec)
    if hyp is None:
        return OutcomeClass.RISK_REJECTED_VALIDLY  # no data = assume valid

    # If signal would have succeeded significantly, rejection was bad
    if hyp >= STRONG_SUCCESS_PCT:
        return OutcomeClass.RISK_REJECTED_BUT_SIGNAL_SUCCEEDED
    return OutcomeClass.RISK_REJECTED_VALIDLY


def _classify_closed(rec: SignalValidationRecord) -> str:
    """Classify a fully-closed position."""
    exit_reason = (rec.exit_reason or "").upper()
    r = rec.R_multiple
    pnl_pct = _realised_pct(rec)

    if pnl_pct is None:
        return OutcomeClass.DATA_INCOMPLETE

    # Named exit types
    if "STOP" in exit_reason or "STOP_LOSS" in exit_reason:
        return OutcomeClass.STOPPED_OUT
    if "TARGET" in exit_reason:
        return OutcomeClass.TARGET_REACHED
    if "TIME" in exit_reason or "EOD" in exit_reason or "CLOSE" in exit_reason:
        # Check if it reversed early
        if _is_early_reversal(rec):
            return OutcomeClass.EARLY_REVERSAL
        return OutcomeClass.TIME_EXIT

    # Check for false breakout: initial move in signal direction then reversal
    if _is_false_breakout(rec):
        return OutcomeClass.FALSE_BREAKOUT

    # Check for late reversal
    if _is_late_reversal(rec):
        return OutcomeClass.LATE_REVERSAL

    # Return-based classification
    if pnl_pct >= STRONG_SUCCESS_PCT:
        return OutcomeClass.STRONG_SUCCESS
    if pnl_pct >= MODERATE_SUCCESS_PCT:
        return OutcomeClass.MODERATE_SUCCESS
    if pnl_pct >= SMALL_SUCCESS_PCT:
        return OutcomeClass.SMALL_SUCCESS
    if pnl_pct >= -FLAT_BAND_PCT:
        return OutcomeClass.FLAT
    if pnl_pct >= SMALL_FAILURE_PCT:
        return OutcomeClass.SMALL_FAILURE
    if pnl_pct >= MODERATE_FAILURE_PCT:
        return OutcomeClass.MODERATE_FAILURE
    return OutcomeClass.STRONG_FAILURE


def _realised_pct(rec: SignalValidationRecord) -> Optional[Decimal]:
    if rec.entry_price is None or rec.exit_price is None or rec.entry_price == 0:
        return None
    if rec.signal_direction in ("BUY", "STRONG_BUY"):
        return (rec.exit_price - rec.entry_price) / rec.entry_price * 100
    else:
        return (rec.entry_price - rec.exit_price) / rec.entry_price * 100


def _hyp_return(rec: SignalValidationRecord) -> Optional[Decimal]:
    """Best available hypothetical return from price checkpoints."""
    for v in (rec.hyp_return_60m, rec.hyp_return_30m, rec.hyp_return_15m, rec.hyp_return_5m):
        if v is not None:
            return v
    return None


def _is_early_reversal(rec: SignalValidationRecord) -> bool:
    """True if MFE was positive but exit was at a loss within the early window."""
    if rec.max_favourable_excursion is None or rec.realised_pnl is None:
        return False
    # Signal made a positive excursion but closed at a loss early
    return (rec.max_favourable_excursion > Decimal("0.5")
            and rec.realised_pnl is not None and rec.realised_pnl < 0)


def _is_false_breakout(rec: SignalValidationRecord) -> bool:
    """True if there was a positive MFE followed by a negative MAE indicating reversal."""
    if rec.max_favourable_excursion is None or rec.max_adverse_excursion is None:
        return False
    return (rec.max_favourable_excursion > Decimal("1.0")
            and rec.max_adverse_excursion < Decimal("-1.0")
            and _realised_pct(rec) is not None
            and _realised_pct(rec) < Decimal("0"))


def _is_late_reversal(rec: SignalValidationRecord) -> bool:
    """Profitable for a while, then reversed late to a loss."""
    pct = _realised_pct(rec)
    if pct is None:
        return False
    return (rec.max_favourable_excursion is not None
            and rec.max_favourable_excursion > Decimal("1.5")
            and pct < Decimal("-0.5"))


def classify_and_update(rec: SignalValidationRecord) -> SignalValidationRecord:
    """Classify and update the record in place. Returns the updated record."""
    rec.outcome_class = classify(rec)

    # Set hypothetical label for missed/rejected signals
    if rec.is_hypothetical or rec.validation_status in (
        LifecycleState.RISK_REJECTED, LifecycleState.MISSED
    ):
        rec.is_hypothetical = True
        rec.hypothetical_label = "HYPOTHETICAL — NOT A TRADE"

    # Compute R if not set
    if rec.R_multiple is None:
        rec.R_multiple = rec.compute_r_multiple()

    # Compute realised P&L if not set
    if rec.realised_pnl is None:
        rec.realised_pnl = rec.compute_realised_pnl()

    return rec


def is_success(outcome: str) -> bool:
    return outcome in (
        OutcomeClass.STRONG_SUCCESS, OutcomeClass.MODERATE_SUCCESS,
        OutcomeClass.SMALL_SUCCESS, OutcomeClass.TARGET_REACHED,
    )


def is_failure(outcome: str) -> bool:
    return outcome in (
        OutcomeClass.STRONG_FAILURE, OutcomeClass.MODERATE_FAILURE,
        OutcomeClass.SMALL_FAILURE, OutcomeClass.STOPPED_OUT,
        OutcomeClass.FALSE_BREAKOUT, OutcomeClass.EARLY_REVERSAL,
        OutcomeClass.LATE_REVERSAL,
    )
