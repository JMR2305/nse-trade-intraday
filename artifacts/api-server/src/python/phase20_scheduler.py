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

import os
import socket
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import phase20_store as store

try:
    from phase3f_logging import get_logger as _get_logger
    _log = _get_logger("phase20_scheduler")
except Exception:
    _log = None

# Stable identity of THIS scheduler process (Autoscale instance visibility).
_OWNER = f"{socket.gethostname()}:{os.getpid()}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_due_iso(interval_min: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=interval_min)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _perf_class(duration_s: float) -> str:
    """Classify scheduled-scan performance for monitoring/UI."""
    if duration_s > 300:
        return "DEGRADED"
    if duration_s > 120:
        return "WARNING"
    return "NORMAL"


def _run_meta_from_snapshot(snap: Dict[str, Any], trigger: str,
                            duration_s: float) -> Dict[str, Any]:
    health = snap.get("provider_health") or {}
    safety = snap.get("safety") or {}
    audit = snap.get("scan_audit") or {}
    return {
        "timings": snap.get("timings") or None,
        "perf": _perf_class(duration_s),
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


def _maybe_run_eod_reconciliation() -> Any:
    """Run EOD broker reconciliation once per day after market close.

    Delegated to eod_reconciliation.run_eod_reconciliation() which has its
    own per-day KV guard and EOD-window check. Never raises — failures are
    captured and returned as a status dict.
    """
    try:
        from eod_reconciliation import run_eod_reconciliation
        result = run_eod_reconciliation(trigger="eod")
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300]}


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
        out = {"generated": True, "date": today_ist,
               "files": result.get("files", []),
               "warnings": result.get("warnings", [])}
        p22_report = None
        try:  # Phase 22 daily close report (JSON/CSV/PDF)
            from phase22_report import export_daily_report
            p22 = export_daily_report()
            out["phase22_files"] = p22.get("files", [])
            p22_report = p22.get("report")
        except Exception as exc:
            out["phase22_error"] = str(exc)[:200]
        try:  # Opt-in daily performance summary email (never breaks the tick)
            from email_alerts import maybe_send_daily_summary_email
            if p22_report is None:
                try:
                    from phase22_report import build_daily_report
                    p22_report = build_daily_report()
                except Exception:
                    p22_report = None
            out["summary_email"] = maybe_send_daily_summary_email(p22_report)
        except Exception as exc:
            out["summary_email"] = {"sent": False, "reason": "ERROR",
                                    "error": str(exc)[:200]}
        return out
    except Exception as exc:  # report generation must never break the tick
        return {"generated": False, "error": str(exc)[:200]}


COVERAGE_ALERT_GRACE_MIN = 15          # minutes after 09:15 IST open
# Per-shortfall alert guard: kv_claim_once("coverage_alert:<day>:<sig>") —
# atomic, so each shortfall signature alerts exactly once per session even
# across concurrent Autoscale ticks, and A→B→A never re-alerts A.
_COVERAGE_LAST_KV_KEY = "coverage_alert_last"   # most recent alert claim key


