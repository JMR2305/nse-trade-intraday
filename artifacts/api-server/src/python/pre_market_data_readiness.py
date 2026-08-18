"""
pre_market_data_readiness.py — Pre-market OHLCV cache readiness check.

Run around 08:45–09:00 IST to verify the local OHLCV cache is ready before
the first scan fires at 09:15 IST.

Outputs one of three verdicts:
  READY             — all symbols have sufficient, fresh cache
  READY_WITH_WARNINGS — minor gaps (single symbol, LTIM, etc.) — safe to scan
  BLOCKED           — critical cache gaps; BUY orders should be blocked

BLOCKED criteria:
  * >20% of symbols have missing required bars
  * cache is older than MAX_CACHE_AGE_DAYS for more than 20% of symbols
  * Kite LTP is unavailable (no live execution price)
  * company master has fewer than 80% of universe mapped

Advisory-only. Never raises. PAPER TRADING ONLY.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BLOCK_THRESHOLD_PCT = 0.20      # >20% symbols missing/stale → BLOCKED
COMPANY_MASTER_MIN_PCT = 0.80   # <80% mapped → BLOCKED


def run_pre_market_readiness_check(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Full pre-market data readiness check.
    Returns {verdict, reasons, checks, timestamp}.
    Never raises.
    """
    try:
        if symbols is None:
            from config import NIFTY_50
            symbols = list(NIFTY_50)
    except Exception as exc:
        return _result("BLOCKED", [f"config.NIFTY_50 unavailable: {exc!s:.80}"], {})

    total = len(symbols)
    checks: Dict[str, Any] = {}
    reasons: List[str] = []
    warnings: List[str] = []

    # ── 1. OHLCV cache completeness ──────────────────────────────────────────
    try:
        from ohlcv_cache_store import get_cache_status, MIN_BARS_REQUIRED
        cache_status = get_cache_status(symbols)
        missing_required = [s for s, info in cache_status.items()
                            if info.get("missing_required") or not info.get("cached")]
        stale_symbols = [s for s, info in cache_status.items()
                         if info.get("data_quality") in ("STALE", "UNAVAILABLE")
                         and info.get("cached")]
        uncached = [s for s, info in cache_status.items() if not info.get("cached")]
        live_symbols = [s for s, info in cache_status.items()
                        if info.get("data_quality") in ("LIVE", "NEAR_LIVE")]
        latest_dates = [info["latest_date"] for info in cache_status.values()
                        if info.get("latest_date")]
        latest_date = max(latest_dates) if latest_dates else None

        missing_pct = len(missing_required) / total if total else 1.0
        stale_pct = len(stale_symbols) / total if total else 0.0
        cache_hit_rate = len(live_symbols) / total * 100 if total else 0.0

        checks["ohlcv_cache"] = {
            "total_symbols": total,
            "live_symbols": len(live_symbols),
            "missing_required_bars": missing_required,
            "stale_symbols": stale_symbols,
            "uncached_symbols": uncached,
            "latest_cached_date": latest_date,
            "cache_hit_rate_pct": round(cache_hit_rate, 1),
            "min_bars_required": MIN_BARS_REQUIRED,
        }

        # LTIM is a known provider gap — exclude from blocking logic
        blocking_missing = [s for s in missing_required if s != "LTIM"]
        if len(blocking_missing) / total > BLOCK_THRESHOLD_PCT:
            reasons.append(
                f"{len(blocking_missing)} symbols ({len(blocking_missing)/total*100:.0f}%)"
                f" missing required OHLCV bars — BUY entries blocked"
            )
        elif missing_required:
            ltim_note = " (including LTIM — known provider gap)" \
                if "LTIM" in missing_required else ""
            warnings.append(f"{len(missing_required)} symbols missing cache{ltim_note}")
        if stale_pct > BLOCK_THRESHOLD_PCT:
            reasons.append(
                f"{len(stale_symbols)} symbols ({stale_pct*100:.0f}%) have STALE cache"
            )
        elif stale_symbols:
            warnings.append(f"{len(stale_symbols)} symbols have STALE cache — capped at WATCH")
    except Exception as exc:
        checks["ohlcv_cache"] = {"error": str(exc)[:200]}
        warnings.append(f"OHLCV cache check failed: {exc!s:.80}")

    # ── 2. Kite session (live execution price) ────────────────────────────────
    try:
        from kite_quote_provider import kite_session_verified  # type: ignore[import]
        kite_ok = kite_session_verified()
        checks["kite_session"] = {
            "verified": kite_ok,
            "required_for": "current_price and execution_price",
            "impact_if_missing": "all paper BUY entries blocked",
        }
        if not kite_ok:
            reasons.append(
                "Kite session NOT verified — live execution price unavailable."
                " Re-authenticate at 09:00 IST before first scan."
            )
    except Exception as exc:
        checks["kite_session"] = {"error": str(exc)[:200], "verified": False}
        warnings.append("Kite session check failed — assume unverified")

    # ── 3. Company master completeness ───────────────────────────────────────
    try:
        from nifty50_company_master_store import get_missing_symbols
        missing_master = get_missing_symbols(symbols)
        master_coverage = 1.0 - len(missing_master) / total if total else 0.0
        checks["company_master"] = {
            "coverage_pct": round(master_coverage * 100, 1),
            "missing_symbols": missing_master,
        }
        if master_coverage < COMPANY_MASTER_MIN_PCT:
            reasons.append(
                f"Company master covers only {master_coverage*100:.0f}% of universe — "
                f"run bootstrap to populate"
            )
        elif missing_master:
            warnings.append(f"{len(missing_master)} symbols not in company master")
    except Exception as exc:
        checks["company_master"] = {"error": str(exc)[:200]}
        warnings.append("Company master check failed")

    # ── 4. yfinance fallback readiness ───────────────────────────────────────
    try:
        import yfinance as yf  # noqa: F401
        checks["yfinance_fallback"] = {"available": True}
    except ImportError:
        checks["yfinance_fallback"] = {"available": False}
        reasons.append("yfinance not installed — no fallback for cache misses")

    # ── 5. Last post-market refresh ──────────────────────────────────────────
    try:
        from ohlcv_cache_store import _get_last_refresh_state
        last = _get_last_refresh_state()
        if last:
            checks["last_postmarket_refresh"] = last
            last_date = last.get("refresh_date")
            if last_date:
                today_str = date.today().isoformat()
                yesterday_str = (date.today() - timedelta(days=1)).isoformat()
                if last_date not in (today_str, yesterday_str):
                    warnings.append(
                        f"Last post-market refresh was {last_date} — older than expected"
                    )
        else:
            checks["last_postmarket_refresh"] = None
            warnings.append("No post-market refresh on record — run backfill before market open")
    except Exception as exc:
        checks["last_postmarket_refresh"] = {"error": str(exc)[:200]}

    # ── Verdict ───────────────────────────────────────────────────────────────
    if reasons:
        verdict = "BLOCKED"
    elif warnings:
        verdict = "READY_WITH_WARNINGS"
    else:
        verdict = "READY"

    return _result(verdict, reasons, checks, warnings=warnings)


def _result(
    verdict: str,
    reasons: List[str],
    checks: Dict[str, Any],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "verdict": verdict,
        "blocking_reasons": reasons,
        "warnings": warnings or [],
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "paper_only": True,
    }
