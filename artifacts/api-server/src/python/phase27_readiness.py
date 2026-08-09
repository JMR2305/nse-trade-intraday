"""
phase27_readiness.py — Phase 27F: System Readiness dashboard aggregator.

Answers ONE question deterministically: "Is ApexQuant AI ready to safely
run the next/current PAPER trading session?"

Design rules (enforced, not aspirational):
  * READ-ONLY — composes EXISTING canonical health indicators; never
    re-probes where a canonical cached probe exists and never re-implements
    a checker (live_readiness, ops_centre, phase26 recovery/consistency,
    kite_session_manager, phase20 circuit breaker/scheduler are the sources).
  * FAIL-SAFE — a check whose evidence is unavailable is UNKNOWN, never
    READY. A blocking check that is UNKNOWN prevents overall READY.
  * Deterministic fold: any blocking BLOCKED → BLOCKED; else any blocking
    UNKNOWN → UNKNOWN; else any WARNING/BLOCKED(non-blocking)/UNKNOWN →
    WARNING; else READY.
  * No new thresholds — freshness budgets come from the existing constants
    (phase13 STALE_SCAN_MINUTES_*, phase26 HEARTBEAT_MAX_AGE_S, kite
    TOKEN expiry logic) — never hard-coded here beyond importing them.
  * Presence-only for secrets (security-center convention).
  * NEVER imports readiness_checker.py (phase 8 broker module).

History: compact snapshots (overall + counts) are appended to the phase20
KV store under READINESS_HISTORY_KEY (capped) — no new persistence layer.

PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

READY = "READY"
WARNING = "WARNING"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"

READINESS_HISTORY_KEY = "system_readiness_history"
HISTORY_CAP = 500  # compact entries; supports 27.1 history stats windows

# Existing thresholds (imported with explicit fallbacks equal to the
# canonical definitions — the import is authoritative when it succeeds).
try:
    from phase13_intelligence import (STALE_SCAN_MINUTES_MARKET_OPEN,
                                      STALE_SCAN_MINUTES_MARKET_CLOSED)
except Exception:                                    # pragma: no cover
    STALE_SCAN_MINUTES_MARKET_OPEN, STALE_SCAN_MINUTES_MARKET_CLOSED = 90, 720
try:
    from phase26_recovery import HEARTBEAT_MAX_AGE_S
except Exception:                                    # pragma: no cover
    HEARTBEAT_MAX_AGE_S = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_s(value: Any, now: Optional[datetime] = None) -> Optional[float]:
    ts = _parse_ts(value)
    if ts is None:
        return None
    return round(((now or _now()) - ts).total_seconds(), 1)


# ── Input collection (each source fail-soft; unavailable = None + error) ────

def collect_inputs() -> Dict[str, Any]:
    out: Dict[str, Any] = {"_errors": {}}

    def _try(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = None
            out["_errors"][name] = f"{type(exc).__name__}: {exc}"[:200]

    def _scan_meta():
        import scan_state_store
        return scan_state_store.load_latest_meta()

    def _db_durable():
        import scan_state_store
        return bool(scan_state_store.db_available())

    def _market():
        import market_hours
        return market_hours.market_status()

    def _scheduler():
        import phase20_store
        return phase20_store.get_scheduler_health()

    def _settings():
        import phase20_store
        return phase20_store.get_settings()

    def _broker():
        import kite_session_manager
        # Cached canonical probe only — a readiness poll must never hammer
        # the Kite API (60s probe cache inside the session manager).
        return kite_session_manager.get_status(force_probe=False)

    def _breaker():
        import phase20_circuit_breaker
        return phase20_circuit_breaker.get_state()

    def _portfolio_health():
        from portfolio_snapshot import get_portfolio_health
        # emit_alerts=False keeps this aggregator strictly read-only —
        # health polling from the readiness page must never write
        # notifications or KV dedup markers.
        return get_portfolio_health(emit_alerts=False)

    def _system():
        from observability_center.system_health import (get_memory_info,
                                                        get_disk_info,
                                                        get_cpu_info,
                                                        get_environment_status)
        return {"memory": get_memory_info(), "disk": get_disk_info(),
                "cpu": get_cpu_info(), "environment": get_environment_status()}

    def _recovery_latest():
        import phase26c_store
        return phase26c_store.latest_result("RECOVERY")

    def _last_event_ts():
        from pipeline_events import query_events, latest_scan_id
        sid = latest_scan_id()
        if not sid:
            return {"scan_id": None, "last_event_at": None, "count": 0}
        rows = query_events(scan_id=sid, limit=1000)
        last = max((str(r.get("created_at") or r.get("ts") or "")
                    for r in rows), default=None)
        return {"scan_id": sid, "last_event_at": last or None,
                "count": len(rows)}

    def _env_flags():
        import os
        # Presence/booleans only — values of secrets are never read here.
        return {
            "LIVE_EXECUTION_ENABLED":
                os.environ.get("LIVE_EXECUTION_ENABLED", "false").lower(),
            "AUTO_EXECUTION_ENABLED_set":
                bool(os.environ.get("AUTO_EXECUTION_ENABLED")),
            "LIVE_ORDERS_ENABLED_set":
                bool(os.environ.get("LIVE_ORDERS_ENABLED")),
            "SESSION_SECRET_present": bool(os.environ.get("SESSION_SECRET")),
            "DATABASE_URL_present": bool(os.environ.get("DATABASE_URL")),
        }

    def _paper_mode():
        import config
        # Explicit boolean required — an absent or non-boolean attribute is
        # missing evidence (None → UNKNOWN downstream), never assumed True.
        value = getattr(config, "PAPER_TRADING_MODE", None)
        return value if isinstance(value, bool) else None

    _try("scan_meta", _scan_meta)
    _try("db_durable", _db_durable)
    _try("market", _market)
    _try("scheduler", _scheduler)
    _try("settings", _settings)
    _try("broker", _broker)
    _try("breaker", _breaker)
    _try("portfolio_health", _portfolio_health)
    _try("system", _system)
    _try("recovery_latest", _recovery_latest)
    _try("pipeline", _last_event_ts)
    _try("env_flags", _env_flags)
    _try("paper_mode", _paper_mode)
    return out


# ── Check record ─────────────────────────────────────────────────────────────

def _check(check_id: str, domain: str, label: str, status: str, *,
           blocking: bool, expected: str, actual: str,
           evidence: Optional[Dict[str, Any]] = None,
           remediation: str = "", checked_at: Optional[str] = None
           ) -> Dict[str, Any]:
    assert status in (READY, WARNING, BLOCKED, UNKNOWN)
    return {"id": check_id, "domain": domain, "label": label,
            "status": status, "blocking": blocking,
            "expected": expected, "actual": actual,
            "evidence": evidence or {}, "remediation": remediation,
            "checked_at": checked_at or _now_iso()}


def _unavailable(check_id: str, domain: str, label: str, *, blocking: bool,
                 expected: str, error: Optional[str],
                 remediation: str) -> Dict[str, Any]:
    """Missing evidence is UNKNOWN — never READY (fail-safe)."""
    return _check(check_id, domain, label, UNKNOWN, blocking=blocking,
                  expected=expected,
                  actual=f"source unavailable"
                         + (f" — {error}" if error else ""),
                  evidence={"error": error}, remediation=remediation)


# ── Domain checks (pure — take collected inputs) ────────────────────────────

def _market_open(inputs: Dict[str, Any]) -> bool:
    m = inputs.get("market") or {}
    return str(m.get("state") or "").upper() == "OPEN"


def check_market_data(inputs: Dict[str, Any],
                      now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    dom = "Market & Data"
    now = now or _now()
    checks: List[Dict[str, Any]] = []
    meta = inputs.get("scan_meta")
    err = inputs["_errors"].get("scan_meta")
    limit_min = (STALE_SCAN_MINUTES_MARKET_OPEN if _market_open(inputs)
                 else STALE_SCAN_MINUTES_MARKET_CLOSED)
    if meta is None:
        checks.append(_unavailable(
            "scan_freshness", dom, "Canonical scan freshness",
            blocking=True, expected=f"snapshot younger than {limit_min}m",
            error=err or "no scan has ever run",
            remediation="Run a scan from Live Data → Run Scan, or check "
                        "DATABASE_URL / scan_state_store availability."))
    else:
        age = _age_s(meta.get("snapshot_ts"), now)
        if age is None:
            checks.append(_check(
                "scan_freshness", dom, "Canonical scan freshness", UNKNOWN,
                blocking=True,
                expected=f"snapshot younger than {limit_min}m",
                actual="snapshot timestamp missing/unparseable",
                evidence={"snapshot_ts": meta.get("snapshot_ts")},
                remediation="Run a fresh scan; investigate scan_state_store "
                            "if the timestamp stays unparseable."))
        else:
            stale = age > limit_min * 60
            checks.append(_check(
                "scan_freshness", dom, "Canonical scan freshness",
                WARNING if stale else READY, blocking=True,
                expected=f"snapshot younger than {limit_min}m "
                         f"({'market open' if limit_min == STALE_SCAN_MINUTES_MARKET_OPEN else 'market closed'} budget)",
                actual=f"snapshot age {round(age / 60)}m",
                evidence={"scan_id": meta.get("scan_id"),
                          "snapshot_ts": meta.get("snapshot_ts"),
                          "age_seconds": age, "limit_minutes": limit_min},
                remediation="Run a fresh scan (BUY recommendations stay "
                            "disabled while stale — by design)." if stale else ""))
        # Provider coverage from the same durable meta — no re-probe.
        # Canonical field is `symbols_received` (scan_state_store schema).
        req = meta.get("symbols_requested")
        got = meta.get("symbols_received")
        if req in (None, "") or got in (None, ""):
            checks.append(_check(
                "provider_coverage", dom, "Data provider coverage", UNKNOWN,
                blocking=False,
                expected="provider delivered the configured universe",
                actual="coverage fields missing from scan metadata",
                evidence={"symbols_requested": req, "symbols_received": got},
                remediation="Re-run a scan; older snapshots may predate "
                            "provider-health recording."))
        else:
            try:
                r, g = int(req), int(got)
            except (TypeError, ValueError):
                checks.append(_check(
                    "provider_coverage", dom, "Data provider coverage",
                    UNKNOWN, blocking=False,
                    expected="provider delivered the configured universe",
                    actual="coverage fields malformed in scan metadata",
                    evidence={"symbols_requested": repr(req),
                              "symbols_received": repr(got)},
                    remediation="Re-run a scan; investigate corrupted scan "
                                "metadata if this persists."))
                return checks
            status = READY if (r > 0 and g >= r) else (
                BLOCKED if g <= 0 else WARNING)
            checks.append(_check(
                "provider_coverage", dom, "Data provider coverage", status,
                blocking=False,
                expected=f"{r}/{r} symbols from the provider chain",
                actual=f"{g}/{r} symbols delivered",
                evidence={"provider": meta.get("provider"),
                          "symbols_requested": r, "symbols_received": g},
                remediation="" if status == READY else
                            "Check provider chain (NSE → Kite → Yahoo) on "
                            "the Live Data page; zero coverage means every "
                            "provider failed."))
    return checks


def check_broker(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Broker & Authentication"
    br = inputs.get("broker")
    if br is None:
        return [_unavailable(
            "broker_session", dom, "Zerodha Kite session",
            blocking=False, expected="coherent session state",
            error=inputs["_errors"].get("broker"),
            remediation="Check the Kite Connect page; the session manager "
                        "could not report a state.")]
    state = str(br.get("connection_state") or "").upper()
    evidence = {"connection_state": state,
                "token_status": br.get("token_status"),
                "probe_source": br.get("probe_source"),
                "last_success_at": br.get("last_success_at")}
    # Paper trading never requires a broker session — broker checks are
    # non-blocking, mirroring phase26 recovery's classification.
    if state == "CONNECTED":
        status, actual, rem = READY, "authenticated probe succeeded", ""
    elif state in ("LOGIN_REQUIRED", "TOKEN_EXPIRED", "NOT_CONFIGURED"):
        status = WARNING
        actual = f"{state} — expected outside a logged-in trading day"
        rem = ("Use Login with Zerodha (Kite Connect page) before the "
               "session if live quotes are wanted; paper trading continues "
               "on the fallback provider chain.")
    elif state in ("API_ERROR", "AUTH_FAILED"):
        status = WARNING
        actual = f"{state} — last probe/authentication failed"
        rem = "Re-login on the Kite Connect page and re-check."
    else:
        status, actual = UNKNOWN, f"unrecognised state '{state}'"
        rem = "Inspect /api/kite/status."
    return [_check("broker_session", dom, "Zerodha Kite session", status,
                   blocking=False,
                   expected="CONNECTED (or an expected logged-out state)",
                   actual=actual, evidence=evidence, remediation=rem)]


def check_pipeline(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Pipeline"
    checks: List[Dict[str, Any]] = []
    meta = inputs.get("scan_meta")
    if meta is None:
        checks.append(_unavailable(
            "last_scan_outcome", dom, "Last scan outcome", blocking=True,
            expected="last recorded scan completed successfully",
            error=inputs["_errors"].get("scan_meta"),
            remediation="Run a scan; verify scan_state_store."))
    else:
        status_s = str(meta.get("status") or "").upper()
        err = meta.get("error")
        ok = status_s in ("SUCCESS", "COMPLETED", "OK") or (
            not err and meta.get("scan_id"))
        checks.append(_check(
            "last_scan_outcome", dom, "Last scan outcome",
            READY if ok else WARNING, blocking=True,
            expected="last recorded scan completed successfully",
            actual=f"status={status_s or '—'}"
                   + (f", error recorded: {str(err)[:120]}" if err else ""),
            evidence={"scan_id": meta.get("scan_id"), "status": status_s,
                      "error": err},
            remediation="" if ok else
                        "Investigate the recorded scan error (Replay / "
                        "Investigation Centre); failed scans never "
                        "overwrite the last good snapshot."))
    pipe = inputs.get("pipeline")
    if pipe is None:
        checks.append(_unavailable(
            "pipeline_events", dom, "Pipeline event stream", blocking=False,
            expected="events recorded for the latest scan",
            error=inputs["_errors"].get("pipeline"),
            remediation="Check pipeline_events store availability."))
    else:
        n = int(pipe.get("count") or 0)
        checks.append(_check(
            "pipeline_events", dom, "Pipeline event stream",
            READY if n > 0 else WARNING, blocking=False,
            expected="events recorded for the latest scan",
            actual=f"{n} events for scan {pipe.get('scan_id') or '—'}",
            evidence=pipe,
            remediation="" if n > 0 else
                        "No pipeline events for the latest scan — Mission "
                        "Control / Investigation pages will be empty until "
                        "the next scan."))
    return checks


def check_strategy_risk(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Strategy & Risk"
    st = inputs.get("settings")
    if st is None:
        return [_unavailable(
            "risk_config", dom, "Risk configuration readable", blocking=True,
            expected="entry-gate settings readable",
            error=inputs["_errors"].get("settings"),
            remediation="phase20 settings store unreadable — entry gates "
                        "cannot be evaluated; investigate the database.")]
    return [_check(
        "risk_config", dom, "Risk configuration readable", READY,
        blocking=True, expected="entry-gate settings readable",
        actual="settings loaded",
        evidence={"daily_loss_limit_pct": st.get("daily_loss_limit_pct"),
                  "max_trades_per_day": st.get("max_trades_per_day"),
                  "risk_per_trade_pct": st.get("risk_per_trade_pct"),
                  "circuit_breaker_loss_threshold":
                      st.get("circuit_breaker_loss_threshold")})]


def check_execution(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Execution"
    st = inputs.get("settings")
    checks: List[Dict[str, Any]] = []
    if st is None:
        checks.append(_unavailable(
            "auto_entries_state", dom, "Auto paper entries state",
            blocking=False, expected="explicit ON/OFF state readable",
            error=inputs["_errors"].get("settings"),
            remediation="Settings store unreadable."))
    else:
        on = bool(st.get("auto_paper_entries"))
        confirmed = st.get("auto_paper_entries_confirmed_at")
        checks.append(_check(
            "auto_entries_state", dom, "Auto paper entries state", READY,
            blocking=False,
            expected="OFF by default; ON only with recorded confirmation",
            actual=("ON (confirmed)" if on and confirmed
                    else "ON without confirmation — forced OFF by store"
                    if on else "OFF"),
            evidence={"auto_paper_entries": on,
                      "confirmed_at": confirmed}))
    return checks


def check_portfolio(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Portfolio"
    ph = inputs.get("portfolio_health")
    if ph is None:
        return [_unavailable(
            "portfolio_health", dom, "Portfolio service health",
            blocking=True, expected="portfolio state loads and reconciles",
            error=inputs["_errors"].get("portfolio_health"),
            remediation="Portfolio health endpoint failed — check the "
                        "Broker Execution page and database.")]
    status_s = str(ph.get("status") or ph.get("health") or "").upper()
    degraded = status_s in ("DEGRADED", "WARN", "WARNING")
    down = status_s in ("DOWN", "ERROR", "FAIL", "FAILED")
    unresolved = ph.get("unresolved_discrepancies",
                        ph.get("unresolved_count"))
    status = BLOCKED if down else (WARNING if degraded else
                                   READY if status_s else UNKNOWN)
    return [_check(
        "portfolio_health", dom, "Portfolio service health", status,
        blocking=True,
        expected="portfolio state loads and reconciles cleanly",
        actual=f"status={status_s or 'not reported'}"
               + (f", {unresolved} unresolved discrepancies"
                  if unresolved else ""),
        evidence={k: ph.get(k) for k in
                  ("status", "initialized", "paper_automation_active",
                   "unresolved_discrepancies", "unresolved_count",
                   "state_age_seconds") if k in ph},
        remediation="" if status == READY else
                    "Open the Broker Execution / Portfolio page and "
                    "resolve reported discrepancies before the session.")]


def check_persistence_recovery(inputs: Dict[str, Any],
                               now: Optional[datetime] = None
                               ) -> List[Dict[str, Any]]:
    dom = "Persistence & Recovery"
    now = now or _now()
    checks: List[Dict[str, Any]] = []
    dbd = inputs.get("db_durable")
    if dbd is None:
        checks.append(_unavailable(
            "db_durability", dom, "Durable Postgres state", blocking=True,
            expected="scan/portfolio state Postgres-backed",
            error=inputs["_errors"].get("db_durable"),
            remediation="scan_state_store could not report durability."))
    else:
        checks.append(_check(
            "db_durability", dom, "Durable Postgres state",
            READY if dbd else WARNING, blocking=True,
            expected="scan/portfolio state Postgres-backed",
            actual="Postgres-backed" if dbd else
                   "file-backed only — a restart on another instance "
                   "loses state",
            evidence={"db_available": bool(dbd)},
            remediation="" if dbd else "Configure DATABASE_URL."))
    rec = inputs.get("recovery_latest")
    if rec is None and "recovery_latest" in inputs["_errors"]:
        checks.append(_unavailable(
            "recovery_validation", dom, "Recovery validation (Phase 26C)",
            blocking=False, expected="latest recovery suite PASS",
            error=inputs["_errors"].get("recovery_latest"),
            remediation="phase26c store unreadable."))
    elif not rec:
        checks.append(_check(
            "recovery_validation", dom, "Recovery validation (Phase 26C)",
            UNKNOWN, blocking=False,
            expected="latest recovery suite PASS",
            actual="no recovery validation run recorded yet",
            remediation="Run the recovery suite from the Validation "
                        "Dashboard (read-only)."))
    else:
        verdict = str(rec.get("verdict") or "").upper()
        age = _age_s(rec.get("created_at"), now)
        status = (READY if verdict == "PASS" else
                  WARNING if verdict in ("WARN", "WARNING") else
                  BLOCKED if verdict == "FAIL" else UNKNOWN)
        checks.append(_check(
            "recovery_validation", dom, "Recovery validation (Phase 26C)",
            status, blocking=False,
            expected="latest recovery suite PASS",
            actual=f"verdict {verdict or '—'}"
                   + (f", run {round(age/3600, 1)}h ago" if age else ""),
            evidence={"verdict": verdict, "created_at": rec.get("created_at"),
                      "result_id": rec.get("result_id")},
            remediation="" if status == READY else
                        "Open the Validation Dashboard → Recovery for the "
                        "failing scenario detail; re-run after fixing."))
    return checks


def check_scheduling(inputs: Dict[str, Any],
                     now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    dom = "Scheduling"
    now = now or _now()
    sched = inputs.get("scheduler")
    if sched is None:
        return [_unavailable(
            "scheduler_health", dom, "Scan scheduler", blocking=True,
            expected="scheduler heartbeat within budget",
            error=inputs["_errors"].get("scheduler"),
            remediation="Scheduler health unreadable — check phase20 store.")]
    health = str(sched.get("health") or "").upper()
    in_session = _market_open(inputs)
    hb_age = _age_s(sched.get("heartbeat_at") or sched.get("last_attempt_at"),
                    now)
    evidence = {"health": health, "heartbeat_at": sched.get("heartbeat_at"),
                "heartbeat_age_s": hb_age, "in_session": in_session,
                "auto_scan_enabled": sched.get("auto_scan_enabled"),
                "last_error": sched.get("last_error")}
    if health == "HEALTHY":
        status, actual = READY, "HEALTHY"
    elif health == "DISABLED":
        status, actual = WARNING, "auto-scan DISABLED"
    elif health == "DEGRADED":
        status, actual = WARNING, "DEGRADED"
    elif health == "DOWN":
        status = BLOCKED if in_session else WARNING
        actual = "DOWN" + ("" if in_session else " (off-session)")
    elif health == "UNKNOWN" or not health:
        status, actual = UNKNOWN, "health not reported"
    else:
        status, actual = UNKNOWN, f"unrecognised health '{health}'"
    if in_session and hb_age is not None and hb_age > HEARTBEAT_MAX_AGE_S \
            and status == READY:
        status = WARNING
        actual += f"; heartbeat {round(hb_age)}s old (budget {HEARTBEAT_MAX_AGE_S}s)"
    return [_check(
        "scheduler_health", dom, "Scan scheduler", status, blocking=True,
        expected=f"HEALTHY with heartbeat < {HEARTBEAT_MAX_AGE_S}s in session",
        actual=actual, evidence=evidence,
        remediation="" if status == READY else
                    "Check Settings → auto-scan and the api-server workflow; "
                    "the scheduler resumes on process start.")]


def check_safety(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Safety Controls"
    checks: List[Dict[str, Any]] = []
    flags = inputs.get("env_flags")
    if flags is None:
        checks.append(_unavailable(
            "execution_mode", dom, "Execution mode (paper-only)",
            blocking=True, expected="LIVE_EXECUTION_ENABLED off",
            error=inputs["_errors"].get("env_flags"),
            remediation="Environment flags unreadable — refusing to assume "
                        "paper mode."))
    else:
        live = str(flags.get("LIVE_EXECUTION_ENABLED", "false")) \
            in ("1", "true", "yes")
        extra = flags.get("AUTO_EXECUTION_ENABLED_set") or \
            flags.get("LIVE_ORDERS_ENABLED_set")
        paper = inputs.get("paper_mode")
        if live or extra:
            checks.append(_check(
                "execution_mode", dom, "Execution mode (paper-only)",
                BLOCKED, blocking=True,
                expected="LIVE_EXECUTION_ENABLED off; no live-order flags set",
                actual="a live-execution flag is set — configuration "
                       "suggests live execution",
                evidence={"LIVE_EXECUTION_ENABLED": flags.get(
                              "LIVE_EXECUTION_ENABLED"),
                          "AUTO_EXECUTION_ENABLED_set":
                              flags.get("AUTO_EXECUTION_ENABLED_set"),
                          "LIVE_ORDERS_ENABLED_set":
                              flags.get("LIVE_ORDERS_ENABLED_set")},
                remediation="Unset LIVE_EXECUTION_ENABLED / "
                            "AUTO_EXECUTION_ENABLED / LIVE_ORDERS_ENABLED. "
                            "This platform is paper trading / research only."))
        elif paper is None:
            # Paper-mode evidence unavailable → UNKNOWN, never READY
            # (fail-safe: absence of evidence is not evidence of safety).
            checks.append(_check(
                "execution_mode", dom, "Execution mode (paper-only)",
                UNKNOWN, blocking=True,
                expected="PAPER TRADING mode verified; live flags off",
                actual="live flags are off, but config.PAPER_TRADING_MODE "
                       "could not be read",
                evidence={"paper_trading_mode": None,
                          "live_flags_set": False,
                          "error": inputs["_errors"].get("paper_mode")},
                remediation="Investigate why config.py failed to load; "
                            "readiness stays non-READY until paper mode "
                            "is positively verified."))
        elif paper is not True:
            checks.append(_check(
                "execution_mode", dom, "Execution mode (paper-only)",
                BLOCKED, blocking=True,
                expected="config.PAPER_TRADING_MODE = True; live flags off",
                actual="config.PAPER_TRADING_MODE is False — platform is "
                       "not verified as paper-only",
                evidence={"paper_trading_mode": paper,
                          "live_flags_set": False},
                remediation="Restore PAPER_TRADING_MODE = True in config. "
                            "This platform is paper trading / research "
                            "only."))
        else:
            checks.append(_check(
                "execution_mode", dom, "Execution mode (paper-only)",
                READY, blocking=True,
                expected="PAPER TRADING mode verified; live flags off",
                actual="PAPER TRADING verified — no live-execution flags set",
                evidence={"paper_trading_mode": True,
                          "live_flags_set": False}))
    br = inputs.get("breaker")
    if br is None:
        checks.append(_unavailable(
            "circuit_breaker", dom, "Entry circuit breaker", blocking=True,
            expected="not tripped (or reviewed)",
            error=inputs["_errors"].get("breaker"),
            remediation="Breaker state unreadable — entries are blocked "
                        "fail-safe by the executor."))
    else:
        tripped = bool(br.get("tripped"))
        unreadable = bool(br.get("unreadable"))
        codes = ", ".join(r.get("code", "?") for r in br.get("reasons") or [])
        status = BLOCKED if (tripped or unreadable) else READY
        checks.append(_check(
            "circuit_breaker", dom, "Entry circuit breaker", status,
            blocking=True, expected="not tripped",
            actual=("state UNREADABLE — entries blocked fail-safe"
                    if unreadable else
                    f"TRIPPED ({codes})" if tripped else "clear"),
            evidence={"tripped": tripped, "unreadable": unreadable,
                      "reasons": br.get("reasons"),
                      "tripped_at": br.get("tripped_at")},
            remediation="" if status == READY else
                        "Manual review required: resume from the Trading "
                        "page with the exact confirmation statement."))
    return checks


def check_configuration(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    dom = "Configuration"
    checks: List[Dict[str, Any]] = []
    flags = inputs.get("env_flags")
    if flags is None:
        checks.append(_unavailable(
            "critical_env", dom, "Critical environment variables",
            blocking=True, expected="DATABASE_URL and SESSION_SECRET present",
            error=inputs["_errors"].get("env_flags"),
            remediation="Environment unreadable."))
    else:
        missing = [k for k, present in
                   (("DATABASE_URL", flags.get("DATABASE_URL_present")),
                    ("SESSION_SECRET", flags.get("SESSION_SECRET_present")))
                   if not present]
        checks.append(_check(
            "critical_env", dom, "Critical environment variables",
            BLOCKED if missing else READY, blocking=True,
            expected="DATABASE_URL and SESSION_SECRET present "
                     "(presence-only check)",
            actual=("missing: " + ", ".join(missing)) if missing
                   else "all present",
            evidence={"missing": missing},
            remediation="Set the missing variable(s) in Secrets."
                        if missing else ""))
    sysd = inputs.get("system")
    if sysd is None:
        checks.append(_unavailable(
            "system_resources", dom, "System resources", blocking=False,
            expected="memory/disk below degradation thresholds",
            error=inputs["_errors"].get("system"),
            remediation="/proc introspection failed."))
    else:
        degraded = [name for name, c in
                    (("memory", sysd.get("memory") or {}),
                     ("disk", sysd.get("disk") or {}),
                     ("cpu", sysd.get("cpu") or {}))
                    if str(c.get("status") or "").upper() == "DEGRADED"]
        unknown = [name for name, c in
                   (("memory", sysd.get("memory") or {}),
                    ("disk", sysd.get("disk") or {}),
                    ("cpu", sysd.get("cpu") or {}))
                   if not c.get("available")]
        status = WARNING if degraded else (UNKNOWN if unknown else READY)
        checks.append(_check(
            "system_resources", dom, "System resources", status,
            blocking=False,
            expected="memory/disk/cpu below degradation thresholds",
            actual=("degraded: " + ", ".join(degraded)) if degraded else
                   ("unreadable: " + ", ".join(unknown)) if unknown
                   else "healthy",
            evidence={"memory_pct": (sysd.get("memory") or {}).get("usage_pct"),
                      "disk_pct": (sysd.get("disk") or {}).get("usage_pct"),
                      "load_1m": (sysd.get("cpu") or {}).get("load_1m")},
            remediation="Free memory/disk or restart the workflow."
                        if degraded else ""))
    return checks


# ── Freshness section (existing thresholds only) ─────────────────────────────

def build_freshness(inputs: Dict[str, Any],
                    now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    in_session = _market_open(inputs)
    scan_limit_s = (STALE_SCAN_MINUTES_MARKET_OPEN if in_session
                    else STALE_SCAN_MINUTES_MARKET_CLOSED) * 60
    rows: List[Dict[str, Any]] = []

    def row(name: str, ts: Any, limit_s: Optional[float],
            source: str, note: str = "") -> None:
        age = _age_s(ts, now)
        if ts is None or age is None:
            status = UNKNOWN
        elif limit_s is None:
            status = READY
        else:
            status = WARNING if age > limit_s else READY
        rows.append({"name": name, "ts": ts, "age_seconds": age,
                     "limit_seconds": limit_s, "status": status,
                     "source": source, "note": note})

    meta = inputs.get("scan_meta") or {}
    row("Canonical scan snapshot", meta.get("snapshot_ts"), scan_limit_s,
        "scan_state_store", "budget from phase13 stale-scan constants")
    pipe = inputs.get("pipeline") or {}
    row("Latest pipeline event", pipe.get("last_event_at"), scan_limit_s,
        "pipeline_events", "same budget as the scan snapshot")
    sched = inputs.get("scheduler") or {}
    row("Scheduler heartbeat",
        sched.get("heartbeat_at") or sched.get("last_attempt_at"),
        float(HEARTBEAT_MAX_AGE_S) if in_session else None,
        "phase20 scheduler",
        "budget enforced in session only (phase26 HEARTBEAT_MAX_AGE_S)")
    br = inputs.get("broker") or {}
    row("Broker probe success", br.get("last_success_at"), None,
        "kite_session_manager", "informational — daily 06:00 IST expiry")
    return rows


# ── Overall fold + report ─────────────────────────────────────────────────────

def derive_overall(checks: List[Dict[str, Any]]) -> str:
    blocking = [c for c in checks if c["blocking"]]
    if any(c["status"] == BLOCKED for c in blocking):
        return BLOCKED
    if any(c["status"] == UNKNOWN for c in blocking):
        return UNKNOWN
    if any(c["status"] in (WARNING, BLOCKED, UNKNOWN) for c in checks):
        return WARNING
    return READY


def build_report(inputs: Optional[Dict[str, Any]] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    if inputs is None:
        inputs = collect_inputs()
    now = now or _now()
    checks: List[Dict[str, Any]] = []
    checks += check_market_data(inputs, now)
    checks += check_broker(inputs)
    checks += check_pipeline(inputs)
    checks += check_strategy_risk(inputs)
    checks += check_execution(inputs)
    checks += check_portfolio(inputs)
    checks += check_persistence_recovery(inputs, now)
    checks += check_scheduling(inputs, now)
    checks += check_safety(inputs)
    checks += check_configuration(inputs)

    overall = derive_overall(checks)
    counts = {s: sum(1 for c in checks if c["status"] == s)
              for s in (READY, WARNING, BLOCKED, UNKNOWN)}
    domains: List[Dict[str, Any]] = []
    for c in checks:
        d = next((x for x in domains if x["domain"] == c["domain"]), None)
        if d is None:
            d = {"domain": c["domain"], "checks": []}
            domains.append(d)
        d["checks"].append(c)
    for d in domains:
        d["status"] = derive_overall(d["checks"])

    market = inputs.get("market") or {}
    return {
        "ok": True,
        "generated_at": _now_iso(),
        "overall": overall,
        "counts": counts,
        "domains": domains,
        "freshness": build_freshness(inputs, now),
        "market": {"state": market.get("state"),
                   "is_open": market.get("is_open"),
                   "next_transition": market.get("next_transition")},
        "source_errors": inputs.get("_errors") or {},
        "paper_trading_only": True,
        "advisory_only": True,
        "note": ("Deterministic readiness fold over canonical health "
                 "sources. Missing evidence is UNKNOWN, never READY. "
                 "PAPER TRADING / RESEARCH ONLY."),
    }


# ── Light history (existing KV infrastructure) ───────────────────────────────

def record_history(report: Dict[str, Any]) -> None:
    """Append a compact snapshot (never the full report). Fail-soft."""
    try:
        import phase20_store as store
        log = store.kv_get(READINESS_HISTORY_KEY) or []
        if not isinstance(log, list):
            log = []
        all_checks = [c for d in report.get("domains") or []
                      for c in d.get("checks") or []]
        log.append({"at": report.get("generated_at"),
                    "overall": report.get("overall"),
                    "counts": report.get("counts"),
                    "blocking_failures": [
                        c["id"] for c in all_checks
                        if c.get("blocking")
                        and c.get("status") in (BLOCKED, UNKNOWN)],
                    # Compact issue list for the 27.1 readiness timeline —
                    # reason/component per non-READY check (capped).
                    "issues": [{"id": c.get("id"),
                                "domain": c.get("domain"),
                                "status": c.get("status"),
                                "blocking": bool(c.get("blocking")),
                                "actual": str(c.get("actual") or "")[:140]}
                               for c in all_checks
                               if c.get("status") != READY][:10]})
        store.kv_set(READINESS_HISTORY_KEY, log[-HISTORY_CAP:])
    except Exception:
        pass


def get_history(limit: int = 20) -> Dict[str, Any]:
    try:
        import phase20_store as store
        log = store.kv_get(READINESS_HISTORY_KEY) or []
        if not isinstance(log, list):
            log = []
        return {"ok": True, "entries": list(reversed(log))[: int(limit)]}
    except Exception as exc:
        return {"ok": True, "entries": [],
                "error": f"{type(exc).__name__}: {exc}"[:200]}


def system_readiness_report(record: bool = True) -> Dict[str, Any]:
    """Entry point for main.py — safe, read-only re-evaluation."""
    report = build_report()
    if record:
        record_history(report)
    return report
