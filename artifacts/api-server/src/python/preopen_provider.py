"""
preopen_provider.py — Phase 5A Pre-Open Intelligence data provider interface.

Abstract base + two concrete implementations:
  YFinancePreOpenProvider  — uses yfinance for development / non-session data
  MockPreOpenProvider      — fixture-based, used in unit tests

SAFETY: Provider failures never crash the app, never generate fake prices,
        never emit actionable BUY/SELL signals directly.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from preopen_data_model import (
    PreOpenSnapshot, ProviderState, Classification, now_ist_str,
)

# ── Feature flag guard ────────────────────────────────────────────────────────
import os
_ENABLED = os.environ.get("PREOPEN_INTELLIGENCE_ENABLED", "false").lower() in ("1", "true", "yes")


def _is_enabled() -> bool:
    return os.environ.get("PREOPEN_INTELLIGENCE_ENABLED", "false").lower() in ("1", "true", "yes")


# ── Abstract provider ─────────────────────────────────────────────────────────

class PreOpenDataProvider(ABC):
    """Provider-independent interface for pre-open market data."""

    @abstractmethod
    def fetch_market_snapshot(self) -> List[PreOpenSnapshot]:
        """Fetch a full market snapshot across the watchlist."""
        ...

    @abstractmethod
    def fetch_symbol_snapshot(self, symbol: str) -> Optional[PreOpenSnapshot]:
        """Fetch a snapshot for a single symbol."""
        ...

    @abstractmethod
    def validate_response(self, raw: Any) -> bool:
        """Validate a raw provider response."""
        ...

    @abstractmethod
    def normalize_response(self, raw: Any, symbol: str) -> Optional[PreOpenSnapshot]:
        """Normalize a raw provider response into a PreOpenSnapshot."""
        ...

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Return provider health metadata."""
        ...


# ── YFinance provider (dev / non-session use) ─────────────────────────────────

