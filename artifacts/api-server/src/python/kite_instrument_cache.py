"""
kite_instrument_cache.py — Phase 19: Zerodha Kite Instrument Token Cache

Responsibilities
----------------
* Maintain a disk-backed JSON cache of NSE instruments (symbol → token map).
* Refresh the cache once per day (Kite's instrument list changes rarely).
* Provide fuzzy symbol search for the frontend instrument search feature.
* Fall back to bare-symbol lookups gracefully when cache is unavailable.
* Never place or modify orders — read-only.

Kite instrument tokens are required for historical_data() API calls.
For the quote() API, only "NSE:SYMBOL" format is needed (no token required).
This cache is therefore most useful for future historical data integration.

Cache file: data/kite_instruments.json  (alongside other JSON state files)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_PATH = os.path.join(_DIR, "kite_instruments_cache.json")

# ── Constants ─────────────────────────────────────────────────────────────────

CACHE_TTL_DAYS = 1              # refresh instrument list daily
MAX_SEARCH_RESULTS = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return date.today().isoformat()


def _load_cache() -> Dict[str, Any]:
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: Dict[str, Any]) -> None:
    tmp = _CACHE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _CACHE_PATH)
    except Exception as exc:
        logger.warning("Failed to save instrument cache: %s", exc)


def _cache_is_fresh(cache: Dict[str, Any]) -> bool:
    """Return True if the cache was populated today."""
    return cache.get("date") == _today_iso() and bool(cache.get("instruments"))


# ── Instrument fetch ──────────────────────────────────────────────────────────

def _fetch_from_kite() -> List[Dict[str, Any]]:
    """Fetch NSE instrument list from Kite. Raises on failure."""
    from kiteconnect import KiteConnect
    api_key = os.environ.get("ZERODHA_API_KEY") or ""
    token   = os.environ.get("ZERODHA_ACCESS_TOKEN") or ""
    if not api_key or not token:
        raise ValueError("Kite credentials not set")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    instruments = kite.instruments("NSE")
    return [
        {
            "symbol": str(i.get("tradingsymbol", "")),
            "name": str(i.get("name", "")),
            "token": i.get("instrument_token"),
            "exchange": str(i.get("exchange", "NSE")),
            "instrument_type": str(i.get("instrument_type", "")),
            "lot_size": i.get("lot_size", 1),
            "tick_size": i.get("tick_size"),
            "segment": str(i.get("segment", "")),
        }
        for i in (instruments or [])
        if i.get("tradingsymbol")
    ]


# ── Public API ────────────────────────────────────────────────────────────────

def refresh(force: bool = False) -> Dict[str, Any]:
    """
    Refresh the instrument cache if stale (or if force=True).
    Returns a status dict. Never raises.
    """
    cache = _load_cache()
    if not force and _cache_is_fresh(cache):
        return {
            "success": True,
            "refreshed": False,
            "reason": "cache_fresh",
            "count": len(cache.get("instruments", [])),
            "date": cache.get("date"),
        }

    try:
        instruments = _fetch_from_kite()
        cache = {
            "date": _today_iso(),
            "fetched_at": _now_utc(),
            "count": len(instruments),
            "instruments": instruments,
        }
        _save_cache(cache)
        return {
            "success": True,
            "refreshed": True,
            "count": len(instruments),
            "date": cache["date"],
        }
    except Exception as exc:
        logger.warning("Instrument cache refresh failed: %s", exc)
        return {
            "success": False,
            "refreshed": False,
            "error": str(exc)[:300],
            "count": len(cache.get("instruments", [])),
            "date": cache.get("date"),
        }


def get_token(symbol: str) -> Optional[int]:
    """Return the Kite instrument token for an NSE symbol, or None."""
    cache = _load_cache()
    sym = symbol.upper().strip()
    for inst in cache.get("instruments", []):
        if inst.get("symbol", "").upper() == sym:
            return inst.get("token")
    return None


def search(query: str, limit: int = MAX_SEARCH_RESULTS) -> List[Dict[str, Any]]:
    """
    Fuzzy search instruments by symbol or name.
    Returns up to `limit` matching instruments, ranked by relevance.
    Falls back to empty list when cache is unavailable.
    """
    if not query or len(query) < 1:
        return []

    cache = _load_cache()
    instruments = cache.get("instruments", [])
    q = query.upper().strip()

    exact: List[Dict[str, Any]] = []
    prefix: List[Dict[str, Any]] = []
    contains: List[Dict[str, Any]] = []

    for inst in instruments:
        sym = inst.get("symbol", "").upper()
        name = inst.get("name", "").upper()
        if sym == q:
            exact.append(inst)
        elif sym.startswith(q) or name.startswith(q):
            prefix.append(inst)
        elif q in sym or q in name:
            contains.append(inst)

    ranked = (exact + prefix + contains)[:limit]
    return [
        {
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "token": r.get("token"),
            "exchange": r.get("exchange"),
            "instrument_type": r.get("instrument_type"),
            "lot_size": r.get("lot_size"),
        }
        for r in ranked
    ]


def cache_status() -> Dict[str, Any]:
    """Return a summary of the current cache state."""
    cache = _load_cache()
    return {
        "date": cache.get("date"),
        "fetched_at": cache.get("fetched_at"),
        "count": len(cache.get("instruments", [])),
        "is_fresh": _cache_is_fresh(cache),
        "path": _CACHE_PATH,
    }


if __name__ == "__main__":
    import json as _json
    print("Cache status:", _json.dumps(cache_status(), indent=2))
    print("Search TCS:", _json.dumps(search("TCS"), indent=2))
