"""
ohlcv_cache_store.py — Local PostgreSQL-backed daily OHLCV cache for NIFTY 50.

Design
------
* Primary store: daily_ohlcv_cache (symbol + trading_date PK — no duplicates).
* Refresh state: daily_ohlcv_refresh_state (append-only log of every refresh run).
* Freshness rule:  LIVE   ≤3 calendar days since latest bar
                   NEAR_LIVE ≤5 days  (long holiday)
                   STALE  ≤14 days
                   UNAVAILABLE  >14 days or cache missing entirely
* Cache is considered "usable" when latest_date is within MAX_CACHE_AGE_DAYS.
* yfinance is used ONLY for initial backfill and incremental fills; never
  called unconditionally on every scan once cache is warm.
* Never raises — all public functions return a result dict or None on error.
* PAPER TRADING ONLY — no order placement.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ── Feature flag ──────────────────────────────────────────────────────────────
OHLCV_CACHE_ENABLED: bool = os.environ.get("OHLCV_CACHE_ENABLED", "true").lower() != "false"

# ── Freshness thresholds ──────────────────────────────────────────────────────
LIVE_DAYS = 3
NEAR_LIVE_DAYS = 5
STALE_DAYS = 14
# Max age beyond which a cache entry is considered UNAVAILABLE
MAX_CACHE_AGE_DAYS = STALE_DAYS

# Minimum number of daily bars required to compute all indicators reliably
MIN_BARS_REQUIRED = 126   # ~6 calendar months of trading days

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_available() -> bool:
    try:
        import psycopg2  # noqa: F401
        _url = os.environ.get("DATABASE_URL", "")
        return bool(_url)
    except Exception:
        return False


@contextmanager
def _connect() -> Generator:
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_tables() -> bool:
    """Create cache tables if they don't exist. Returns True on success."""
    if not _db_available():
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS daily_ohlcv_cache (
                        symbol          TEXT NOT NULL,
                        trading_date    DATE NOT NULL,
                        open            NUMERIC(14,4),
                        high            NUMERIC(14,4),
                        low             NUMERIC(14,4),
                        close           NUMERIC(14,4),
                        adjusted_close  NUMERIC(14,4),
                        volume          BIGINT,
                        source          TEXT DEFAULT 'yfinance',
                        fetched_at      TIMESTAMPTZ DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ DEFAULT NOW(),
                        data_quality    TEXT,
                        PRIMARY KEY (symbol, trading_date)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS daily_ohlcv_refresh_state (
                        id                  SERIAL PRIMARY KEY,
                        refresh_date        DATE,
                        refresh_type        TEXT,
                        status              TEXT,
                        symbols_requested   INTEGER DEFAULT 0,
                        symbols_updated     INTEGER DEFAULT 0,
                        missing_symbols     TEXT[],
                        stale_symbols       TEXT[],
                        failed_symbols      TEXT[],
                        start_time          TIMESTAMPTZ,
                        end_time            TIMESTAMPTZ,
                        duration_seconds    NUMERIC(10,2),
                        error_summary       TEXT
                    )
                """)
        return True
    except Exception as exc:
        logger.warning("ohlcv_cache_store.ensure_tables failed: %s", exc)
        return False


# ── Read from cache ───────────────────────────────────────────────────────────

def read_symbol_from_cache(
    symbol: str,
    min_bars: int = MIN_BARS_REQUIRED,
) -> Optional[pd.DataFrame]:
    """
    Return a DataFrame of daily OHLCV bars from the local cache for *symbol*.
    Returns None if the cache is empty, stale, or DB is unavailable.
    The returned DataFrame has a DatetimeIndex and columns: open high low close volume.
    """
    if not OHLCV_CACHE_ENABLED or not _db_available():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT trading_date, open, high, low, close, volume
                    FROM daily_ohlcv_cache
                    WHERE symbol = %s
                    ORDER BY trading_date ASC
                """, (symbol.upper(),))
                rows = cur.fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()
        if len(df) < min_bars:
            return None   # not enough history
        # Freshness check: reject if latest bar is too old
        latest = df.index[-1].date()
        age_days = (date.today() - latest).days
        if age_days > MAX_CACHE_AGE_DAYS:
            return None   # STALE/UNAVAILABLE — force a yfinance refresh
        return df
    except Exception as exc:
        logger.warning("ohlcv_cache_store.read_symbol_from_cache(%s): %s", symbol, exc)
        return None


