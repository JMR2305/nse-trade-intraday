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

# Minimum number of daily bars required to compute all indicators reliably.
# 120 ≈ 6 months of Indian trading days after deducting holidays.
# yfinance "6mo" typically returns 122-126 bars; 120 is the safe lower bound.
MIN_BARS_REQUIRED = 120   # ~6 calendar months accounting for NSE holidays

# ── Task978ZR R37 — bounded backfill / rate-limit hardening constants ─────────
# All timing is injectable via module attributes so offline tests never sleep.
# Serialized small batches (never threads=True) — a cold-start backfill must
# not storm Yahoo with a provider-wide fan-out that trips IP-level limits.
_BACKFILL_BATCH_SIZE = 5          # symbols per serialized batch
_BACKFILL_MAX_ATTEMPTS = 2        # bounded per-symbol retries inside Yahoo phase
_BACKFILL_COOLDOWN_S = 20.0       # pause after a detected rate-limit response
_BACKFILL_BATCH_PAUSE_S = 1.0     # polite pause between batches (0 disables)
_SLEEP = time.sleep               # injectable in tests: module._SLEEP = fake
_KITE_PACING_S = 0.35             # conservative pacing between Kite calls


def _looks_rate_limited(exc: Exception) -> bool:
    """Heuristic detection of provider-wide rate limiting from exception text.

    yfinance surfaces 429s / "Too Many Requests" / "rate limit" in error text.
    Never raises. Detection is intentionally conservative: matching strings
    must clearly indicate throttling, not a bad symbol or empty payload.
    """
    try:
        text = str(exc).lower()
        if not text:
            return False
        markers = (
            "rate limit",
            "ratelimit",
            "too many requests",
            "429",
            "yfratelimiterror",
        )
        return any(m in text for m in markers)
    except Exception:
        return False


# ── Task978ZR R37 — read-only Kite historical fallback ───────────────────────

def _kite_historical_available() -> bool:
    """True when ZERODHA_API_KEY and a resolvable access token exist.

    Credential resolution mirrors the established read-only precedent in
    kite_quote_provider._resolve_creds (durable token store first, env
    fallback, env-token expiry honored). NO order APIs are touched — this
    helper only ever calls kite.historical_data (read-only market data).
    Never raises.
    """
    try:
        if not os.environ.get("ZERODHA_API_KEY"):
            return False
        import kite_token_store
        token, from_store = kite_token_store.resolve_preferred_token()
        if token and not from_store:
            # Env-fallback token: honor the same daily-expiry check as quotes.
            ts = os.environ.get("ZERODHA_TOKEN_TIMESTAMP") or ""
            if ts:
                expiry = kite_token_store.token_expiry_utc(ts)
                if expiry is None:
                    return False
                if datetime.now(timezone.utc) >= expiry:
                    return False
        return bool(token)
    except Exception:
        return False


def _fetch_single_kite_historical(
    symbol: str,
    period_days: int = 250,
    interval: str = "day",
) -> Optional[pd.DataFrame]:
    """READ-ONLY daily-candle fetch from Kite historical_data for one symbol.

    Instrument tokens come exclusively from the validated instrument cache
    (kite_instrument_cache.get_token). Returns a DataFrame with the same
    lowercase OHLCV column contract as _fetch_single_yfinance, or None on any
    failure/insufficient data. Never raises. Requests are conservatively paced.
    """
    try:
        import kite_instrument_cache
        token = kite_instrument_cache.get_token(symbol)
        if not token:
            logger.info(
                "kite_historical(%s): no validated instrument token — skip",
                symbol,
            )
            return None
        from kiteconnect import KiteConnect
        import kite_token_store
        api_key = os.environ.get("ZERODHA_API_KEY") or ""
        access_token, _ = kite_token_store.resolve_preferred_token()
        if not api_key or not access_token:
            return None
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        to_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        from_dt = to_dt - timedelta(days=period_days)
        _SLEEP(_KITE_PACING_S)  # conservative pacing between Kite requests
        raw = kite.historical_data(token, from_dt, to_dt, interval)
        if not raw:
            return None
        df = pd.DataFrame(raw)
        if df.empty or "date" not in df.columns:
            return None
        df = df.rename(
            columns={
                "open": "open", "high": "high", "low": "low",
                "close": "close", "volume": "volume",
            }
        )
        needed = {"open", "high", "low", "close"}
        if not needed.issubset(set(df.columns)):
            return None
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df.dropna(subset=["open", "high", "low", "close"])
        if df.empty:
            return None
        if "volume" not in df.columns:
            df["volume"] = 0
        df.index.name = None
        return df
    except Exception as exc:
        logger.warning(
            "kite_historical(%s) failed (no credentials echoed): %s",
            symbol, str(exc)[:120],
        )
        return None


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
                # Remove the stale DESC index that was briefly introduced and then
                # retracted.  The PRIMARY KEY (symbol, trading_date) already covers
                # every ASC query pattern; this cleanup is idempotent.
                cur.execute(
                    "DROP INDEX IF EXISTS idx_ohlcv_cache_symbol_date"
                )
        return True
    except Exception as exc:
        logger.warning("ohlcv_cache_store.ensure_tables failed: %s", exc)
        return False


