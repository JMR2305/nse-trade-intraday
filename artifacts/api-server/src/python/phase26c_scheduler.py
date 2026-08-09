"""
phase26c_scheduler.py — scheduled Phase 26C validation (recovery,
performance, trading quality) at session milestones.

Called from the phase20 scheduler tick. Runs the three heavier 26C suites
exactly once per milestone per IST trading day:

* "open"  — during the OPEN session, once the post-open grace period has
            passed (so the first scheduled scan + pipeline have had a chance
            to run and the suites judge real session state).
* "close" — after market close (POST_CLOSE, 15:30–16:00 IST, so results
            exist before the first CLOSED tick builds the Phase 26D daily
            report; CLOSED is also accepted as a catch-up path), so the
            end-of-day book/funnel is validated the same day.

Exactly-once semantics use phase20_store.kv_claim_once (atomic across
concurrent Autoscale processes) with ONE claim PER SUITE per milestone.
A suite that errors releases its own claim so the next tick retries just
that suite — a transient error in one suite never skips it for the day,
and never causes the suites that DID complete to re-run.

FAIL verdicts raise an operator notification through the existing
add_notification path (kind VALIDATION_FAILED is emailed when email alerts
are enabled). The suites themselves already feed the Phase 26 issue store.

READ-ONLY / ADVISORY-ONLY. Never raises out of maybe_run_session_validation.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

# Grace period after the 09:15 IST open before the "open" milestone runs —
# gives the first scheduled scan + post-scan pipeline time to complete so
# the suites validate real session state, not a cold start.
OPEN_MILESTONE_GRACE_MIN = 30

SUITES = ("recovery", "performance", "quality")

_CLAIM_PREFIX = "p26c_session"


def _claim_key(day_ist: str, milestone: str, suite: str) -> str:
    return f"{_CLAIM_PREFIX}:{day_ist}:{milestone}:{suite}"


def _due_milestone(mstate: str, now_ist=None) -> Optional[str]:
    """Which milestone (if any) is due for the given market state."""
    state = str(mstate or "").upper()
    if state in ("POST_CLOSE", "CLOSED"):
        return "close"
    if state != "OPEN":
        return None
    import market_hours
    now = now_ist or market_hours.now_ist()
    open_dt = now.replace(hour=market_hours.MARKET_OPEN.hour,
                          minute=market_hours.MARKET_OPEN.minute,
                          second=0, microsecond=0)
    if now < open_dt + timedelta(minutes=OPEN_MILESTONE_GRACE_MIN):
        return None
    return "open"


_RUNNERS = {
    "recovery": ("phase26_recovery", "run_recovery_validation"),
    "performance": ("phase26_performance", "run_performance_validation"),
    "quality": ("phase26_quality", "run_quality_validation"),
}


def _run_suite(name: str) -> Dict[str, Any]:
    """Run one 26C suite. Exceptions are captured as an ERROR result so one
    broken suite never blocks the others."""
    module_name, fn_name = _RUNNERS[name]
    try:
        module = __import__(module_name)
        report = getattr(module, fn_name)(persist=True)
        # The suite runners swallow persistence failures into persist_error
        # — for a SCHEDULED run an unpersisted result is a failed run (it
        # must be retried), so surface it as ERROR.
        if report.get("persist_error"):
            return {"verdict": "ERROR",
                    "error": f"persist failed: {report['persist_error']}"
                             [:200]}
        return {"verdict": report.get("verdict"),
                "fully_evaluated": report.get("fully_evaluated"),
                "result_id": report.get("result_id")}
    except Exception as exc:
        return {"verdict": "ERROR", "error": str(exc)[:200]}


def _notify_failures(milestone: str, day_ist: str,
                     results: Dict[str, Any]) -> bool:
    """One CRITICAL notification covering every FAIL/ERROR suite verdict.
    Returns True when a notification was raised."""
    import phase20_store as store
    bad = {}
    for name, r in results.items():
        verdict = str((r or {}).get("verdict") or "").upper()
        if verdict == "FAIL":
            bad[name] = r          # suite claim held → seen at most once
        elif verdict == "ERROR":
            # An errored suite retries every tick — alert it once per
            # milestone (atomic claim) so retries don't spam operators.
            if store.kv_claim_once(
                    f"{_CLAIM_PREFIX}_err_notified:{day_ist}:"
                    f"{milestone}:{name}"):
                bad[name] = r
    if not bad:
        return False
    lines = []
    for name, r in bad.items():
        v = str(r.get("verdict") or "").upper()
        extra = f" ({r.get('error')})" if r.get("error") else ""
        lines.append(f"{name}: {v}{extra}")
    store.add_notification(
        kind="VALIDATION_FAILED",
        title=(f"Phase 26C {milestone}-of-session validation failed "
               f"({', '.join(sorted(bad))})"),
        body=("Scheduled Phase 26C validation detected failures — "
              + "; ".join(lines)
              + ". See the Phase 26 issue store for details."),
        severity="CRITICAL",
        context={"milestone": milestone, "day": day_ist,
                 "verdicts": {n: (r or {}).get("verdict")
                              for n, r in results.items()}},
    )
    return True


def maybe_run_session_validation(mstate: str) -> Optional[Dict[str, Any]]:
    """Scheduler entry point. Runs each 26C suite exactly once per due
    milestone per IST trading day (atomic per-suite KV claims, cross-process
    safe). A suite that errors releases its own claim and retries on a later
    tick; completed suites never re-run. Never raises."""
    try:
        milestone = _due_milestone(mstate)
        if milestone is None:
            return None
        import market_hours
        import phase20_store as store
        day_ist = market_hours.now_ist().strftime("%Y-%m-%d")

        results: Dict[str, Any] = {}
        skipped = []
        for suite in SUITES:
            key = _claim_key(day_ist, milestone, suite)
            if not store.kv_claim_once(key):
                skipped.append(suite)
                continue
            try:
                result = _run_suite(suite)
            except Exception as exc:   # defensive; _run_suite captures
                result = {"verdict": "ERROR", "error": str(exc)[:200]}
            results[suite] = result
            if str(result.get("verdict") or "").upper() == "ERROR":
                # The suite did not complete/persist — release its claim so
                # the next tick retries it (completed suites stay claimed).
                try:
                    store.kv_release(key)
                except Exception:
                    pass

        if not results:
            return {"ran": False, "milestone": milestone,
                    "reason": "already ran this milestone"}
        notified = _notify_failures(milestone, day_ist, results)
        return {"ran": True, "milestone": milestone, "day": day_ist,
                "results": results, "skipped": skipped,
                "notified": notified}
    except Exception as exc:          # never break the scheduler tick
        return {"ran": False, "error": str(exc)[:200]}
