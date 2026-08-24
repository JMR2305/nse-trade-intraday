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
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import phase20_store as store

try:
    from phase3f_logging import get_logger as _get_logger
    _log = _get_logger("phase20_scheduler")
except Exception:
    _log = None

# Stable identity of THIS scheduler process (Autoscale instance visibility).
_OWNER = f"{socket.gethostname()}:{os.getpid()}"
_IST = ZoneInfo("Asia/Kolkata")
_PREMARKET_READINESS_START = (8, 45)
_PREMARKET_READINESS_END = (9, 5)


def _persist_seal_result(
    seal_result: Dict[str, Any],
    scan_id: str,
    reason: str,
) -> None:
    """Durably store the last execution-seal result for the dashboard.

    Idempotency guard
    -----------------
    ``seal_execution_outcomes`` is idempotent: a second call for the same
    scan_id returns ``sealed=0`` because the orphans were already handled.
    Without a guard, the POST_CLOSE tick (or a repeated OPEN tick) would
    overwrite a stored ``sealed=2`` record with a misleading ``sealed=0``,
    making the dashboard silently show the healthy state while orphans *were*
    present.

    We advance the stored record only when:
    • A genuinely new ``scan_id`` appears (fresh session / clean scan).
    • This call sealed orphans (``sealed > 0``).
    • An error state must be recorded (never silently show zero on failure).

    Notification
    ------------
    Fires an INFO notification once per scan_id (via ``kv_claim_once``) when
    orphans were sealed and no error occurred.  Never raises — all failures are
    swallowed so the scheduler tick cannot be blocked by a persistence glitch.
    """
    try:
        n_sealed = int(seal_result.get("sealed") or 0)
        seal_error = seal_result.get("error")

        existing_kv: Dict[str, Any] = store.kv_get("last_execution_seal") or {}
        is_new_scan = scan_id != existing_kv.get("scan_id")

        if is_new_scan or n_sealed > 0 or seal_error:
            record: Dict[str, Any] = {
                "sealed":      n_sealed,
                "scan_id":     seal_result.get("scan_id"),
                "orphans":     seal_result.get("orphans", []),
                "reason":      reason,
                "recorded_at": _iso_now(),
            }
            if seal_error:
                record["error"] = seal_error
            store.kv_set("last_execution_seal", record)

        if n_sealed > 0 and not seal_error:
            _notify_key = f"orphan_seal_notified:{scan_id}"
            if store.kv_claim_once(_notify_key):
                store.add_notification(
                    "EXECUTION_ORPHANS_SEALED",
                    f"{n_sealed} BUY signal(s) sealed at session end",
                    (f"Scan {scan_id}: "
                     f"{', '.join(seal_result.get('orphans', [])[:5])}"
                     f" had no execution outcome and were automatically "
                     f"sealed as SKIPPED. Investigate if this count "
                     f"grows unexpectedly across sessions."),
                    severity="INFO",
                    context={"scan_id":  scan_id,
                             "sealed":   n_sealed,
                             "orphans":  seal_result.get("orphans", [])},
                )
    except Exception:
        pass


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


def _entry_execution_allowed(job_type: str, market_state: str) -> bool:
    """Only in-session scheduled market scans may reach paper-entry execution."""
    return job_type == "MARKET_SCAN" and market_state == "OPEN"