def get_cache_status(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Return per-symbol cache metadata:
      {SYMBOL: {cached, latest_date, age_days, bars, data_quality, missing_required}}
    """
    if not _db_available():
        return {s.upper(): {"cached": False, "error": "db_unavailable"} for s in symbols}
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        symbol,
                        MAX(trading_date) AS latest_date,
                        COUNT(*)          AS bars
                    FROM daily_ohlcv_cache
                    WHERE symbol = ANY(%s)
                    GROUP BY symbol
                """, ([s.upper() for s in symbols],))
                rows = cur.fetchall()
        by_sym = {r[0]: r for r in rows}
        today = date.today()
        result: Dict[str, Dict[str, Any]] = {}
        for sym in symbols:
            key = sym.upper()
            row = by_sym.get(key)
            if row is None:
                result[key] = {"cached": False, "bars": 0, "data_quality": "UNAVAILABLE"}
            else:
                latest = row[1]          # date object
                bars = int(row[2])
                age_days = (today - latest).days
                if age_days <= LIVE_DAYS:
                    quality = "LIVE"
                elif age_days <= NEAR_LIVE_DAYS:
                    quality = "NEAR_LIVE"
                elif age_days <= STALE_DAYS:
                    quality = "STALE"
                else:
                    quality = "UNAVAILABLE"
                result[key] = {
                    "cached": True,
                    "latest_date": latest.isoformat(),
                    "age_days": age_days,
                    "bars": bars,
                    "data_quality": quality,
                    "missing_required": bars < MIN_BARS_REQUIRED,
                }
        # Symbols not in DB at all
        for sym in symbols:
            if sym.upper() not in result:
                result[sym.upper()] = {"cached": False, "bars": 0, "data_quality": "UNAVAILABLE"}
        return result
    except Exception as exc:
        logger.warning("ohlcv_cache_store.get_cache_status: %s", exc)
        return {s.upper(): {"cached": False, "error": str(exc)[:120]} for s in symbols}


def get_overall_cache_summary(symbols: List[str]) -> Dict[str, Any]:
    """Aggregate cache status across all symbols for dashboard display."""
    status = get_cache_status(symbols)
    counts: Dict[str, int] = {"LIVE": 0, "NEAR_LIVE": 0, "STALE": 0, "UNAVAILABLE": 0}
    missing_required: List[str] = []
    uncached: List[str] = []
    stale: List[str] = []
    latest_dates: List[str] = []
    for sym, info in status.items():
        q = info.get("data_quality", "UNAVAILABLE")
        counts[q] = counts.get(q, 0) + 1
        if not info.get("cached"):
            uncached.append(sym)
        if info.get("missing_required"):
            missing_required.append(sym)
        if q in ("STALE", "UNAVAILABLE") and info.get("cached"):
            stale.append(sym)
        ld = info.get("latest_date")
        if ld:
            latest_dates.append(ld)

    latest_date = max(latest_dates) if latest_dates else None
    total = len(symbols)
    live_count = counts["LIVE"] + counts["NEAR_LIVE"]
    cache_hit_rate = round(live_count / total * 100, 1) if total else 0.0

    # Get last refresh run
    last_refresh = _get_last_refresh_state()

    return {
        "ohlcv_source": "local_yfinance_cache" if cache_hit_rate >= 80 else "yfinance_fallback",
        "original_data_source": "yfinance",
        "cache_enabled": OHLCV_CACHE_ENABLED,
        "total_symbols": total,
        "quality_counts": counts,
        "cache_hit_rate_pct": cache_hit_rate,
        "live_symbols": live_count,
        "uncached_symbols": uncached,
        "stale_symbols": stale,
        "missing_required_bars": missing_required,
        "latest_cached_date": latest_date,
        "last_postmarket_refresh": last_refresh,
        "min_bars_required": MIN_BARS_REQUIRED,
    }


