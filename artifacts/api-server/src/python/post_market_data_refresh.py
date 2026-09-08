"""
post_market_data_refresh.py — Post-market OHLCV refresh job.

Runs after 15:30 IST (triggered from POST_CLOSE/CLOSED scheduler tick).
Fetches today's final daily candle for all NIFTY 50 symbols via yfinance,
appends to daily_ohlcv_cache, emits pipeline events, and logs refresh state.

Design rules
------------
* Exactly one successful refresh per IST trading day; failed/partial work can
  retry a bounded number of times for only unfinished symbols.
* Runs ONLY during POST_CLOSE / CLOSED market state.
* If yfinance is unavailable, keeps existing cache and emits FAILED event.
* Never disrupts EOD squareoff or paper trade logic.
* Advisory-only; never raises.
* PAPER TRADING ONLY.
"""

from __future__ import annotations

import logging
import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from threading import Event, Thread
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CLAIM_TTL_SECONDS = 86_400      # 24 h — one claim per IST calendar day
_TIMEOUT_SECONDS = 300           # 5-minute hard cap for the whole refresh job
_MAX_RETRY_ATTEMPTS = 3
_LEASE_SECONDS = 10 * 60


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


def _download_batch_with_deadline(tickers: List[str]) -> Any:
    """Fetch one provider batch in an isolated, killable Python subprocess."""
    child_script = """
import json
import pickle
import sys
import yfinance as yf

tickers = json.loads(sys.argv[1])
output_path = sys.argv[2]
result = yf.download(
    tickers, period="5d", interval="1d", progress=False,
    auto_adjust=True, group_by="ticker", threads=True,
)
with open(output_path, "wb") as output:
    pickle.dump(result, output, protocol=pickle.HIGHEST_PROTOCOL)
"""
    handle, output_path = tempfile.mkstemp(prefix="postmarket-yfinance-", suffix=".pkl")
    os.close(handle)
    command = [
        sys.executable, "-c", child_script, json.dumps(tickers), output_path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"provider worker failed (exit={completed.returncode}): "
                f"{(completed.stderr or completed.stdout)[-300:]}"
            )
        with open(output_path, "rb") as output:
            return pickle.load(output)
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills and reaps the child before raising; no provider
        # thread or orphan process can survive the bounded maintenance job.
        raise TimeoutError(
            f"provider deadline exceeded ({_TIMEOUT_SECONDS}s)"
        ) from exc
    finally:
        try:
            os.unlink(output_path)
        except FileNotFoundError:
            pass


