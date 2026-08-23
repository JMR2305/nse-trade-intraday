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


def _env_token_expired() -> bool:
    """True if the env token carries a timestamp past the daily 06:00 IST
    expiry. An env token without a timestamp is trusted (legacy setups).
    Fail-safe: a timestamp that is present but unparseable counts as expired."""
    ts = os.environ.get("ZERODHA_TOKEN_TIMESTAMP") or ""
    if not ts:
        return False
    try:
        import kite_token_store
        from datetime import datetime, timezone as _tz
        expiry = kite_token_store.token_expiry_utc(ts)
        if expiry is None:
            return True  # unparseable timestamp — do not trust the token
        return datetime.now(_tz.utc) >= expiry
    except Exception:
        return True


def _resolve_creds() -> tuple:
    """Resolve (api_key, access_token) with shared durable state first."""
    api_key = os.environ.get("ZERODHA_API_KEY") or ""
    try:
        import kite_token_store
        token, from_store = kite_token_store.resolve_preferred_token()
    except Exception:
        token = os.environ.get("ZERODHA_ACCESS_TOKEN") or ""
        from_store = False
    if token and not from_store and _env_token_expired():
        token = ""
    return api_key, token or ""


def _get_kite_client():
    """Instantiate a KiteConnect client. Raises if credentials unavailable."""
    from kiteconnect import KiteConnect
    api_key, token = _resolve_creds()
    if not api_key or not token:
        raise ValueError("ZERODHA_API_KEY and an access token (env or stored session) required")
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
        raw_ltp = q.get("last_price")
        try:
            has_live_ltp = float(raw_ltp) > 0
        except (TypeError, ValueError):
            has_live_ltp = False
        result[sym.upper()] = {
            "symbol": sym.upper(),
            "ltp": raw_ltp,
            "open": ohlc.get("open"),
            "high": ohlc.get("high"),
            "low": ohlc.get("low"),
            "close": ohlc.get("close"),      # previous day close
            "volume": q.get("volume"),
            "net_change": q.get("net_change"),
            "oi": q.get("oi"),
            "bid": (q.get("depth") or {}).get("buy", [{}])[0].get("price"),
            "ask": (q.get("depth") or {}).get("sell", [{}])[0].get("price"),
            # A successful bulk response does not prove every requested
            # instrument was quoted.  Never attribute an empty/malformed
            # per-symbol result to Kite live market data.
            "data_source": "kite_live" if has_live_ltp else "kite_unavailable",
            "data_quality": "LIVE" if has_live_ltp else "UNAVAILABLE",
            "fetched_at": fetched_at,
            **({} if has_live_ltp else {
                "reason_not_live": "Kite returned no valid last_price for symbol",
            }),
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
    """True if Kite api key AND an access token (env or durable stored
    session) are available to this process. Credential PRESENCE only —
    use kite_session_verified() to prove the session actually works."""
    api_key, token = _resolve_creds()
    return bool(api_key and token)


_verify_cache: Dict[str, Any] = {"ts": 0.0, "ok": False}
VERIFY_TTL_S = 300.0          # re-probe at most every 5 minutes
VERIFY_FAIL_TTL_S = 60.0      # re-probe failures sooner (login may happen)


def kite_session_verified(force: bool = False) -> bool:
    """
    True only if the stored Zerodha session has been PROVEN to work by a
    lightweight authenticated API probe (kite.profile()) within the TTL.

    Credential presence is NOT enough — an expired/invalid token must
    never let fallback data pass the provider gate for paper entries.
    Never raises.
    """
    if not kite_available():
        return False
    now = time.monotonic()
    age = now - _verify_cache["ts"]
    ttl = VERIFY_TTL_S if _verify_cache["ok"] else VERIFY_FAIL_TTL_S
    if not force and _verify_cache["ts"] > 0 and age < ttl:
        return bool(_verify_cache["ok"])
    ok = False
    try:
        kite = _get_kite_client()
        _throttle()
        prof = kite.profile()          # cheap authenticated call
        ok = bool(prof and prof.get("user_id"))
        try:
            import kite_token_store
            if ok:
                kite_token_store.record_success()
            else:
                kite_token_store.record_auth_failure()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Kite session probe failed: %s", str(exc)[:200])
        try:
            import kite_token_store
            kite_token_store.record_auth_failure()
        except Exception:
            pass
    _verify_cache["ts"] = time.monotonic()
    _verify_cache["ok"] = ok
    return ok


def kite_configured() -> bool:
    """True if the Kite API key is set (regardless of a live session)."""
    return bool(os.environ.get("ZERODHA_API_KEY"))


def provider_label() -> str:
    """Human-readable provider label for UI display.

    Distinguishes three honest states — never labels Yahoo data as Zerodha:
      * key + token       → Zerodha live quotes overlay Yahoo history
      * key, no token     → daily Zerodha login required
      * no key            → Kite Connect not configured
    """
    if kite_available():
        return "Zerodha Kite Connect (Live) + Yahoo Finance (History)"
    if kite_configured():
        return "Yahoo Finance (History) — Zerodha login required (no active session)"
    return "Yahoo Finance (History) — Kite Connect not configured"


def invalidate_cache() -> None:
    """Force fresh quotes and session verification after a credential change."""
    global _quote_cache, _quote_cache_ts, _verify_cache
    _quote_cache = {}
    _quote_cache_ts = 0.0
    _verify_cache = {"ts": 0.0, "ok": False}


if __name__ == "__main__":
    import json
    syms = ["RELIANCE", "TCS", "INFY"]
    print("Available:", kite_available())
    print("Provider:", provider_label())
    print(json.dumps(get_quotes(syms), indent=2, default=str))
