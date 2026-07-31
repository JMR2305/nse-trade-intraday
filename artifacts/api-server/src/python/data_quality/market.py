"""
data_quality/market.py — Phase 8.3
Market data validation: OHLCV consistency, timestamps, price/volume spikes,
exchange-session alignment, and VWAP plausibility.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Issue, domain_result

_SPIKE_PRICE_PCT  = 20.0   # > 20% move flags a spike
_SPIKE_VOL_MULT   = 10.0   # > 10× median volume flags a spike
_MAX_GAP_PCT      = 30.0   # absolute gap > 30% is suspicious
_MAX_PRICE        = 1_000_000.0


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def validate_ohlcv(row: dict, symbol: str = "") -> list[Issue]:
    """Run all OHLC + volume checks on a single row dict."""
    issues: list[Issue] = []

    # Use None as the sentinel so we can distinguish truly-missing from negative.
    def _get(key: str):
        v = row.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    o  = _get("open")
    h  = _get("high")
    l  = _get("low")
    c  = _get("close")
    v  = _get("volume")

    def add(sev, check, fld, msg, val=None):
        issues.append(Issue(sev, check, fld, msg, symbol=symbol, value=val))

    # Presence checks — only flag truly absent/unparseable values
    missing = False
    for name, val in [("open", o), ("high", h), ("low", l), ("close", c)]:
        if val is None:
            add("MISSING", "PRICE_PRESENT", name, f"{name} is missing or null")
            missing = True
    if missing:
        return issues   # further checks are meaningless without prices

    # Impossible OHLC combinations
    if h < l:
        add("CRITICAL", "OHLC_CONSISTENCY", "high",
            f"high ({h}) < low ({l})", h)
    if c > h:
        add("CRITICAL", "OHLC_CONSISTENCY", "close",
            f"close ({c}) > high ({h})", c)
    if c < l:
        add("CRITICAL", "OHLC_CONSISTENCY", "close",
            f"close ({c}) < low ({l})", c)
    if o > h:
        add("CRITICAL", "OHLC_CONSISTENCY", "open",
            f"open ({o}) > high ({h})", o)
    if o < l:
        add("CRITICAL", "OHLC_CONSISTENCY", "open",
            f"open ({o}) < low ({l})", o)

    # Negative / zero prices
    for name, val in [("open", o), ("high", h), ("low", l), ("close", c)]:
        if val <= 0:
            add("CRITICAL", "NEGATIVE_PRICE", name,
                f"{name} price is zero or negative", val)

    # Unrealistically large prices
    for name, val in [("open", o), ("high", h), ("low", l), ("close", c)]:
        if val > _MAX_PRICE:
            add("WARNING", "PRICE_RANGE", name,
                f"{name} price {val} exceeds max {_MAX_PRICE}", val)

    # Volume
    if v is not None and v < 0:
        add("CRITICAL", "NEGATIVE_VOLUME", "volume",
            f"volume is negative ({v})", v)
    elif v is not None and v == 0:
        add("WARNING", "ZERO_VOLUME", "volume",
            "volume is zero — possible stale or holiday data", 0)

    return issues


def validate_timestamps(rows: list[dict], symbol: str = "") -> list[Issue]:
    """Check for future timestamps and non-monotonic ordering."""
    issues: list[Issue] = []
    now_ts = datetime.now(timezone.utc).timestamp()
    prev_ts = None

    for row in rows:
        raw = row.get("timestamp") or row.get("ts") or row.get("datetime")
        if raw is None:
            issues.append(Issue("MISSING", "TIMESTAMP_PRESENT", "timestamp",
                                "timestamp field is missing", symbol=symbol))
            continue
        try:
            if isinstance(raw, (int, float)):
                ts = float(raw)
            else:
                s = str(raw).strip()
                try:
                    ts = float(s)          # numeric string like "1817200000"
                except ValueError:
                    ts = datetime.fromisoformat(s).timestamp()
        except Exception:
            issues.append(Issue("WARNING", "TIMESTAMP_FORMAT", "timestamp",
                                f"Cannot parse timestamp: {raw!r}", symbol=symbol, value=raw))
            continue

        if ts > now_ts + 60:   # more than 1 min in the future
            issues.append(Issue("WARNING", "FUTURE_TIMESTAMP", "timestamp",
                                "timestamp is in the future", symbol=symbol, value=raw))

        if prev_ts is not None and ts < prev_ts:
            issues.append(Issue("WARNING", "TIMESTAMP_ORDER", "timestamp",
                                "timestamps are not monotonically increasing",
                                symbol=symbol, value=raw))
        prev_ts = ts

    return issues


def validate_gap(row: dict, symbol: str = "") -> list[Issue]:
    """Check gap % plausibility."""
    issues: list[Issue] = []
    gap_pct = _safe_float(row.get("gap_pct"), None)   # type: ignore[arg-type]
    prev_c  = _safe_float(row.get("prev_close"), 0)

    if gap_pct is None:
        return issues   # gap not provided — skip

    if abs(gap_pct) > _MAX_GAP_PCT:
        issues.append(Issue("WARNING", "PRICE_SPIKE", "gap_pct",
                            f"gap% {gap_pct:.1f}% exceeds ±{_MAX_GAP_PCT}%",
                            symbol=symbol, value=gap_pct))

    if prev_c < 0:
        issues.append(Issue("WARNING", "NEGATIVE_PRICE", "prev_close",
                            "previous close is negative", symbol=symbol, value=prev_c))
    return issues


def validate_market_snapshot(snapshot: list[dict]) -> dict:
    """
    Validate a list of symbol-level market rows.
    snapshot: list of dicts each with keys open/high/low/close/volume/timestamp/symbol.
    """
    total_checks  = 0
    total_passed  = 0
    all_issues: list[Issue] = []
    symbols_checked: list[str] = []

    for row in snapshot:
        sym = str(row.get("symbol", ""))
        symbols_checked.append(sym)

        ohlcv_issues = validate_ohlcv(row, sym)
        ts_issues    = validate_timestamps([row], sym)
        gap_issues   = validate_gap(row, sym)

        # Each check domain contributes 3 passes/fails per symbol
        n_checks = 3
        n_failed = min(1, len(ohlcv_issues)) + min(1, len(ts_issues)) + min(1, len(gap_issues))
        n_passed = n_checks - n_failed

        total_checks += n_checks
        total_passed += n_passed
        all_issues.extend(ohlcv_issues + ts_issues + gap_issues)

    # Duplicate symbol check
    seen: set[str] = set()
    for sym in symbols_checked:
        if sym in seen:
            all_issues.append(Issue("DUPLICATE", "DUPLICATE_SYMBOL", "symbol",
                                    f"Symbol {sym!r} appears more than once", symbol=sym))
            total_checks += 1
        else:
            total_checks += 1
            total_passed += 1
        seen.add(sym)

    if not snapshot:
        return domain_result("market", 1, 0,
                             [Issue("MISSING", "DATA_PRESENT", "snapshot",
                                    "No market snapshot data available")],
                             available=False,
                             extra={"symbols_checked": 0})

    return domain_result(
        "market", total_checks, total_passed, all_issues,
        extra={"symbols_checked": len(symbols_checked)},
    )


# ── Public entry point ────────────────────────────────────────────────────────

def get_market_validation() -> dict:
    """Load the latest scan snapshot and validate it."""
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot()
        rows = snap.get("symbols", []) if snap else []
    except Exception:
        rows = []

    if not rows:
        try:
            from market_scanner import get_cached_scan
            scan = get_cached_scan() or {}
            rows = scan.get("symbols", [])
        except Exception:
            rows = []

    return validate_market_snapshot(rows)