def _maybe_alert_low_coverage(mstate: str) -> Any:
    """Raise a deduplicated operator notification when scanner coverage is
    still below the expected universe well into the session.

    Rules (validation-of-recovery, all judged by scanner_coverage.coverage_probe):
    * Only during the OPEN session, and only after a grace period
      (COVERAGE_ALERT_GRACE_MIN minutes past 09:15 IST market open) so the
      normal Monday self-recovery has a chance to happen first.
    * At most ONE alert per session per shortfall signature (KV-guarded,
      durable across process restarts). A DIFFERENT shortfall in the same
      session (e.g. new missing symbols) may alert again.
    * When a later scan reaches full coverage, a one-time INFO "recovered"
      notification resolves the alert.
    Never raises. Returns a small status dict (or None when idle).
    """
    if mstate != "OPEN":
        return None
    try:
        import market_hours
        from scanner_coverage import coverage_probe

        now = market_hours.now_ist()
        open_dt = now.replace(hour=market_hours.MARKET_OPEN.hour,
                              minute=market_hours.MARKET_OPEN.minute,
                              second=0, microsecond=0)
        grace_end = open_dt + timedelta(minutes=COVERAGE_ALERT_GRACE_MIN)
        if now < grace_end:
            return {"checked": False, "reason": "within grace period"}

        probe = coverage_probe()
        if not probe.get("in_session"):
            return {"checked": False, "reason": "not in session"}
        today = now.strftime("%Y-%m-%d")

        if probe.get("ok"):
            # Coverage OK — resolve the most recent alert exactly once
            # (atomic claim; a NEW alert later re-arms recovery because it
            # rewrites the last-alert key).
            prev = str(store.kv_get(_COVERAGE_LAST_KV_KEY) or "")
            if prev.startswith(f"coverage_alert:{today}:") and \
                    store.kv_claim_once("resolved:" + prev):
                store.add_notification(
                    kind="DATA_QUALITY_RECOVERED",
                    title="Scanner coverage recovered",
                    body=(f"Coverage is back to "
                          f"{probe.get('coverage')}/"
                          f"{probe.get('min_symbols_expected')} symbols "
                          f"(scan {probe.get('scan_id') or 'unknown'})."),
                    severity="INFO",
                    context={"coverage": probe.get("coverage"),
                             "scan_id": probe.get("scan_id")},
                )
                return {"checked": True, "ok": True, "resolved": True}
            return {"checked": True, "ok": True}

        # Shortfall signature: distinguishes "no fresh scan" from specific
        # missing-symbol sets so each distinct problem alerts once.
        missing = sorted(str(s) for s in probe.get("missing_symbols") or [])
        if not probe.get("scan_fresh_for_session"):
            sig = "no-fresh-scan"
        elif missing:
            sig = "missing:" + ",".join(missing)[:200]
        else:
            sig = f"coverage:{probe.get('coverage')}"
        claim_key = f"coverage_alert:{today}:{sig}"

        # Atomic once-per-session-per-shortfall claim (cross-process safe).
        if not store.kv_claim_once(claim_key):
            return {"checked": True, "ok": False, "alerted": False,
                    "reason": "already alerted this session"}
        store.kv_set(_COVERAGE_LAST_KV_KEY, claim_key)
        store.add_notification(
            kind="DATA_QUALITY_CRITICAL",
            title=(f"Scanner coverage still "
                   f"{probe.get('coverage') if probe.get('coverage') is not None else '?'}"
                   f"/{probe.get('min_symbols_expected')} after market open"),
            body=(str(probe.get("warning") or "Coverage below expected "
                      "universe during market hours.")
                  + f" (checked {COVERAGE_ALERT_GRACE_MIN}+ min after "
                    "09:15 IST open)"),
            severity="CRITICAL",
            context={"coverage": probe.get("coverage"),
                     "expected": probe.get("min_symbols_expected"),
                     "missing_symbols": missing,
                     "scan_id": probe.get("scan_id"),
                     "scan_fresh_for_session":
                         probe.get("scan_fresh_for_session"),
                     "signature": sig},
        )
        return {"checked": True, "ok": False, "alerted": True,
                "signature": sig}
    except Exception as exc:            # never break the scheduler tick
        return {"checked": False, "error": str(exc)[:200]}


def _maybe_run_live_validation(mstate: str) -> Any:
    """Phase 26B live validation, delegated to phase26_live_monitor (which
    holds the 5-minute KV bucket guard). Never raises."""
    try:
        from phase26_live_monitor import maybe_run_live_validation
        return maybe_run_live_validation(mstate)
    except Exception as exc:
        return {"ran": False, "error": str(exc)[:200]}

def _maybe_run_phase26c_validation(mstate: str) -> Any:
    """Phase 26C recovery/performance/quality suites at session milestones
    (once after open, once after close — atomic KV claim). Delegated to
    phase26c_scheduler. Never raises."""
    try:
        from phase26c_scheduler import maybe_run_session_validation
        return maybe_run_session_validation(mstate)
    except Exception as exc:
        return {"ran": False, "error": str(exc)[:200]}