def _get_last_refresh_state() -> Optional[Dict[str, Any]]:
    if not _db_available():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT refresh_date, refresh_type, status,
                           symbols_requested, symbols_updated,
                           failed_symbols, duration_seconds, end_time
                    FROM daily_ohlcv_refresh_state
                    ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
        if not row:
            return None
        return {
            "refresh_date": str(row[0]) if row[0] else None,
            "refresh_type": row[1],
            "status": row[2],
            "symbols_requested": row[3],
            "symbols_updated": row[4],
            "failed_symbols": row[5] or [],
            "duration_seconds": float(row[6]) if row[6] else None,
            "end_time": row[7].isoformat() if row[7] else None,
        }
    except Exception:
        return None


# ── Write to cache ────────────────────────────────────────────────────────────

def write_symbol_to_cache(
    symbol: str,
    df: pd.DataFrame,
    source: str = "yfinance",
) -> int:
    """
    Upsert all rows from *df* into daily_ohlcv_cache for *symbol*.
    Returns the number of rows written. Never raises.
    """
    if not _db_available() or df is None or df.empty:
        return 0
    try:
        sym = symbol.upper()
        today = date.today()
        rows = []
        for idx, row in df.iterrows():
            try:
                td = idx.date() if hasattr(idx, "date") else pd.Timestamp(idx).date()
                o = float(row.get("open", row.get("Open", 0)))
                h = float(row.get("high", row.get("High", 0)))
                lo = float(row.get("low", row.get("Low", 0)))
                cl = float(row.get("close", row.get("Close", 0)))
                adj_cl = float(row.get("adj close", row.get("Adj Close", cl)))
                vol = int(row.get("volume", row.get("Volume", 0)))
                age_days = (today - td).days
                if age_days <= LIVE_DAYS:
                    dq = "LIVE"
                elif age_days <= NEAR_LIVE_DAYS:
                    dq = "NEAR_LIVE"
                elif age_days <= STALE_DAYS:
                    dq = "STALE"
                else:
                    dq = "UNAVAILABLE"
                rows.append((sym, td, o, h, lo, cl, adj_cl, vol, source, dq))
            except Exception:
                continue

        if not rows:
            return 0

        with _connect() as conn:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(cur, """
                    INSERT INTO daily_ohlcv_cache
                        (symbol, trading_date, open, high, low, close, adjusted_close,
                         volume, source, data_quality, updated_at)
                    VALUES %s
                    ON CONFLICT (symbol, trading_date) DO UPDATE SET
                        open           = EXCLUDED.open,
                        high           = EXCLUDED.high,
                        low            = EXCLUDED.low,
                        close          = EXCLUDED.close,
                        adjusted_close = EXCLUDED.adjusted_close,
                        volume         = EXCLUDED.volume,
                        source         = EXCLUDED.source,
                        data_quality   = EXCLUDED.data_quality,
                        updated_at     = NOW()
                """, [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9])
                      for r in rows])
        return len(rows)
    except Exception as exc:
        logger.warning("ohlcv_cache_store.write_symbol_to_cache(%s): %s", symbol, exc)
        return 0


# ── Refresh state logging ─────────────────────────────────────────────────────

def log_refresh_start(
    refresh_type: str,
    symbols_requested: int,
) -> Optional[int]:
    """Insert a RUNNING refresh row, return its id."""
    if not _db_available():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO daily_ohlcv_refresh_state
                        (refresh_date, refresh_type, status, symbols_requested, start_time)
                    VALUES (%s, %s, 'RUNNING', %s, NOW())
                    RETURNING id
                """, (date.today(), refresh_type, symbols_requested))
                row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception as exc:
        logger.warning("ohlcv_cache_store.log_refresh_start: %s", exc)
        return None


def log_refresh_complete(
    run_id: Optional[int],
    status: str,
    symbols_updated: int,
    failed_symbols: List[str],
    missing_symbols: List[str],
    stale_symbols: List[str],
    duration_seconds: float,
    error_summary: Optional[str] = None,
) -> None:
    if not _db_available() or run_id is None:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE daily_ohlcv_refresh_state SET
                        status            = %s,
                        symbols_updated   = %s,
                        failed_symbols    = %s,
                        missing_symbols   = %s,
                        stale_symbols     = %s,
                        duration_seconds  = %s,
                        error_summary     = %s,
                        end_time          = NOW()
                    WHERE id = %s
                """, (status, symbols_updated, failed_symbols,
                      missing_symbols, stale_symbols,
                      round(duration_seconds, 2), error_summary, run_id))
    except Exception as exc:
        logger.warning("ohlcv_cache_store.log_refresh_complete: %s", exc)