# ── Read from cache ───────────────────────────────────────────────────────────

def read_symbol_from_cache(
    symbol: str,
    min_bars: int = MIN_BARS_REQUIRED,
    end_date: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """
    Return a DataFrame of daily OHLCV bars from the local cache for *symbol*.
    Returns None if the cache is empty, stale, or DB is unavailable.
    The returned DataFrame has a DatetimeIndex and columns: open high low close volume.

    When *end_date* (ISO "YYYY-MM-DD") is provided the read is an **as-of**
    read: only bars with trading_date <= end_date are returned, and the
    freshness check is evaluated relative to end_date instead of today.
    This is the backtest path — a historical window must never be rejected
    just because it is old relative to the current date.
    """
    if not OHLCV_CACHE_ENABLED or not _db_available():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                if end_date:
                    cur.execute("""
                        SELECT trading_date, open, high, low, close, volume
                        FROM daily_ohlcv_cache
                        WHERE symbol = %s AND trading_date <= %s
                        ORDER BY trading_date ASC
                    """, (symbol.upper(), end_date))
                else:
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
        # Freshness check: reject if latest bar is too old.
        # For as-of (backtest) reads, age is measured against end_date so a
        # historical window is never rejected for being old vs today.
        latest = df.index[-1].date()
        ref_day = date.fromisoformat(end_date) if end_date else date.today()
        age_days = (ref_day - latest).days
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
                         volume, source, data_quality)
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
    period: str = "8mo",   # 8mo guarantees ≥120 bars even in heavy-holiday periods
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
    # Task978ZL — bounded non-secret per-symbol failure detail so a 50/50
    # style failure is diagnosable from the result payload alone.
    failure_details: Dict[str, Dict[str, str]] = {}

    def _record_failure(sym: str, reason: str) -> None:
        sym_u = sym.upper()
        # Task978ZR R37: a symbol is counted failed at most once even across
        # bounded retry passes — failure_details keeps the LATEST reason.
        if sym_u in failure_details:
            failure_details[sym_u] = {"reason": str(reason)[:120]}
            return
        failed.append(sym_u)
        if len(failure_details) < 50:
            failure_details[sym_u] = {"reason": str(reason)[:120]}

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

    # Task978ZR R37 — bounded serialized backfill (provider-hammering removed)
    # ---------------------------------------------------------------------
    # Old behavior (R37H root cause): yf.download(threads=True) bulk fan-out,
    # and on ANY bulk exception an IMMEDIATE unbounded per-symbol storm over
    # all remaining symbols with zero rate-limit detection, zero cooldown, and
    # zero retry bound. That pattern trips IP-wide Yahoo limits and keeps
    # hammering while limited.
    #
    # New behavior:
    #   1. serialized small batches (no threads), polite inter-batch pause
    #   2. per-symbol single-shot fetch; a rate-limited response raises a
    #      _RateLimited sentinel handled by the batch loop, not by hammering
    #   3. ONE bounded retry pass over remaining symbols after ONE cooldown
    #   4. remaining symbols after bounded Yahoo retries fall back to the
    #      READ-ONLY Kite historical adapter (daily candles only)
    #   5. every success persists immediately — partial progress is preserved

    rate_limited = False
    rate_limit_events = 0
    cooldown_disposition = "not_triggered"
    provider_used = "none"
    kite_fetched: List[str] = []
    attempts = 0

    if symbols_to_fetch:
        def _batched(seq: List[str]) -> Generator[List[str], None, None]:
            for i in range(0, len(seq), _BACKFILL_BATCH_SIZE):
                yield seq[i:i + _BACKFILL_BATCH_SIZE]

        def _run_yahoo_pass(pending: List[str]) -> List[str]:
            """One serialized pass over pending symbols. Returns still-missing.
            No sleeps on success path except the polite inter-batch pause."""
            nonlocal rate_limited, rate_limit_events, provider_used
            still_missing: List[str] = []
            for batch in _batched(pending):
                batch_rated = False
                for sym in batch:
                    try:
                        df = _fetch_single_yfinance(sym, period, interval)
                    except Exception as exc:
                        if _looks_rate_limited(exc):
                            rate_limited = True
                            rate_limit_events += 1
                            batch_rated = True
                            # Provider-wide limit detected — stop issuing
                            # requests immediately (no hammering).
                            still_missing.append(sym)
                            break
                        logger.warning("backfill yahoo(%s): %s", sym, str(exc)[:120])
                        still_missing.append(sym)
                        continue
                    if df is not None:
                        n = write_symbol_to_cache(sym, df, source="yfinance")
                        if n > 0:
                            provider_used = "yfinance" if provider_used == "none" else provider_used
                            updated.append(sym.upper())
                        else:
                            _record_failure(sym, "empty_or_write_rejected")
                            still_missing.append(sym)
                    else:
                        still_missing.append(sym)
                if batch_rated:
                    # Symbols later in this pass (later batch items and every
                    # following batch) are not hammered; a single cooldown then
                    # ONE bounded retry pass covers them.
                    break
                if _BACKFILL_BATCH_PAUSE_S > 0:
                    _SLEEP(_BACKFILL_BATCH_PAUSE_S)
            # Any symbols never attempted (deferred after a rate-limit break)
            # must be carried into still_missing so they are retried once and,
            # if still failing, reported as explicit failures — never silently
            # dropped.
            handled = {s.upper() for s in still_missing} | {u for u in updated}
            for s in pending:
                if s.upper() not in handled:
                    still_missing.append(s)
            # de-dup while preserving order, excluding updated symbols
            seen = set()
            ordered_missing = []
            updated_set = {u for u in updated}
            for s in still_missing:
                s_u = s.upper()
                if s_u not in seen and s_u not in updated_set:
                    seen.add(s_u)
                    ordered_missing.append(s)
            return ordered_missing

        remaining = _run_yahoo_pass(list(symbols_to_fetch))

        # ONE bounded cooldown + ONE bounded retry pass for rate-limit case.
        attempts = 1
        if remaining and rate_limited:
            cooldown_disposition = "single_cooldown_then_bounded_retry"
            _SLEEP(_BACKFILL_COOLDOWN_S)
            remaining = _run_yahoo_pass(remaining)
            attempts += 1
        elif remaining:
            # Non-rate-limit failures: one bounded immediate retry pass.
            cooldown_disposition = "single_bounded_retry_no_cooldown"
            remaining = _run_yahoo_pass(remaining)
            attempts += 1

        # Kite historical fallback — READ-ONLY, only for still-remaining symbols.
        if remaining and _kite_historical_available():
            cooldown_disposition = (
                cooldown_disposition + "+kite_historical_fallback"
                if cooldown_disposition != "not_triggered"
                else "kite_historical_fallback"
            )
            still_after_kite: List[str] = []
            for sym in remaining:
                df = _fetch_single_kite_historical(sym)
                if df is not None:
                    n = write_symbol_to_cache(sym, df, source="kite_historical")
                    if n > 0:
                        kite_fetched.append(sym.upper())
                        updated.append(sym.upper())
                        provider_used = "kite_historical" if provider_used == "none" else provider_used
                    else:
                        _record_failure(sym, "kite_write_rejected")
                        still_after_kite.append(sym)
                else:
                    still_after_kite.append(sym)
            remaining = still_after_kite

        for sym in remaining:
            sym_u = sym.upper()
            if sym_u not in updated and sym_u not in failed:
                _record_failure(sym, "provider_fetch_empty_after_bounded_retries")

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
        "failure_details": failure_details,
        "skipped_symbols": skipped,
        "duration_seconds": duration,
        "status": status_str,
        # Task978ZR R37 structured provider/rate-limit evidence
        "provider": provider_used,
        "rate_limited": rate_limited,
        "attempts": attempts,
        "rate_limit_events": rate_limit_events,
        "cooldown_disposition": cooldown_disposition,
        "kite_historical_used": bool(kite_fetched),
        "kite_symbols_fetched": kite_fetched,
    }


def _fetch_single_yfinance(
    symbol: str, period: str, interval: str
) -> Optional[pd.DataFrame]:
    """Single-symbol yfinance fetch. Returns cleaned DataFrame or None.

    Task978ZR R37: provider-wide rate-limit responses are RE-RAISED (not
    swallowed) so the bounded backfill loop can detect throttling, pause, and
    defer remaining symbols instead of hammering the provider. All other
    errors still return None and never raise.
    """
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
    except Exception as exc:
        if _looks_rate_limited(exc):
            raise
        return None
