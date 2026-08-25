"""
scanner_coverage.py — market-hours scanner coverage probe.

Phase 2B/2C observed the scanner stuck below full coverage over weekends
(Yahoo returns no weekend data for some symbols, e.g. TMPV).
That gap is expected to self-resolve at Monday market open — but nothing
confirmed the recovery actually happened. This probe makes the check
explicit and automated:

* Outside market hours (WEEKEND / HOLIDAY / CLOSED / POST_CLOSE):
  coverage < expected is EXPECTED → ok=True, in_session=False.
* During the session (OPEN / PRE_OPEN), recovery is only CONFIRMED by a
  scan completed in TODAY'S session. Therefore during the session:
    - no scan snapshotted since today's session start → ok=False
      (a full-coverage Friday scan must NOT mask a Monday failure);
    - a fresh scan with coverage < MIN_SYMBOLS_EXPECTED → ok=False
      (coverage is measured against the configured expected universe,
      never the scan's own requested count — a reduced request universe
      cannot fake full coverage);
    - a fresh scan covering the full expected universe → ok=True.

Consumed by:
* main.py `scanner_coverage` command → /health/ready warning and the
  dashboard banner via GET /api/live-data/coverage (canonical — the
  browser applies NO market-hours logic of its own)
* phase2a_health_audit.py "Market-Hours Coverage" probe

PAPER TRADING / RESEARCH ONLY — read-only; never triggers a scan.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Session states where full, session-fresh coverage is required.
IN_SESSION_STATES = {"OPEN", "PRE_OPEN"}


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp (naive values assumed UTC). None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _expected_universe() -> Tuple[str, List[str]]:
    """Return the authoritative active universe and its symbols.

    The static NIFTY list is the source of truth for the default mode. Custom
    mode is deliberately resolved from durable settings and the custom master;
    an empty or unreadable custom master must never be treated as zero expected
    symbols, because that would make an empty scan look healthy.

    A database-free NIFTY configuration is supported for local/test runs. Once
    a database is configured, settings read failures remain fail-closed.
    """
    import config

    try:
        mode = config.get_active_intraday_universe_strict()
    except Exception:
        if os.environ.get("DATABASE_URL") or (
            config.ACTIVE_INTRADAY_UNIVERSE
            == config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR
        ):
            raise
        mode = config.ACTIVE_INTRADAY_UNIVERSE

    if mode == config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR:
        from custom_universe_store import get_active_symbols

        symbols = sorted({
            str(symbol).strip().upper()
            for symbol in get_active_symbols()
            if str(symbol).strip()
        })
        if not symbols:
            raise RuntimeError(
                "Durable custom active universe is unavailable or empty"
            )
        return mode.value, symbols

    symbols = sorted({
        str(symbol).strip().upper()
        for symbol in config.NIFTY_50
        if str(symbol).strip()
    })
    if not symbols:
        raise RuntimeError("Configured NIFTY 50 universe is empty")
    return mode.value, symbols


def coverage_probe() -> Dict[str, Any]:
    """Return the market-hours coverage verdict. Never raises."""
    result: Dict[str, Any] = {
        "success": True,
        "label": "PAPER / RESEARCH ONLY",
    }
    try:
        import market_hours
        ms = market_hours.market_status()
        state = ms.get("state", "UNKNOWN")
        now = market_hours.now_ist()
        session_start = now.replace(
            hour=market_hours.PRE_OPEN_START.hour,
            minute=market_hours.PRE_OPEN_START.minute,
            second=0, microsecond=0,
        )
    except Exception as exc:
        result.update({"success": False, "ok": False, "in_session": False,
                       "market_state": "UNKNOWN",
                       "warning": f"Market state unavailable: {exc}"})
        return result

    in_session = state in IN_SESSION_STATES
    result["market_state"] = state
    result["in_session"] = in_session
    result["session_start_ist"] = session_start.isoformat()

    try:
        active_universe, expected_symbols = _expected_universe()
        expected_count = len(expected_symbols)
        result.update({
            "active_universe": active_universe,
            "expected_symbols": expected_symbols,
            # Keep the established field name for dashboard/scheduler
            # consumers, but make it reflect the selected universe.
            "min_symbols_expected": expected_count,
        })
    except Exception as exc:
        result.update({
            "success": False,
            "ok": not in_session,
            "coverage": None,
            "warning": (
                f"Active universe unavailable: {exc}"
                if in_session else None
            ),
        })
        return result

    try:
        import scan_state_store
        meta = scan_state_store.load_latest_meta()
    except Exception as exc:
        result.update({"ok": not in_session, "coverage": None,
                       "warning": (f"Scan metadata unavailable: {exc}"
                                   if in_session else None)})
        return result

    if not meta:
        result.update({
            "ok": not in_session,
            "coverage": None,
            "warning": ("No completed scan found during market hours — "
                        "scanner may not be running") if in_session else None,
        })
        return result

    received = int(meta.get("symbols_received") or 0)
    requested = int(meta.get("symbols_requested") or 0)
    missing = list(meta.get("missing_symbols") or [])
    scan_ts = _parse_ts(meta.get("completed_at") or meta.get("snapshot_ts"))
    scan_fresh = bool(scan_ts and scan_ts >= session_start)
    result.update({
        "coverage": received,
        "symbols_requested": requested,
        "missing_symbols": missing,
        "scan_id": meta.get("scan_id"),
        "snapshot_ts": meta.get("snapshot_ts"),
        "scan_fresh_for_session": scan_fresh,
    })

    # Coverage is judged against the active expected universe, never the
    # scan's own requested count. This prevents a reduced custom scan from
    # declaring itself complete merely because its own request was satisfied.
    low = received < expected_count

    if not in_session:
        result["ok"] = True
        result["warning"] = None
        if low:
            result["note"] = (
                f"Coverage {received}/{expected_count} outside market "
                f"hours ({state}) — expected to self-resolve at next open."
            )
        return result

    # In session: recovery must be CONFIRMED by a scan from today's session.
    if not scan_fresh:
        result["ok"] = False
        age = f" (last scan: {meta.get('completed_at') or meta.get('snapshot_ts') or 'unknown'})"
        result["warning"] = (
            f"No scan completed in today's session{age} — coverage "
            f"{received}/{expected_count} is from a previous session and "
            "does NOT confirm recovery; run a fresh scan."
        )
        return result

    if low:
        result["ok"] = False
        miss = f" (missing: {', '.join(missing)})" if missing else ""
        # On Monday (first session after a weekend/holiday) the missing symbols
        # may be a lingering weekend data gap.  On any other weekday they are
        # a mid-session provider outage — do not say "weekend gap" on a Tuesday.
        if now.weekday() == 0:  # Monday = 0
            gap_note = "weekend data gap may not have resolved at open — "
        else:
            gap_note = "symbol(s) currently unavailable from provider — "
        result["warning"] = (
            f"Scanner coverage {received}/{expected_count} during market "
            f"hours{miss} — {gap_note}"
            "run a fresh scan and investigate the provider."
        )
        return result

    result["ok"] = True
    result["warning"] = None
    return result
