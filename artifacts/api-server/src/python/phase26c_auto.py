"""
phase26c_auto.py — Phase 26C: automatic per-session validation runs.

Runs the recovery, performance, and trading-quality validation suites
automatically once per IST trading day, post-close, from the Phase 20
scheduler tick — so regressions are caught without anyone clicking "Run".

Conventions (mirrors phase26_reports.maybe_generate_daily_report):
* Build first (read-only, cheap), claim the day only right before
  persisting — a build failure leaves the day unclaimed so the next tick
  retries.
* kv_claim_once per (area, IST day) gives exactly-once across processes.
* Fail-safe: never raises into the scheduler tick; one area failing never
  blocks the others.
* Manual runs stay possible and are unaffected (they persist directly).

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional

IST = timezone(timedelta(hours=5, minutes=30))

# area → runner returning a built (unpersisted) report
def _runners() -> Dict[str, Callable[[], Dict[str, Any]]]:
    from phase26_recovery import run_recovery_validation
    from phase26_performance import run_performance_validation
    from phase26_quality import run_quality_validation
    return {
        "RECOVERY": lambda: run_recovery_validation(persist=False),
        "PERFORMANCE": lambda: run_performance_validation(persist=False),
        "QUALITY": lambda: run_quality_validation(persist=False),
    }


def _ran_today(area: str, today_ist: str) -> bool:
    """True when the newest persisted run for `area` is from today (IST)."""
    try:
        import phase26c_store as store
        rows = store.list_results(area, limit=1)
        if not rows:
            return False
        raw = str(rows[0].get("created_at") or "")
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).date().isoformat() == today_ist
    except Exception:
        return False   # unknown → attempt the run; the KV claim still
                       # guarantees at most one persist per day


def maybe_run_session_validations(mstate: str) -> Optional[Dict[str, Any]]:
    """Post-close automatic 26C runs, exactly once per IST trading day per
    area. Never raises.

    Triggers on POST_CLOSE (15:30–16:00 IST) so results exist by the time
    the first CLOSED tick generates the 26D daily report; CLOSED is also
    accepted as a catch-up path (restarts, missed ticks)."""
    if str(mstate).upper() not in ("POST_CLOSE", "CLOSED"):
        return None
    try:
        import phase20_store as store
        today_ist = datetime.now(IST).date().isoformat()
        out: Dict[str, Any] = {"ran": [], "skipped": [], "errors": {}}
        for area, run in _runners().items():
            try:
                if _ran_today(area, today_ist):
                    out["skipped"].append(area)
                    continue
                report = run()                      # build only, no persist
                # Deterministic day-scoped id: the store's primary key
                # (ON CONFLICT DO NOTHING) then enforces at most one
                # automatic result per (area, IST day) durably, even if
                # two processes race past the KV claim.
                report["result_id"] = f"auto-{area.lower()}-{today_ist}"
                claim_key = f"p26c_auto:{area}:{today_ist}"
                if not store.kv_claim_once(claim_key):
                    out["skipped"].append(area)     # another process won
                    continue
                try:
                    import phase26c_store as c_store
                    stored = c_store.append_result(area, report)
                except Exception:
                    # Persist failed AFTER claiming: release so the next
                    # tick retries instead of skipping the day forever.
                    try:
                        store.kv_release(claim_key)
                    except Exception:
                        pass
                    raise
                out["ran"].append({"area": area,
                                   "result_id": stored["result_id"],
                                   "verdict": report.get("verdict")})
            except Exception as exc:                # one area never blocks the rest
                out["errors"][area] = str(exc)[:200]
        if not out["errors"]:
            out.pop("errors")
        return out
    except Exception as exc:                        # never break the tick
        return {"ran": [], "error": str(exc)[:200]}
