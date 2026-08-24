"""Read-only market-data readiness derived from existing local state only."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

MARKET_TIMESTAMP_FRESH_TTL_S = 300


def _iso_age_seconds(value: Any, now: datetime) -> Optional[float]:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (now - stamp).total_seconds()
        # A future timestamp is not trustworthy market evidence either.
        return round(age, 1) if age >= 0 else None
    except Exception:
        return None


def _symbols(items: Iterable[Any]) -> List[str]:
    return sorted({str(item).upper().strip() for item in items if str(item).strip()})


def build_market_data_health(
    scan: Optional[Dict[str, Any]],
    session: Optional[Dict[str, Any]],
    instruments: Optional[Iterable[Dict[str, Any]]],
    now: Optional[datetime] = None,
    current_universe: Optional[Iterable[Any]] = None,
    active_universe: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the health contract without fetching quotes, profiles, or tokens."""
    now = now or datetime.now(timezone.utc)
    scan = scan if isinstance(scan, dict) else {}
    session = session if isinstance(session, dict) else {}
    latest_scan_universe = _symbols(scan.get("universe") or [])
    universe = _symbols(
        current_universe if current_universe is not None else latest_scan_universe
    )
    records = {
        str(row.get("symbol") or "").upper().strip(): row
        for row in (scan.get("recommendations") or [])
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }
    instrument_tokens = {
        str(row.get("symbol") or "").upper().strip()
        for row in (instruments or [])
        if isinstance(row, dict)
        and str(row.get("symbol") or "").strip()
        and row.get("token") not in (None, "", 0)
    }
    missing_symbols = [symbol for symbol in universe if symbol not in instrument_tokens]
    valid_quote_timestamps: List[tuple[str, float]] = []
    invalid_live_quote_timestamp_symbols: List[str] = []
    counts = {"kite": 0, "fallback": 0, "stale": 0, "unavailable": 0, "synthetic": 0}
    for symbol in universe:
        row = records.get(symbol)
        if not row:
            counts["unavailable"] += 1
            continue
        source = " ".join(str(row.get(k) or "").lower() for k in (
            "data_source", "current_price_source", "execution_price_source",
        ))
        quality = str(row.get("data_quality_for_execution") or row.get("data_quality") or "").upper()
        if "synthetic" in source or "mock" in source:
            counts["synthetic"] += 1
        elif row.get("error") or quality == "UNAVAILABLE":
            counts["unavailable"] += 1
        elif quality == "STALE":
            counts["stale"] += 1
        elif (row.get("kite_ltp_available") is True
              and str(row.get("execution_price_source") or "") == "kite_live_ltp"):
            counts["kite"] += 1
            quote_timestamp = row.get("latest_price_time_ist")
            quote_age_s = _iso_age_seconds(quote_timestamp, now)
            if quote_age_s is None or quote_age_s > MARKET_TIMESTAMP_FRESH_TTL_S:
                invalid_live_quote_timestamp_symbols.append(symbol)
            else:
                valid_quote_timestamps.append((str(quote_timestamp), quote_age_s))
        elif "yfinance" in source:
            counts["fallback"] += 1
        else:
            # Unknown provenance must not be silently counted as usable data.
            counts["unavailable"] += 1

    if valid_quote_timestamps:
        latest_quote_timestamp, latest_quote_age_s = min(
            valid_quote_timestamps, key=lambda item: item[1])
    else:
        latest_quote_timestamp, latest_quote_age_s = None, None
    kite_quote_timestamps_fresh = bool(
        counts["kite"] > 0 and not invalid_live_quote_timestamp_symbols)
    # The scan snapshot is the bounded-freshness timestamp for the whole
    # universe; a single symbol's latest quote cannot attest to a full scan.
    market_timestamp = scan.get("snapshot_ts")
    market_timestamp_age_s = _iso_age_seconds(market_timestamp, now)
    market_timestamp_fresh = bool(
        market_timestamp_age_s is not None
        and market_timestamp_age_s <= MARKET_TIMESTAMP_FRESH_TTL_S
    )
    active = len(universe)
    valid_tokens = active - len(missing_symbols)
    coverage_pct = round((valid_tokens / active) * 100, 2) if active else 0.0
    service_ready = bool(scan and scan.get("snapshot_ts"))
    scan_origin = str(scan.get("trigger_origin") or "UNKNOWN").upper()
    certifying_scheduled_scan = scan_origin == "SCHEDULED"
    data_ready = bool(
        active
        and len(records) == active
        and not counts["stale"]
        and not counts["unavailable"]
        and not counts["synthetic"]
    )
    session_fresh = session.get("session_fresh") is True
    kite_connected = session.get("kite_connected") is True and session_fresh
    trading_data_ready = bool(
        service_ready and data_ready and session_fresh and kite_connected
        and counts["kite"] == active
        and valid_tokens == active
        and market_timestamp_fresh
        and kite_quote_timestamps_fresh
        and certifying_scheduled_scan
    )
    return {
        "active_universe": active_universe or "UNKNOWN",
        "active_universe_count": active,
        "kite_connected": kite_connected,
        "valid_token_count": valid_tokens,
        "missing_token_count": len(missing_symbols),
        "missing_symbols": missing_symbols,
        "token_coverage_pct": coverage_pct,
        "symbols_on_kite": counts["kite"],
        "symbols_fallback": counts["fallback"],
        "symbols_stale": counts["stale"],
        "symbols_unavailable": counts["unavailable"],
        "symbols_synthetic": counts["synthetic"],
        "latest_quote_timestamp": latest_quote_timestamp,
        "latest_quote_age_s": latest_quote_age_s,
        "kite_quote_timestamps_fresh": kite_quote_timestamps_fresh,
        "invalid_live_quote_timestamp_symbols": invalid_live_quote_timestamp_symbols,
        "market_timestamp": market_timestamp if market_timestamp_age_s is not None else None,
        "market_timestamp_age_s": market_timestamp_age_s,
        "market_timestamp_fresh": market_timestamp_fresh,
        "service_ready": service_ready,
        "data_ready": data_ready,
        "session_fresh": session_fresh,
        "trading_data_ready": trading_data_ready,
        "latest_scan": {
            "scan_id": scan.get("scan_id"),
            "scan_timestamp": scan.get("snapshot_ts"),
            "scan_universe": latest_scan_universe,
            "scan_symbol_count": len(latest_scan_universe),
            "scan_fresh_for_session": market_timestamp_fresh,
            "trigger_origin": scan_origin,
            "certifying_scheduled_scan": certifying_scheduled_scan,
        },
        "read_only": True,
    }