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

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import MIN_SYMBOLS_EXPECTED

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


def coverage_probe() -> Dict[str, Any]:
    """Return the market-hours coverage verdict. Never raises."""
    result: Dict[str, Any] = {
        "success": True,
        "min_symbols_expected": MIN_SYMBOLS_EXPECTED,
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

    # Coverage is judged against the configured expected universe, never the
    # scan's own requested count.
    low = received < MIN_SYMBOLS_EXPECTED

    if not in_session:
        result["ok"] = True
        result["warning"] = None
        if low:
            result["note"] = (
                f"Coverage {received}/{MIN_SYMBOLS_EXPECTED} outside market "
                f"hours ({state}) — expected to self-resolve at next open."
            )
        return result

    # In session: recovery must be CONFIRMED by a scan from today's session.
    if not scan_fresh:
        result["ok"] = False
        age = f" (last scan: {meta.get('completed_at') or meta.get('snapshot_ts') or 'unknown'})"
        result["warning"] = (
            f"No scan completed in today's session{age} — coverage "
            f"{received}/{MIN_SYMBOLS_EXPECTED} is from a previous session and "
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
            f"Scanner coverage {received}/{MIN_SYMBOLS_EXPECTED} during market "
            f"hours{miss} — {gap_note}"
            "run a fresh scan and investigate the provider."
        )
        return result

    result["ok"] = True
    result["warning"] = None
    return result
