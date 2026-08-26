"""
nse_preopen_provider.py — Phase 5D: NSE Official Pre-Open Data Provider (Primary).

 Fetches real auction data from NSE's public API endpoint. The default scope is
 `ALL`, because Phase 5A can collect an operator-selected custom universe that
 is not limited to NIFTY constituents.

Provides:
  • Indicative Equilibrium Price (IEP)
  • Previous Close
  • Gap %
  • Buy Quantity / Sell Quantity from the auction
  • Imbalance %
  • Matched / Traded Quantity
  • Timestamp of last auction update

NSE requires a two-request cookie dance: hit the main page first to obtain
session cookies, then call the API endpoint.  The session is reused for
NSE_SESSION_TTL seconds to reduce latency and avoid rate-limiting.

If the API is unavailable (403, timeout, any network error), the provider
returns UNAVAILABLE and the caller falls back to the next provider in the
priority chain (Zerodha Kite → Yahoo Finance).

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

_NSE_MAIN = "https://www.nseindia.com/"
_NSE_PREOPEN_API = "https://www.nseindia.com/api/market-data-pre-open?key={key}"

# Cookie session TTL — refresh every 4.5 minutes
NSE_SESSION_TTL   = 270
# Data cache TTL — don't hammer NSE more than once a minute
NSE_DATA_TTL      = 55
NSE_TIMEOUT_S     = 10

_NSE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection":      "keep-alive",
}
_NSE_API_HEADERS = {
    "Accept":          "application/json, */*; q=0.01",
    "Referer":         _NSE_MAIN,
    "X-Requested-With": "XMLHttpRequest",
}

# ── Module-level session cache (one Python process = one session) ─────────────

_session_obj    = None
_session_ts: float = 0.0
_data_cache: Dict[str, Dict] = {}   # keyed by UPPER symbol
_data_cache_ts: float = 0.0
_data_cache_key: Optional[str] = None


def _preopen_key() -> str:
    """The custom-universe Phase 5A path must always query all NSE equities."""
    return "ALL"


def _get_session():
    """Return a live requests.Session, refreshing cookies when stale."""
    global _session_obj, _session_ts
    import requests
    now = time.monotonic()
    if _session_obj is not None and now - _session_ts < NSE_SESSION_TTL:
        return _session_obj
    s = requests.Session()
    s.headers.update(_NSE_HEADERS)
    try:
        s.get(_NSE_MAIN, timeout=8, allow_redirects=True)
        time.sleep(0.4)          # brief pause before the actual API call
    except Exception:
        pass                     # continue even if main page fails
    _session_obj = s
    _session_ts  = now
    return s


def _fetch_raw(force: bool = False, key: Optional[str] = None) -> Optional[Dict[str, Dict]]:
    """
    Fetch scoped NSE pre-open data. Returns a dict keyed by UPPER symbol,
    each value: {"meta": {...}, "detail": {...}}.
    Returns None on any network / parse failure.
    """
    global _data_cache, _data_cache_ts, _data_cache_key
    key = (key or _preopen_key()).upper()
    now = time.monotonic()
    if (
        not force
        and _data_cache
        and _data_cache_key == key
        and now - _data_cache_ts < NSE_DATA_TTL
    ):
        return _data_cache

    try:
        s = _get_session()
        s.headers.update(_NSE_API_HEADERS)
        r = s.get(_NSE_PREOPEN_API.format(key=key), timeout=NSE_TIMEOUT_S)
        if r.status_code != 200:
            return None
        payload = r.json()
        by_sym: Dict[str, Dict] = {}
        for item in payload.get("data", []):
            meta   = item.get("metadata") or {}
            detail = (item.get("detail") or {}).get("preOpenMarket") or {}
            sym    = str(meta.get("symbol") or "").upper().strip()
            if sym:
                by_sym[sym] = {"meta": meta, "detail": detail}
        _data_cache    = by_sym
        _data_cache_ts = now
        _data_cache_key = key
        return by_sym
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        import math
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _nse_last_update_age_seconds(last_update_time: str,
                                 now: Optional[Any] = None) -> int:
    """Return NSE wall-clock update age; unknown timestamps fail closed."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    try:
        updated_at = datetime.strptime(
            str(last_update_time or "").strip(),
            "%d-%b-%Y %H:%M:%S",
        ).replace(tzinfo=ist)
        current = now or datetime.now(ist)
        if current.tzinfo is None:
            current = current.replace(tzinfo=ist)
        age_seconds = int((current.astimezone(ist) - updated_at).total_seconds())
        # Provider time ahead of the collection clock cannot prove freshness.
        # With no explicitly approved skew policy, treat it as stale.
        return age_seconds if age_seconds >= 0 else 300
    except Exception:
        # A missing or unparseable provider timestamp is not evidence of a
        # current auction row and therefore cannot satisfy the live-data gate.
        return 300


