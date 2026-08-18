"""
post_market_data_refresh.py — Post-market OHLCV refresh job.

Runs after 15:30 IST (triggered from POST_CLOSE/CLOSED scheduler tick).
Fetches today's final daily candle for all NIFTY 50 symbols via yfinance,
appends to daily_ohlcv_cache, emits pipeline events, and logs refresh state.

Design rules
------------
* Exactly-once per IST calendar day via kv_claim_once guard.
* Runs ONLY during POST_CLOSE / CLOSED market state.
* If yfinance is unavailable, keeps existing cache and emits FAILED event.
* Never disrupts EOD squareoff or paper trade logic.
* Advisory-only; never raises.
* PAPER TRADING ONLY.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CLAIM_TTL_SECONDS = 86_400      # 24 h — one claim per IST calendar day
_TIMEOUT_SECONDS = 300           # 5-minute hard cap for the whole refresh job


def _today_ist() -> str:
    """Return today's IST calendar date as YYYY-MM-DD."""
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    return now_ist.strftime("%Y-%m-%d")


def _emit(event_type: str, stage: str, payload: Dict[str, Any]) -> None:
    try:
        from scan_state_store import _pe_emit  # type: ignore[attr-defined]
        _pe_emit(event_type, stage, scan_id=None, payload=payload)
    except Exception:
        pass


def maybe_run_postmarket_refresh(mstate: str) -> Optional[Dict[str, Any]]:
    """
    Gate wrapper: runs only during POST_CLOSE / CLOSED, once per IST day.
    Returns result dict or None if skipped.
    """
    if mstate not in ("POST_CLOSE", "CLOSED"):
        return None
    try:
        from phase20_store import kv_claim_once
        claim_key = f"ohlcv_postmarket_refresh:{_today_ist()}"
        if not kv_claim_once(claim_key, ttl_seconds=_CLAIM_TTL_SECONDS):
            return None    # already ran today
        return run_postmarket_refresh()
    except Exception as exc:
        logger.warning("maybe_run_postmarket_refresh gating error: %s", exc)
        return {"ran": False, "error": str(exc)[:200]}


def run_postmarket_refresh() -> Dict[str, Any]:
    """
    Full post-market daily candle append for all NIFTY 50 symbols.
    Safe to call directly (no gate). Returns result dict. Never raises.
    """
    t0 = time.monotonic()
    today = _today_ist()
    logger.info("post_market_data_refresh: starting for %s", today)

    try:
        from config import NIFTY_50 as _universe
        symbols: List[str] = list(_universe)
    except Exception as exc:
        return {"success": False, "error": f"config import: {exc!s:.100}"}

    try:
        from ohlcv_cache_store import (
            ensure_tables, write_symbol_to_cache,
            log_refresh_start, log_refresh_complete,
        )
        ensure_tables()
    except Exception as exc:
        return {"success": False, "error": f"cache store import: {exc!s:.100}"}

    run_id = log_refresh_start("postmarket", len(symbols))
    updated: List[str] = []
    failed: List[str] = []
    missing: List[str] = []

    try:
        import yfinance as yf
        import pandas as pd

        # Fetch 5d window — ensures we capture today's close even if yfinance
        # has a 1-day lag. We upsert so existing rows are only overwritten
        # when newer adjusted data is available.
        tickers = [s.upper() + ".NS" for s in symbols]
        bulk = yf.download(
            tickers, period="5d", interval="1d",
            progress=False, auto_adjust=True,
            group_by="ticker", threads=True,
        )

        for sym, tick in zip(symbols, tickers):
            try:
                if isinstance(bulk.columns, pd.MultiIndex) and \
                        tick in bulk.columns.get_level_values(0):
                    df_raw = bulk[tick].copy()
                elif len(symbols) == 1:
                    df_raw = bulk.copy()
                else:
                    df_raw = None

                if df_raw is None or (hasattr(df_raw, "empty") and df_raw.empty):
                    missing.append(sym.upper())
                    continue

                df_raw.columns = [str(c).lower() for c in df_raw.columns]
                df_raw = df_raw.dropna()
                if df_raw.empty:
                    missing.append(sym.upper())
                    continue

                n = write_symbol_to_cache(sym, df_raw, source="yfinance_postmarket")
                if n > 0:
                    updated.append(sym.upper())
                else:
                    failed.append(sym.upper())
            except Exception as exc:
                logger.warning("postmarket_refresh(%s): %s", sym, exc)
                failed.append(sym.upper())

    except Exception as exc:
        logger.warning("postmarket_refresh bulk download failed: %s", exc)
        duration = round(time.monotonic() - t0, 2)
        log_refresh_complete(
            run_id, "FAILED",
            symbols_updated=0,
            failed_symbols=symbols,
            missing_symbols=[],
            stale_symbols=[],
            duration_seconds=duration,
            error_summary=str(exc)[:300],
        )
        _emit("DATA_CACHE_POSTMARKET_REFRESH_FAILED", "DATA_CACHE", {
            "date": today, "error": str(exc)[:200],
        })
        return {
            "success": False,
            "refresh_type": "postmarket",
            "date": today,
            "error": str(exc)[:300],
            "duration_seconds": duration,
        }

    duration = round(time.monotonic() - t0, 2)
    # LTIM is a known provider gap — don't count it as a failure
    known_missing = [s for s in missing if s == "LTIM"]
    true_failed = [s for s in failed if s not in ("LTIM",)]

    status = "SUCCESS" if not true_failed else ("PARTIAL" if updated else "FAILED")
    log_refresh_complete(
        run_id, status,
        symbols_updated=len(updated),
        failed_symbols=failed,
        missing_symbols=missing,
        stale_symbols=[],
        duration_seconds=duration,
        error_summary=f"{len(failed)} failed, {len(missing)} missing" if (failed or missing) else None,
    )
    event_type = "DATA_CACHE_POSTMARKET_REFRESH_COMPLETED" if status != "FAILED" \
        else "DATA_CACHE_POSTMARKET_REFRESH_FAILED"
    _emit(event_type, "DATA_CACHE", {
        "date": today,
        "symbols_updated": len(updated),
        "symbols_failed": len(failed),
        "symbols_missing": len(missing),
        "known_missing": known_missing,
        "duration_seconds": duration,
        "status": status,
    })
    logger.info(
        "post_market_data_refresh: %s — updated=%d failed=%d missing=%d in %.1fs",
        status, len(updated), len(failed), len(missing), duration,
    )
    return {
        "success": True,
        "refresh_type": "postmarket",
        "date": today,
        "status": status,
        "symbols_requested": len(symbols),
        "symbols_updated": len(updated),
        "symbols_failed": len(failed),
        "symbols_missing": len(missing),
        "known_missing_ltim": "LTIM" in missing,
        "duration_seconds": duration,
    }
