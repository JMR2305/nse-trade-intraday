"""
execution_quality/report.py — Trade quality scoring.

Score weighting:
  30%  Entry quality   (low slippage)
  25%  Exit quality    (exit type)
  20%  Fill speed      (delay to fill)
  15%  Stop execution  (stop-loss was set)
  10%  Target execution (target was set and reached)

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations
from .models import ExecutionRecord


def score_trade(rec: ExecutionRecord) -> tuple[int, str]:
    """Return (0-100 score, grade label) for one ExecutionRecord."""

    # ── Entry quality (0–30) ─────────────────────────────────────────────────
    # Deduct 5 points per 0.1% of entry slippage.
    slip_pct = abs(rec.entry_slippage_pct)
    entry_score = max(0.0, 30.0 - slip_pct * 50.0)

    # ── Exit quality (0–25) ──────────────────────────────────────────────────
    _exit_map = {
        "TARGET_HIT":  25,
        "SIGNAL_EXIT": 18,
        "MANUAL":      12,
        "STOP_HIT":     8,
    }
    if rec.is_complete:
        exit_score = float(_exit_map.get((rec.exit_type or "").upper(), 12))
    else:
        exit_score = 12.0   # open position — partial credit

    # ── Fill speed (0–20) ────────────────────────────────────────────────────
    d = rec.fill_delay_seconds
    if d < 5:
        fill_score = 20.0
    elif d < 30:
        fill_score = 15.0
    elif d < 60:
        fill_score = 10.0
    elif d < 300:
        fill_score = 5.0
    else:
        fill_score = 2.0

    # ── Stop execution (0–15) ────────────────────────────────────────────────
    stop_score = 15.0 if rec.stop_loss_set else 7.0

    # ── Target execution (0–10) ──────────────────────────────────────────────
    if rec.target_set:
        target_score = 10.0 if rec.exit_type.upper() == "TARGET_HIT" else 6.0
    else:
        target_score = 3.0

    total = int(entry_score + exit_score + fill_score + stop_score + target_score)
    total = min(100, max(0, total))
    return total, grade(total)


def grade(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    return "Poor"
