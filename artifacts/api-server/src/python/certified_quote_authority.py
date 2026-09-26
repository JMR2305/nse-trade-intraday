"""Fail-closed Kite-live quote extraction for certification checkpoints.

``kite_quote_provider`` intentionally supports a Yahoo fallback for
non-certifying consumers.  This adapter rejects that fallback and exposes only
exact-symbol, positive, explicitly Kite-live values to Phase5 evidence.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def certified_prices(symbols: Iterable[str], *, require_open: bool = False) -> Dict[str, Any]:
    requested: List[str] = [str(symbol).upper().strip() for symbol in symbols
                            if str(symbol).strip()]
    requested = list(dict.fromkeys(requested))
    try:
        from kite_quote_provider import get_quotes
        rows = get_quotes(requested, force_refresh=True)
    except Exception:
        rows = {}

    open_prices: Dict[str, float] = {}
    ltp_prices: Dict[str, float] = {}
    missing: List[str] = []
    for symbol in requested:
        row = rows.get(symbol) if isinstance(rows, dict) else None
        row_symbol = str((row or {}).get("symbol") or symbol).upper().strip()
        ltp = _positive((row or {}).get("ltp"))
        opening = _positive((row or {}).get("open"))
        live = bool(
            isinstance(row, dict)
            and row_symbol == symbol
            and row.get("data_source") == "kite_live"
            and row.get("data_quality") == "LIVE"
            and ltp is not None
            and (not require_open or opening is not None)
        )
        if not live:
            missing.append(symbol)
            continue
        ltp_prices[symbol] = ltp
        if opening is not None:
            open_prices[symbol] = opening

    live_count = len(ltp_prices)
    return {
        "open_prices": open_prices,
        "ltp_prices": ltp_prices,
        "requested_count": len(requested),
        "live_count": live_count,
        "missing_count": len(missing),
        "missing_symbols": missing,
        "provider": "kite_quote_provider",
        "provenance": "kite_live/LIVE",
        "status": "COMPLETE" if live_count == len(requested) else "INCOMPLETE",
    }