def _job_meta(
    *,
    job_type: str,
    scan_type: str,
    trigger: str,
    market_state: str,
    started_at: str,
    completed_at: Optional[str] = None,
    duration_s: Optional[float] = None,
    status: str = "SUCCESS",
    source: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """One canonical, append-only metadata contract for displayed jobs."""
    allowed = _entry_execution_allowed(job_type, market_state)
    return {
        "job_type": job_type,
        "scan_type": scan_type,
        "trigger_source": trigger,
        "source": source or trigger,
        "market_state": market_state or "UNKNOWN",
        "entry_eligible": allowed,
        "execution_eligible": allowed,
        "started_at": started_at,
        "completed_at": completed_at or _iso_now(),
        "duration_s": round(float(duration_s or 0), 2),
        "status": status,
        "details": details or {},
        **fields,
    }


def _run_meta_from_snapshot(snap: Dict[str, Any], trigger: str,
                            duration_s: float,
                            market_state: str = "OPEN",
                            job_type: str = "MARKET_SCAN") -> Dict[str, Any]:
    health = snap.get("provider_health") or {}
    safety = snap.get("safety") or {}
    audit = snap.get("scan_audit") or {}
    return _job_meta(
        job_type=job_type,
        scan_type="CANONICAL",
        trigger=trigger,
        market_state=market_state,
        source=trigger,
        started_at=snap.get("snapshot_ts") or _iso_now(),
        completed_at=audit.get("scan_completed_ts") or snap.get("snapshot_ts") or _iso_now(),
        duration_s=duration_s,
        status="SUCCESS",
        timings=snap.get("timings") or None,
        perf=_perf_class(duration_s),
        scan_id=snap.get("scan_id"),
        symbols_requested=health.get("symbols_requested"),
        symbols_received=health.get("symbols_succeeded"),
        missing_symbols=list(health.get("unavailable_symbols") or []),
        stale_symbols=list(health.get("stale_symbols") or []),
        unavailable_symbols=list(health.get("unavailable_symbols") or []),
        provider=safety.get("data_provider") or health.get("provider"),
        error=None,
    )


def record_manual_scan(snap: Dict[str, Any], duration_s: float = 0.0) -> None:
    """Record a MANUAL scan run (called from the phase7_scan CLI path)."""
    try:
        from market_hours import market_status
        mstate = str((market_status() or {}).get("state") or "UNKNOWN").upper()
        # Manual scans are diagnostic evidence. They never grant scheduler
        # entry/execution eligibility, including when an operator runs one
        # during an open market.
        record = _run_meta_from_snapshot(
            snap, "MANUAL", duration_s, market_state=mstate, job_type="MANUAL_SCAN")
        record["entry_eligible"] = False
        record["execution_eligible"] = False
        store.record_scan_run(record)
    except Exception:
        pass


def record_system_job(
    job_type: str,
    *,
    market_state: str,
    trigger: str,
    started_at: str,
    duration_s: float,
    status: str,
    details: Optional[Dict[str, Any]] = None,
    symbols_requested: Optional[int] = None,
    symbols_received: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Append a non-market operator job without coupling it to pipeline events."""
    store.record_scan_run(_job_meta(
        job_type=job_type,
        scan_type="NON_MARKET",
        trigger=trigger,
        source=trigger,
        market_state=market_state,
        started_at=started_at,
        duration_s=duration_s,
        status=status,
        details=details,
        symbols_requested=symbols_requested,
        symbols_received=symbols_received,
        error=error,
    ))


def _maybe_record_heartbeat(mstate: str, reason: str) -> None:
    """Record one non-trading heartbeat per 15-minute IST bucket."""
    now = datetime.now(_IST)
    bucket = now.minute // 15
    key = f"system_heartbeat:{now.date().isoformat()}:{now.hour:02d}:{bucket}"
    try:
        if store.kv_claim_once(key):
            started = _iso_now()
            record_system_job(
                "SYSTEM_HEARTBEAT", market_state=mstate, trigger="SCHEDULER",
                started_at=started, duration_s=0, status="SUCCESS",
                details={"reason": reason, "owner": _OWNER},
            )
    except Exception:
        pass


def _maybe_run_premarket_readiness(mstate: str) -> Optional[Dict[str, Any]]:
    """Run exactly one readiness check in the 08:45–09:05 IST window."""
    now = datetime.now(_IST)
    minute = now.hour * 60 + now.minute
    start = _PREMARKET_READINESS_START[0] * 60 + _PREMARKET_READINESS_START[1]
    end = _PREMARKET_READINESS_END[0] * 60 + _PREMARKET_READINESS_END[1]
    if not (start <= minute < end):
        return None
    try:
        from market_hours import is_trading_day
        if not is_trading_day(now.date()):
            return None
        key = f"premarket_readiness:{now.date().isoformat()}"
        if not store.kv_claim_once(key):
            return None
        t0 = time.monotonic()
        started = _iso_now()
        from pre_market_data_readiness import run_pre_market_readiness_check
        result = run_pre_market_readiness_check()
        verdict = str(result.get("verdict") or "UNKNOWN")
        record_system_job(
            "PREMARKET_READINESS_CHECK", market_state=mstate, trigger="SCHEDULER",
            started_at=started, duration_s=time.monotonic() - t0,
            status="SUCCESS" if verdict.startswith("READY") else "FAILED",
            details=result,
        )
        return result
    except Exception as exc:
        record_system_job(
            "PREMARKET_READINESS_CHECK", market_state=mstate, trigger="SCHEDULER",
            started_at=_iso_now(), duration_s=0, status="FAILED",
            error=str(exc), details={"error": str(exc)[:300]},
        )
        return {"verdict": "BLOCKED", "error": str(exc)[:300]}


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


def _custom_low_price_universe_enabled() -> bool:
    """Avoid importing refresh dependencies unless the opt-in mode is active."""
    try:
        from config import get_active_intraday_universe, UniverseMode
        return get_active_intraday_universe() == UniverseMode.CUSTOM_LOW_PRICE_SECTOR
    except Exception:
        return False


def _maybe_refresh_low_price_universe_pre_market() -> Optional[Dict[str, Any]]:
    """Run the custom-universe refresh once in the 08:45–09:05 IST window."""
    if not _custom_low_price_universe_enabled():
        return None
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        minutes = now.hour * 60 + now.minute
        if not (8 * 60 + 45 <= minutes <= 9 * 60 + 5):
            return None
        claim = f"low_price_sector_universe_preopen:{now.date().isoformat()}"
        if not store.kv_claim_once(claim, ttl_seconds=86_400):
            return {"ran": False, "reason": "already_refreshed_today"}
        # Import only after configuration/time/claim gates so normal NIFTY mode
        # never pays refresh import cost.
        from low_price_universe_refresh import refresh_low_price_sector_universe
        result = refresh_low_price_sector_universe()
        if not result.get("success"):
            # A failed refresh must not consume the daily work slot; a later
            # tick can retry after the cache/database recovers.
            store.kv_release(claim)
        return {"ran": True, **result}
    except Exception as exc:
        try:
            store.kv_release(claim)
        except Exception:
            pass
        return {"ran": False, "error": str(exc)[:200]}


def _maybe_refresh_low_price_universe_after_scan() -> Optional[Dict[str, Any]]:
    """Apply the session's first observed prices after the first successful scan."""
    if not _custom_low_price_universe_enabled():
        return None
    try:
        today = _today_ist_date()
        claim = f"low_price_sector_universe_postscan:{today}"
        if not store.kv_claim_once(claim, ttl_seconds=86_400):
            return {"ran": False, "reason": "already_refreshed_after_scan"}
        from low_price_universe_refresh import refresh_low_price_sector_universe
        result = refresh_low_price_sector_universe()
        if not result.get("success"):
            store.kv_release(claim)
        return {"ran": True, **result}
    except Exception as exc:
        try:
            store.kv_release(claim)
        except Exception:
            pass
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


def check_overnight_carry_on_startup() -> Dict[str, Any]:
    """Cold-start safety net: close OPEN positions that carried overnight.

    The POST_CLOSE_FORCE_EXIT scheduler block fires only when the server is
    running during POST_CLOSE/CLOSED state (15:30–18:00 IST).  If the server
    was down or restarted at exactly 15:30 IST, the ``eod_squareoff:<date>``
    KV claim for that day was never taken, and any OPEN paper positions would
    silently carry into the next trading session without any warning.

    This function runs once per IST calendar day (guarded by its own
    ``startup_overnight_check:<today>`` KV claim so multiple Autoscale
    instances or rapid restarts don't trigger duplicate cleanups).

    On each cold-start it checks whether *yesterday's* eod_squareoff claim
    was taken.  If not:

      1. Emits ``MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED`` pipeline event for
         each OPEN trade whose fill_ts predates today's IST trading day.
      2. Fires :func:`phase20_exits.eod_force_close_open_positions` to
         close those positions regardless of the current market state.
      3. Claims the ``eod_squareoff:<yesterday>`` key so the normal
         POST_CLOSE tick is a no-op for that date if the server stays up
         into the evening.

    Returns a JSON-safe result dict.  Never raises — all failures are caught
    and returned as ``{"ran": False, "error": ...}``.
    """
    try:
        from zoneinfo import ZoneInfo
        _IST = ZoneInfo("Asia/Kolkata")
        import datetime as _dt
        now_ist = _dt.datetime.now(_IST)
        today_ist = now_ist.date().isoformat()
        yesterday_ist = (now_ist.date() - timedelta(days=1)).isoformat()
    except Exception as exc:
        return {"ran": False, "error": f"timezone init: {str(exc)[:200]}"}

    # Exactly-once per IST calendar day (cross-process, Autoscale-safe).
    _startup_claim_key = f"startup_overnight_check:{today_ist}"
    if not store.kv_claim_once(_startup_claim_key):
        return {"ran": False, "reason": "already_ran_today"}

    try:
        # kv_claim_once stores True on claim; kv_get returns True if claimed.
        _eod_key = f"eod_squareoff:{yesterday_ist}"
        _retry_key = f"eod_squareoff_unresolved:{yesterday_ist}"
        _eod_claimed = bool(store.kv_get(_eod_key))

        if _eod_claimed:
            # Normal case: EOD force-exit ran yesterday. Nothing to do.
            return {"ran": True, "eod_claimed": True,
                    "reason": "eod_squareoff_ran_yesterday",
                    "yesterday": yesterday_ist}

        # An earlier cold-start may have recorded an unresolved audit write.
        # Retry only that write; do not re-submit a sell for positions whose
        # original close-window outcome was already persisted.
        retry_outcomes = store.kv_get(_retry_key)
        if isinstance(retry_outcomes, list) and retry_outcomes:
            from phase20_store import get_settings as _ls
            from phase20_exits import eod_force_close_open_positions
            eod_result = eod_force_close_open_positions(
                _ls(), session_date=yesterday_ist, retry_outcomes=retry_outcomes,
            )
            unresolved = list((eod_result or {}).get("unresolved") or [])
            if unresolved:
                store.kv_set(_retry_key, unresolved)
                store.kv_release(_startup_claim_key)
            else:
                store.kv_release(_retry_key)
                store.kv_claim_once(_eod_key, ttl_seconds=86400)
            return {
                "ran": True, "eod_claimed": False, "yesterday": yesterday_ist,
                "prior_session_count": 0, "symbols": [],
                "eod_force_close": eod_result, "retryable": bool(unresolved),
            }

        # Yesterday's EOD squareoff was never claimed — server was likely
        # down during the POST_CLOSE/CLOSED window.  Check for OPEN positions.
        from phase20_executor import get_all_open_trades
        open_trades = get_all_open_trades()

        if not open_trades:
            # No OPEN positions — mark yesterday's EOD as complete so the
            # normal POST_CLOSE tick is a no-op if the state rotates later.
            store.kv_claim_once(_eod_key, ttl_seconds=86400)
            return {"ran": True, "eod_claimed": False, "open_count": 0,
                    "reason": "no_open_positions",
                    "yesterday": yesterday_ist}

        # Filter to prior-session trades (fill_ts before today IST).
        try:
            from zoneinfo import ZoneInfo as _ZI
            _ist2 = _ZI("Asia/Kolkata")
        except Exception:
            _ist2 = None

        prior_session_trades = []
        for t in open_trades:
            fill_ts_str = str(t.get("fill_ts") or "")
            if not fill_ts_str:
                # No fill_ts — conservatively treat as a prior-session trade.
                prior_session_trades.append(t)
                continue
            try:
                fill_dt = datetime.fromisoformat(
                    fill_ts_str.replace("Z", "+00:00"))
                fill_date_ist = (
                    fill_dt.astimezone(_ist2).date().isoformat()
                    if _ist2 else fill_dt.date().isoformat()
                )
                if fill_date_ist < today_ist:
                    prior_session_trades.append(t)
            except Exception:
                # Malformed timestamp — treat conservatively as prior-session.
                prior_session_trades.append(t)

        if not prior_session_trades:
            # All open trades were opened in today's session — not overnight.
            return {"ran": True, "eod_claimed": False,
                    "open_count": len(open_trades),
                    "prior_session_count": 0,
                    "reason": "no_prior_session_trades",
                    "yesterday": yesterday_ist}

        # Emit MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED for each prior-session
        # trade so the event appears in the pipeline dashboard.
        carry_symbols = [str(t.get("symbol") or "") for t in prior_session_trades]
        for trade in prior_session_trades:
            sym = str(trade.get("symbol") or "").upper()
            trade_id = str(trade.get("trade_id") or "")
            try:
                from pipeline_events import emit as _pe
                _pe("MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED", "PORTFOLIO",
                    symbol=sym,
                    payload={
                        "trade_id": trade_id,
                        "fill_ts": trade.get("fill_ts"),
                        "yesterday_date": yesterday_ist,
                        "today_date": today_ist,
                        "reason": (
                            "OPEN position from prior session detected at "
                            f"server cold-start — eod_squareoff was never "
                            f"claimed for {yesterday_ist}. Server was likely "
                            "down during the POST_CLOSE/CLOSED window "
                            "(15:30–18:00 IST)."
                        ),
                    })
            except Exception:
                pass

        store.add_notification(
            "MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED",
            (f"{len(prior_session_trades)} position(s) carried overnight "
             f"from {yesterday_ist}"),
            (f"Server restarted without running POST_CLOSE_FORCE_EXIT on "
             f"{yesterday_ist}. "
             f"Affected symbols: {', '.join(carry_symbols[:5])}. "
             f"Running EOD force-close now to prevent a second day of "
             f"unintended overnight exposure."),
            severity="WARN",
            context={
                "yesterday": yesterday_ist,
                "symbols": carry_symbols,
                "trade_count": len(prior_session_trades),
            },
        )

        # Run EOD force-close immediately, regardless of current mstate.
        # Process only the trades that were proven to predate today's session:
        # fresh positions must never be swept just because a server restarted.
        from phase20_store import get_settings as _ls
        from phase20_exits import eod_force_close_open_positions
        eod_result = eod_force_close_open_positions(
            _ls(), open_trades=prior_session_trades, session_date=yesterday_ist,
        )

        # A durable CLOSED or BLOCKED outcome completes the old close window.
        # An unresolved audit write does not: release the startup claim so a
        # later restart can try again instead of silently accepting a carry.
        unresolved = list((eod_result or {}).get("unresolved") or [])
        if unresolved:
            store.kv_set(_retry_key, unresolved)
            store.kv_release(_startup_claim_key)
        else:
            store.kv_release(_retry_key)
            # Claim yesterday's eod_squareoff so the normal POST_CLOSE tick
            # (if the server remains up through the evening) is a no-op.
            store.kv_claim_once(_eod_key, ttl_seconds=86400)

        return {
            "ran": True,
            "eod_claimed": False,
            "yesterday": yesterday_ist,
            "prior_session_count": len(prior_session_trades),
            "symbols": carry_symbols,
            "eod_force_close": eod_result,
            "retryable": bool(unresolved),
        }

    except Exception as exc:
        # Release the startup claim so a later cold-start can retry when
        # this was a transient error (e.g. DB temporarily unavailable at boot).
        try:
            store.kv_release(_startup_claim_key)
        except Exception:
            pass
        return {"ran": False, "error": str(exc)[:300]}


# ── Cold-start backfill constants ─────────────────────────────────────────────
# Lease TTL: how long the owner's lease is considered valid after it writes the
# lease_started record.  Set to 25 minutes — comfortably above the documented
# worst-case 22-minute yfinance bulk download — so a legitimately slow backfill
# is never incorrectly displaced by a takeover.  The owner does not need to send
# a heartbeat because the TTL already covers the entire backfill window.
_COLD_START_LEASE_TTL_S: int = 1500     # 25 minutes
# Grace period for claim-without-lease crash recovery: if claim_key exists
# but lease_started_key is absent after this many seconds, the initial owner
# likely died before writing the lease.  Peers attempt takeover after this.
_COLD_START_CLAIM_GRACE_PERIOD_S: int = 60  # 1 minute
# Non-owner wait budget.  MUST be strictly greater than _COLD_START_LEASE_TTL_S
# (plus at least one poll interval) so peers always have remaining time to read
# the expired lease and attempt a takeover before they give up.
_COLD_START_WAIT_TIMEOUT_S: int = 1800  # 30 minutes (> LEASE_TTL by 5 min)
_COLD_START_POLL_INTERVAL_S: int = 15   # check every 15 seconds


def _today_ist_date() -> str:
    """Return today's IST calendar date as YYYY-MM-DD (no external deps)."""
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    # IST = UTC+5:30
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    return now_ist.strftime("%Y-%m-%d")


def check_cold_cache_on_startup() -> Dict[str, Any]:
    """Cold-start OHLCV cache check with Autoscale-safe cross-instance coordination.

    Design
    ------
    Exactly one Autoscale instance runs the backfill; all others wait for it to
    finish before their Node-side readiness gate is cleared.

    Owner path  (kv_claim_once returns True):
      1. Probes the cache; returns no-op immediately if warm.
      2. Logs a prominent WARNING and runs backfill_all_symbols().
      3. Writes a completion record to kv so peers can stop polling.
      4. On any unhandled exception, releases the claim so a later instance
         can retry (transient failures — e.g. yfinance rate-limit).

    Non-owner path  (kv_claim_once returns False):
      * Polls the completion kv key every _COLD_START_POLL_INTERVAL_S seconds
        for up to _COLD_START_WAIT_TIMEOUT_S seconds.
      * Returns a summary derived from the completion record once it appears.
      * If the owner never writes a completion record within the timeout, returns
        a timeout result so the Node .finally() clears the gate and allows scans
        to proceed with the existing yfinance fallback.

    The Node caller (scanScheduler.ts) keeps _ohlcvColdStartPending = true while
    this function is running (Python process is blocking), clearing it only in
    .finally().  That means every Autoscale instance — owner and non-owners alike —
    defers scheduled_scan_tick until backfill is confirmed complete.

    Never raises.
    """
    import logging as _logging
    import time as _time

    _log_cc = _logging.getLogger("phase20_scheduler.cold_cache")

    today = _today_ist_date()
    claim_key         = f"ohlcv_cold_start_backfill:{today}"
    done_key          = f"ohlcv_cold_start_backfill_done:{today}"
    lease_started_key = f"ohlcv_cold_start_lease_started:{today}"
    takeover_key      = f"ohlcv_cold_start_takeover:{today}"

    # token held by THIS instance when it wins a takeover claim; used for the
    # token-conditional release so a stale instance never deletes a live peer's
    # active lease.
    _takeover_token: Optional[str] = None

    # ── 1. Load universe ──────────────────────────────────────────────────────
    try:
        from config import NIFTY_50 as _n50
        symbols = list(_n50)
    except Exception as exc:
        _log_cc.warning("check_cold_cache_on_startup: config import failed: %s", exc)
        return {"ran": False, "error": f"config import: {str(exc)[:150]}"}

    # ── 2. Load cache store ───────────────────────────────────────────────────
    try:
        from ohlcv_cache_store import (
            OHLCV_CACHE_ENABLED as _CE,
            get_overall_cache_summary,
            backfill_all_symbols,
            ensure_tables,
        )
    except Exception as exc:
        _log_cc.warning("check_cold_cache_on_startup: ohlcv_cache_store import failed: %s", exc)
        return {"ran": False, "error": f"ohlcv_cache_store import: {str(exc)[:150]}"}

    if not _CE:
        return {"ran": False, "reason": "OHLCV_CACHE_ENABLED=false"}

    ensure_tables()

    # ── 3. Probe current cache state ──────────────────────────────────────────
    try:
        summary = get_overall_cache_summary(symbols)
    except Exception as exc:
        _log_cc.warning("check_cold_cache_on_startup: cache summary failed: %s", exc)
        return {"ran": False, "error": f"cache summary: {str(exc)[:150]}"}

    total = summary.get("total_symbols", len(symbols))
    uncached = list(summary.get("uncached_symbols") or [])
    missing_bars = list(summary.get("missing_required_bars") or [])
    stale_syms = list(summary.get("stale_symbols") or [])
    cache_hit_rate = float(summary.get("cache_hit_rate_pct") or 0.0)

    # Union: symbols with no rows, fewer than MIN_BARS_REQUIRED, OR data older
    # than MAX_CACHE_AGE_DAYS (STALE / UNAVAILABLE).  read_symbol_from_cache()
    # rejects data aged > MAX_CACHE_AGE_DAYS and falls through to a live yfinance
    # download, so stale symbols must trigger a backfill on the same footing as
    # uncached ones.  get_overall_cache_summary() already classifies these under
    # "stale_symbols" (quality in STALE / UNAVAILABLE).
    cold_set = set(uncached) | set(missing_bars) | set(stale_syms)

    if not cold_set:
        # Cache is warm — return immediately without acquiring the claim.
        # Any peer that already acquired the claim for a different startup can
        # proceed normally; we just don't need to do anything.
        _log_cc.info(
            "check_cold_cache_on_startup: cache warm (hit-rate %.1f%%, %d/%d symbols). "
            "No backfill needed.",
            cache_hit_rate, total, total,
        )
        return {
            "ran": True,
            "action": "no_op",
            "reason": "cache_warm",
            "cache_hit_rate_pct": cache_hit_rate,
            "total_symbols": total,
        }

    is_fully_cold = len(uncached) == total

    # ── 4. Try to become the owner ────────────────────────────────────────────
    # Use kv_claim_with_value (not kv_claim_once) so the record embeds a
    # claimed_at timestamp that non-owners can use to detect the
    # "claim-without-lease" crash scenario (owner died before writing
    # lease_started_key).
    _claim_now_iso: str = ""
    try:
        from datetime import datetime, timezone as _tz_
        _claim_now_iso = datetime.now(_tz_).isoformat()
    except Exception:
        pass
    is_owner = store.kv_claim_with_value(claim_key, {
        "claimed_at": _claim_now_iso,
        "role": "owner",
    })

    # Track which key this instance owns so the failure handler releases the
    # right key.  "owner" → initial claimer, releases claim_key on exception.
    # "takeover" → won the expiring token lease, releases takeover_key on
    # exception (claim_key belongs to the dead first owner and must stay so
    # subsequent instances remain on the non-owner polling path).
    _owner_role = "owner"

    def _acquire_takeover_lease() -> bool:
        """Atomically acquire the takeover lease.

        Uses kv_acquire_expiring_claim so that:
        * Two concurrent peers racing for the same empty slot — only one
          wins (storage-level INSERT ON CONFLICT DO NOTHING).
        * A dead takeover owner that was SIGKILL'd (no cleanup) leaves a
          record with an expires_at.  Once that time passes, any peer can
          overwrite it with their own token via the storage-level
          UPDATE … WHERE expires_at < NOW().

        On success, sets the module-level _takeover_token so the failure
        handler can call kv_release_if_owned (token-conditional) instead of
        the unfenced kv_release.

        Returns True if this instance acquired the lease.
        """
        nonlocal _takeover_token
        try:
            import uuid as _uuid
            from datetime import datetime, timezone as _tz, timedelta as _td

            _token = str(_uuid.uuid4())
            _now = datetime.now(_tz.utc)
            _record = {
                "token": _token,
                "started_at": _now.isoformat(),
                "expires_at": (_now + _td(seconds=_COLD_START_LEASE_TTL_S)).isoformat(),
            }
            won = store.kv_acquire_expiring_claim(takeover_key, _record)
            if won:
                _takeover_token = _token
            return won
        except Exception:
            return False  # Non-fatal; treat as "did not win the lease"

    if not is_owner:
        # ── Non-owner: poll for done_key; extend deadline to cover lease TTL;
        #    attempt a fenced takeover via a separate atomic key once the owner
        #    lease has expired. ────────────────────────────────────────────────
        #
        # Design:
        # - deadline_mono starts at now + WAIT_TIMEOUT_S (30 min).
        # - While polling, if we read the lease metadata we extend deadline_mono
        #   to ensure we wait at least until (lease_expires_at + poll_interval).
        #   This prevents "timeout before TTL" when instances start together.
        # - Takeover is gated on lease_expires_at being in the past AND winning
        #   kv_claim_once(takeover_key).  Two peers both see an expired lease:
        #   only one wins the atomic kv_claim_once; the loser keeps polling.
        # - We NEVER call kv_release on the original claim_key during takeover.
        #   Releasing it unconditionally could delete a fresh claim just won by
        #   another peer.  The original claim stays; takeover_key is the new
        #   coordination point.
        _log_cc.info(
            "check_cold_cache_on_startup: another instance owns the backfill lease "
            "(%s). Waiting up to %ds for it to complete (lease TTL %ds).",
            claim_key, _COLD_START_WAIT_TIMEOUT_S, _COLD_START_LEASE_TTL_S,
        )
        deadline_mono = _time.monotonic() + _COLD_START_WAIT_TIMEOUT_S
        while _time.monotonic() < deadline_mono:
            done = store.kv_get(done_key)
            if done:
                _log_cc.info(
                    "check_cold_cache_on_startup: peer backfill complete. "
                    "Clearing readiness gate.",
                )
                return {
                    "ran": False,
                    "reason": "completed_by_peer",
                    "peer_result": done if isinstance(done, dict) else {},
                    "total_symbols": total,
                }

            lease_meta = store.kv_get(lease_started_key)
            if lease_meta and isinstance(lease_meta, dict):
                try:
                    from datetime import datetime, timezone as _tz
                    exp_iso = str(lease_meta.get("lease_expires_at") or "")
                    if exp_iso:
                        exp_dt = datetime.fromisoformat(exp_iso)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=_tz.utc)
                        exp_ts = exp_dt.timestamp()
                        now_ts = _time.time()
                        if now_ts < exp_ts:
                            # Lease still valid.  Extend our deadline so we never
                            # time out before the lease can expire.
                            needed_mono = (
                                _time.monotonic()
                                + (exp_ts - now_ts)
                                + _COLD_START_POLL_INTERVAL_S
                            )
                            if needed_mono > deadline_mono:
                                deadline_mono = needed_mono
                        else:
                            # Lease has expired and done_key is still absent —
                            # owner likely died mid-backfill.  Attempt fenced
                            # takeover using an expiring token record so a dead
                            # takeover owner (killed without running its exception
                            # handler) can also be recovered once its own expiry
                            # passes.  Two peers race here: only the one whose
                            # token survives the read-back wins.
                            _log_cc.warning(
                                "check_cold_cache_on_startup: owner lease expired "
                                "(started_at=%s, lease_ttl=%ds). Attempting "
                                "token-fenced takeover via %s.",
                                lease_meta.get("started_at"),
                                _COLD_START_LEASE_TTL_S,
                                takeover_key,
                            )
                            if _acquire_takeover_lease():
                                is_owner = True
                                _owner_role = "takeover"
                                break  # → fall through to owner block
                            # Another peer won the takeover; keep polling so we
                            # eventually see their done_key.
                except Exception:
                    pass  # Malformed lease record — treat as no expiry info
            else:
                # lease_started_key is absent: the initial owner died after
                # kv_claim_with_value but before writing its lease metadata.
                # After a grace period, treat this as a dead owner and attempt
                # takeover.  The claimed_at timestamp in the claim record
                # tells us how long ago the claim was taken.
                try:
                    from datetime import datetime, timezone as _tz
                    claim_meta = store.kv_get(claim_key)
                    if isinstance(claim_meta, dict):
                        claimed_at_iso = str(claim_meta.get("claimed_at") or "")
                        if claimed_at_iso:
                            ca_dt = datetime.fromisoformat(claimed_at_iso)
                            if ca_dt.tzinfo is None:
                                ca_dt = ca_dt.replace(tzinfo=_tz.utc)
                            elapsed = _time.time() - ca_dt.timestamp()
                            if elapsed > _COLD_START_CLAIM_GRACE_PERIOD_S:
                                _log_cc.warning(
                                    "check_cold_cache_on_startup: claim "
                                    "exists but no lease metadata after "
                                    "%.0fs (grace=%ds). Owner likely died "
                                    "before writing lease. Attempting "
                                    "takeover via %s.",
                                    elapsed,
                                    _COLD_START_CLAIM_GRACE_PERIOD_S,
                                    takeover_key,
                                )
                                if _acquire_takeover_lease():
                                    is_owner = True
                                    _owner_role = "takeover"
                                    break
                except Exception:
                    pass  # Non-fatal; keep polling

            remaining = int(deadline_mono - _time.monotonic())
            _log_cc.debug(
                "check_cold_cache_on_startup: waiting for peer backfill "
                "(%ds remaining)...", max(0, remaining),
            )
            _time.sleep(_COLD_START_POLL_INTERVAL_S)
        else:
            # Loop exhausted without a takeover.  Unblock scans so the server
            # is not stuck forever; first scan uses yfinance fallback.
            _log_cc.warning(
                "check_cold_cache_on_startup: timed out waiting %ds for peer "
                "backfill to complete. Clearing readiness gate — first scan "
                "will use live yfinance fallback.",
                _COLD_START_WAIT_TIMEOUT_S,
            )
            return {
                "ran": False,
                "reason": "peer_timeout",
                "wait_timeout_s": _COLD_START_WAIT_TIMEOUT_S,
                "total_symbols": total,
                "recovery_hint": "POST /api/ohlcv-cache/backfill",
            }
        # is_owner = True (takeover) → fall through to owner block

    # ── 5. Owner (initial or takeover): write lease metadata, run backfill ────
    # Write / overwrite lease_started_key so non-owners know who holds the
    # lease and when it expires.  The TTL (_COLD_START_LEASE_TTL_S = 25 min)
    # covers the documented worst-case 22-minute yfinance bulk download, so a
    # legitimately slow backfill will never be displaced by a takeover.
    try:
        from datetime import datetime, timezone as _tz, timedelta as _td
        _now_dt = datetime.now(_tz.utc)
        _exp_dt = _now_dt + _td(seconds=_COLD_START_LEASE_TTL_S)
        store.kv_set(lease_started_key, {
            "started_at": _now_dt.isoformat(),
            "lease_expires_at": _exp_dt.isoformat(),
            "lease_ttl_s": _COLD_START_LEASE_TTL_S,
            "role": _owner_role,
        })
    except Exception:
        pass  # Non-fatal: non-owners will use the hardcoded TTL as fallback

    if is_fully_cold:
        _log_cc.warning(
            "OHLCV cache is COMPLETELY EMPTY on this server (%d/%d symbols "
            "have no rows). This is normal on a fresh production deployment. "
            "Triggering automatic 8-month backfill now — this will take "
            "2–8 minutes. Other instances will wait for this to complete.",
            len(uncached), total,
        )
    else:
        _log_cc.warning(
            "OHLCV cache is partially cold: %d/%d symbols uncached or "
            "missing required bars. Backfilling missing symbols now.",
            len(cold_set), total,
        )

    try:
        bf_result = backfill_all_symbols(symbols, force=False)
        n_updated = bf_result.get("symbols_updated", 0)
        n_skipped = bf_result.get("symbols_skipped", 0)
        n_failed = bf_result.get("symbols_failed", 0)
        failed_syms = list(bf_result.get("failed_symbols") or [])
        duration_s = float(bf_result.get("duration_seconds") or 0)
        status = str(bf_result.get("status") or "UNKNOWN")

        if failed_syms:
            _log_cc.warning(
                "Cold-start OHLCV backfill finished with %d failure(s): %s. "
                "Those symbols will fall back to live yfinance on first scan. "
                "Retry via POST /api/ohlcv-cache/backfill.",
                n_failed, failed_syms[:5],
            )
        else:
            _log_cc.info(
                "Cold-start OHLCV backfill complete in %.1fs: %d updated, "
                "%d skipped, %d failed. First scan will serve from cache.",
                duration_s, n_updated, n_skipped, n_failed,
            )

        # Write completion record so non-owners can stop polling.
        completion_record: Dict[str, Any] = {
            "status": status,
            "symbols_updated": n_updated,
            "symbols_skipped": n_skipped,
            "symbols_failed": n_failed,
            "failed_symbols": failed_syms,
            "duration_seconds": duration_s,
            "completed_at": _iso_now(),
        }
        store.kv_set(done_key, completion_record)

        return {
            "ran": True,
            "action": "backfill",
            "role": _owner_role,
            "was_fully_cold": is_fully_cold,
            "cold_symbol_count": len(cold_set),
            "total_symbols": total,
            "symbols_updated": n_updated,
            "symbols_skipped": n_skipped,
            "symbols_failed": n_failed,
            "failed_symbols": failed_syms,
            "duration_seconds": duration_s,
            "status": status,
            "recovery_hint": (
                "POST /api/ohlcv-cache/backfill" if failed_syms else None
            ),
        }

    except Exception as exc:
        # Release ONLY the key this instance owns — using token-conditional
        # release for the takeover key so a stale owner that lost its lease
        # cannot delete a new peer's active record.
        #
        # - Initial owner: plain kv_release(claim_key) so the next startup
        #   can claim and retry.
        # - Takeover owner: kv_release_if_owned(takeover_key, _takeover_token)
        #   — only deletes if OUR token still matches.  If our lease expired
        #   and another peer already wrote their token, this is a no-op.
        try:
            if _owner_role == "owner":
                store.kv_release(claim_key)
            elif _takeover_token is not None:
                store.kv_release_if_owned(takeover_key, _takeover_token)
        except Exception:
            pass
        _released = claim_key if _owner_role == "owner" else takeover_key
        _log_cc.error(
            "Cold-start OHLCV backfill raised an exception (role=%s): %s. "
            "%s released for retry. The first scan will fall back to a "
            "live yfinance download (7–22 minutes). "
            "Manual retry: POST /api/ohlcv-cache/backfill",
            _owner_role, str(exc)[:300], _released,
        )
        return {
            "ran": True,
            "action": "backfill_failed",
            "role": _owner_role,
            "was_fully_cold": is_fully_cold,
            "cold_symbol_count": len(cold_set),
            "total_symbols": total,
            "error": str(exc)[:300],
            "recovery_hint": "POST /api/ohlcv-cache/backfill",
        }


def run_tick() -> Dict[str, Any]:
    """One scheduler tick. Returns a JSON-safe result dict."""
    settings = store.get_settings()
    interval_min = int(settings.get("scan_interval_minutes", 5))
    now_iso = _iso_now()

    from market_hours import market_status
    mstat = market_status()
    mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()
    readiness = _maybe_run_premarket_readiness(mstate)

    if not settings.get("auto_scan_enabled", True):
        # Scans stay suppressed, but the market-open session alert must
        # still be evaluated — a disabled scheduler is exactly the kind of
        # situation where the session silently misses the day. Never raises.
        disabled_alert: Any = None
        try:
            from daily_session_manager import check_open_alert
            disabled_alert = check_open_alert(mstate)
        except Exception as exc:
            disabled_alert = {"alerted": False, "error": str(exc)[:200]}
        store.update_scheduler_state(
            last_attempt_at=now_iso, status="DISABLED",
            detail="Auto scan disabled in settings",
            owner=_OWNER, heartbeat_at=now_iso,
        )
        out_disabled: Dict[str, Any] = {"success": True, "ran_scan": False,
                                        "reason": "Auto scan disabled"}
        _maybe_record_heartbeat(mstate or "UNKNOWN", "auto_scan_disabled")
        if readiness is not None:
            out_disabled["premarket_readiness"] = readiness
        if disabled_alert is not None:
            out_disabled["session_alert"] = disabled_alert
        return out_disabled

    # ── Daily session initialisation (pre-market + OPEN fallback) ────────────
    # Runs once per trading day before the first scan.  Idempotent.
    # Handles: portfolio archive, ₹50K capital reset, preserved entry state,
    # agent warm-start, and Mode B top-up check.
    session_init: Any = None
    try:
        from daily_session_manager import check_and_maybe_initialize
        session_init = check_and_maybe_initialize(mstate)
    except Exception as exc:
        session_init = {"error": str(exc)[:200]}

    # If the market is OPEN and today's session is still not INITIALISED
    # (init never ran or ended in ERROR), raise a once-per-day CRITICAL
    # operator alert (atomic KV claim; includes persisted last_error).
    # Never raises.
    session_alert: Any = None
    try:
        from daily_session_manager import check_open_alert
        session_alert = check_open_alert(mstate)
    except Exception as exc:
        session_alert = {"alerted": False, "error": str(exc)[:200]}

    # Custom universe pre-market refresh lives before the non-OPEN early
    # return. It is independently time-gated and cannot cause scans/orders.
    premarket_universe_refresh = _maybe_refresh_low_price_universe_pre_market()

    if mstate != "OPEN":
        _maybe_record_heartbeat(mstate or "UNKNOWN", "market_not_open")
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
        # EOD post-close force-exit: close any OPEN paper positions that
        # survived past 15:30 IST (missed the 15:20 intraday square-off window).
        # Runs on POST_CLOSE and CLOSED so the first non-OPEN tick after the
        # session end triggers the cleanup. Uses a KV claim so it fires exactly
        # once per IST trading day regardless of how many ticks hit this block.
        # Never raises.
        eod_squareoff = None
        if mstate in ("POST_CLOSE", "CLOSED"):
            _claim_key: Optional[str] = None
            _claim_taken = False
            _retry_key: Optional[str] = None

            def _report_eod_scheduler_failure(error: Exception | str) -> None:
                """Surface a scheduler-level failure that produced no outcome."""
                message = str(error)[:200]
                try:
                    from pipeline_events import emit as _emit
                    _emit(
                        "MARKET_CLOSE_EXIT_BLOCKED", "PORTFOLIO",
                        payload={
                            "reason": (
                                "POST_CLOSE_FORCE_EXIT scheduler failure before "
                                "per-position outcomes were persisted"
                            ),
                            "error": message,
                            "session_date_ist": _today_ist_date(),
                        },
                        dedupe_key=(
                            f"market-close-scheduler-failure:{_today_ist_date()}"
                        ),
                    )
                except Exception:
                    pass
                try:
                    store.add_notification(
                        "MARKET_CLOSE_EXIT_BLOCKED",
                        "EOD force-close scheduler failed before completion",
                        (f"POST_CLOSE_FORCE_EXIT did not complete: {message}. "
                         "The daily claim was released so the next scheduler "
                         "tick can retry."),
                        severity="WARN",
                        context={"error": message, "claim_key": _claim_key},
                    )
                except Exception:
                    pass

            try:
                from phase20_store import kv_claim_once, kv_release
                from phase20_store import get_settings as _ls
                # IMPORTANT: import the close function BEFORE claiming the
                # daily KV slot.  A cold-start ImportError / ModuleNotFoundError
                # / AttributeError that fires after kv_claim_once would
                # silently consume the only retry available for that calendar
                # day, leaving OPEN positions stranded overnight.  By resolving
                # all imports first we guarantee the claim is only written when
                # the full close logic is known to be available.
                from phase20_exits import eod_force_close_open_positions
                _today_ist = _today_ist_date()
                _claim_key = f"eod_squareoff:{_today_ist}"
                _retry_key = f"eod_squareoff_unresolved:{_today_ist}"
                if kv_claim_once(_claim_key, ttl_seconds=86400):
                    _claim_taken = True
                    _retry_outcomes = store.kv_get(_retry_key)
                    if isinstance(_retry_outcomes, list) and _retry_outcomes:
                        eod_squareoff = eod_force_close_open_positions(
                            _ls(), session_date=_today_ist,
                            retry_outcomes=_retry_outcomes,
                        )
                    else:
                        eod_squareoff = eod_force_close_open_positions(_ls())
                    # A blocked trade already has one durable, per-position
                    # outcome and must not emit duplicate blocked events on
                    # every post-close tick.  Release only when the event
                    # write itself was unresolved, leaving no audit trail.
                    if (not eod_squareoff
                            or eod_squareoff.get("unresolved")
                            or eod_squareoff.get("error")):
                        if _retry_key:
                            store.kv_set(
                                _retry_key,
                                list((eod_squareoff or {}).get("unresolved") or []),
                            )
                        kv_release(_claim_key)
                        _claim_taken = False
                        _report_eod_scheduler_failure(
                            (eod_squareoff or {}).get("error")
                            or "EOD close returned unresolved audit outcomes"
                        )
                    elif _retry_key:
                        store.kv_release(_retry_key)
            except (ImportError, ModuleNotFoundError, AttributeError) as exc:
                # Setup / dependency error — kv_claim_once was never reached
                # (all imports run before it), so the daily retry slot is still
                # available.  Surface the error for observability without
                # blocking tomorrow's retry.
                eod_squareoff = {"error": f"setup_error: {str(exc)[:200]}",
                                 "claim_consumed": False}
                _report_eod_scheduler_failure(eod_squareoff["error"])
            except Exception as exc:
                eod_squareoff = {"error": str(exc)[:200]}
                # Runtime errors happen after the claim in the failure mode
                # that previously stranded positions.  Make this retryable and
                # visible instead of consuming the close window silently.
                if _claim_taken and _claim_key:
                    try:
                        kv_release(_claim_key)
                    except Exception:
                        pass
                    _claim_taken = False
                _report_eod_scheduler_failure(exc)

        # Post-market OHLCV cache refresh — append today's final daily bar for
        # all NIFTY 50 symbols so tomorrow's scans use local cache and skip
        # the 7–22 min yfinance bulk download.  Exactly once per IST calendar
        # day via kv_claim_once.  Advisory-only; never raises.
        ohlcv_postmarket_refresh = None
        if mstate in ("POST_CLOSE", "CLOSED"):
            try:
                from post_market_data_refresh import maybe_run_postmarket_refresh
                ohlcv_postmarket_refresh = maybe_run_postmarket_refresh(mstate)
                if isinstance(ohlcv_postmarket_refresh, dict) and \
                        ohlcv_postmarket_refresh.get("ran"):
                    record_system_job(
                        "POSTMARKET_CACHE_REFRESH",
                        market_state=mstate,
                        trigger="SCHEDULER",
                        started_at=str(ohlcv_postmarket_refresh.get("started_at") or now_iso),
                        duration_s=float(ohlcv_postmarket_refresh.get("duration_seconds") or 0),
                        status=str(ohlcv_postmarket_refresh.get("status") or (
                            "SUCCESS" if ohlcv_postmarket_refresh.get("success") else "FAILED"
                        )),
                        symbols_requested=ohlcv_postmarket_refresh.get("symbols_requested"),
                        symbols_received=ohlcv_postmarket_refresh.get("symbols_updated"),
                        error=ohlcv_postmarket_refresh.get("error"),
                        details=ohlcv_postmarket_refresh,
                    )
            except Exception as exc:
                ohlcv_postmarket_refresh = {"ran": False, "error": str(exc)[:200]}

        # Exports retention: delete workspace-root exports/ files older than
        # 7 days, exactly once per IST calendar day (kv_claim_once guard).
        # Advisory-only; never raises.
        exports_cleanup = None
        if mstate == "CLOSED":
            try:
                from exports_retention import maybe_run_exports_cleanup
                exports_cleanup = maybe_run_exports_cleanup()
            except Exception as exc:
                exports_cleanup = {"ran": False, "error": str(exc)[:200]}
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
        if eod_squareoff is not None:
            out["eod_squareoff"] = eod_squareoff
        if ohlcv_postmarket_refresh is not None:
            out["ohlcv_postmarket_refresh"] = ohlcv_postmarket_refresh
        if exports_cleanup is not None:
            out["exports_cleanup"] = exports_cleanup
        if p26d_daily is not None:
            out["phase26d_daily_report"] = p26d_daily
        if p26c is not None:
            out["phase26c_validation"] = p26c
        if premarket_universe_refresh is not None:
            out["low_price_universe_refresh"] = premarket_universe_refresh
        if readiness is not None:
            out["premarket_readiness"] = readiness
        # ── Post-close orphan seal ────────────────────────────────────────────
        # Covers the "last-tick-of-session" gap: if the last scan of the day
        # completed while mstate was still OPEN but the market crossed 15:30
        # before the next scheduled tick, _manage_paper() never fires and
        # BUY_GENERATED events are left without a terminal outcome.  Calling
        # the seal here (POST_CLOSE / CLOSED only — not PRE_OPEN / WEEKEND /
        # HOLIDAY) ensures the orphan-check query returns 0 rows.
        # The seal is idempotent: if it already ran in the OPEN tick it is a
        # no-op. Never raises.
        if mstate in ("POST_CLOSE", "CLOSED"):
            try:
                _post_close_scan_id: Optional[str] = None
                try:
                    from phase15_scan_context import build_scan_context as _bsc
                    _post_close_scan_id = (_bsc() or {}).get("scan_id")
                except Exception:
                    pass
                if _post_close_scan_id:
                    from phase20_executor import seal_execution_outcomes
                    _pc_seal = seal_execution_outcomes(
                        _post_close_scan_id, reason="post_close_seal")
                    out["execution_seal"] = _pc_seal
                    _persist_seal_result(
                        _pc_seal, _post_close_scan_id, "post_close_seal")
            except Exception as _exc:
                out["execution_seal"] = {"error": str(_exc)[:200]}
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

    # ── Dedicated 15:20 IST intraday squareoff (TASK 4) ─────────────────────
    # Fires exactly once per IST trading day via kv_claim_once, independent of
    # scan cadence. This is the primary EOD close path — runs even when the
    # snapshot is fresh and the scanner skips the full run. Imports resolve
    # BEFORE claiming so a setup error doesn't consume the daily retry slot.
    # Never raises — a failure is recorded but never blocks the tick.
    intraday_squareoff_1520: Optional[Dict[str, Any]] = None
    try:
        from market_hours import now_ist as _nist_sq
        from phase20_exits import close_all_for_intraday_squareoff as _sq_fn
        from phase20_store import get_settings as _sq_gs
        _sq_now = _nist_sq()
        _SQ_H, _SQ_M = 15, 20
        if (_sq_now.hour > _SQ_H
                or (_sq_now.hour == _SQ_H and _sq_now.minute >= _SQ_M)):
            _sq_key = f"intraday_squareoff_1520:{_sq_now.date().isoformat()}"
            if store.kv_claim_once(_sq_key):
                intraday_squareoff_1520 = _sq_fn(_sq_gs())
    except Exception as _sq_exc:
        intraday_squareoff_1520 = {"error": str(_sq_exc)[:200]}

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
        if intraday_squareoff_1520 is not None:
            result["intraday_squareoff_1520"] = intraday_squareoff_1520
        if session_alert is not None:
            result["session_alert"] = session_alert
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
    # One durable observability event per *due* scheduled scan attempt. The
    # outer Node heartbeat calls this module every minute, so emitting above the
    # freshness gate would incorrectly inflate the displayed scheduler-tick
    # count. This evidence is advisory only and cannot affect scan execution.
    try:
        from pipeline_events import emit as _pe_emit
        _pe_emit(
            "SCHEDULER_TICK",
            "SCHEDULER",
            payload={"interval_minutes": interval_min, "owner": _OWNER},
        )
    except Exception:
        pass
    t0 = time.time()
    try:
        from live_scan_engine import get_or_run_scan
        snap = get_or_run_scan(max_age_s=interval_min * 60, force=False,
                               wait_for_lock=False, trigger_origin="SCHEDULED")
        duration = time.time() - t0

        if snap.get("_scan_lock_busy"):
            # Another instance is mid-scan. Record the skip (concurrency
            # safety evidence) and return immediately — never poll, never
            # start a second scan.
            store.record_scan_run(_job_meta(
                job_type="MARKET_SCAN", scan_type="CANONICAL",
                trigger="SCHEDULED", market_state=mstate, started_at=now_iso,
                duration_s=duration, status="SKIPPED_ACTIVE_SCAN",
                error=None,
            ))
            try:
                store.kv_set("scan_skipped_active_count",
                             int(store.kv_get("scan_skipped_active_count") or 0) + 1)
            except Exception:
                pass
            # Emit pipeline event so operators can see skips in the cadence panel.
            try:
                from pipeline_events import emit as _pe_emit
                _pe_emit("SCAN_SKIPPED_BUSY", "SCAN",
                         payload={"reason": "SKIPPED_ACTIVE_SCAN — another scan in progress",
                                  "interval_minutes": interval_min})
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
            if session_alert is not None:
                busy_out["session_alert"] = session_alert
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
            store.record_scan_run(
                _run_meta_from_snapshot(snap, "SCHEDULED", duration, mstate)
            )
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
            result_refresh = _maybe_refresh_low_price_universe_after_scan()
        else:
            result_refresh = None
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
        if result_refresh is not None:
            result["low_price_universe_refresh"] = result_refresh
        if pipeline is not None:
            result["pipeline"] = {
                "status": pipeline.get("status"),
                "failed_modules": pipeline.get("failed_modules"),
            }
        result["paper"] = _manage_paper(settings, ran_scan=ran)
        if intraday_squareoff_1520 is not None:
            result["intraday_squareoff_1520"] = intraday_squareoff_1520
        if session_alert is not None:
            result["session_alert"] = session_alert
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
        store.record_scan_run(_job_meta(
            job_type="MARKET_SCAN", scan_type="CANONICAL",
            trigger="SCHEDULED", market_state=mstate, started_at=now_iso,
            duration_s=duration, status="FAILED", error=str(exc),
        ))
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
    # ── Entry window pre-guard (defense-in-depth layer 1) ────────────────────
    # Check the paper-entry window AFTER exits and circuit-breaker, BEFORE
    # calling either auto-entry path.  Exits may have just cleared the
    # no_open_duplicate gate on this very tick; without this pre-guard a
    # post-15:15 tick would immediately re-use that cleared gate and rely
    # solely on the final lock-held _insert_row() check to block the insert.
    # This layer eliminates the race at the scheduler level.
    # Also blocks entries if today's startup overnight-carry check has not
    # yet completed (Autoscale-safe via KV).
    # Never raises — an unreadable market_hours module fails closed.
    _entry_window: Dict[str, Any] = {}
    try:
        from market_hours import automatic_paper_entry_status as _ape_status
        from market_hours import now_ist as _nist_ew
        _ew_ts = _nist_ew()
        _entry_window = _ape_status(_ew_ts)
        _entry_window = dict(_entry_window)
        _entry_window["checked_at_ist"] = _ew_ts.isoformat()
    except Exception as _ewexc:
        _entry_window = {
            "allowed": False,
            "reason": f"entry_window_check_error: {str(_ewexc)[:100]}",
            "market_state": "UNKNOWN",
            "cutoff_ist": "15:15",
            "cutoff_reached": True,
            "checked_at_ist": None,
        }
    _entry_window_open = bool(_entry_window.get("allowed"))

    # Startup overnight-carry check: block entries if today's startup safety net
    # has not yet completed.  check_overnight_carry_on_startup() sets the
    # startup_overnight_check:{today} KV key when it runs.  A missing key means
    # either the key never existed (startup not yet run) or the DB is briefly
    # unavailable — in both cases fail-closed is the safer choice.
    if _entry_window_open:
        try:
            from market_hours import now_ist as _nist_sc
            _today_sc = _nist_sc().date().isoformat()
            _startup_done = bool(store.kv_get(f"startup_overnight_check:{_today_sc}"))
            if not _startup_done:
                _entry_window_open = False
                _entry_window = dict(_entry_window)
                _entry_window["allowed"] = False
                _entry_window["reason"] = (
                    "OVERNIGHT_CARRY_CHECK_PENDING — startup safety net has not "
                    "yet completed for today; entries blocked until remediation "
                    "is recorded"
                )
        except Exception:
            pass  # KV unavailable — don't block on infrastructure failure

    try:
        if not _entry_window_open:
            out["entries"] = {
                "skipped": True,
                "reason": "ENTRY_WINDOW_CLOSED",
                "entry_window": _entry_window,
                "cutoff_ist": _entry_window.get("cutoff_ist"),
                "checked_at_ist": _entry_window.get("checked_at_ist"),
                "market_state": _entry_window.get("market_state"),
            }
        elif settings.get("auto_paper_entries") and settings.get("auto_paper_entries_confirmed_at"):
            from phase20_executor import run_auto_entries
            out["entries"] = run_auto_entries(settings)
        else:
            out["entries"] = {"skipped": "auto_paper_entries OFF (default)"}
    except Exception as exc:
        out["entries"] = {"error": str(exc)[:200]}
    # ── Bootstrap paper entry ─────────────────────────────────────────────────
    # Requires the same operator confirmation as normal auto entries: both
    # auto_paper_entries and bootstrap_paper_enabled must be ON and confirmed.
    # This preserves the Phase 20 explicit-confirmation invariant: bootstrap
    # never opens canonical positions without operator opt-in.
    # Never raises — a failure here must never block exits or evidence.
    try:
        _bs_entries_on = (settings.get("auto_paper_entries")
                          and settings.get("auto_paper_entries_confirmed_at"))
        _bs_flag_on = settings.get("bootstrap_paper_enabled", False)
        if not _entry_window_open:
            out["bootstrap"] = {
                "ran": False,
                "reason": "ENTRY_WINDOW_CLOSED",
                "entry_window": _entry_window,
                "cutoff_ist": _entry_window.get("cutoff_ist"),
                "checked_at_ist": _entry_window.get("checked_at_ist"),
                "market_state": _entry_window.get("market_state"),
            }
        elif not _bs_entries_on or not _bs_flag_on:
            out["bootstrap"] = {
                "ran": False,
                "reason": (
                    "bootstrap_paper_enabled=False in settings"
                    if not _bs_flag_on
                    else "auto_paper_entries not confirmed — bootstrap requires same confirmation"
                ),
            }
        else:
            from phase20_executor import run_bootstrap_auto_entry
            from scan_state_store import load_latest_snapshot as _load_snap
            _bs_snap = _load_snap()
            if _bs_snap:
                _cb = out.get("circuit_breaker") or {}
                _cb_tripped = bool(_cb.get("tripped")) or bool(_cb.get("error"))
                out["bootstrap"] = run_bootstrap_auto_entry(
                    _bs_snap, settings, circuit_breaker_tripped=_cb_tripped
                )
            else:
                out["bootstrap"] = {"ran": False, "reason": "No snapshot available"}
    except Exception as exc:
        out["bootstrap"] = {"error": str(exc)[:200]}
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
    # ── Execution-outcome seal ────────────────────────────────────────────────
    # Ensure every BUY_GENERATED event for the current scan has a terminal
    # EXECUTION-stage outcome event.  This closes the "last scan of the
    # session" gap: the executor runs on a 1-minute tick, so by the time it
    # fires for the final scan the market is already closed and no terminal
    # event (ORDER_EXECUTED / ORDER_REJECTED / EXECUTION_SKIPPED_WITH_REASON)
    # is ever written — producing orphan BUY signals in the Agent Journey.
    # Calling this after every paper-management run (both auto-entries ON and
    # OFF) guarantees the orphan-check query returns 0 rows. Never raises.
    try:
        _seal_scan_id: Optional[str] = None
        entries = out.get("entries") or {}
        if isinstance(entries, dict):
            # Auto-entries path: scan_id recorded in the run result.
            _seal_scan_id = entries.get("scan_id")
        if not _seal_scan_id:
            # Evidence-only path (auto_paper_entries OFF): derive from context.
            try:
                from phase15_scan_context import build_scan_context as _bsc
                _seal_scan_id = (_bsc() or {}).get("scan_id")
            except Exception:
                pass
        if _seal_scan_id:
            auto_on = bool(settings.get("auto_paper_entries")
                           and settings.get("auto_paper_entries_confirmed_at"))
            _seal_reason = ("post_auto_entry_seal" if auto_on
                            else "auto_paper_entries_off")
            from phase20_executor import seal_execution_outcomes
            _seal_result = seal_execution_outcomes(_seal_scan_id, _seal_reason)
            out["execution_seal"] = _seal_result
            _persist_seal_result(_seal_result, _seal_scan_id, _seal_reason)
    except Exception as exc:
        out["execution_seal"] = {"error": str(exc)[:200]}
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
    # ── Paper Intraday Learning / Exploration Mode ───────────────────────────
    # Only runs when operator has explicitly enabled exploration mode.
    # Writes to experimental_paper_trades; NEVER touches the canonical
    # phase20 portfolio, cash, positions, or daily trade counter.
    if settings.get("paper_exploration_mode"):
        try:
            from paper_exploration_engine import run_exploration_tick
            out["exploration"] = run_exploration_tick(settings)
        except Exception as exc:
            out["exploration"] = {"error": str(exc)[:300]}
    return out