def _live_validation_brief(lv: Any) -> Any:
    """Keep the tick output small — full snapshot lives in the store."""
    if not isinstance(lv, dict):
        return lv
    if not lv.get("ran"):
        return lv
    return {"ran": True, "verdict": lv.get("verdict"),
            "snapshot_id": lv.get("snapshot_id"),
            "subsystem_counts": lv.get("subsystem_counts"),
            "issue_count": len(lv.get("issues") or [])}


def run_tick() -> Dict[str, Any]:
    """One scheduler tick. Returns a JSON-safe result dict."""
    settings = store.get_settings()
    interval_min = int(settings.get("scan_interval_minutes", 5))
    now_iso = _iso_now()

    if not settings.get("auto_scan_enabled", True):
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="DISABLED",
            detail="Auto scan disabled in settings",
            owner=_OWNER, heartbeat_at=now_iso,
        )
        return {"success": True, "ran_scan": False, "reason": "Auto scan disabled"}

    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()

    # ── Daily session initialisation (pre-market + OPEN fallback) ────────────
    # Runs once per trading day before the first scan.  Idempotent.
    # Handles: portfolio archive, ₹50K capital reset, auto_paper_entries ON,
    # agent warm-start, and Mode B top-up check.
    session_init: Any = None
    try:
        from daily_session_manager import check_and_maybe_initialize
        session_init = check_and_maybe_initialize(mstate)
    except Exception as exc:
        session_init = {"error": str(exc)[:200]}

    if mstate != "OPEN":
        report = _maybe_generate_session_report(mstate)
        eod_recon = _maybe_run_eod_reconciliation() if mstate == "CLOSED" else None
        # Phase 26C: close-of-session validation milestone (recovery /
        # performance / quality), exactly once per suite per IST trading
        # day — triggered from POST_CLOSE (15:30 IST) so results are
        # persisted BEFORE the first CLOSED tick builds the one-shot 26D
        # daily report; CLOSED also accepted as catch-up. Never raises.
        p26c = _maybe_run_phase26c_validation(mstate) \
            if mstate in ("POST_CLOSE", "CLOSED") else None
        # Phase 26D: daily validation report, once per IST trading day
        # post-close (KV claim taken only right before persisting, so a
        # build failure retries next tick). Never raises.
        p26d_daily = None
        if mstate == "CLOSED":
            try:
                from phase26_reports import maybe_generate_daily_report
                p26d_daily = maybe_generate_daily_report(mstate)
            except Exception as exc:
                p26d_daily = {"generated": False, "error": str(exc)[:200]}
        # Phase 24: KV-guarded daily learning run (advisory only, never raises)
        p24_learning = None
        if mstate == "CLOSED":
            try:
                from phase24_recommendations import maybe_run_daily_learning
                p24_learning = maybe_run_daily_learning()
            except Exception as exc:
                p24_learning = {"ran": False, "error": str(exc)[:200]}
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="IDLE",
            detail=f"Market not open (state={mstate or 'UNKNOWN'})",
            owner=_OWNER, heartbeat_at=now_iso,
        )
        out: Dict[str, Any] = {"success": True, "ran_scan": False,
                               "reason": f"Market not open (state={mstate or 'UNKNOWN'})",
                               "market": mstat}
        if session_init is not None:
            out["session_init"] = session_init
        if report is not None:
            out["session_report"] = report
        if eod_recon is not None:
            out["eod_reconciliation"] = eod_recon
        if p24_learning is not None:
            out["phase24_learning"] = p24_learning
        if p26d_daily is not None:
            out["phase26d_daily_report"] = p26d_daily
        if p26c is not None:
            out["phase26c_validation"] = p26c
        return out

    # Coverage watchdog: alert operators automatically (dedup per session)
    # when coverage is still short well after open. Never raises.
    coverage_alert = _maybe_alert_low_coverage(mstate)

    # Phase 26B: live subsystem + consistency validation snapshot, once per
    # 5-minute bucket (atomic KV claim, cross-process safe). Never raises.
    live_validation = _maybe_run_live_validation(mstate)

    # Phase 26C: in-session validation milestone (recovery/performance/
    # quality), once per day after the post-open grace period. Never raises.
    p26c_session = _maybe_run_phase26c_validation(mstate)

    from phase15_scan_context import scan_age_seconds
    age = scan_age_seconds()
    if age is not None and age < interval_min * 60:
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="FRESH",
            next_due_at=_next_due_iso(max(1, int(interval_min - age / 60))),
            detail=f"Snapshot fresh ({round(age)}s old, interval {interval_min}m)",
            owner=_OWNER, heartbeat_at=now_iso,
        )
        result: Dict[str, Any] = {
            "success": True, "ran_scan": False,
            "reason": f"Snapshot fresh ({round(age)}s old, interval {interval_min}m)",
        }
        result["paper"] = _manage_paper(settings, ran_scan=False)
        if coverage_alert is not None:
            result["coverage_alert"] = coverage_alert
        if live_validation is not None:
            result["live_validation"] = _live_validation_brief(live_validation)
        if p26c_session is not None:
            result["phase26c_validation"] = p26c_session
        return result

    store.update_scheduler_state(last_attempt_at=now_iso, status="SCANNING",
                                 detail="Scheduled scan starting",
                                 owner=_OWNER, heartbeat_at=now_iso,
                                 last_trigger="SCHEDULED")
    t0 = time.time()
    try:
        from live_scan_engine import get_or_run_scan
        snap = get_or_run_scan(max_age_s=interval_min * 60, force=False,
                               wait_for_lock=False)
        duration = time.time() - t0

        if snap.get("_scan_lock_busy"):
            # Another instance is mid-scan. Record the skip (concurrency
            # safety evidence) and return immediately — never poll, never
            # start a second scan.
            store.record_scan_run({
                "scan_id": None, "trigger_source": "SCHEDULED",
                "started_at": now_iso, "completed_at": _iso_now(),
                "duration_s": round(duration, 2),
                "status": "SKIPPED_ACTIVE_SCAN", "error": None,
            })
            try:
                store.kv_set("scan_skipped_active_count",
                             int(store.kv_get("scan_skipped_active_count") or 0) + 1)
            except Exception:
                pass
            store.update_scheduler_state(
                last_attempt_at=now_iso, status="BUSY",
                detail="Skipped — another scan is already running",
                owner=_OWNER, heartbeat_at=_iso_now(),
                last_trigger="SCHEDULED",
            )
            busy_out: Dict[str, Any] = {
                "success": True, "ran_scan": False,
                "reason": "SKIPPED_ACTIVE_SCAN — another scan in progress"}
            if coverage_alert is not None:
                busy_out["coverage_alert"] = coverage_alert
            if live_validation is not None:
                busy_out["live_validation"] = \
                    _live_validation_brief(live_validation)
            if p26c_session is not None:
                busy_out["phase26c_validation"] = p26c_session
            return busy_out

        ran = not snap.get("_from_cache", False)
        pipeline = None
        if ran:
            store.record_scan_run(_run_meta_from_snapshot(snap, "SCHEDULED", duration))
            # Phase 22 — regenerate EVERY scan-derived dataset from this exact
            # scan_id, validate consistency, atomically publish the bundle.
            try:
                from scan_pipeline import run_post_scan_pipeline
                pipeline = run_post_scan_pipeline(snap, trigger="SCHEDULED")
            except Exception as exc:
                pipeline = {"status": "FAILED", "error": str(exc)[:300]}
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
            owner=_OWNER, heartbeat_at=_iso_now(),
            last_trigger="SCHEDULED", last_error=None,
        )
        result = {"success": True, "ran_scan": ran,
                  "scan_id": snap.get("scan_id"),
                  "snapshot_ts": snap.get("snapshot_ts"),
                  "duration_s": round(duration, 2)}
        if pipeline is not None:
            result["pipeline"] = {
                "status": pipeline.get("status"),
                "failed_modules": pipeline.get("failed_modules"),
            }
        result["paper"] = _manage_paper(settings, ran_scan=ran)
        if coverage_alert is not None:
            result["coverage_alert"] = coverage_alert
        if live_validation is not None:
            result["live_validation"] = _live_validation_brief(live_validation)
        if p26c_session is not None:
            result["phase26c_validation"] = p26c_session
        # ── RC-10C1: scheduled portfolio reconciliation after each scan tick.
        # Fail-open — reconcile_now() never raises; it returns an error dict.
        if ran:
            try:
                import portfolio_bridge
                result["portfolio_reconciliation"] = portfolio_bridge.reconcile_now()
            except Exception as exc:
                result["portfolio_reconciliation"] = {"error": str(exc)[:200]}
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
            owner=_OWNER, heartbeat_at=_iso_now(),
            last_trigger="SCHEDULED", last_error=str(exc)[:300],
        )
        store.add_notification(
            "SCAN_FAILED", "Scheduled scan failed",
            str(exc)[:500], severity="ERROR",
        )
        fail_out: Dict[str, Any] = {
            "success": True, "ran_scan": False, "error": str(exc)[:300],
            "reason": "Scan failed — previous snapshot preserved"}
        if coverage_alert is not None:
            fail_out["coverage_alert"] = coverage_alert
        if live_validation is not None:
            fail_out["live_validation"] = \
                _live_validation_brief(live_validation)
        if p26c_session is not None:
            fail_out["phase26c_validation"] = p26c_session
        return fail_out


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
    # Circuit breaker: evaluate after exits so a loss that just closed can
    # pause new entries on this very tick. Never auto-resumes. Exits,
    # monitoring, scheduling, and evidence collection stay active regardless.
    try:
        from phase20_circuit_breaker import evaluate_and_maybe_trip
        cb = evaluate_and_maybe_trip(settings)
        out["circuit_breaker"] = {"tripped": bool(cb.get("tripped")),
                                  "tripped_at": cb.get("tripped_at"),
                                  "reasons": cb.get("reasons") or []}
    except Exception as exc:
        out["circuit_breaker"] = {"error": str(exc)[:200]}
    # Performance-degradation alerts (advisory only — losing streak / low
    # win rate). Notifies via the notification system; never blocks entries.
    try:
        from performance_alerts import evaluate_and_notify
        out["performance_alerts"] = evaluate_and_notify(settings)
    except Exception as exc:
        out["performance_alerts"] = {"error": str(exc)[:200]}
    try:
        if settings.get("auto_paper_entries") and settings.get("auto_paper_entries_confirmed_at"):
            from phase20_executor import run_auto_entries
            out["entries"] = run_auto_entries(settings)
        else:
            out["entries"] = {"skipped": "auto_paper_entries OFF (default)"}
    except Exception as exc:
        out["entries"] = {"error": str(exc)[:200]}
    # ── Phase 22 evidence accumulation (records ALL candidates, opened AND
    # blocked, regardless of automation state; time-safe outcome updates).
    try:
        entries = out.get("entries") or {}
        if isinstance(entries, dict) and entries.get("ran"):
            # Evidence for the EXACT evaluation payload the entry run used —
            # never a second evaluation pass (avoids decision-set drift).
            from phase22_evidence import record_candidates
            evaluation = entries.get("evaluation")
            if evaluation:
                out["evidence"] = record_candidates(
                    evaluation, created=entries.get("created") or [])
        elif ran_scan:
            # Automation OFF — still record candidate evidence for the fresh
            # scan (research only, no trades are created here).
            from phase20_gates import evaluate_entries
            from phase22_evidence import record_candidates
            out["evidence"] = record_candidates(evaluate_entries())
    except Exception as exc:
        out["evidence"] = {"error": str(exc)[:200]}
    try:
        from phase22_evidence import update_outcomes
        out["evidence_outcomes"] = update_outcomes()
    except Exception as exc:
        out["evidence_outcomes"] = {"error": str(exc)[:200]}
    # ── Continuous Research Mode (Mode B) top-up ─────────────────────────────
    # Apply a capital top-up if the operator has selected Mode B and cash has
    # fallen below the configured threshold. Advisory-only; never places a
    # live order. Idempotent per threshold crossing.
    try:
        from phase11_autonomous import check_and_apply_topup
        topup = check_and_apply_topup()
        if topup:
            out["crm_topup"] = topup
    except Exception as exc:
        out["crm_topup"] = {"error": str(exc)[:200]}
    return out
