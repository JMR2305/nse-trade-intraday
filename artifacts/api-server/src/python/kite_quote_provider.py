"""
kite_quote_provider.py — Phase 19: Zerodha Kite Connect Live Quote Provider

Responsibilities
----------------
* Fetch live LTP (Last Traded Price) and OHLC from Kite Connect quote API.
* Accept NSE symbols; format them as "NSE:{SYMBOL}" for Kite's API.
* Implement a 30-second in-memory cache to avoid rate-limit hits.
* Rate-limit to ≤3 calls/second on the Kite API.
* Fall back to yfinance-derived last close on any Kite error.
* Always label data_source so callers know which provider served the data.
* Never place or modify orders — read-only.

Kite rate limits (as of 2024):
  - Quote API: 10 req/s (we stay well under with caching)
  - Historical data API: 3 req/s
  - No pagination needed for quote (bulk up to ~500 symbols per call)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

QUOTE_CACHE_TTL_S  = 30          # seconds to cache bulk quote response
RATE_LIMIT_INTERVAL = 0.35       # 1 / ~3 req/s safety margin
MAX_SYMBOLS_PER_CALL = 200       # Kite's bulk quote limit is ~500; we stay low

# ── Module-level cache ────────────────────────────────────────────────────────

_quote_cache: Dict[str, Dict[str, Any]] = {}   # symbol → quote dict
_quote_cache_ts: float = 0.0
_last_call_ts: float = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kite_symbol(symbol: str) -> str:
    """Convert bare NSE symbol to Kite's "NSE:SYMBOL" format."""
    s = symbol.upper().strip()
    if ":" in s:
        return s
    return f"NSE:{s}"


def _get_kite_client():
    """Instantiate a KiteConnect client from env vars. Raises if unavailable."""
    from kiteconnect import KiteConnect
    api_key = os.environ.get("ZERODHA_API_KEY") or ""
    token   = os.environ.get("ZERODHA_ACCESS_TOKEN") or ""
    if not api_key or not token:
        raise ValueError("ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN env vars required")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    return kite


def _throttle() -> None:
    global _last_call_ts
    elapsed = time.monotonic() - _last_call_ts
    if elapsed < RATE_LIMIT_INTERVAL:
        time.sleep(RATE_LIMIT_INTERVAL - elapsed)
    _last_call_ts = time.monotonic()


def _yfinance_fallback_ltp(symbol: str) -> Optional[float]:
    """Get last close from yfinance as a fallback LTP estimate."""
    try:
        import yfinance as yf
        ticker = symbol.upper().strip()
        if not ticker.endswith(".NS"):
            ticker += ".NS"
        df = yf.download(ticker, period="2d", interval="1d",
                         progress=False, auto_adjust=True)
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    return None


# ── Core fetch ────────────────────────────────────────────────────────────────

def _fetch_quotes_from_kite(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch live quotes from Kite for the given NSE symbols.
    Returns {symbol: {ltp, open, high, low, close, volume, data_source, ...}}.
    Raises on Kite error — caller wraps with fallback.
    """
    kite = _get_kite_client()
    kite_syms = [_kite_symbol(s) for s in symbols]
    _throttle()
    raw = kite.quote(kite_syms)   # {kite_sym: {last_price, ohlc, volume, ...}}
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result: Dict[str, Dict[str, Any]] = {}
    for sym, ks in zip(symbols, kite_syms):
        q = raw.get(ks) or {}
        ohlc = q.get("ohlc") or {}
        result[sym.upper()] = {
            "symbol": sym.upper(),
            "ltp": q.get("last_price"),
            "open": ohlc.get("open"),
            "high": ohlc.get("high"),
            "low": ohlc.get("low"),
            "close": ohlc.get("close"),      # previous day close
            "volume": q.get("volume"),
            "net_change": q.get("net_change"),
            "oi": q.get("oi"),
            "bid": (q.get("depth") or {}).get("buy", [{}])[0].get("price"),
            "ask": (q.get("depth") or {}).get("sell", [{}])[0].get("price"),
            "data_source": "kite_live",
            "data_quality": "LIVE",
            "fetched_at": fetched_at,
        }
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def get_quotes(symbols: List[str], force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Return live quotes for the given NSE symbols.

    Uses 30s cache. On any Kite error, falls back to yfinance last close.
    Never raises — returns a result dict with data_source field indicating
    which provider served each symbol.
    """
    global _quote_cache, _quote_cache_ts

    if not symbols:
        return {}

    syms_upper = [s.upper().strip() for s in symbols]
    now_ts = time.monotonic()

    # Check cache
    cache_age = now_ts - _quote_cache_ts
    if not force_refresh and cache_age < QUOTE_CACHE_TTL_S and _quote_cache:
        cached = {s: _quote_cache[s] for s in syms_upper if s in _quote_cache}
        missing = [s for s in syms_upper if s not in _quote_cache]
        if not missing:
            return cached
        syms_upper = missing   # only fetch missing ones

    result: Dict[str, Dict[str, Any]] = {}

    # Try Kite in batches
    try:
        for i in range(0, len(syms_upper), MAX_SYMBOLS_PER_CALL):
            batch = syms_upper[i : i + MAX_SYMBOLS_PER_CALL]
            batch_result = _fetch_quotes_from_kite(batch)
            result.update(batch_result)
        # Update cache
        _quote_cache.update(result)
        _quote_cache_ts = time.monotonic()
    except Exception as exc:
        logger.warning("Kite quote fetch failed (%s), falling back to yfinance", exc)
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for sym in syms_upper:
            if sym not in result:
                ltp = _yfinance_fallback_ltp(sym)
                result[sym] = {
                    "symbol": sym,
                    "ltp": ltp,
                    "open": None, "high": None, "low": None, "close": ltp,
                    "volume": None, "net_change": None, "oi": None,
                    "bid": None, "ask": None,
                    "data_source": "yfinance_fallback",
                    "data_quality": "NEAR_LIVE",
                    "fetched_at": fetched_at,
                    "kite_error": str(exc)[:200],
                }

    # Merge cached hits for originally-cached symbols
    final: Dict[str, Dict[str, Any]] = {}
    for s in [s.upper().strip() for s in symbols]:
        if s in result:
            final[s] = result[s]
        elif s in _quote_cache:
            final[s] = _quote_cache[s]
    return final


def get_ltp(symbols: List[str]) -> Dict[str, Optional[float]]:
    """
    Convenience: return just {symbol: ltp_float} for each symbol.
    Returns None for symbols where LTP is unavailable.
    """
    quotes = get_quotes(symbols)
    return {s: (q.get("ltp") if isinstance(q.get("ltp"), (int, float)) else None)
            for s, q in quotes.items()}


def kite_available() -> bool:
    """True if Kite credentials are present in the environment."""
    return bool(
        os.environ.get("ZERODHA_API_KEY") and
        os.environ.get("ZERODHA_ACCESS_TOKEN")
    )


def provider_label() -> str:
    """Human-readable provider label for UI display."""
    if kite_available():
        return "Zerodha Kite Connect (Live) + Yahoo Finance (History)"
    return "Yahoo Finance (History) — Kite Connect not configured"


def invalidate_cache() -> None:
    """Force next get_quotes() to fetch fresh data from Kite."""
    global _quote_cache, _quote_cache_ts
    _quote_cache = {}
    _quote_cache_ts = 0.0


if __name__ == "__main__":
    import json
    syms = ["RELIANCE", "TCS", "INFY"]
    print("Available:", kite_available())
    print("Provider:", provider_label())
    print(json.dumps(get_quotes(syms), indent=2, default=str))
