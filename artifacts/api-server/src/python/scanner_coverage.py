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


def _expected_universe() -> Tuple[str, List[str], Dict[str, Any]]:
    """Resolve the same pinned durable version as collection and scanning."""
    from runtime_universe import resolve_active_universe
    context = resolve_active_universe()
    return context["universe_key"], list(context["enabled_symbols"]), context


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
        active_universe, expected_symbols, universe_context = _expected_universe()
        expected_count = len(expected_symbols)
        result.update({
            "active_universe": active_universe,
            "expected_symbols": expected_symbols,
            # Keep the established field name for dashboard/scheduler
            # consumers, but make it reflect the selected universe.
            "min_symbols_expected": expected_count,
            "universe": universe_context,
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
    meta_universe = meta.get("universe_context") or meta.get("universe") or {}
    expected_hash = universe_context.get("exact_set_hash")
    expected_version = universe_context.get("version")
    if (meta_universe.get("exact_set_hash", meta_universe.get("universe_set_hash")) != expected_hash
            or meta_universe.get("version", meta_universe.get("universe_version")) != expected_version):
        result.update({
            "success": False,
            "ok": not in_session,
            "warning": "Latest scan was produced by a different pinned universe version",
            "universe_mismatch": True,
        })
        return result

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
