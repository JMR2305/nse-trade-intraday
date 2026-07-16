"""
phase20_scheduler.py — Phase 20 market-hours scheduled scan tick.

Called every minute by the Node scheduler; this module decides whether a scan
is actually due, based on durable Phase 20 settings (interval, auto-scan
toggle), NSE market hours (Asia/Kolkata, weekends + holidays), snapshot
freshness, and the distributed scan lease.

Records scheduler health and scan-run history durably, and after a
successful scheduled scan runs paper-position management (exits) and — only
when explicitly enabled AND confirmed — automatic paper entries.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
A failed scan never overwrites the last successful snapshot
(guaranteed by scan_state_store / live_scan_engine).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import phase20_store as store


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_due_iso(interval_min: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=interval_min)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_meta_from_snapshot(snap: Dict[str, Any], trigger: str,
                            duration_s: float) -> Dict[str, Any]:
    health = snap.get("provider_health") or {}
    safety = snap.get("safety") or {}
    audit = snap.get("scan_audit") or {}
    return {
        "scan_id": snap.get("scan_id"),
        "trigger_source": trigger,
        "started_at": snap.get("snapshot_ts"),
        "completed_at": audit.get("scan_completed_ts") or snap.get("snapshot_ts"),
        "duration_s": round(duration_s, 2),
        "symbols_requested": health.get("symbols_requested"),
        "symbols_received": health.get("symbols_succeeded"),
        "missing_symbols": list(health.get("unavailable_symbols") or []),
        "stale_symbols": list(health.get("stale_symbols") or []),
        "unavailable_symbols": list(health.get("unavailable_symbols") or []),
        "provider": safety.get("data_provider") or health.get("provider"),
        "status": "SUCCESS",
        "error": None,
    }


def record_manual_scan(snap: Dict[str, Any], duration_s: float = 0.0) -> None:
    """Record a MANUAL scan run (called from the phase7_scan CLI path)."""
    try:
        store.record_scan_run(_run_meta_from_snapshot(snap, "MANUAL", duration_s))
    except Exception:
        pass


def _maybe_generate_session_report(mstate: str) -> Any:
    """After the market closes on a trading day, generate the daily
    validation report bundle (CSV/XLSX/PDF) exactly once per day.

    Runs only when state is CLOSED (post-session on a trading day, not
    HOLIDAY/WEEKEND pre-open states) and only if a scan actually ran today.
    Returns a small summary dict when a report was generated, else None.
    """
    if mstate != "CLOSED":
        return None
    try:
        from zoneinfo import ZoneInfo
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        if store.kv_get("session_report_date") == today_ist:
            return None
        sched = store.get_scheduler_health()
        last_ok = str((sched or {}).get("last_success_at") or "")
        if not last_ok.startswith(today_ist):
            # No successful scan yet today — don't stamp, so a later
            # recovery/manual scan can still trigger today's report.
            return None
        # Claim the day up-front so concurrent ticks don't both build.
        prev = store.kv_get("session_report_date")
        store.kv_set("session_report_date", today_ist)
        try:
            from phase16_exports import build_exports
            result = build_exports()
        except Exception:
            store.kv_set("session_report_date", prev)  # allow retry next tick
            raise
        return {"generated": True, "date": today_ist,
                "files": result.get("files", []),
                "warnings": result.get("warnings", [])}
    except Exception as exc:  # report generation must never break the tick
        return {"generated": False, "error": str(exc)[:200]}


def run_tick() -> Dict[str, Any]:
    """One scheduler tick. Returns a JSON-safe result dict."""
    settings = store.get_settings()
    interval_min = int(settings.get("scan_interval_minutes", 5))
    now_iso = _iso_now()

    if not settings.get("auto_scan_enabled", True):
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="DISABLED",
            detail="Auto scan disabled in settings",
        )
        return {"success": True, "ran_scan": False, "reason": "Auto scan disabled"}

    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()
    if mstate != "OPEN":
        report = _maybe_generate_session_report(mstate)
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="IDLE",
            detail=f"Market not open (state={mstate or 'UNKNOWN'})",
        )
        out: Dict[str, Any] = {"success": True, "ran_scan": False,
                               "reason": f"Market not open (state={mstate or 'UNKNOWN'})",
                               "market": mstat}
        if report is not None:
            out["session_report"] = report
        return out

    from phase15_scan_context import scan_age_seconds
    age = scan_age_seconds()
    if age is not None and age < interval_min * 60:
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="FRESH",
            next_due_at=_next_due_iso(max(1, int(interval_min - age / 60))),
            detail=f"Snapshot fresh ({round(age)}s old, interval {interval_min}m)",
        )
        result: Dict[str, Any] = {
            "success": True, "ran_scan": False,
            "reason": f"Snapshot fresh ({round(age)}s old, interval {interval_min}m)",
        }
        result["paper"] = _manage_paper(settings, ran_scan=False)
        return result

    store.update_scheduler_state(last_attempt_at=now_iso, status="SCANNING",
                                 detail="Scheduled scan starting")
    t0 = time.time()
    try:
        from live_scan_engine import get_or_run_scan
        snap = get_or_run_scan(max_age_s=interval_min * 60, force=False)
        duration = time.time() - t0
        ran = not snap.get("_from_cache", False)
        if ran:
            store.record_scan_run(_run_meta_from_snapshot(snap, "SCHEDULED", duration))
            store.add_notification(
                "SCAN_SUCCESS", "Scheduled scan completed",
                f"Scan {snap.get('scan_id')} completed in {round(duration, 1)}s",
                severity="INFO",
                context={"scan_id": snap.get("scan_id"),
                         "snapshot_ts": snap.get("snapshot_ts")},
            )
        store.update_scheduler_state(
            last_attempt_at=now_iso, last_success_at=_iso_now(),
            last_scan_id=snap.get("scan_id"),
            next_due_at=_next_due_iso(interval_min),
            status="OK", detail="Scheduled scan ok" if ran else "Snapshot reused",
        )
        result = {"success": True, "ran_scan": ran,
                  "scan_id": snap.get("scan_id"),
                  "snapshot_ts": snap.get("snapshot_ts"),
                  "duration_s": round(duration, 2)}
        result["paper"] = _manage_paper(settings, ran_scan=ran)
        return result
    except Exception as exc:  # failed scan: prior snapshot preserved by design
        duration = time.time() - t0
        store.record_scan_run({
            "scan_id": None, "trigger_source": "SCHEDULED",
            "started_at": now_iso, "completed_at": _iso_now(),
            "duration_s": round(duration, 2), "status": "FAILED",
            "error": str(exc),
        })
        store.update_scheduler_state(
            last_attempt_at=now_iso, missed_increment=1,
            status="ERROR", detail=str(exc)[:300],
        )
        store.add_notification(
            "SCAN_FAILED", "Scheduled scan failed",
            str(exc)[:500], severity="ERROR",
        )
        return {"success": True, "ran_scan": False, "error": str(exc)[:300],
                "reason": "Scan failed — previous snapshot preserved"}


def _manage_paper(settings: Dict[str, Any], ran_scan: bool) -> Dict[str, Any]:
    """
    Run paper position management (exits) and, only when enabled AND
    confirmed, automatic paper entries. Never raises.
    """
    out: Dict[str, Any] = {"exits": None, "entries": None}
    try:
        if settings.get("auto_paper_exits", True):
            from phase20_exits import manage_open_positions
            out["exits"] = manage_open_positions(settings)
    except Exception as exc:
        out["exits"] = {"error": str(exc)[:200]}
    try:
        if settings.get("auto_paper_entries") and settings.get("auto_paper_entries_confirmed_at"):
            from phase20_executor import run_auto_entries
            out["entries"] = run_auto_entries(settings)
        else:
            out["entries"] = {"skipped": "auto_paper_entries OFF (default)"}
    except Exception as exc:
        out["entries"] = {"error": str(exc)[:200]}
    return out
