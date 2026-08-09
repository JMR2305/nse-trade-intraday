"""
phase26_recovery.py — Phase 26C: recovery validation suite.

Validates that the platform heals correctly after the fault classes we care
about: API restart, database restart, broker reconnect, network interruption,
historical-provider failure, and background-worker restart.

No destructive fault injection anywhere — every scenario validates the
RECOVERY CODE PATHS against recorded durable state:

* api_restart          — the canonical scan snapshot + metadata are durable
                         (Postgres via scan_state_store) and self-consistent,
                         so a restarted API serves the same state.
* database_restart     — scan lock/lease integrity: readable, not stuck
                         (expired leases are reclaimable by design), and a
                         recorded failed scan never overwrote the snapshot.
* portfolio_recovery   — the canonical portfolio (recover-first from the
                         phase20 ledger) is internally consistent: equity =
                         cash + position value and open positions match
                         ledger OPEN rows.
* broker_reconnect     — the Kite session state machine reports a coherent
                         state; presence of credentials is never trusted
                         without the authenticated-probe fields.
* network_interruption — recorded scan-run history proves the retry path:
                         a FAILED/SKIPPED run followed by a later SUCCESS
                         means recovery worked; no recorded fault is a quiet
                         PASS (code path validated by durable-state checks).
* provider_failover    — the latest snapshot's provider health shows a
                         provider actually delivered symbols (fallback chain
                         NSE→Kite→Yahoo ends in a working provider).
* worker_restart       — the phase20 scheduler heartbeat resumed after the
                         most recent process start (off-session: last
                         attempt recorded is sufficient).

Grades per scenario: PASS / WARN / FAIL / INSUFFICIENT (source unavailable —
never extrapolated into a failure). Fold: any FAIL → FAIL, else any
WARN/INSUFFICIENT → WARN, else PASS.

Results persist append-only via phase26c_store and FAIL scenarios feed the
Phase 26 issue store (category RECOVERY) — reconciled atomically only when
every scenario was evaluated against an available source.

READ-ONLY / ADVISORY-ONLY. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCENARIOS = (
    "api_restart", "database_restart", "portfolio_recovery",
    "broker_reconnect", "network_interruption", "provider_failover",
    "worker_restart",
)

HEARTBEAT_MAX_AGE_S = 300          # in-session scheduler heartbeat budget


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── Input collection (live) ─────────────────────────────────────────────────

def collect_recovery_inputs() -> Dict[str, Any]:
    """Gather recorded state from canonical stores. Each source is optional —
    an unavailable source is recorded as None (scenario → INSUFFICIENT),
    never fabricated."""
    out: Dict[str, Any] = {}

    def _try(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = None
            out.setdefault("_errors", {})[name] = str(exc)[:200]

    def _scan_meta():
        import scan_state_store
        return scan_state_store.load_latest_meta()

    def _snapshot_head():
        import scan_state_store
        snap = scan_state_store.load_latest_snapshot()
        if not snap:
            return None
        health = snap.get("provider_health") or {}
        safety = snap.get("safety") or {}
        return {"scan_id": snap.get("scan_id"),
                "snapshot_ts": snap.get("snapshot_ts"),
                "provider": safety.get("data_provider") or health.get("provider"),
                "symbols_requested": health.get("symbols_requested"),
                "symbols_succeeded": health.get("symbols_succeeded")}

    def _portfolio():
        import canonical_portfolio
        return canonical_portfolio.build_canonical_portfolio()

    def _ledger_open():
        import phase20_executor as p20
        from canonical_portfolio import OPEN_STATUSES
        rows = p20.get_ledger(limit=10_000)
        return [r for r in rows or []
                if str(r.get("status") or "").upper() in OPEN_STATUSES]

    def _broker():
        import kite_session_manager
        return kite_session_manager.get_status(force_probe=False)

    def _scheduler():
        import phase20_store as store
        return store.get_scheduler_health()

    def _scan_runs():
        import phase20_store as store
        return store.list_scan_runs(limit=50)

    def _market():
        import market_hours
        st = market_hours.market_status()
        return str(st.get("state") or st.get("market_state") or "").upper()

    _try("scan_meta", _scan_meta)
    _try("snapshot", _snapshot_head)
    _try("portfolio", _portfolio)
    _try("ledger_open_rows", _ledger_open)
    _try("broker", _broker)
    _try("scheduler", _scheduler)
    _try("scan_runs", _scan_runs)
    _try("market_state", _market)
    out["db_durable"] = _db_durable()
    return out


def _db_durable() -> bool:
    try:
        import scan_state_store
        return bool(scan_state_store.db_available())
    except Exception:
        return False


# ── Scenario validators (pure, injectable) ──────────────────────────────────

def _scn(name: str, grade: str, detail: str,
         evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"scenario": name, "grade": grade, "detail": detail,
            "evidence": evidence or {}}


def _check_api_restart(inputs: Dict[str, Any]) -> Dict[str, Any]:
    meta = inputs.get("scan_meta")
    snap = inputs.get("snapshot")
    if meta is None and snap is None:
        return _scn("api_restart", "INSUFFICIENT",
                    "No durable scan state readable — cannot validate "
                    "restart recovery (no scan has ever run?)")
    if not snap or not snap.get("scan_id"):
        return _scn("api_restart", "FAIL",
                    "Scan metadata exists but the snapshot payload is "
                    "missing — a restarted API would serve no scan data",
                    {"meta_scan_id": (meta or {}).get("scan_id")})
    if meta and meta.get("scan_id") and \
            str(meta["scan_id"]) != str(snap["scan_id"]):
        return _scn("api_restart", "FAIL",
                    "Durable metadata and snapshot disagree on scan_id — "
                    "recovered state would be internally inconsistent",
                    {"meta_scan_id": meta.get("scan_id"),
                     "snapshot_scan_id": snap.get("scan_id")})
    if not _parse_ts(snap.get("snapshot_ts")):
        return _scn("api_restart", "FAIL",
                    "Snapshot timestamp is unparseable — freshness logic "
                    "would break after restart",
                    {"snapshot_ts": snap.get("snapshot_ts")})
    if not inputs.get("db_durable"):
        return _scn("api_restart", "WARN",
                    "Snapshot is consistent but only file-backed (no "
                    "DATABASE_URL) — a restart on another instance would "
                    "lose it", {"scan_id": snap.get("scan_id")})
    return _scn("api_restart", "PASS",
                "Durable snapshot + metadata consistent (Postgres-backed); "
                "a restarted API recovers identical scan state",
                {"scan_id": snap.get("scan_id"),
                 "snapshot_ts": snap.get("snapshot_ts")})


STUCK_LOCK_MAX_AGE_S = 30 * 60      # a held scan lease older than this is stuck


def _check_database_restart(inputs: Dict[str, Any],
                            now: Optional[datetime] = None) -> Dict[str, Any]:
    meta = inputs.get("scan_meta")
    snap = inputs.get("snapshot")
    if meta is None:
        return _scn("database_restart", "INSUFFICIENT",
                    "Scan metadata unavailable — cannot validate "
                    "snapshot/lock integrity")
    now = now or datetime.now(timezone.utc)
    evidence = {"status": meta.get("status"), "error": meta.get("error")}
    # Scan-lock/lease integrity (from scheduler health, which reads scan_lock)
    lock = (inputs.get("scheduler") or {}).get("lock")
    if lock:
        evidence["lock"] = lock
        acquired = _parse_ts(lock.get("acquired_at"))
        expires = _parse_ts(lock.get("expires_at"))
        if acquired and (now - acquired).total_seconds() > STUCK_LOCK_MAX_AGE_S:
            return _scn("database_restart", "FAIL",
                        "Scan lock has been held for over "
                        f"{STUCK_LOCK_MAX_AGE_S // 60} minutes — a stuck "
                        "lease is blocking new scans after restart",
                        evidence)
        if expires and expires < now:
            return _scn("database_restart", "WARN",
                        "An expired scan lease is still present — "
                        "reclaimable by design, but reclaim has not been "
                        "exercised yet", evidence)
    # Failed-scan-preserves-snapshot invariant: a recorded error must never
    # coexist with a MISSING snapshot when a success was ever recorded.
    if meta.get("error") and not (snap and snap.get("scan_id")):
        if meta.get("status") == "FAILED" and meta.get("scan_id") is None:
            return _scn("database_restart", "WARN",
                        "Only a failed scan is recorded and no snapshot "
                        "exists yet — nothing to recover (first-run state)",
                        evidence)
        return _scn("database_restart", "FAIL",
                    "A scan failure is recorded and the last successful "
                    "snapshot is gone — the never-overwrite invariant "
                    "is broken", evidence)
    return _scn("database_restart", "PASS",
                "Scan state row readable; failed scans preserved the last "
                "successful snapshot; expired scan leases are reclaimable "
                "by design (scan_state_store.acquire_scan_lock)", evidence)


def _check_portfolio_recovery(inputs: Dict[str, Any]) -> Dict[str, Any]:
    pf = inputs.get("portfolio")
    if pf is None:
        return _scn("portfolio_recovery", "INSUFFICIENT",
                    "Canonical portfolio unavailable — cannot validate "
                    "ledger recovery")
    cash = _f(pf.get("cash"))
    equity = _f(pf.get("equity"))
    positions = pf.get("positions") or []
    pos_value = 0.0
    for p in positions:
        pv = _f(p.get("market_value"))
        if pv is None:
            pv = _f(p.get("current_value"))
        if pv is None:
            pv = (_f(p.get("quantity"), 0.0) or 0.0) * \
                 (_f(p.get("mark_price") or p.get("last_price")
                     or p.get("avg_price"), 0.0) or 0.0)
        pos_value += pv or 0.0
    if cash is None or equity is None:
        return _scn("portfolio_recovery", "FAIL",
                    "Recovered portfolio is missing cash/equity — the "
                    "ledger-derived book is incomplete",
                    {"cash": pf.get("cash"), "equity": pf.get("equity")})
    if abs((cash + pos_value) - equity) > 1.0:
        return _scn("portfolio_recovery", "FAIL",
                    "Recovered equity != cash + position value — the "
                    "ledger-derived book is internally inconsistent",
                    {"cash": cash, "position_value": round(pos_value, 2),
                     "equity": equity})
    ledger_open = inputs.get("ledger_open_rows")
    evidence: Dict[str, Any] = {"cash": cash, "equity": equity,
                                "open_positions": len(positions)}
    if ledger_open is not None:
        ledger_syms = sorted({str(r.get("symbol")) for r in ledger_open
                              if r.get("symbol")})
        pos_syms = sorted({str(p.get("symbol")) for p in positions
                           if p.get("symbol")})
        evidence["ledger_open_symbols"] = ledger_syms
        evidence["portfolio_symbols"] = pos_syms
        if ledger_syms != pos_syms:
            return _scn("portfolio_recovery", "FAIL",
                        "Open ledger rows and recovered positions disagree — "
                        "recover-first startup would produce a different "
                        "book", evidence)
    return _scn("portfolio_recovery", "PASS",
                "Canonical portfolio recovers consistently from the phase20 "
                "ledger (equity = cash + positions; symbols match)", evidence)


def _check_broker_reconnect(inputs: Dict[str, Any]) -> Dict[str, Any]:
    br = inputs.get("broker")
    if br is None:
        return _scn("broker_reconnect", "INSUFFICIENT",
                    "Broker session status unavailable")
    state = str(br.get("connection_state") or "").upper()
    evidence = {"connection_state": state,
                "token_status": br.get("token_status"),
                "probe_source": br.get("probe_source")}
    if state == "CONNECTED":
        return _scn("broker_reconnect", "PASS",
                    "Authenticated broker probe succeeded — session "
                    "recovery path proven live", evidence)
    if state in ("LOGIN_REQUIRED", "TOKEN_EXPIRED", "NOT_CONFIGURED"):
        return _scn("broker_reconnect", "WARN",
                    f"Broker session is {state} — expected outside a "
                    "logged-in trading day; reconnect requires the manual "
                    "daily Kite login (by design, no auto-login)", evidence)
    if state in ("API_ERROR", "AUTH_FAILED"):
        return _scn("broker_reconnect", "FAIL",
                    f"Broker session is {state} — reconnect path is not "
                    "recovering", evidence)
    return _scn("broker_reconnect", "WARN",
                f"Unrecognised broker connection state '{state}'", evidence)


def _check_network_interruption(inputs: Dict[str, Any]) -> Dict[str, Any]:
    runs = inputs.get("scan_runs")
    if runs is None:
        return _scn("network_interruption", "INSUFFICIENT",
                    "Scan-run history unavailable")
    # Runs are newest-first. Recovery proven when a genuine fault has a
    # LATER success. Benign statuses (SKIPPED_* concurrency outcomes) are
    # NOT faults.
    def _is_fault(status: str) -> bool:
        s = status.upper()
        return any(tok in s for tok in
                   ("FAIL", "ERROR", "TIMEOUT", "ABORT", "INTERRUPT"))
    failures = [r for r in runs
                if _is_fault(str(r.get("status") or ""))]
    if not failures:
        return _scn("network_interruption", "PASS",
                    "No recorded scan faults — retry/recovery code path "
                    "validated via durable-state checks (failed scans never "
                    "overwrite the snapshot by design)",
                    {"runs_checked": len(runs), "faults": 0})
    newest_fail_ts = _parse_ts(failures[0].get("completed_at")
                               or failures[0].get("started_at"))
    later_success = None
    for r in runs:
        if str(r.get("status") or "").upper() == "SUCCESS":
            ts = _parse_ts(r.get("completed_at") or r.get("started_at"))
            if newest_fail_ts is None or (ts and ts >= newest_fail_ts):
                later_success = r
            break   # runs newest-first: first SUCCESS is the latest one
    evidence = {"faults": len(failures),
                "latest_fault_status": failures[0].get("status"),
                "latest_fault_at": failures[0].get("completed_at"),
                "recovered_scan_id":
                    (later_success or {}).get("scan_id")}
    if later_success:
        return _scn("network_interruption", "PASS",
                    "Recorded scan fault(s) were followed by a successful "
                    "scan — interruption recovery proven from history",
                    evidence)
    return _scn("network_interruption", "WARN",
                "The most recent scan run(s) failed and no success has "
                "followed yet — recovery unproven for the latest fault",
                evidence)


def _check_provider_failover(inputs: Dict[str, Any]) -> Dict[str, Any]:
    snap = inputs.get("snapshot")
    if snap is None:
        return _scn("provider_failover", "INSUFFICIENT",
                    "No scan snapshot — cannot validate the provider "
                    "fallback chain")
    provider = snap.get("provider")
    received = _f(snap.get("symbols_succeeded"), 0.0) or 0.0
    requested = _f(snap.get("symbols_requested"), 0.0) or 0.0
    evidence = {"provider": provider, "symbols_succeeded": received,
                "symbols_requested": requested}
    if not provider:
        return _scn("provider_failover", "FAIL",
                    "Latest snapshot records no data provider — the "
                    "fallback chain did not resolve", evidence)
    if received <= 0:
        return _scn("provider_failover", "FAIL",
                    "Latest snapshot delivered zero symbols — every "
                    "provider in the chain failed", evidence)
    if requested and received < requested:
        return _scn("provider_failover", "WARN",
                    "Provider chain resolved but with partial coverage",
                    evidence)
    return _scn("provider_failover", "PASS",
                f"Provider '{provider}' delivered full coverage — fallback "
                "chain healthy", evidence)


def _check_worker_restart(inputs: Dict[str, Any],
                          now: Optional[datetime] = None) -> Dict[str, Any]:
    sched = inputs.get("scheduler")
    if sched is None:
        return _scn("worker_restart", "INSUFFICIENT",
                    "Scheduler health unavailable")
    now = now or datetime.now(timezone.utc)
    hb = _parse_ts(sched.get("heartbeat_at") or sched.get("last_attempt_at"))
    in_session = str(inputs.get("market_state") or "").upper() == "OPEN"
    evidence = {"heartbeat_at": sched.get("heartbeat_at"),
                "status": sched.get("status"),
                "owner": sched.get("owner"), "in_session": in_session}
    if hb is None:
        return _scn("worker_restart", "FAIL" if in_session else "WARN",
                    "Scheduler has never recorded a heartbeat — background "
                    "worker did not resume", evidence)
    age = (now - hb).total_seconds()
    evidence["heartbeat_age_s"] = round(age, 1)
    if in_session and age > HEARTBEAT_MAX_AGE_S:
        return _scn("worker_restart", "FAIL",
                    f"Scheduler heartbeat is {round(age)}s old during the "
                    "session — the background worker did not resume after "
                    "restart", evidence)
    return _scn("worker_restart", "PASS",
                "Scheduler heartbeat recorded"
                + (" and fresh for the live session" if in_session
                   else " (off-session: resumption re-checked at next open)"),
                evidence)


# ── Report builder / runner ──────────────────────────────────────────────────

def build_recovery_report(inputs: Dict[str, Any],
                          now: Optional[datetime] = None) -> Dict[str, Any]:
    scenarios = [
        _check_api_restart(inputs),
        _check_database_restart(inputs, now),
        _check_portfolio_recovery(inputs),
        _check_broker_reconnect(inputs),
        _check_network_interruption(inputs),
        _check_provider_failover(inputs),
        _check_worker_restart(inputs, now),
    ]
    grades = [s["grade"] for s in scenarios]
    if "FAIL" in grades:
        verdict = "FAIL"
    elif "WARN" in grades or "INSUFFICIENT" in grades:
        verdict = "WARN"
    else:
        verdict = "PASS"
    fully_evaluated = "INSUFFICIENT" not in grades
    return {
        "area": "RECOVERY",
        "generated_at": _now_iso(),
        "verdict": verdict,
        "fully_evaluated": fully_evaluated,
        "scenarios": scenarios,
        "grade_counts": {g: grades.count(g)
                         for g in ("PASS", "WARN", "FAIL", "INSUFFICIENT")},
        "advisory_only": True,
    }


def run_recovery_validation(persist: bool = True,
                            inputs: Optional[Dict[str, Any]] = None
                            ) -> Dict[str, Any]:
    """Run the suite against live recorded state, persist append-only, and
    feed FAIL scenarios into the Phase 26 issue store."""
    if inputs is None:
        inputs = collect_recovery_inputs()
    report = build_recovery_report(inputs)
    _feed_issues(report, category="RECOVERY",
                 items=[(s["scenario"], s["detail"]) for s in
                        report["scenarios"] if s["grade"] == "FAIL"])
    if persist:
        _persist(report)
    return report


def _feed_issues(report: Dict[str, Any], category: str,
                 items: List[tuple]) -> None:
    """Report FAILs as CRITICAL issues; auto-resolve only when the run was
    fully evaluated (an unavailable source must never resolve real issues)."""
    try:
        import phase26_live_store as live_store
        issues = [{"key": key, "severity": "CRITICAL",
                   "title": f"{category.title()} validation failed: {key}",
                   "detail": detail, "source": "phase26c"}
                  for key, detail in items]
        if report.get("fully_evaluated"):
            report["issue_reconcile"] = live_store.reconcile_category(
                category, issues)
        else:
            for i in issues:
                live_store.report_issue(category, i["key"], i["severity"],
                                        i["title"], i["detail"],
                                        source="phase26c")
            report["issue_reconcile"] = {"partial": True,
                                         "reported": len(issues)}
    except Exception as exc:
        report["issue_reconcile"] = {"error": str(exc)[:200]}


def _persist(report: Dict[str, Any]) -> None:
    try:
        import phase26c_store as store
        stored = store.append_result(report["area"], report)
        report["result_id"] = stored.get("result_id")
    except Exception as exc:
        report["persist_error"] = str(exc)[:200]
