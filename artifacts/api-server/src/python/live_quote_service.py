"""
live_quote_service.py — Phase 11 Live Data Foundation
Provider-interface quote layer: normalized, null-preserving spot quotes for
NSE symbols and index benchmarks, with TTL cache, throttling and a
circuit breaker.

Design principles
-----------------
* Provider interface (QuoteProvider) — yfinance today, swappable later.
* Honest values only: a missing price is None, never fabricated.
* TTL cache keeps repeated polls cheap; cache age is always reported.
* Circuit breaker: after CB_FAILURE_THRESHOLD consecutive full failures the
  provider is marked OPEN for CB_COOLDOWN_S seconds and returns cached /
  UNAVAILABLE data instead of hammering the upstream.
* Symbol whitelist: only NIFTY-50 universe symbols + known indices allowed.
* PAPER TRADING ONLY — no orders, research only.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import NIFTY_50
from market_hours import market_state, market_status

PROVIDER_ID = "yfinance"
PROVIDER_NAME = "Yahoo Finance (yfinance)"

QUOTE_TTL_S = 20.0            # market open: quotes considered fresh for 20s
QUOTE_TTL_CLOSED_S = 300.0    # market closed: 5 min TTL
CB_FAILURE_THRESHOLD = 3      # consecutive batch failures to open breaker
CB_COOLDOWN_S = 60.0

STATE_FILE = os.path.join(os.path.dirname(__file__), "phase11_quote_state.json")

INDICES = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "INDIAVIX": "^INDIAVIX",
}

_ALLOWED = {s.upper() for s in NIFTY_50} | set(INDICES.keys())

# ── Demerged / suspended symbols ─────────────────────────────────────────────
# Symbols listed here are rejected immediately without a yfinance call.
# They return quality=UNAVAILABLE, tradable=False, and a clear note so any
# UI layer can display "Data unavailable — no BUY allowed" rather than
# showing a stale/fabricated price.
# The scan-engine quality gate (_apply_quality_gate in live_scan_engine.py)
# already caps UNAVAILABLE data to IGNORE — these symbols can never produce
# a BUY or STRONG BUY even if they were allowed through.
_DEMERGED: dict[str, str] = {
    "TATAMOTORS": (
        "TATAMOTORS was demerged in 2024 into TMPV (Tata Motors Passenger "
        "Vehicles Ltd, ~₹343) and TMCV (Tata Motors Commercial Vehicles Ltd, "
        "~₹457). yfinance raises an exchange-metadata error for TATAMOTORS.NS. "
        "Use TMPV or TMCV. DATA UNAVAILABLE — no BUY allowed."
    ),
}


def is_allowed_symbol(symbol: str) -> bool:
    return symbol.upper().strip() in _ALLOWED


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v: Any) -> Optional[float]:
    """Normalize numbers; NaN/inf/negative-zero garbage becomes None."""
    try:
        if v is None:
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


class QuoteProvider:
    """Interface for spot-quote providers."""

    provider_id = "abstract"
    provider_name = "Abstract Provider"

    def fetch_quote(self, symbol: str) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class YFinanceQuoteProvider(QuoteProvider):
    provider_id = PROVIDER_ID
    provider_name = PROVIDER_NAME

    RATE_LIMIT_S = 0.15

    def __init__(self) -> None:
        self._last_call = 0.0

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.RATE_LIMIT_S:
            time.sleep(self.RATE_LIMIT_S - gap)
        self._last_call = time.monotonic()

    def _ticker_symbol(self, symbol: str) -> str:
        s = symbol.upper().strip()
        if s in INDICES:
            return INDICES[s]
        return s if s.endswith(".NS") else s + ".NS"

    def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch one normalized quote. Never raises; errors are reported."""
        import yfinance as yf

        t0 = time.monotonic()
        self._throttle()
        out: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "ltp": None,
            "prev_close": None,
            "change": None,
            "change_pct": None,
            "day_high": None,
            "day_low": None,
            "volume": None,
            "currency": "INR",
            "source": self.provider_id,
            "fetch_ts": _utc_now_iso(),
            "latency_ms": None,
            "quality": "UNAVAILABLE",
            "error": None,
        }
        try:
            tk = yf.Ticker(self._ticker_symbol(symbol))
            fi = tk.fast_info
            ltp = _clean(getattr(fi, "last_price", None))
            prev = _clean(getattr(fi, "previous_close", None))
            out["ltp"] = ltp
            out["prev_close"] = prev
            out["day_high"] = _clean(getattr(fi, "day_high", None))
            out["day_low"] = _clean(getattr(fi, "day_low", None))
            vol = getattr(fi, "last_volume", None)
            out["volume"] = int(vol) if isinstance(vol, (int, float)) and not math.isnan(float(vol)) else None
            if ltp is not None and prev not in (None, 0):
                out["change"] = round(ltp - prev, 4)
                out["change_pct"] = round((ltp - prev) / prev * 100, 4)
            if ltp is None:
                out["error"] = "No last price returned by provider"
            else:
                state = market_state()
                out["quality"] = "LIVE" if state == "OPEN" else "NEAR_LIVE"
        except Exception as exc:
            out["error"] = str(exc)[:300]
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        return out


# ── Cache + circuit breaker (persisted so short-lived CLI processes share it) ──

def _load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"cache": {}, "breaker": {"failures": 0, "opened_at": None},
                "last_success_ts": None, "fetch_count": 0, "error_count": 0}


