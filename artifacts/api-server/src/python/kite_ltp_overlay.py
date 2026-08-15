"""
kite_ltp_overlay.py — Kite Live LTP overlay helper (Option A).

Responsibilities
----------------
* Read KITE_LTP_OVERLAY_ENABLED from config.
* Fetch bulk Kite LTP for a symbol list — ONE round-trip, 30s cached.
* Build a per-symbol overlay dict used by the scan engine and exit manager.

Option A contract (enforced here, not aspirational):
  indicator_source  = yfinance_daily_bars   (NEVER changes)
  ohlcv_source      = yfinance_daily_bars   (NEVER changes)
  current_price_source  = kite_live_ltp    (when available)
  execution_price_source = kite_live_ltp   (when available)
  data_quality_for_indicators = yfinance DataQuality  (NEVER changes)
  data_quality_for_execution  = LIVE       (when Kite LTP available)

This module NEVER places or modifies orders. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INDICATOR_SOURCE = "yfinance_daily_bars"
OHLCV_SOURCE = "yfinance_daily_bars"
OVERLAY_MODE_LABEL = "Daily indicators + Kite live LTP overlay"
DAILY_BAR_MODE_LABEL = "Daily-bar research mode, not true intraday LTP mode"


def is_overlay_enabled() -> bool:
    """Return True if KITE_LTP_OVERLAY_ENABLED=true in the environment."""
    try:
        from config import KITE_LTP_OVERLAY_ENABLED
        return bool(KITE_LTP_OVERLAY_ENABLED)
    except Exception:
        return False


def fetch_ltp_overlay(symbols: List[str]) -> Dict[str, Any]:
    """
    Fetch live LTP for all symbols from Kite Connect in one bulk call.

    Returns:
        {
            "enabled": bool,
            "session_verified": bool,
            "ltps": {SYMBOL: float_or_None},
            "fetched_at": str ISO timestamp,
            "note": str,
            "error": str or None,
        }

    Always returns without raising. Falls back gracefully on any error.
    """
    if not is_overlay_enabled():
        return {
            "enabled": False,
            "session_verified": False,
            "ltps": {},
            "fetched_at": None,
            "note": DAILY_BAR_MODE_LABEL,
            "error": None,
        }

    try:
        from kite_quote_provider import kite_session_verified, get_ltp
        session_ok = kite_session_verified()
        if not session_ok:
            return {
                "enabled": True,
                "session_verified": False,
                "ltps": {},
                "fetched_at": None,
                "note": (
                    "KITE_LTP_OVERLAY_ENABLED=true but Kite session not "
                    "verified — using yfinance daily close fallback"
                ),
                "error": None,
            }
        ltps = get_ltp(symbols)
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        available = sum(1 for v in ltps.values() if v is not None and float(v) > 0)
        return {
            "enabled": True,
            "session_verified": True,
            "ltps": ltps,
            "fetched_at": fetched_at,
            "note": (
                f"{OVERLAY_MODE_LABEL} — "
                f"{available}/{len(symbols)} symbols have live LTP"
            ),
            "error": None,
        }
    except Exception as exc:
        logger.warning("kite_ltp_overlay.fetch_ltp_overlay error: %s", exc)
        return {
            "enabled": True,
            "session_verified": False,
            "ltps": {},
            "fetched_at": None,
            "note": f"KITE_LTP_OVERLAY_ENABLED=true but LTP fetch failed: {exc!s:.120}",
            "error": str(exc)[:200],
        }


def build_symbol_overlay(
    symbol: str,
    yfinance_close: float,
    yfinance_data_quality: str,
    overlay_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the per-symbol overlay field dict from the bulk overlay result.

    Always safe to call; returns yfinance-only fields when overlay is
    disabled or Kite is unavailable.
    """
    enabled = overlay_result.get("enabled", False)
    session_ok = overlay_result.get("session_verified", False)
    ltps: Dict[str, Any] = overlay_result.get("ltps") or {}
    fetched_at = overlay_result.get("fetched_at")

    out: Dict[str, Any] = {
        # Option A invariants — never change regardless of Kite state
        "indicator_source": INDICATOR_SOURCE,
        "ohlcv_source": OHLCV_SOURCE,
        "data_quality_for_indicators": yfinance_data_quality,
        # Per-symbol provenance (defaults to yfinance)
        "yfinance_last_close": round(float(yfinance_close), 2) if yfinance_close else None,
        "kite_ltp": None,
        "kite_ltp_available": False,
        "kite_session_verified_flag": bool(session_ok),
        "current_price_source": INDICATOR_SOURCE,
        "execution_price_source": INDICATOR_SOURCE,
        "quote_reliable": False,
        "data_quality_for_execution": yfinance_data_quality,
        "latest_price_time_ist": None,
        "reason_not_live_ltp": None,
        "kite_ltp_overlay_enabled": enabled,
    }

    if not enabled:
        out["reason_not_live_ltp"] = "KITE_LTP_OVERLAY_ENABLED=false"
        return out

    if not session_ok:
        out["reason_not_live_ltp"] = (
            overlay_result.get("error")
            or "Kite session not verified"
        )
        return out

    raw_ltp = ltps.get(symbol.upper())
    if raw_ltp is not None:
        try:
            ltp = round(float(raw_ltp), 2)
        except (TypeError, ValueError):
            ltp = 0.0
    else:
        ltp = 0.0

    if ltp > 0:
        out["kite_ltp"] = ltp
        out["kite_ltp_available"] = True
        out["current_price_source"] = "kite_live_ltp"
        out["execution_price_source"] = "kite_live_ltp"
        out["quote_reliable"] = True
        out["data_quality_for_execution"] = "LIVE"
        out["latest_price_time_ist"] = fetched_at
    else:
        out["reason_not_live_ltp"] = (
            f"Kite session verified but LTP not available for {symbol}"
        )

    return out


def apply_overlay_to_rec(rec: Any, overlay: Dict[str, Any]) -> None:
    """
    Mutate a Phase7Recommendation dataclass in-place with overlay fields.
    rec must have the new Optional fields defined on it (with defaults).
    """
    for attr, val in overlay.items():
        try:
            setattr(rec, attr, val)
        except Exception:
            pass
