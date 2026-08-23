"""
preopen_provider_manager.py — Phase 5D: Multi-Provider Priority Manager.

Provider selection:

  1. NSE Official  (primary)   — full auction data: IEP, buy/sell qty, imbalance
  2. Zerodha Kite  (secondary) — IEP + prev close; no order-book quantities
  3. Yahoo Finance (fallback)  — open price post-09:15; no IEP, no order book

The manager tries each provider in order.  The first one that returns
non-empty data wins and is remembered for the remainder of the session
(caching window: PROVIDER_CACHE_TTL seconds).

PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no strategy modification.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from preopen_data_model import PreOpenSnapshot, ProviderState

_LABEL = "PAPER TRADING / ADVISORY ONLY"

# Re-probe providers this often (seconds).
PROVIDER_CACHE_TTL = 300

_cached_provider    = None
_cached_provider_ts = 0.0


def _try_nse(symbols: List[str]) -> Tuple[Optional[Any], str]:
    try:
        from nse_preopen_provider import NSEPreOpenProvider
        p = NSEPreOpenProvider(symbols)
        h = p.health_check()
        if h.get("status") in (ProviderState.LIVE, ProviderState.STALE):
            return p, NSEPreOpenProvider.PROVIDER_LABEL
    except Exception:
        pass
    return None, ""


def _try_kite(symbols: List[str]) -> Tuple[Optional[Any], str]:
    try:
        api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
        from kite_preopen_provider import KitePreOpenProvider, resolve_preopen_token
        token = resolve_preopen_token()
        if not api_key or not token:
            return None, ""
        p = KitePreOpenProvider(symbols)
        h = p.health_check()
        if h.get("status") in (ProviderState.LIVE, ProviderState.STALE):
            return p, KitePreOpenProvider.PROVIDER_LABEL
    except Exception:
        pass
    return None, ""


def _try_yfinance(symbols: List[str]) -> Tuple[Optional[Any], str]:
    try:
        from preopen_provider import YFinancePreOpenProvider
        p = YFinancePreOpenProvider(symbols)
        h = p.health_check()
        if h.get("status") != ProviderState.UNAVAILABLE:
            return p, YFinancePreOpenProvider.PROVIDER_LABEL
    except Exception:
        pass
    return None, ""


def get_best_provider(
    symbols: Optional[List[str]] = None,
    force: bool = False,
) -> Tuple[Any, str]:
    """
    Return (provider_instance, provider_label) for the highest-priority
    available provider.  Falls back through NSE → Kite → Yahoo.

    Caches the winning provider for PROVIDER_CACHE_TTL seconds to avoid
    repeated health checks on every collect tick.

    Returns (YFinancePreOpenProvider, "Yahoo Finance (Fallback)") in the
    worst case — never raises.
    """
    global _cached_provider, _cached_provider_ts

    now = time.monotonic()
    if (not force and _cached_provider is not None
            and now - _cached_provider_ts < PROVIDER_CACHE_TTL):
        return _cached_provider

    if symbols is None:
        try:
            import config
            symbols = list(config.DEFAULT_WATCHLIST)
        except Exception:
            symbols = []

    # 1. NSE Official
    p, label = _try_nse(symbols)
    if p:
        _cached_provider    = (p, label)
        _cached_provider_ts = now
        return _cached_provider

    # 2. Zerodha Kite
    p, label = _try_kite(symbols)
    if p:
        _cached_provider    = (p, label)
        _cached_provider_ts = now
        return _cached_provider

    # 3. Yahoo Finance (fallback)
    p, label = _try_yfinance(symbols)
    if p:
        _cached_provider    = (p, label)
        _cached_provider_ts = now
        return _cached_provider

    # Should never reach here, but be safe
    from preopen_provider import YFinancePreOpenProvider
    fallback = (YFinancePreOpenProvider(symbols), YFinancePreOpenProvider.PROVIDER_LABEL)
    _cached_provider    = fallback
    _cached_provider_ts = now
    return fallback


def provider_chain_status(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Return a diagnostic dict showing the health of ALL three providers.
    Used by the /api/preopen/health endpoint.
    """
    if symbols is None:
        try:
            import config
            symbols = list(config.DEFAULT_WATCHLIST)
        except Exception:
            symbols = []

    def _health(factory):
        try:
            p = factory(symbols)
            return p.health_check()
        except Exception as exc:
            return {"status": ProviderState.UNAVAILABLE, "message": str(exc)}

    from nse_preopen_provider   import NSEPreOpenProvider
    from kite_preopen_provider  import KitePreOpenProvider
    from preopen_provider       import YFinancePreOpenProvider

    nse_h   = _health(NSEPreOpenProvider)
    kite_h  = _health(KitePreOpenProvider)
    yf_h    = _health(YFinancePreOpenProvider)

    # Determine active provider
    if nse_h.get("status") in (ProviderState.LIVE, ProviderState.STALE):
        active = "NSE Official"
    elif kite_h.get("status") in (ProviderState.LIVE, ProviderState.STALE):
        active = "Zerodha Kite"
    else:
        active = "Yahoo Finance (Fallback)"

    return {
        "active_provider": active,
        "providers": {
            "nse_official":     {**nse_h,  "priority": 1},
            "zerodha_kite":     {**kite_h, "priority": 2},
            "yahoo_finance":    {**yf_h,   "priority": 3},
        },
        "label": _LABEL,
    }


def invalidate_cache() -> None:
    """Force re-selection of provider on next call."""
    global _cached_provider, _cached_provider_ts
    _cached_provider    = None
    _cached_provider_ts = 0.0
