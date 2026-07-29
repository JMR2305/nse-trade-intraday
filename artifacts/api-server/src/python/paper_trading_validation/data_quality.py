"""
data_quality.py — Phase 6.1
Seven quality checks over the raw trade records.
Generates a DataQualityReport without modifying any data.
"""
from __future__ import annotations
import sys, os
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .validation_models import DataQualityReport, TradeRecord


def _score(total: int, issues: int) -> float:
    """Quality score 0–100.  Deduct proportionally, floor at 0."""
    if total == 0:
        return 100.0
    deduct_per_issue = 100.0 / max(total, 1)
    return max(0.0, 100.0 - issues * deduct_per_issue)


def run_quality_checks(records: List[TradeRecord]) -> DataQualityReport:
    """
    Run all 7 data quality checks.
    Returns a DataQualityReport — never modifies records.
    """
    missing_values: list = []
    duplicate_trade_ids: list = []
    invalid_timestamps: list = []
    negative_quantities: list = []
    impossible_prices: list = []
    incomplete_ai: list = []
    corrupted: list = []

    seen_ids: dict = {}

    for rec in records:
        tid = rec.trade_id

        # 1. Missing critical values
        missing: list = []
        if not rec.symbol or rec.symbol in ("", "UNKNOWN"):
            missing.append("symbol")
        if not rec.strategy or rec.strategy == "Unknown":
            missing.append("strategy")
        if not rec.timestamp:
            missing.append("timestamp")
        if rec.entry_price == 0.0:
            missing.append("entry_price")
        if rec.exit_price == 0.0:
            missing.append("exit_price")
        if missing:
            missing_values.append({"trade_id": tid, "fields": missing})

        # 2. Duplicate trade IDs
        if tid in seen_ids:
            if tid not in duplicate_trade_ids:
                duplicate_trade_ids.append(tid)
        else:
            seen_ids[tid] = True

        # 3. Invalid timestamps
        if rec.timestamp:
            try:
                from datetime import datetime
                datetime.fromisoformat(str(rec.timestamp).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                invalid_timestamps.append(tid)
        else:
            invalid_timestamps.append(tid)

        # 4. Negative quantities
        if rec.quantity <= 0:
            negative_quantities.append(tid)

        # 5. Impossible prices
        if rec.entry_price < 0 or rec.exit_price < 0:
            impossible_prices.append(tid)
        elif rec.entry_price > 0 and (
            rec.exit_price > rec.entry_price * 10.0 or rec.exit_price < rec.entry_price * 0.1
        ):
            # Price moved more than 10x or dropped below 10% — flag as suspicious
            impossible_prices.append(f"{tid}:suspicious_price_move")

        # 6. Incomplete AI data (confidence expected but missing)
        if rec.ai_confidence is None and rec.ai_recommendation is None:
            incomplete_ai.append(tid)

        # 7. Corrupted records (holding time < 0 or extreme, pnl doesn't reconcile with price)
        if rec.holding_time_minutes < 0:
            corrupted.append(f"{tid}:negative_holding_time")
        elif rec.entry_price > 0 and rec.exit_price > 0 and rec.quantity > 0:
            expected_pnl = (rec.exit_price - rec.entry_price) * rec.quantity
            if abs(expected_pnl - rec.pnl) > 0.01:
                corrupted.append(f"{tid}:pnl_mismatch")

    # --- Quality score and verdict ---
    total_issues = (
        len(missing_values)
        + len(duplicate_trade_ids)
        + len(invalid_timestamps)
        + len(negative_quantities)
        + len(impossible_prices)
        + len(incomplete_ai)
        + len(corrupted)
    )

    # Incomplete AI data is a warning, not an error — weight at 0.5
    weighted_issues = (
        len(missing_values)
        + len(duplicate_trade_ids)
        + len(invalid_timestamps)
        + len(negative_quantities)
        + len(impossible_prices)
        + len(incomplete_ai) * 0.5
        + len(corrupted)
    )

    quality_score = _score(len(records) if records else 1, weighted_issues)

    if quality_score >= 90:
        verdict = "CLEAN"
    elif quality_score >= 70:
        verdict = "WARNINGS"
    else:
        verdict = "ISSUES"

    return DataQualityReport(
        total_records=len(records),
        missing_values=missing_values,
        duplicate_trades=duplicate_trade_ids,
        invalid_timestamps=invalid_timestamps,
        negative_quantities=negative_quantities,
        impossible_prices=impossible_prices,
        incomplete_ai_data=incomplete_ai,
        corrupted_records=corrupted,
        quality_score=quality_score,
        verdict=verdict,
    )
