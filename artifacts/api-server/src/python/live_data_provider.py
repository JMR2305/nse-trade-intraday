"""
live_data_provider.py  —  Phase 7: Live Market Intelligence
Provider abstraction layer for NSE OHLCV data.

Design principles
-----------------
* Never places real broker orders.
* Reports honest staleness — never fabricates or silently caches bad data.
* No BUY / STRONG BUY recommendation may pass the safety gate when data
  quality is STALE or UNAVAILABLE (enforced by live_scan_engine.py).
* Retry with exponential back-off; hard rate-limit throttle between calls.
* Per-symbol health tracked so a single failing symbol cannot hide bad data.
* Provider is a simple abstraction: swappable for Zerodha Kite Connect later
  by implementing the same _fetch_symbol() signature.

Data-quality taxonomy
---------------------
  LIVE       : data from today or (weekend) last business day within 3 days
  NEAR_LIVE  : data 4–5 calendar days old (long weekend / market holiday)
  STALE      : data 6–14 days old
  UNAVAILABLE: data older than 14 days OR fetch completely failed

Safety gate (enforced externally in live_scan_engine.py):
  LIVE + NEAR_LIVE  → eligible for BUY/STRONG BUY
  STALE             → capped at WATCH
  UNAVAILABLE       → capped at IGNORE (symbol treated as failed)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

PROVIDER_NAME  = "Yahoo Finance (yfinance)"
PROVIDER_ID    = "yfinance"
MAX_RETRIES    = 3
RETRY_BASE_S   = 2.0          # exponential back-off base (seconds)
RATE_LIMIT_S   = 0.25         # minimum gap between yfinance calls (seconds)

LIVE_DAYS      = 3            # ≤3 calendar days → LIVE (covers weekends)
NEAR_LIVE_DAYS = 5            # ≤5 calendar days → NEAR_LIVE (long holiday)
STALE_DAYS     = 14           # ≤14 calendar days → STALE; beyond → UNAVAILABLE

SCAN_PERIOD    = "6mo"
SCAN_INTERVAL  = "1d"

# ── Data-quality states ──────────────────────────────────────────────────────

class DataQuality:
    LIVE        = "LIVE"
    NEAR_LIVE   = "NEAR_LIVE"
    STALE       = "STALE"
    UNAVAILABLE = "UNAVAILABLE"

    @staticmethod
    def from_age(age_days: Optional[float]) -> str:
        if age_days is None:
            return DataQuality.UNAVAILABLE
        if age_days <= LIVE_DAYS:
            return DataQuality.LIVE
        if age_days <= NEAR_LIVE_DAYS:
            return DataQuality.NEAR_LIVE
        if age_days <= STALE_DAYS:
            return DataQuality.STALE
        return DataQuality.UNAVAILABLE

    @staticmethod
    def eligible_for_buy(quality: str) -> bool:
        """Only LIVE and NEAR_LIVE data may generate BUY / STRONG BUY."""
        return quality in (DataQuality.LIVE, DataQuality.NEAR_LIVE)


# ── Per-symbol result ─────────────────────────────────────────────────────────

@dataclass
class SymbolFetchResult:
    symbol: str
    success: bool
    df: Optional[pd.DataFrame]               # OHLCV, None on failure
    latest_date: Optional[str]               # ISO date of the last bar
    data_age_days: Optional[float]           # calendar days since latest bar
    data_quality: str                        # DataQuality.*
    data_source: str                         # e.g. "yfinance"
    fetch_ts: str                            # ISO timestamp of this fetch
    fetch_latency_ms: int                    # round-trip time
    retries_used: int                        # how many retries were needed
    error: Optional[str]                     # human-readable error message
    bars: int                                # number of OHLCV bars returned
    via_fallback: bool = False               # fetched via per-symbol fallback path


# ── Provider health summary ───────────────────────────────────────────────────

@dataclass
class ProviderHealth:
    provider: str
    provider_id: str
    connection_status: str          # CONNECTED | DEGRADED | ERROR | NOT_TESTED
    last_successful_fetch: Optional[str]   # ISO timestamp
    symbols_requested: int
    symbols_succeeded: int
    symbols_stale: int
    symbols_unavailable: int
    symbol_coverage_pct: float
    stale_symbols: List[str]
    unavailable_symbols: List[str]
    errors: List[Dict[str, Any]]    # [{symbol, error}]
    avg_latency_ms: float
    max_latency_ms: int
    retry_events: int               # total retries across all symbols
    rate_limit_events: int
    snapshot_id: str
    snapshot_ts: str
    paper_execution_eligible: bool  # true if ≥80% symbols have LIVE/NEAR_LIVE data
    quality_summary: Dict[str, int] # {LIVE:n, NEAR_LIVE:n, STALE:n, UNAVAILABLE:n}
    notes: List[str]


# ── Core provider ─────────────────────────────────────────────────────────────

class LiveDataProvider:
    """
    Thin abstraction over yfinance for NSE daily OHLCV data.
    Swap out _fetch_raw() for Zerodha Kite Connect to upgrade the provider.
    """

    def __init__(self):
        self._last_call_ts: float = 0.0

    def _throttle(self):
        """Enforce per-call rate limit."""
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < RATE_LIMIT_S:
            time.sleep(RATE_LIMIT_S - elapsed)
        self._last_call_ts = time.monotonic()

    def _nse(self, symbol: str) -> str:
        s = symbol.upper().strip()
        return s if s.endswith(".NS") else s + ".NS"

    def _fetch_raw(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        """Single yfinance download — no retry logic here."""
        ticker = self._nse(symbol)
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data returned for {ticker}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                raise ValueError(f"Missing column '{col}' in data for {ticker}")
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index)
        df = df.dropna()
        if df.empty:
            raise ValueError(f"All rows NaN after dropna for {ticker}")
        return df

    def fetch_symbol(
        self,
        symbol: str,
        period: str = SCAN_PERIOD,
        interval: str = SCAN_INTERVAL,
    ) -> SymbolFetchResult:
        """
        Fetch OHLCV for one symbol with retry/back-off.
        Returns a SymbolFetchResult regardless of success/failure.
        Never raises.
        """
        fetch_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()
        last_err: Optional[str] = None
        retries = 0

        for attempt in range(MAX_RETRIES):
            try:
                self._throttle()
                df = self._fetch_raw(symbol, period, interval)
                latency = int((time.monotonic() - t0) * 1000)

                # Age calculation
                latest_dt = df.index[-1]
                if hasattr(latest_dt, "date"):
                    latest_date = latest_dt.date().isoformat()
                    age_days = (datetime.now(timezone.utc).date() - latest_dt.date()).days
                else:
                    latest_date = str(latest_dt)[:10]
                    age_days = None

                quality = DataQuality.from_age(age_days)

                return SymbolFetchResult(
                    symbol=symbol.upper(), success=True, df=df,
                    latest_date=latest_date, data_age_days=float(age_days) if age_days is not None else None,
                    data_quality=quality, data_source=PROVIDER_ID,
                    fetch_ts=fetch_ts, fetch_latency_ms=latency,
                    retries_used=retries, error=None, bars=len(df),
                )

            except Exception as exc:
                last_err = str(exc)
                retries = attempt + 1
                if attempt < MAX_RETRIES - 1:
                    sleep_s = RETRY_BASE_S * (2 ** attempt)
                    logger.warning("Retry %d for %s in %.1fs: %s", attempt + 1, symbol, sleep_s, exc)
                    time.sleep(sleep_s)

        latency = int((time.monotonic() - t0) * 1000)
        return SymbolFetchResult(
            symbol=symbol.upper(), success=False, df=None,
            latest_date=None, data_age_days=None,
            data_quality=DataQuality.UNAVAILABLE, data_source=PROVIDER_ID,
            fetch_ts=fetch_ts, fetch_latency_ms=latency,
            retries_used=retries, error=last_err or "Unknown error", bars=0,
        )

    def _build_result_from_df(self, symbol: str, df: pd.DataFrame,
                              fetch_ts: str, latency_ms: int,
                              retries: int = 0,
                              source: str = PROVIDER_ID) -> SymbolFetchResult:
        """Build a SymbolFetchResult from a clean OHLCV frame (honest age)."""
        latest_dt = df.index[-1]
        if hasattr(latest_dt, "date"):
            latest_date = latest_dt.date().isoformat()
            age_days: Optional[int] = (
                datetime.now(timezone.utc).date() - latest_dt.date()).days
        else:
            latest_date = str(latest_dt)[:10]
            age_days = None
        quality = DataQuality.from_age(age_days)
        return SymbolFetchResult(
            symbol=symbol.upper(), success=True, df=df,
            latest_date=latest_date,
            data_age_days=float(age_days) if age_days is not None else None,
            data_quality=quality, data_source=source,
            fetch_ts=fetch_ts, fetch_latency_ms=latency_ms,
            retries_used=retries, error=None, bars=len(df),
        )

    def _clean_symbol_frame(self, raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Normalise a per-symbol frame from a bulk download. None if unusable."""
        try:
            df = raw.copy()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            for col in ("open", "high", "low", "close", "volume"):
                if col not in df.columns:
                    return None
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            df = df.dropna()
            if df.empty:
                return None
            return df
        except Exception:
            return None

    def fetch_batch(
        self,
        symbols: List[str],
        period: str = SCAN_PERIOD,
        interval: str = SCAN_INTERVAL,
        progress_cb: Optional[Any] = None,
    ) -> Dict[str, SymbolFetchResult]:
        """
        Fetch all symbols. Phase 22: ONE bulk multi-ticker download replaces
        50 serial per-symbol calls — the serial path (0.25s throttle + up to
        3 retries with 2s/4s back-off per symbol) is what stretched
        production scans to 900+ seconds under provider throttling.

        Symbols missing or unusable in the bulk response fall back to the
        original per-symbol retry path, so coverage is never reduced.
        Data-quality labelling (LIVE/STALE/UNAVAILABLE) is identical.
        """
        results: Dict[str, SymbolFetchResult] = {}
        remaining = [s for s in symbols]

        fetch_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0 = time.monotonic()
        try:
            tickers = [self._nse(s) for s in remaining]
            self._throttle()
            bulk = yf.download(tickers, period=period, interval=interval,
                               progress=False, auto_adjust=True,
                               group_by="ticker", threads=True)
            latency = int((time.monotonic() - t0) * 1000)
            if bulk is not None and not bulk.empty:
                still: List[str] = []
                for sym, tick in zip(remaining, tickers):
                    df_raw = None
                    try:
                        if isinstance(bulk.columns, pd.MultiIndex) and \
                                tick in bulk.columns.get_level_values(0):
                            df_raw = bulk[tick]
                        elif len(remaining) == 1:
                            df_raw = bulk
                    except Exception:
                        df_raw = None
                    df = self._clean_symbol_frame(df_raw) if df_raw is not None else None
                    if df is not None:
                        results[sym.upper()] = self._build_result_from_df(
                            sym, df, fetch_ts, latency)
                    else:
                        still.append(sym)
                remaining = still
        except Exception as exc:
            logger.warning("Bulk download failed (%s) — falling back to "
                           "per-symbol fetch for all %d symbols",
                           str(exc)[:200], len(remaining))

        if progress_cb is not None:
            try:
                progress_cb(len(results), len(symbols))
            except Exception:
                pass

        # Per-symbol fallback (original retry/back-off path) for stragglers.
        for i, sym in enumerate(remaining, start=1):
            res = self.fetch_symbol(sym, period, interval)
            res.via_fallback = True
            results[sym.upper()] = res
            if progress_cb is not None:
                try:
                    progress_cb(len(results), len(symbols))
                except Exception:
                    pass
        return results

    def build_health_report(
        self,
        results: Dict[str, SymbolFetchResult],
        snapshot_id: str,
        snapshot_ts: str,
    ) -> ProviderHealth:
        """Summarise a batch of fetch results into a ProviderHealth record."""
        n = len(results)
        succeeded = [r for r in results.values() if r.success]
        stale = [r for r in results.values() if r.data_quality == DataQuality.STALE]
        unavail = [r for r in results.values() if r.data_quality == DataQuality.UNAVAILABLE]
        errors = [{"symbol": r.symbol, "error": r.error}
                  for r in results.values() if r.error]

        quality_counts = {DataQuality.LIVE: 0, DataQuality.NEAR_LIVE: 0,
                          DataQuality.STALE: 0, DataQuality.UNAVAILABLE: 0}
        for r in results.values():
            quality_counts[r.data_quality] = quality_counts.get(r.data_quality, 0) + 1

        latencies = [r.fetch_latency_ms for r in results.values()]
        avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
        max_lat = max(latencies) if latencies else 0

        retry_events = sum(r.retries_used for r in results.values())
        last_ok = max((r.fetch_ts for r in succeeded), default=None)

        coverage_pct = round(len(succeeded) / n * 100, 1) if n else 0.0
        live_count = quality_counts[DataQuality.LIVE] + quality_counts[DataQuality.NEAR_LIVE]
        paper_eligible = n > 0 and (live_count / n) >= 0.80

        if len(succeeded) == n:
            conn_status = "CONNECTED"
        elif len(succeeded) == 0:
            conn_status = "ERROR"
        else:
            conn_status = "DEGRADED"

        notes: List[str] = []
        if len(stale):
            notes.append(f"{len(stale)} symbols have STALE data — capped at WATCH decisions.")
        if len(unavail):
            notes.append(f"{len(unavail)} symbols UNAVAILABLE — excluded from BUY/STRONG BUY.")
        if retry_events:
            notes.append(f"{retry_events} retry event(s) during this fetch batch.")
        if not paper_eligible:
            notes.append("Paper execution NOT eligible — <80% symbols have fresh data.")
        notes.append("PAPER TRADING ONLY — no real orders are placed by this system.")

        return ProviderHealth(
            provider=PROVIDER_NAME, provider_id=PROVIDER_ID,
            connection_status=conn_status,
            last_successful_fetch=last_ok,
            symbols_requested=n, symbols_succeeded=len(succeeded),
            symbols_stale=len(stale), symbols_unavailable=len(unavail),
            symbol_coverage_pct=coverage_pct,
            stale_symbols=[r.symbol for r in stale],
            unavailable_symbols=[r.symbol for r in unavail],
            errors=errors, avg_latency_ms=avg_lat, max_latency_ms=max_lat,
            retry_events=retry_events, rate_limit_events=0,
            snapshot_id=snapshot_id, snapshot_ts=snapshot_ts,
            paper_execution_eligible=paper_eligible,
            quality_summary=quality_counts,
            notes=notes,
        )