def _save_state(state: Dict[str, Any]) -> None:
    """Atomic write (temp file + rename) so concurrent short-lived CLI
    processes never observe a partially-written state file."""
    try:
        tmp_path = STATE_FILE + f".tmp.{os.getpid()}"
        with open(tmp_path, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _breaker_open(state: Dict[str, Any]) -> bool:
    br = state.get("breaker", {})
    opened = br.get("opened_at")
    if opened is None:
        return False
    if time.time() - float(opened) >= CB_COOLDOWN_S:
        return False  # half-open: allow a probe
    return True


def get_quotes(symbols: List[str], force: bool = False) -> Dict[str, Any]:
    """
    Batch quote fetch with TTL cache + circuit breaker.
    Returns {quotes: {SYM: quote}, market: {...}, provider: {...}}.
    Unknown symbols are rejected (whitelist).
    """
    provider = YFinanceQuoteProvider()
    state = _load_state()
    cache: Dict[str, Any] = state.get("cache", {})
    ms = market_status()
    ttl = QUOTE_TTL_S if ms["state"] == "OPEN" else QUOTE_TTL_CLOSED_S
    now = time.time()

    quotes: Dict[str, Any] = {}
    rejected: List[str] = []
    fetched = 0
    errors = 0
    breaker_was_open = _breaker_open(state)

    for raw in symbols:
        sym = raw.upper().strip()

        # Demerged / suspended symbol — return immediately with a clear
        # UNAVAILABLE response (never calls yfinance, never returns a price).
        # The scan-engine quality gate caps these to IGNORE so no BUY is generated.
        if sym in _DEMERGED:
            quotes[sym] = {
                "symbol": sym,
                "ltp": None,
                "quality": "UNAVAILABLE",
                "tradable": False,
                "demerger_note": _DEMERGED[sym],
                "error": f"DATA UNAVAILABLE — {sym} is demerged. No BUY allowed.",
                "source": PROVIDER_ID,
                "fetch_ts": _utc_now_iso(),
                "from_cache": False,
                "cache_age_s": None,
            }
            continue

        if not is_allowed_symbol(sym):
            rejected.append(sym)
            continue

        entry = cache.get(sym)
        age = (now - entry["cached_at"]) if entry else None
        if entry and not force and age is not None and age < ttl:
            q = dict(entry["quote"])
            q["cache_age_s"] = round(age, 1)
            q["from_cache"] = True
            quotes[sym] = q
            continue

        if breaker_was_open:
            # Serve stale cache honestly, or report unavailable.
            if entry:
                q = dict(entry["quote"])
                q["cache_age_s"] = round(age, 1) if age is not None else None
                q["from_cache"] = True
                q["quality"] = "STALE"
                q["error"] = "Circuit breaker open — serving cached data"
                quotes[sym] = q
            else:
                quotes[sym] = {
                    "symbol": sym, "ltp": None, "quality": "UNAVAILABLE",
                    "error": "Circuit breaker open — provider unavailable",
                    "source": PROVIDER_ID, "fetch_ts": _utc_now_iso(),
                    "from_cache": False, "cache_age_s": None,
                }
            continue

        q = provider.fetch_quote(sym)
        fetched += 1
        if q.get("error"):
            errors += 1
            if entry:
                stale = dict(entry["quote"])
                stale["cache_age_s"] = round(age, 1) if age is not None else None
                stale["from_cache"] = True
                stale["quality"] = "STALE"
                stale["error"] = f"Fetch failed; cached value shown. ({q['error']})"
                quotes[sym] = stale
                continue
        else:
            cache[sym] = {"cached_at": now, "quote": q}
            state["last_success_ts"] = _utc_now_iso()
        q["cache_age_s"] = 0.0
        q["from_cache"] = False
        quotes[sym] = q

    # Circuit breaker accounting: full-batch failure counts as one strike.
    br = state.setdefault("breaker", {"failures": 0, "opened_at": None})
    if fetched > 0:
        if errors == fetched:
            br["failures"] = int(br.get("failures", 0)) + 1
            if br["failures"] >= CB_FAILURE_THRESHOLD and not br.get("opened_at"):
                br["opened_at"] = now
        else:
            br["failures"] = 0
            br["opened_at"] = None

    state["cache"] = cache
    state["fetch_count"] = int(state.get("fetch_count", 0)) + fetched
    state["error_count"] = int(state.get("error_count", 0)) + errors
    _save_state(state)

    return {
        "quotes": quotes,
        "rejected_symbols": rejected,
        "market": ms,
        "provider": provider_status(state),
        "label": "PAPER / RESEARCH ONLY",
    }


def provider_status(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    st = state if state is not None else _load_state()
    br = st.get("breaker", {})
    open_now = _breaker_open(st)
    return {
        "provider": PROVIDER_NAME,
        "provider_id": PROVIDER_ID,
        "circuit_breaker": "OPEN" if open_now else "CLOSED",
        "consecutive_failures": int(br.get("failures", 0)),
        "last_success_ts": st.get("last_success_ts"),
        "total_fetches": int(st.get("fetch_count", 0)),
        "total_errors": int(st.get("error_count", 0)),
        "cached_symbols": len(st.get("cache", {})),
        "quote_ttl_s": QUOTE_TTL_S,
        "quote_ttl_closed_s": QUOTE_TTL_CLOSED_S,
    }