# ── Backfill (initial load) ───────────────────────────────────────────────────

def backfill_all_symbols(
    symbols: List[str],
    period: str = "6mo",
    interval: str = "1d",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Backfill 6-month daily OHLCV history for all symbols into the cache.
    Skips symbols that already have fresh cache (unless force=True).
    Returns a summary dict. Never raises.
    """
    ensure_tables()
    t0 = time.monotonic()
    run_id = log_refresh_start("backfill", len(symbols))

    updated: List[str] = []
    skipped: List[str] = []
    failed: List[str] = []

    # Check which symbols already have adequate fresh cache
    status = get_cache_status(symbols) if not force else {}

    symbols_to_fetch: List[str] = []
    for sym in symbols:
        info = status.get(sym.upper(), {})
        if not force and info.get("cached") and not info.get("missing_required") \
                and info.get("data_quality") in ("LIVE", "NEAR_LIVE"):
            skipped.append(sym.upper())
        else:
            symbols_to_fetch.append(sym)

    if symbols_to_fetch:
        try:
            import yfinance as yf
            tickers = [s.upper() + ".NS" for s in symbols_to_fetch]
            bulk = yf.download(
                tickers, period=period, interval=interval,
                progress=False, auto_adjust=True,
                group_by="ticker", threads=True,
            )
            for sym, tick in zip(symbols_to_fetch, tickers):
                try:
                    if isinstance(bulk.columns, pd.MultiIndex) and \
                            tick in bulk.columns.get_level_values(0):
                        df_raw = bulk[tick].copy()
                    elif len(symbols_to_fetch) == 1:
                        df_raw = bulk.copy()
                    else:
                        df_raw = None

                    if df_raw is not None:
                        df_raw.columns = [c.lower() for c in df_raw.columns]
                        df_raw = df_raw.dropna()
                        n = write_symbol_to_cache(sym, df_raw, source="yfinance")
                        if n > 0:
                            updated.append(sym.upper())
                        else:
                            failed.append(sym.upper())
                    else:
                        # Per-symbol fallback
                        _res = _fetch_single_yfinance(sym, period, interval)
                        if _res is not None:
                            write_symbol_to_cache(sym, _res, source="yfinance")
                            updated.append(sym.upper())
                        else:
                            failed.append(sym.upper())
                except Exception as exc:
                    logger.warning("backfill_all_symbols(%s): %s", sym, exc)
                    failed.append(sym.upper())
        except Exception as exc:
            logger.warning("backfill_all_symbols bulk download failed: %s", exc)
            # Fall back to per-symbol
            for sym in symbols_to_fetch:
                try:
                    df = _fetch_single_yfinance(sym, period, interval)
                    if df is not None:
                        write_symbol_to_cache(sym, df, source="yfinance")
                        updated.append(sym.upper())
                    else:
                        failed.append(sym.upper())
                except Exception as e2:
                    logger.warning("backfill per-symbol fallback(%s): %s", sym, e2)
                    failed.append(sym.upper())

    duration = round(time.monotonic() - t0, 2)
    status_str = "SUCCESS" if not failed else ("PARTIAL" if updated else "FAILED")
    log_refresh_complete(
        run_id, status_str,
        symbols_updated=len(updated),
        failed_symbols=failed,
        missing_symbols=[],
        stale_symbols=[],
        duration_seconds=duration,
        error_summary=f"{len(failed)} failed" if failed else None,
    )
    return {
        "success": True,
        "refresh_type": "backfill",
        "symbols_requested": len(symbols),
        "symbols_updated": len(updated),
        "symbols_skipped": len(skipped),
        "symbols_failed": len(failed),
        "failed_symbols": failed,
        "skipped_symbols": skipped,
        "duration_seconds": duration,
        "status": status_str,
    }


def _fetch_single_yfinance(
    symbol: str, period: str, interval: str
) -> Optional[pd.DataFrame]:
    """Single-symbol yfinance fetch. Returns cleaned DataFrame or None."""
    try:
        import yfinance as yf
        ticker = symbol.upper() + ".NS"
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]
        df = df.dropna()
        return df if not df.empty else None
    except Exception:
        return None