def maybe_run_postmarket_refresh(mstate: str) -> Optional[Dict[str, Any]]:
    """
    Gate wrapper: runs only during POST_CLOSE / CLOSED, once per IST day.
    Returns result dict or None if skipped.
    """
    if mstate not in ("POST_CLOSE", "CLOSED"):
        return None
    try:
        from market_hours import MARKET_CLOSE, is_trading_day, now_ist
        from phase20_store import (
            kv_acquire_expiring_claim, kv_get, kv_release_if_owned,
            kv_renew_expiring_claim, kv_set,
        )
        today = _today_ist()
        ist_now = now_ist()
        # CLOSED also describes the overnight/pre-open period. It is not a
        # post-market window until today's configured NSE close has passed.
        if not is_trading_day(ist_now.date()) or ist_now.time() < MARKET_CLOSE:
            return None
        state_key = f"ohlcv_postmarket_refresh_state:{today}"
        state = kv_get(state_key) or {}
        if isinstance(state, dict) and state.get("status") == "SUCCESS":
            return None    # already ran today
        attempts = int(state.get("attempts") or 0) if isinstance(state, dict) else 0
        if attempts >= _MAX_RETRY_ATTEMPTS:
            return None
        claim_key = f"ohlcv_postmarket_refresh_lease:{today}"
        token = uuid.uuid4().hex
        lease = {
            "token": token,
            "expires_at": (datetime.now(timezone.utc) + timedelta(
                seconds=_LEASE_SECONDS
            )).isoformat(),
        }
        if not kv_acquire_expiring_claim(claim_key, lease):
            return None
        lost_lease = Event()
        stop_renewal = Event()

        def renew_lease() -> None:
            while not stop_renewal.wait(_LEASE_SECONDS / 3):
                expires_at = (datetime.now(timezone.utc) + timedelta(
                    seconds=_LEASE_SECONDS
                )).isoformat()
                if not kv_renew_expiring_claim(claim_key, token, expires_at):
                    lost_lease.set()
                    return

        renewal = Thread(target=renew_lease, name="postmarket-refresh-lease",
                         daemon=True)
        renewal.start()
        retry_symbols = list(state.get("unfinished_symbols") or []) \
            if isinstance(state, dict) else []
        try:
            result = _perform_postmarket_refresh(retry_symbols=retry_symbols or None)
        finally:
            stop_renewal.set()
            renewal.join(timeout=1)
        # Never publish a stale worker's outcome over a newer lease owner's
        # state. Cache writes are idempotent/upserted; the durable job result is
        # not, so it is owner-fenced here.
        expires_at = (datetime.now(timezone.utc) + timedelta(
            seconds=_LEASE_SECONDS
        )).isoformat()
        if lost_lease.is_set() or not kv_renew_expiring_claim(
            claim_key, token, expires_at
        ):
            return {
                "success": False, "ran": True, "status": "FAILED",
                "error": "Post-market refresh lost its lease before state publish",
                "retry_symbols": retry_symbols,
            }
        status = str(result.get("status") or (
            "SUCCESS" if result.get("success") else "FAILED"
        )).upper()
        unfinished = list(result.get("failed_symbols") or []) + \
            list(result.get("missing_symbols") or [])
        result["ran"] = True
        result["attempt"] = attempts + 1
        result["retry_symbols"] = retry_symbols
        result["started_at"] = result.get("started_at")
        kv_set(state_key, {
            "status": status,
            "attempts": attempts + 1,
            "unfinished_symbols": sorted(set(unfinished)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        # Only a clean success consumes the day. Release failures/partials so
        # the next scheduler tick can recover the unfinished cache rows; the
        # lease keeps concurrent instances from duplicating work.
        if status != "SUCCESS":
            kv_release_if_owned(claim_key, token)
        return result
    except Exception as exc:
        logger.warning("maybe_run_postmarket_refresh gating error: %s", exc)
        return {"ran": False, "error": str(exc)[:200]}


def run_postmarket_refresh(retry_symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Public command/programmatic entry point. It always uses the guarded,
    per-day scheduler path so it cannot become an ungated cache refresh.
    """
    try:
        from market_hours import market_status
        state = str((market_status() or {}).get("state") or "UNKNOWN").upper()
        result = maybe_run_postmarket_refresh(state)
        return result or {
            "success": True, "ran": False,
            "reason": "Post-market cache refresh is not due",
            "market_state": state,
        }
    except Exception as exc:
        return {"success": False, "ran": False, "error": str(exc)[:300]}


def _perform_postmarket_refresh(
    retry_symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """The guarded worker body. Call only from maybe_run_postmarket_refresh."""
    t0 = time.monotonic()
    today = _today_ist()
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("post_market_data_refresh: starting for %s", today)

    try:
        from config import get_active_intraday_universe, NIFTY_50, UniverseMode
        if get_active_intraday_universe() == UniverseMode.CUSTOM_LOW_PRICE_SECTOR:
            from custom_universe_store import get_active_symbols
            symbols = get_active_symbols()
        else:
            symbols = list(NIFTY_50)
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

    if retry_symbols:
        wanted = {str(sym).upper() for sym in retry_symbols}
        symbols = [sym for sym in symbols if str(sym).upper() in wanted]
    run_id = log_refresh_start("postmarket", len(symbols))
    updated: List[str] = []
    failed: List[str] = []
    missing: List[str] = []

    try:
        import pandas as pd

        # Fetch 5d window — ensures we capture today's close even if yfinance
        # has a 1-day lag. We upsert so existing rows are only overwritten
        # when newer adjusted data is available.
        tickers = [s.upper() + ".NS" for s in symbols]
        # A separate process gives this provider deadline real teeth: a hung
        # yfinance request is terminated and cannot outlive the lease or write
        # cache/state from a late background thread.
        try:
            bulk = _download_batch_with_deadline(tickers)
        except TimeoutError:
            duration = round(time.monotonic() - t0, 2)
            log_refresh_complete(
                run_id, "FAILED", symbols_updated=0, failed_symbols=symbols,
                missing_symbols=[], stale_symbols=[], duration_seconds=duration,
                error_summary=f"provider deadline exceeded ({_TIMEOUT_SECONDS}s)",
            )
            return {
                "success": False, "ran": True, "refresh_type": "postmarket",
                "date": today, "status": "FAILED",
                "error": f"provider deadline exceeded ({_TIMEOUT_SECONDS}s)",
                "duration_seconds": duration, "started_at": started_at,
                "failed_symbols": list(symbols), "missing_symbols": [],
            }

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
            "ran": True,
            "refresh_type": "postmarket",
            "date": today,
            "error": str(exc)[:300],
            "duration_seconds": duration,
            "started_at": started_at,
            "failed_symbols": list(symbols),
            "missing_symbols": [],
            "status": "FAILED",
        }

    duration = round(time.monotonic() - t0, 2)

    # Any failed or missing symbol degrades the run: PARTIAL if some symbols
    # updated, FAILED if none did.
    problem_symbols = failed + missing
    if not problem_symbols:
        status = "SUCCESS"
    elif updated:
        status = "PARTIAL"
    else:
        status = "FAILED"
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
        "duration_seconds": duration,
        "status": status,
    })
    logger.info(
        "post_market_data_refresh: %s — updated=%d failed=%d missing=%d in %.1fs",
        status, len(updated), len(failed), len(missing), duration,
    )
    return {
        "success": True,
        "ran": True,
        "refresh_type": "postmarket",
        "date": today,
        "started_at": started_at,
        "status": status,
        "symbols_requested": len(symbols),
        "symbols_updated": len(updated),
        "symbols_failed": len(failed),
        "symbols_missing": len(missing),
        "failed_symbols": failed,
        "missing_symbols": missing,
        "duration_seconds": duration,
    }
