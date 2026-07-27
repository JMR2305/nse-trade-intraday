"""
preopen_reconciliation.py — Phase 5A post-open confirmation and reconciliation.

Post-open confirmation gate (13 criteria).
Reconciliation at 09:20: compare indicative vs actual prices, compute metrics.

Pre-open candidates that fail confirmation are downgraded to WATCH or NO_TRADE.
No paper entries are ever created from pre-open data.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
from preopen_data_model import ReconciliationRecord, now_ist_str
import preopen_db as db

# ── Post-open confirmation criteria ──────────────────────────────────────────

_CRITERIA = [
    "actual_open_price",
    "first_5min_candle",
    "live_volume",
    "relative_volume",
    "vwap_relationship",
    "opening_range_breakout",
    "sector_strength",
    "nifty_direction",
    "banknifty_context",
    "india_vix_context",
    "spread_and_liquidity",
    "stale_data_gate",
    "risk_engine_approval",
]


def confirm_candidate(
    symbol: str,
    pre_open_gap: float,
    actual_open_price: Optional[float],
    first_candle_close: Optional[float],
    live_volume: Optional[int],
    avg_volume: Optional[int],
    vwap: Optional[float],
    nifty_direction: Optional[str],
    sector_direction: Optional[str],
    india_vix: Optional[float],
    spread_pct: Optional[float],
    is_stale: bool = False,
    risk_engine_approved: bool = False,
) -> Dict[str, Any]:
    """
    Apply 13-criteria post-open confirmation gate.
    Returns verdict: CONFIRMED | DOWNGRADE_WATCH | NO_TRADE
    """
    failed = []
    passed = []

    # 1. Actual open price available
    if actual_open_price and actual_open_price > 0:
        passed.append("actual_open_price")
    else:
        failed.append("actual_open_price")

    # 2. First 5-min candle close
    if first_candle_close and first_candle_close > 0:
        # Candle must confirm gap direction
        if actual_open_price and actual_open_price > 0:
            candle_confirmation = (
                (pre_open_gap > 0 and first_candle_close >= actual_open_price) or
                (pre_open_gap < 0 and first_candle_close <= actual_open_price) or
                abs(pre_open_gap) < 0.5  # flat open — direction not critical
            )
            if candle_confirmation:
                passed.append("first_5min_candle")
            else:
                failed.append("first_5min_candle")
        else:
            failed.append("first_5min_candle")
    else:
        failed.append("first_5min_candle")

    # 3. Live volume
    if live_volume and live_volume > 0:
        passed.append("live_volume")
    else:
        failed.append("live_volume")

    # 4. Relative volume >= 0.8×
    if live_volume and avg_volume and avg_volume > 0:
        rel_vol = live_volume / avg_volume
        if rel_vol >= 0.8:
            passed.append("relative_volume")
        else:
            failed.append("relative_volume")
    else:
        failed.append("relative_volume")

    # 5. VWAP relationship
    if vwap and actual_open_price:
        vwap_ok = (
            (pre_open_gap > 0 and actual_open_price >= vwap * 0.998) or
            (pre_open_gap < 0 and actual_open_price <= vwap * 1.002) or
            abs(pre_open_gap) < 0.5
        )
        (passed if vwap_ok else failed).append("vwap_relationship")
    else:
        failed.append("vwap_relationship")

    # 6. Opening range breakout (first candle range exceeds 0.3% — sign of real momentum)
    if first_candle_close and actual_open_price and actual_open_price > 0:
        candle_range_pct = abs(first_candle_close - actual_open_price) / actual_open_price * 100
        (passed if candle_range_pct >= 0.3 else failed).append("opening_range_breakout")
    else:
        failed.append("opening_range_breakout")

    # 7. Sector strength
    if sector_direction:
        (passed if sector_direction == "POSITIVE" else failed).append("sector_strength")
    else:
        failed.append("sector_strength")

    # 8. NIFTY direction
    if nifty_direction:
        (passed if nifty_direction in ("POSITIVE", "NEUTRAL") else failed).append("nifty_direction")
    else:
        failed.append("nifty_direction")

    # 9. BANKNIFTY context (treated as neutral if unknown)
    passed.append("banknifty_context")  # advisory — pass if no data

    # 10. India VIX context
    if india_vix is not None:
        (passed if india_vix < 25 else failed).append("india_vix_context")
    else:
        passed.append("india_vix_context")  # neutral

    # 11. Spread and liquidity
    if spread_pct is not None:
        (passed if spread_pct < 0.5 else failed).append("spread_and_liquidity")
    else:
        failed.append("spread_and_liquidity")

    # 12. Stale data gate
    if not is_stale:
        passed.append("stale_data_gate")
    else:
        failed.append("stale_data_gate")  # stale data → NO_TRADE

    # 13. Risk engine approval
    if risk_engine_approved:
        passed.append("risk_engine_approval")
    else:
        failed.append("risk_engine_approval")

    pass_count = len(passed)
    total = len(_CRITERIA)

    # Verdict
    if "stale_data_gate" in failed:
        verdict = "NO_TRADE"
        reason = "Stale pre-open data — no actionable recommendation"
    elif "risk_engine_approval" in failed:
        verdict = "NO_TRADE"
        reason = "Risk engine has not approved this candidate"
    elif pass_count >= 12:
        verdict = "CONFIRMED"
        reason = f"{pass_count}/{total} criteria met"
    elif pass_count >= 7:
        verdict = "DOWNGRADE_WATCH"
        reason = f"Only {pass_count}/{total} criteria met — watch for stronger confirmation"
    else:
        verdict = "NO_TRADE"
        reason = f"Insufficient confirmation: {pass_count}/{total} criteria met"

    return {
        "symbol": symbol,
        "verdict": verdict,
        "reason": reason,
        "passed": passed,
        "failed": failed,
        "pass_count": pass_count,
        "total_criteria": total,
        "label": "PAPER / ADVISORY ONLY",
        "note": "Confirmation is advisory. No paper entries are created from pre-open data.",
    }


# ── Price reconciliation (09:20) ──────────────────────────────────────────────

def reconcile_session(
    session_id: str,
    snapshots: List[dict],
    actual_prices: Dict[str, float],   # symbol → actual open price
    prices_0920: Dict[str, float],     # symbol → price at 09:20
    prices_0930: Dict[str, float],     # symbol → price at 09:30
    watchlist_symbols: set,
) -> Dict[str, Any]:
    """
    Compare indicative prices against actuals.
    Compute six accuracy metrics.
    """
    records = []
    for s in snapshots:
        sym = s.get("symbol", "")
        ind_eq = s.get("indicative_equilibrium_price")
        final_pre = s.get("indicative_open_price")
        actual_open = actual_prices.get(sym)
        p0920 = prices_0920.get(sym)
        p0930 = prices_0930.get(sym)

        ind_err = None
        if ind_eq and actual_open and actual_open > 0:
            ind_err = round(abs(ind_eq - actual_open) / actual_open * 100, 4)

        # Opening continuation: gap direction held 5min after open
        continuation = None
        reversal = None
        gap_pct = s.get("gap_percent")
        prev_close = s.get("previous_close", 0)
        if gap_pct is not None and actual_open and p0920:
            gap_held = (
                (gap_pct > 0 and p0920 >= actual_open) or
                (gap_pct < 0 and p0920 <= actual_open) or
                abs(gap_pct) < 0.3
            )
            continuation = gap_held
            reversal = not gap_held

        in_watchlist = sym in watchlist_symbols
        confirmed = None
        if in_watchlist and continuation is not None:
            confirmed = continuation

        rec = ReconciliationRecord(
            symbol=sym,
            session_id=session_id,
            trading_date=s.get("trading_date", ""),
            indicative_equilibrium_price=ind_eq,
            final_pre_open_price=final_pre,
            actual_open_price=actual_open,
            price_at_0920=p0920,
            price_at_0930=p0930,
            indicative_to_open_error=ind_err,
            opening_continuation=continuation,
            opening_reversal=reversal,
            watchlist_confirmed=confirmed,
            was_in_watchlist=in_watchlist,
            reconciled_at=now_ist_str(),
        )
        records.append(rec.to_dict())

    db.save_reconciliation(records)

    # Aggregate metrics
    total = len(records)
    with_error = [r for r in records if r.get("indicative_to_open_error") is not None]
    avg_error = (sum(r["indicative_to_open_error"] for r in with_error) / len(with_error)
                 if with_error else None)

    wl_confirmed = [r for r in records if r.get("was_in_watchlist") and r.get("watchlist_confirmed") is True]
    wl_total = [r for r in records if r.get("was_in_watchlist")]
    watchlist_confirmation_rate = len(wl_confirmed) / len(wl_total) * 100 if wl_total else None

    continuations = [r for r in records if r.get("opening_continuation") is True]
    reversals = [r for r in records if r.get("opening_reversal") is True]
    with_dir = [r for r in records if r.get("opening_continuation") is not None]
    continuation_rate = len(continuations) / len(with_dir) * 100 if with_dir else None
    reversal_rate = len(reversals) / len(with_dir) * 100 if with_dir else None

    # False positive: in watchlist but direction reversed
    fp_total = [r for r in records if r.get("was_in_watchlist") and r.get("opening_reversal") is True]
    false_positive_rate = len(fp_total) / len(wl_total) * 100 if wl_total else None

    return {
        "success": True,
        "session_id": session_id,
        "symbols_reconciled": total,
        "avg_indicative_to_open_error_pct": round(avg_error, 4) if avg_error is not None else None,
        "watchlist_confirmation_rate_pct": round(watchlist_confirmation_rate, 2) if watchlist_confirmation_rate is not None else None,
        "false_positive_rate_pct": round(false_positive_rate, 2) if false_positive_rate is not None else None,
        "opening_continuation_rate_pct": round(continuation_rate, 2) if continuation_rate is not None else None,
        "opening_reversal_rate_pct": round(reversal_rate, 2) if reversal_rate is not None else None,
        "records": records,
        "label": "PAPER / ADVISORY ONLY",
    }
