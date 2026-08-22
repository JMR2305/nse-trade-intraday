"""Strict custom-universe validation for advisory analysis."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from .contracts import advisory_output


CUSTOM_UNIVERSE = "CUSTOM_LOW_PRICE_SECTOR"
EXPECTED_ACTIVE_COUNT = 23
REQUIRED_INACTIVE = frozenset({"IOB", "UCOBANK"})
APPROVED_ACTIVE_SYMBOLS = frozenset({
    "BANKBARODA", "BANKINDIA", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
    "KTKBANK", "MAHABANK", "PNB", "UNIONBANK", "COALINDIA", "GAIL",
    "HUDCO", "IRCON", "IRFC", "MRPL", "NBCC", "NMDC", "NTPC", "PFC",
    "RECLTD", "RVNL", "SAIL", "WIPRO",
})


def validate_universe(
    rows: Iterable[Mapping[str, Any]],
    *,
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
) -> Dict[str, Any]:
    """Validate the exact active universe without any legacy fallback."""
    all_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    active_rows = [row for row in all_rows if row.get("is_active") is True]
    active_symbols = sorted(
        {str(row.get("symbol") or "").strip().upper() for row in active_rows if row.get("symbol")}
    )
    inactive_symbols = sorted(
        {str(row.get("symbol") or "").strip().upper() for row in all_rows if row.get("is_active") is False}
    )
    unexpected_universe_rows = sorted(
        {
            str(row.get("symbol") or "").strip().upper()
            for row in all_rows
            if row.get("allowed_universe") != CUSTOM_UNIVERSE
        }
    )
    active_nifty_rows = sorted(
        {
            str(row.get("symbol") or "").strip().upper()
            for row in active_rows
            if "NIFTY_50" in str(row.get("allowed_universe") or "").upper()
            or "NIFTY_50" in str(row.get("universe") or "").upper()
        }
    )

    reasons: List[str] = []
    if len(active_symbols) != EXPECTED_ACTIVE_COUNT:
        reasons.append(f"active_count={len(active_symbols)} expected={EXPECTED_ACTIVE_COUNT}")
    if len(active_symbols) != len(active_rows):
        reasons.append("duplicate_active_symbols")
    active_rows_without_custom_label = sorted(
        str(row.get("symbol") or "").strip().upper()
        for row in active_rows
        if row.get("allowed_universe") != CUSTOM_UNIVERSE
    )
    if active_rows_without_custom_label:
        reasons.append("active_rows_not_custom_universe")
    if active_nifty_rows:
        reasons.append("nifty_50_fallback_detected")
    unknown_active_symbols = sorted(set(active_symbols) - APPROVED_ACTIVE_SYMBOLS)
    missing_approved_symbols = sorted(APPROVED_ACTIVE_SYMBOLS - set(active_symbols))
    if unknown_active_symbols or missing_approved_symbols:
        reasons.append("active_symbols_do_not_match_approved_universe")
    if not REQUIRED_INACTIVE.issubset(set(inactive_symbols)):
        reasons.append("required_inactive_symbols_not_excluded")
    healthy = not reasons
    reason = (
        "exact 23-symbol CUSTOM_LOW_PRICE_SECTOR universe; inactive exclusions verified"
        if healthy
        else "; ".join(reasons)
    )
    output = advisory_output(
        symbol="__UNIVERSE__",
        bot_name="market-data-universe-bot",
        strategy_name="UNIVERSE_HEALTH",
        score=100 if healthy else 0,
        decision="WATCH" if healthy else "SUPERVISOR_BLOCKED",
        reason=reason,
        data_quality="UNIVERSE_HEALTHY" if healthy else "UNIVERSE_INVALID",
        risk_flags=[] if healthy else ["UNIVERSE_SCOPE_BLOCKED"],
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
        active_universe=CUSTOM_UNIVERSE if healthy else None,
        active_count=len(active_symbols),
        active_symbols=active_symbols,
        inactive_symbols=inactive_symbols,
        required_inactive=sorted(REQUIRED_INACTIVE),
        unexpected_symbols=unexpected_universe_rows,
        unknown_active_symbols=unknown_active_symbols,
        missing_approved_symbols=missing_approved_symbols,
        nifty_fallback_detected=bool(active_nifty_rows),
        healthy=healthy,
    )
    return output