def _build_sector_map() -> Dict[str, str]:
    try:
        import config
        return {sym: sector for sector, syms in config.SECTOR_MAP.items() for sym in syms}
    except Exception:
        return {}


# ── Provider class ────────────────────────────────────────────────────────────

class NSEPreOpenProvider:
    """
    Primary pre-open provider using NSE's official API.
    Provides IEP, buy/sell quantities, imbalance, gap %.
    Provider state: LIVE when data < 5 min old, STALE when older.
    Falls through (returns UNAVAILABLE) if NSE API is unreachable.

    PAPER TRADING / ADVISORY ONLY.
    """

    PROVIDER_ID    = "nse_official"
    PROVIDER_LABEL = "NSE Official"

    def __init__(self, symbols: Optional[List[str]] = None):
        import config
        self.symbols    = symbols or list(config.DEFAULT_WATCHLIST)
        self._sector    = _build_sector_map()

    # ── Availability ──────────────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        """Quick check: can we reach the NSE API right now?"""
        try:
            data = _fetch_raw()
            return bool(data)
        except Exception:
            return False

    def health_check(self) -> Dict[str, Any]:
        try:
            t0   = time.monotonic()
            data = _fetch_raw()
            if not data:
                return {"status": ProviderState.UNAVAILABLE,
                        "message": "NSE API unreachable (403 / network error)",
                        "provider": self.PROVIDER_LABEL}
            lat = round((time.monotonic() - t0) * 1000)
            age = int(time.monotonic() - _data_cache_ts)
            return {
                "status":      ProviderState.LIVE if age < 300 else ProviderState.STALE,
                "message":     (
                    f"NSE Official ({_preopen_key()}) — {len(data)} symbols, "
                    f"data age {age}s"
                ),
                "latency_ms":  lat,
                "provider":    self.PROVIDER_LABEL,
                "symbol_count": len(data),
                "provider_scope": _preopen_key(),
            }
        except Exception as exc:
            return {"status": ProviderState.UNAVAILABLE,
                    "message": f"NSE health check error: {exc}",
                    "provider": self.PROVIDER_LABEL}

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalize(self, raw: Dict, symbol: str) -> Optional[PreOpenSnapshot]:
        """
        Convert one NSE API item (meta + detail) into a PreOpenSnapshot.
        Returns None if the record lacks a valid previous close.
        """
        meta   = raw.get("meta")   or {}
        detail = raw.get("detail") or {}

        prev_close = _safe_float(meta.get("previousClose"))
        if not prev_close or prev_close <= 0:
            return None

        # IEP lives in detail.preOpenMarket, NOT in metadata (meta.IEP is often null)
        iep = _safe_float(detail.get("IEP")) or _safe_float(detail.get("finalPrice"))

        gap_pct = 0.0
        if iep and prev_close > 0 and iep != prev_close:
            gap_pct = round((iep - prev_close) / prev_close * 100, 4)
        elif _safe_float(meta.get("pChange")) is not None:
            gap_pct = round(float(meta["pChange"]), 4)

        buy_qty  = _safe_int(detail.get("totalBuyQuantity"))  or 0
        sell_qty = _safe_int(detail.get("totalSellQuantity")) or 0
        traded   = _safe_int(detail.get("totalTradedVolume")) or \
                   _safe_int(detail.get("totalTradedQuantity")) or \
                   _safe_int(meta.get("finalQuantity")) or 0

        total_qty = buy_qty + sell_qty
        imbalance_pct = 0.0
        if total_qty > 0:
            imbalance_pct = round((buy_qty - sell_qty) / total_qty * 100, 4)

        # NSE returns an IST wall-clock timestamp, not UTC. Unknown timestamps
        # are stale so no caller can infer liveness from a missing field.
        age_s = _nse_last_update_age_seconds(detail.get("lastUpdateTime") or "")
        state = ProviderState.LIVE if age_s < 300 else ProviderState.STALE
        sym   = symbol.upper()

        return PreOpenSnapshot(
            snapshot_id                 = f"nse-{sym}-{uuid.uuid4().hex[:8]}",
            trading_date                = now_ist_str()[:10],
            timestamp_ist               = now_ist_str(),
            symbol                      = sym,
            company_name                = sym,
            sector                      = self._sector.get(sym, "Unknown"),
            previous_close              = prev_close,
            indicative_equilibrium_price = iep,
            indicative_open_price       = iep,
            final_open_price            = _safe_float(detail.get("finalPrice")),
            price_change                = round(iep - prev_close, 2) if iep else None,
            gap_percent                 = gap_pct,
            total_buy_quantity          = buy_qty,
            total_sell_quantity         = sell_qty,
            matched_quantity            = traded,
            final_executed_quantity     = traded,
            total_traded_value          = 0.0,
            buy_sell_imbalance          = buy_qty - sell_qty,
            imbalance_percent           = imbalance_pct,
            liquidity_score             = 0.0,
            data_source                 = self.PROVIDER_ID,
            provider_label              = self.PROVIDER_LABEL,
            data_freshness_seconds      = age_s,
            source_status               = state,
            is_stale                    = age_s >= 300,
            validation_status           = "VALID",
            order_book_available        = buy_qty > 0 or sell_qty > 0,
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def fetch_symbol_snapshot(self, symbol: str) -> Optional[PreOpenSnapshot]:
        data = _fetch_raw()
        if not data:
            return None
        raw = data.get(symbol.upper())
        if not raw:
            return None
        return self._normalize(raw, symbol)

    def fetch_market_snapshot(self) -> List[PreOpenSnapshot]:
        return self.fetch_collection_evidence()["snapshots"]

    def fetch_collection_evidence(self) -> Dict[str, Any]:
        """Return real snapshots plus auditable outcomes for every request.

        `PreOpenSnapshot` rows are emitted only for provider records that
        normalize successfully. Missing or invalid provider rows are represented
        as metadata outcomes, never as fabricated price rows.
        """
        scope = _preopen_key()
        data = _fetch_raw(key=scope)
        expected_symbols = [
            str(symbol or "").strip().upper()
            for symbol in self.symbols
            if str(symbol or "").strip()
        ]
        if not data:
            return {
                "snapshots": [],
                "outcomes": [{
                    "symbol": symbol,
                    "outcome_status": "NO_PREOPEN_DATA",
                    "reason_code": "NSE_EMPTY_OR_UNAVAILABLE_RESPONSE",
                    "provider_symbol": symbol,
                    "provider_response_present": False,
                    "normalization_result": "NOT_ATTEMPTED",
                    "eligibility_status": "UNKNOWN",
                    "provider_scope": scope,
                } for symbol in expected_symbols],
                "provider_raw_count": 0,
                "provider_scope": scope,
            }

        results = []
        outcomes = []
        for symbol in expected_symbols:
            raw = data.get(symbol)
            if raw is None:
                outcomes.append({
                    "symbol": symbol,
                    "outcome_status": "NO_PREOPEN_DATA",
                    "reason_code": "SYMBOL_ABSENT_FROM_NSE_RESPONSE",
                    "provider_symbol": symbol,
                    "provider_response_present": False,
                    "normalization_result": "NOT_ATTEMPTED",
                    "eligibility_status": "UNKNOWN",
                    "provider_scope": scope,
                })
                continue
            snapshot = self._normalize(raw, symbol)
            if snapshot is None:
                outcomes.append({
                    "symbol": symbol,
                    "outcome_status": "NORMALIZATION_FAILED",
                    "reason_code": "MISSING_OR_INVALID_PREVIOUS_CLOSE",
                    "provider_symbol": symbol,
                    "provider_response_present": True,
                    "normalization_result": "REJECTED",
                    "eligibility_status": "UNKNOWN",
                    "provider_scope": scope,
                })
                continue
            results.append(snapshot)
            outcomes.append({
                "symbol": symbol,
                "outcome_status": "LIVE_PREOPEN_DATA",
                "reason_code": "NSE_ROW_NORMALIZED",
                "provider_symbol": symbol,
                "provider_response_present": True,
                "normalization_result": "NORMALIZED",
                "eligibility_status": "UNKNOWN",
                "snapshot_id": snapshot.snapshot_id,
                "provider_scope": scope,
            })
        return {
            "snapshots": results,
            "outcomes": outcomes,
            "provider_raw_count": len(data),
            "provider_scope": scope,
        }

    def validate_response(self, raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        meta = raw.get("meta") or {}
        return (_safe_float(meta.get("previousClose")) or 0) > 0
