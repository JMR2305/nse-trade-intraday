"""
kite_preopen_provider.py — Phase 5D: Zerodha Kite Pre-Open Provider (Secondary).

Uses the Zerodha Kite API to fetch pre-open data when a valid session exists.

During the NSE pre-open session (08:45–09:15 IST):
  • kite.quote() returns last_price = IEP (Indicative Equilibrium Price)
  • ohlc.close = previous session's closing price
  • volume = traded quantity up to that moment

Kite does not expose the full NSE auction order book through its quote API,
so buy/sell quantities are not available (order_book_available=False).
This provider is better than Yahoo Finance (real IEP) but inferior to the
NSE Official provider (no auction quantities/imbalance).

Requires:
  ZERODHA_API_KEY    env var
  KITE_ACCESS_TOKEN  env var (set by the Kite OAuth flow)

Falls through to Yahoo Finance if the Kite session is absent or invalid.

PAPER TRADING / ADVISORY ONLY.
No order submission, no broker call, no strategy modification.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from preopen_data_model import PreOpenSnapshot, ProviderState, now_ist_str

_LABEL = "PAPER TRADING / ADVISORY ONLY"

_QUOTE_TTL = 20  # seconds — Kite quotes are considered fresh for 20s
_quote_cache: Dict[str, Dict]  = {}
_quote_cache_ts: float = 0.0


def _safe_float(v: Any) -> Optional[float]:
    try:
        import math
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _build_sector_map() -> Dict[str, str]:
    try:
        import config
        return {sym: sector for sector, syms in config.SECTOR_MAP.items() for sym in syms}
    except Exception:
        return {}


class KitePreOpenProvider:
    """
    Secondary pre-open provider using the Zerodha Kite API.
    Provides IEP and previous close; no order-book quantities.

    PAPER TRADING / ADVISORY ONLY.
    """

    PROVIDER_ID    = "zerodha_kite"
    PROVIDER_LABEL = "Zerodha Kite"

    def __init__(self, symbols: Optional[List[str]] = None):
        import config
        self.symbols  = symbols or list(config.DEFAULT_WATCHLIST)
        self._sector  = _build_sector_map()
        self._kite    = None          # lazy-initialised

    # ── Kite session ──────────────────────────────────────────────────────────

    def _get_kite(self):
        if self._kite is not None:
            return self._kite
        api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
        token   = os.environ.get("KITE_ACCESS_TOKEN", "").strip()
        if not api_key or not token:
            return None
        try:
            from kiteconnect import KiteConnect
            k = KiteConnect(api_key=api_key)
            k.set_access_token(token)
            self._kite = k
            return k
        except Exception:
            return None

    @classmethod
    def is_available(cls) -> bool:
        api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
        token   = os.environ.get("KITE_ACCESS_TOKEN", "").strip()
        if not api_key or not token:
            return False
        try:
            from kiteconnect import KiteConnect
            k = KiteConnect(api_key=api_key)
            k.set_access_token(token)
            # Minimal probe: fetch a single well-known symbol
            k.quote("NSE:INFY")
            return True
        except Exception:
            return False

    def health_check(self) -> Dict[str, Any]:
        kite = self._get_kite()
        if not kite:
            return {
                "status":  ProviderState.UNAVAILABLE,
                "message": "No Kite session (KITE_ACCESS_TOKEN not set or expired)",
                "provider": self.PROVIDER_LABEL,
            }
        try:
            t0  = time.monotonic()
            kite.quote("NSE:INFY")
            lat = round((time.monotonic() - t0) * 1000)
            return {
                "status":     ProviderState.LIVE,
                "message":    "Zerodha Kite — session active (IEP available; no order book)",
                "latency_ms": lat,
                "provider":   self.PROVIDER_LABEL,
            }
        except Exception as exc:
            return {
                "status":  ProviderState.UNAVAILABLE,
                "message": f"Kite quote error: {exc}",
                "provider": self.PROVIDER_LABEL,
            }

    # ── Fetching ──────────────────────────────────────────────────────────────

    def _fetch_quotes(self, symbols: List[str]) -> Optional[Dict[str, Dict]]:
        global _quote_cache, _quote_cache_ts
        now = time.monotonic()
        if _quote_cache and now - _quote_cache_ts < _QUOTE_TTL:
            return _quote_cache
        kite = self._get_kite()
        if not kite:
            return None
        try:
            instruments = [f"NSE:{s.upper()}" for s in symbols]
            raw = kite.quote(instruments)           # {"NSE:RELIANCE": {...}, ...}
            by_sym = {
                k.replace("NSE:", "").upper(): v
                for k, v in raw.items()
            }
            _quote_cache    = by_sym
            _quote_cache_ts = now
            return by_sym
        except Exception:
            return None

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalize(self, quote: Dict, symbol: str) -> Optional[PreOpenSnapshot]:
        """
        Convert a Kite quote dict to PreOpenSnapshot.
        last_price = IEP during pre-open session.
        ohlc.close = previous session close.
        """
        ohlc        = quote.get("ohlc") or {}
        prev_close  = _safe_float(ohlc.get("close"))
        if not prev_close or prev_close <= 0:
            # fallback: try last_price as prev close proxy
            prev_close = _safe_float(quote.get("last_price"))
            if not prev_close or prev_close <= 0:
                return None

        iep     = _safe_float(quote.get("last_price"))
        volume  = _safe_int(quote.get("volume")) or 0

        gap_pct = 0.0
        if iep and prev_close > 0 and iep != prev_close:
            gap_pct = round((iep - prev_close) / prev_close * 100, 4)

        sym = symbol.upper()
        return PreOpenSnapshot(
            snapshot_id                  = f"kite-{sym}-{uuid.uuid4().hex[:8]}",
            trading_date                 = now_ist_str()[:10],
            timestamp_ist                = now_ist_str(),
            symbol                       = sym,
            company_name                 = sym,
            sector                       = self._sector.get(sym, "Unknown"),
            previous_close               = prev_close,
            indicative_equilibrium_price = iep,
            indicative_open_price        = iep,
            final_open_price             = None,
            price_change                 = round(iep - prev_close, 2) if iep else None,
            gap_percent                  = gap_pct,
            total_buy_quantity           = 0,
            total_sell_quantity          = 0,
            matched_quantity             = volume,
            final_executed_quantity      = volume,
            total_traded_value           = 0.0,
            buy_sell_imbalance           = 0,
            imbalance_percent            = 0.0,
            liquidity_score              = 0.0,
            data_source                  = self.PROVIDER_ID,
            provider_label               = self.PROVIDER_LABEL,
            data_freshness_seconds       = 20,
            source_status                = ProviderState.LIVE,
            is_stale                     = False,
            validation_status            = "VALID",
            order_book_available         = False,  # Kite quote has no auction order book
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def validate_response(self, raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        ohlc = raw.get("ohlc") or {}
        return (_safe_float(ohlc.get("close")) or 0) > 0

    def fetch_symbol_snapshot(self, symbol: str) -> Optional[PreOpenSnapshot]:
        quotes = self._fetch_quotes([symbol])
        if not quotes:
            return None
        q = quotes.get(symbol.upper())
        return self._normalize(q, symbol) if q else None

    def fetch_market_snapshot(self) -> List[PreOpenSnapshot]:
        quotes = self._fetch_quotes(self.symbols)
        if not quotes:
            return []
        results = []
        for sym in self.symbols:
            q = quotes.get(sym.upper())
            if q:
                snap = self._normalize(q, sym)
                if snap:
                    results.append(snap)
        return results