class YFinancePreOpenProvider(PreOpenDataProvider):
    """
    Fallback pre-open provider using yfinance.

    NOTE: yfinance does not expose NSE pre-open auction order books directly.
    This implementation fetches the previous close and uses it to construct
    a best-effort snapshot. Gap % is 0 until an actual open price is available.
    Provider state is set to DELAYED to reflect this limitation.
    order_book_available is always False (no auction quantities from Yahoo).
    """

    PROVIDER_ID    = "yfinance"
    PROVIDER_LABEL = "Yahoo Finance (Fallback)"

    def __init__(self, symbols: Optional[List[str]] = None, timeout: int = 30):
        import config
        self.symbols = symbols or list(config.DEFAULT_WATCHLIST)
        self.timeout = timeout
        self._sector_map: Dict[str, str] = {}
        try:
            self._sector_map = {
                sym: sector
                for sector, syms in config.SECTOR_MAP.items()
                for sym in syms
            }
        except Exception:
            pass

    def health_check(self) -> Dict[str, Any]:
        try:
            import yfinance as yf
            t = yf.Ticker("RELIANCE.NS")
            info = t.fast_info
            price = getattr(info, "last_price", None)
            if price and price > 0:
                return {"status": ProviderState.DELAYED,
                        "message": "yfinance available (DELAYED — no auction order book)",
                        "latency_ms": None}
        except Exception as e:
            return {"status": ProviderState.UNAVAILABLE, "message": str(e)}
        return {"status": ProviderState.DELAYED,
                "message": "yfinance available (DELAYED)"}

    def validate_response(self, raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        return raw.get("previous_close", 0) > 0

    def normalize_response(self, raw: Any, symbol: str) -> Optional[PreOpenSnapshot]:
        if not self.validate_response(raw):
            return None
        snap_id = f"yf-{symbol}-{uuid.uuid4().hex[:8]}"
        now = now_ist_str()
        prev_close = float(raw.get("previous_close", 0))
        # "indicative_price" comes from LiveNSEPreOpenProvider (Kite auction IEP).
        # yfinance doesn't provide it, so fall back to the actual open_price that
        # _fetch_one() already fetched.  Do NOT fall back to prev_close — that
        # would make gap_pct = 0 permanently because (prev_close - prev_close) = 0.
        ind_price = raw.get("indicative_price") or raw.get("open_price") or None
        gap_pct = 0.0
        if ind_price and prev_close > 0 and ind_price != prev_close:
            gap_pct = round((ind_price - prev_close) / prev_close * 100, 4)

        return PreOpenSnapshot(
            snapshot_id=snap_id,
            trading_date=now[:10],
            timestamp_ist=now,
            symbol=symbol.upper(),
            company_name=raw.get("company_name", symbol),
            sector=self._sector_map.get(symbol.upper(), "Unknown"),
            # Store None instead of 0.0 when yfinance hasn't returned a close yet —
            # 0.0 is not a valid close price and confuses downstream analytics.
            previous_close=prev_close if prev_close > 0 else None,
            indicative_equilibrium_price=ind_price,
            indicative_open_price=ind_price,
            final_open_price=raw.get("open_price"),
            price_change=raw.get("price_change"),
            gap_percent=gap_pct,
            total_buy_quantity=0,
            total_sell_quantity=0,
            matched_quantity=0,
            final_executed_quantity=int(raw.get("volume", 0)),
            total_traded_value=float(raw.get("traded_value", 0)),
            buy_sell_imbalance=0,
            imbalance_percent=0.0,
            liquidity_score=0.0,
            data_source=self.PROVIDER_ID,
            provider_label=self.PROVIDER_LABEL,
            data_freshness_seconds=int(raw.get("age_seconds", 0)),
            source_status=ProviderState.DELAYED,
            is_stale=raw.get("age_seconds", 9999) > 300,
            validation_status="VALID",
            order_book_available=False,  # Yahoo Finance does not supply auction quantities
        )

    def _fetch_one(self, symbol: str) -> Optional[dict]:
        try:
            import yfinance as yf
            ns_sym = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
            t = yf.Ticker(ns_sym)
            fi = t.fast_info
            prev_close = getattr(fi, "previous_close", None) or getattr(fi, "last_price", 0)
            open_price = getattr(fi, "open", None)
            volume = getattr(fi, "three_month_average_volume", 0) or 0
            return {
                "previous_close": float(prev_close or 0),
                "open_price": float(open_price) if open_price else None,
                "volume": int(volume or 0),
                "traded_value": 0.0,
                "buy_qty": 0,
                "sell_qty": 0,
                "age_seconds": 60,
                "company_name": symbol,
            }
        except Exception:
            return None

    def fetch_symbol_snapshot(self, symbol: str) -> Optional[PreOpenSnapshot]:
        raw = self._fetch_one(symbol)
        if not raw:
            return None
        return self.normalize_response(raw, symbol)

    def fetch_market_snapshot(self) -> List[PreOpenSnapshot]:
        results: List[PreOpenSnapshot] = []
        for sym in self.symbols:
            snap = self.fetch_symbol_snapshot(sym)
            if snap:
                results.append(snap)
        return results


# ── Mock provider (unit tests / fixture data) ─────────────────────────────────

# Fixture data covering diverse scenarios for testing
FIXTURE_SNAPSHOTS: List[Dict] = [
    {"symbol": "RELIANCE",     "prev_close": 2800.0,  "ind_price": 2856.0,  "buy_qty": 120000, "sell_qty": 40000,  "volume": 85000,  "age_seconds": 30,  "sector": "Energy"},
    {"symbol": "INFY",         "prev_close": 1500.0,  "ind_price": 1425.0,  "buy_qty": 30000,  "sell_qty": 90000,  "volume": 60000,  "age_seconds": 45,  "sector": "IT"},
    {"symbol": "TCS",          "prev_close": 3500.0,  "ind_price": 3500.5,  "buy_qty": 50000,  "sell_qty": 52000,  "volume": 40000,  "age_seconds": 60,  "sector": "IT"},
    {"symbol": "HDFCBANK",     "prev_close": 1700.0,  "ind_price": 1734.0,  "buy_qty": 80000,  "sell_qty": 60000,  "volume": 95000,  "age_seconds": 20,  "sector": "Banking"},
    {"symbol": "TATAMOTORS",   "prev_close": 900.0,   "ind_price": 864.0,   "buy_qty": 20000,  "sell_qty": 110000, "volume": 70000,  "age_seconds": 55,  "sector": "Auto"},
    {"symbol": "WIPRO",        "prev_close": 450.0,   "ind_price": 454.5,   "buy_qty": 35000,  "sell_qty": 33000,  "volume": 25000,  "age_seconds": 90,  "sector": "IT"},
    {"symbol": "SUNPHARMA",    "prev_close": 1200.0,  "ind_price": 1260.0,  "buy_qty": 60000,  "sell_qty": 10000,  "volume": 55000,  "age_seconds": 15,  "sector": "Pharma"},
    {"symbol": "ITC",          "prev_close": 460.0,   "ind_price": 441.6,   "buy_qty": 15000,  "sell_qty": 85000,  "volume": 80000,  "age_seconds": 40,  "sector": "FMCG"},
    {"symbol": "AXISBANK",     "prev_close": 1100.0,  "ind_price": 1100.0,  "buy_qty": 0,      "sell_qty": 0,      "volume": 0,      "age_seconds": 400, "sector": "Banking"},  # stale/low liquidity
    {"symbol": "BAJFINANCE",   "prev_close": 7000.0,  "ind_price": 7350.0,  "buy_qty": 95000,  "sell_qty": 5000,   "volume": 120000, "age_seconds": 10,  "sector": "Finance"},
]


class MockPreOpenProvider(PreOpenDataProvider):
    """Fixture-based provider for unit testing. No network calls."""

    PROVIDER_ID    = "mock"
    PROVIDER_LABEL = "Mock Data"

    def __init__(self, fixtures: Optional[List[dict]] = None,
                 state: str = ProviderState.LIVE,
                 fail: bool = False,
                 stale: bool = False):
        self.fixtures = fixtures or FIXTURE_SNAPSHOTS
        self.state = state
        self.fail = fail      # simulate provider failure
        self.stale = stale    # mark all results as stale

    def health_check(self) -> Dict[str, Any]:
        if self.fail:
            return {"status": ProviderState.UNAVAILABLE, "message": "Simulated failure"}
        return {"status": self.state, "message": "Mock provider healthy"}

    def validate_response(self, raw: Any) -> bool:
        if self.fail:
            return False
        return isinstance(raw, dict) and raw.get("prev_close", 0) > 0

    def normalize_response(self, raw: Any, symbol: str) -> Optional[PreOpenSnapshot]:
        if not self.validate_response(raw):
            return None
        snap_id = f"mock-{symbol}-{uuid.uuid4().hex[:8]}"
        now = now_ist_str()
        prev_close = float(raw.get("prev_close", 0))
        ind_price = float(raw.get("ind_price") or prev_close)
        age = raw.get("age_seconds", 0)
        is_stale = self.stale or age > 300
        gap_pct = 0.0
        if prev_close > 0:
            gap_pct = round((ind_price - prev_close) / prev_close * 100, 4)
        buy_qty = int(raw.get("buy_qty", 0))
        sell_qty = int(raw.get("sell_qty", 0))

        total_qty = buy_qty + sell_qty
        imbalance_pct = round((buy_qty - sell_qty) / max(total_qty, 1) * 100, 4) if total_qty > 0 else 0.0
        return PreOpenSnapshot(
            snapshot_id=snap_id,
            trading_date=now[:10],
            timestamp_ist=now,
            symbol=symbol.upper(),
            company_name=raw.get("company_name", symbol),
            sector=raw.get("sector", "Unknown"),
            previous_close=prev_close,
            indicative_equilibrium_price=ind_price,
            indicative_open_price=ind_price,
            final_open_price=raw.get("final_open"),
            price_change=round(ind_price - prev_close, 2),
            gap_percent=gap_pct,
            total_buy_quantity=buy_qty,
            total_sell_quantity=sell_qty,
            matched_quantity=int(raw.get("matched", 0)),
            final_executed_quantity=int(raw.get("volume", 0)),
            total_traded_value=float(raw.get("traded_value", 0)),
            buy_sell_imbalance=buy_qty - sell_qty,
            imbalance_percent=imbalance_pct,
            liquidity_score=0.0,
            data_source=self.PROVIDER_ID,
            provider_label=self.PROVIDER_LABEL,
            data_freshness_seconds=age,
            source_status=self.state if not is_stale else ProviderState.STALE,
            is_stale=is_stale,
            validation_status="VALID" if not is_stale else "STALE",
            order_book_available=buy_qty > 0 or sell_qty > 0,
        )

    def fetch_symbol_snapshot(self, symbol: str) -> Optional[PreOpenSnapshot]:
        if self.fail:
            return None
        sym = symbol.upper()
        for f in self.fixtures:
            if f["symbol"].upper() == sym:
                return self.normalize_response(f, sym)
        return None

    def fetch_market_snapshot(self) -> List[PreOpenSnapshot]:
        if self.fail:
            return []
        results = []
        for f in self.fixtures:
            snap = self.normalize_response(f, f["symbol"])
            if snap:
                results.append(snap)
        return results
