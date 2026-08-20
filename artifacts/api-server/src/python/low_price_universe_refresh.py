"""Build the custom low-price NSE IT/Infra/Bank paper-trading universe.

This module uses the Kite instrument *cache* and optional read-only quote
overlay. It never imports an order client and never creates, modifies, or
cancels broker orders.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

PRICE_MIN = 20.0
PRICE_MAX = 200.0
MIN_AVG_VOLUME_20D = 500_000.0
MIN_AVG_TURNOVER_20D = 50_000_000.0  # ₹5 crore
MIN_OHLCV_BARS = 120
# Initial hydration is intentionally bounded. Subsequent daily refreshes skip
# newly cached rows and progress through remaining candidates without a large
# cold-start yfinance fan-out.
MAX_OHLCV_BOOTSTRAP_SYMBOLS = 150


def is_nse_equity(instrument: Dict[str, Any]) -> bool:
    return (
        str(instrument.get("exchange") or "").upper() == "NSE"
        and str(instrument.get("instrument_type") or "").upper() == "EQ"
    )


def in_price_band(price: Optional[float]) -> bool:
    return price is not None and PRICE_MIN <= float(price) <= PRICE_MAX


def _normalise_sector(value: Any) -> Optional[str]:
    from config import normalize_low_price_sector
    return normalize_low_price_sector(str(value or ""))


def _cached_instruments() -> List[Dict[str, Any]]:
    from kite_instrument_cache import get_cached_instruments
    return [row for row in get_cached_instruments() if is_nse_equity(row)]


def _master_metadata(symbol: str) -> Dict[str, Any]:
    try:
        from nifty50_company_master_store import get_symbol
        return get_symbol(symbol) or {}
    except Exception:
        return {}


def _yfinance_metadata(symbol: str) -> Dict[str, Any]:
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info or {}
        return {
            "company_name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception:
        return {}


def _fallback_yfinance_prices(symbols: List[str]) -> Dict[str, float]:
    """One bulk close fetch when Kite LTP is unavailable; never raises."""
    if not symbols:
        return {}
    try:
        import pandas as pd
        import yfinance as yf
        tickers = [f"{symbol}.NS" for symbol in symbols]
        bulk = yf.download(
            tickers, period="5d", interval="1d", progress=False,
            auto_adjust=True, group_by="ticker", threads=True,
        )
        out: Dict[str, float] = {}
        for symbol, ticker in zip(symbols, tickers):
            try:
                frame = bulk[ticker] if isinstance(bulk.columns, pd.MultiIndex) else bulk
                close = frame["Close"] if "Close" in frame else frame["close"]
                value = float(close.dropna().iloc[-1])
                if value > 0:
                    out[symbol.upper()] = value
            except Exception:
                continue
        return out
    except Exception as exc:
        logger.info("low-price yfinance fallback unavailable: %s", exc)
        return {}


def _cached_ohlcv(symbol: str) -> tuple[Any, bool]:
    try:
        from ohlcv_cache_store import read_symbol_from_cache
        frame = read_symbol_from_cache(symbol, min_bars=MIN_OHLCV_BARS)
        return frame, bool(frame is not None and len(frame) >= MIN_OHLCV_BARS)
    except Exception:
        return None, False


def _liquidity(frame: Any) -> tuple[float, float]:
    recent = frame.tail(20)
    volume = float(recent["volume"].mean())
    turnover = float((recent["volume"] * recent["close"]).mean())
    return volume, turnover


def _candidate_row(
    instrument: Dict[str, Any],
    ltp: Optional[float],
    ltp_source: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    symbol = str(instrument.get("symbol") or "").upper()
    if metadata is None:
        master = _master_metadata(symbol)
        metadata = master or _yfinance_metadata(symbol)
    sector = _normalise_sector(metadata.get("sector") or metadata.get("industry"))
    frame, ohlcv_available = _cached_ohlcv(symbol)
    avg_volume, avg_turnover = (0.0, 0.0)
    if ohlcv_available:
        avg_volume, avg_turnover = _liquidity(frame)
    company_name = (
        metadata.get("company_name") or metadata.get("name")
        or instrument.get("name") or symbol
    )
    row: Dict[str, Any] = {
        "symbol": symbol,
        "yahoo_symbol": f"{symbol}.NS",
        "kite_symbol": symbol,
        "instrument_token": instrument.get("token"),
        "company_name": company_name,
        "sector": sector or "OTHER",
        "industry": metadata.get("industry"),
        "price_min": PRICE_MIN,
        "price_max": PRICE_MAX,
        "last_ltp": ltp,
        "last_ltp_source": ltp_source,
        "avg_volume_20d": avg_volume,
        "avg_turnover_20d": avg_turnover,
        "ohlcv_available": ohlcv_available,
        "last_verified_at": datetime.now(timezone.utc).isoformat(),
    }
    reason: Optional[str] = None
    if ltp is None or ltp <= 0:
        reason = "LTP unavailable"
    elif not in_price_band(ltp):
        reason = f"price ₹{ltp:.2f} outside ₹{PRICE_MIN:.0f}–₹{PRICE_MAX:.0f}"
    elif sector is None:
        reason = "sector not in IT/INFRA/BANK"
    elif not ohlcv_available:
        reason = f"missing OHLCV evidence (<{MIN_OHLCV_BARS} bars)"
    elif avg_volume < MIN_AVG_VOLUME_20D:
        reason = f"avg volume {avg_volume:.0f} < {MIN_AVG_VOLUME_20D:.0f}"
    elif avg_turnover < MIN_AVG_TURNOVER_20D:
        reason = f"avg turnover ₹{avg_turnover:.0f} < ₹{MIN_AVG_TURNOVER_20D:.0f}"
    row["is_active"] = reason is None
    row["reason_included"] = (
        "NSE EQ; sector, price, OHLCV, volume and turnover filters passed"
        if reason is None else None
    )
    row["reason_excluded"] = reason
    return row


def _hydrate_missing_ohlcv(symbols: List[str]) -> Dict[str, Any]:
    """Bounded cache bootstrap for price/sector-eligible candidates only."""
    if not symbols:
        return {"requested": 0, "updated": 0}
    missing = []
    for symbol in symbols:
        _frame, available = _cached_ohlcv(symbol)
        if not available:
            missing.append(symbol)
    batch = missing[:MAX_OHLCV_BOOTSTRAP_SYMBOLS]
    if not batch:
        return {"requested": 0, "updated": 0}
    try:
        from ohlcv_cache_store import backfill_all_symbols
        outcome = backfill_all_symbols(batch, period="8mo")
        return {
            "requested": len(batch),
            "updated": len(outcome.get("updated") or []),
            "failed": len(outcome.get("failed") or []),
        }
    except Exception as exc:
        logger.info("custom universe OHLCV bootstrap unavailable: %s", exc)
        return {"requested": len(batch), "updated": 0, "error": str(exc)[:160]}


def refresh_low_price_sector_universe() -> Dict[str, Any]:
    """Refresh and persist all NSE EQ candidates. Advisory, paper-only."""
    from custom_universe_store import get_status, upsert_symbols
    instruments = _cached_instruments()
    if not instruments:
        return {
            "success": False, "error": "kite_instrument_cache_empty",
            "active_count": 0, "candidates": 0,
        }

    symbols = [str(row.get("symbol") or "").upper() for row in instruments]
    if not all(symbols):
        return {
            "success": False, "error": "invalid_instrument_cache_schema",
            "active_count": 0, "candidates": 0,
        }
    # The overlay is read-only and has no broker order surface.
    try:
        from kite_ltp_overlay import fetch_ltp_overlay
        overlay = fetch_ltp_overlay(symbols)
        kite_ltps = {
            key.upper(): float(value) for key, value in (overlay.get("ltps") or {}).items()
            if value is not None and float(value) > 0
        }
        kite_enabled = bool(overlay.get("session_verified"))
    except Exception:
        kite_ltps, kite_enabled = {}, False
    missing = [symbol for symbol in symbols if symbol not in kite_ltps]
    yfinance_ltps = _fallback_yfinance_prices(missing)

    prices = {
        symbol: kite_ltps.get(symbol, yfinance_ltps.get(symbol))
        for symbol in symbols
    }
    # Avoid metadata lookups for securities already outside the price band.
    # Only those that can enter the low-price universe need sector enrichment.
    metadata_by_symbol: Dict[str, Dict[str, Any]] = {}
    sector_candidates: List[str] = []
    for instrument in instruments:
        symbol = str(instrument["symbol"]).upper()
        if not in_price_band(prices.get(symbol)):
            continue
        master = _master_metadata(symbol)
        metadata = master or _yfinance_metadata(symbol)
        metadata_by_symbol[symbol] = metadata
        if _normalise_sector(metadata.get("sector") or metadata.get("industry")):
            sector_candidates.append(symbol)
    hydration = _hydrate_missing_ohlcv(sector_candidates)

    rows = []
    for instrument in instruments:
        symbol = str(instrument.get("symbol") or "").upper()
        if symbol in kite_ltps:
            row = _candidate_row(
                instrument, kite_ltps[symbol], "kite_ltp",
                metadata_by_symbol.get(symbol, {}),
            )
        else:
            row = _candidate_row(
                instrument, yfinance_ltps.get(symbol),
                "yfinance_close" if symbol in yfinance_ltps else "unavailable",
                metadata_by_symbol.get(symbol, {}),
            )
        rows.append(row)

    saved = upsert_symbols(rows)
    active_count = sum(1 for row in rows if row.get("is_active"))
    result = {
        "success": bool(saved.get("success")),
        "candidates": len(rows),
        "active_count": active_count,
        "excluded_count": len(rows) - active_count,
        "kite_ltp_session_verified": kite_enabled,
        "ohlcv_bootstrap": hydration,
        "upsert": saved,
        "status": get_status(),
        "paper_trading_only": True,
        "no_live_broker_orders": True,
    }
    try:
        from pipeline_events import emit
        emit("LOW_PRICE_UNIVERSE_REFRESH_COMPLETED", "DATA_CACHE", payload={
            "candidates": len(rows), "active_count": active_count,
            "excluded_count": len(rows) - active_count,
            "kite_ltp_session_verified": kite_enabled,
        })
    except Exception:
        pass
    try:
        from low_price_universe_report import generate_report
        result["report"] = generate_report().get("path")
    except Exception as exc:
        result["report_error"] = str(exc)[:160]
    return result