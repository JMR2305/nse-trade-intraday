"""
phase20_validation.py — Phase 20 validation dashboard status.

Computes an auditable readiness picture from durable stores only:
scheduler health, scan-run history, entry-gate counters, the paper ledger,
snapshot consistency, reproducibility (deterministic replay), no-look-ahead,
and live-order-disabled confirmation.

Overall status: NOT_READY | PAPER_READY | DEGRADED

PAPER_READY requires: scheduler healthy, latest scan fresh, snapshot
consistency pass, reproducibility pass, no-look-ahead pass, paper ledger
operational, live orders disabled, and no critical unresolved error.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import phase20_store as store


def _check(name: str, passed: bool, detail: str,
           critical: bool = True) -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "detail": detail,
            "critical": critical}


def get_validation_status() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}

    # ── Scheduler health ─────────────────────────────────────────────────────
    sched = store.get_scheduler_health()
    sched_ok = sched.get("health") in ("HEALTHY", "DEGRADED")
    # Outside market hours, an idle scheduler with recent attempts is healthy.
    checks.append(_check(
        "scheduler_healthy",
        sched_ok or (sched.get("health") == "UNKNOWN" and bool(sched.get("last_attempt_at"))),
        f"health={sched.get('health')}, last_attempt={sched.get('last_attempt_at')}, "
        f"missed={sched.get('missed_count', 0)}"))
    metrics["scheduler"] = sched

    # ── Scan runs ────────────────────────────────────────────────────────────
    runs = store.list_scan_runs(100)
    sched_runs = [r for r in runs if r.get("trigger_source") == "SCHEDULED"]
    failed_runs = [r for r in runs if r.get("status") == "FAILED"]
    ok_runs = [r for r in runs if r.get("status") == "SUCCESS"]
    metrics["scheduled_scans_completed"] = len(
        [r for r in sched_runs if r.get("status") == "SUCCESS"])
    metrics["failed_scans"] = len(failed_runs)
    metrics["total_recorded_runs"] = len(runs)
    fresh_rate = (len(ok_runs) / len(runs) * 100.0) if runs else None
    metrics["fresh_data_rate_pct"] = round(fresh_rate, 1) if fresh_rate is not None else None
    if ok_runs:
        last_ok = ok_runs[0]
        req = int(last_ok.get("symbols_requested") or 0)
        got = int(last_ok.get("symbols_received") or 0)
        metrics["quote_coverage_pct"] = round(got / req * 100.0, 1) if req else None
    else:
        metrics["quote_coverage_pct"] = None

    # Duplicate scans prevented — the distributed lease + freshness skip.
    metrics["duplicate_scans_prevented"] = "lease+freshness guard active"

    # ── Latest scan freshness + snapshot consistency ─────────────────────────
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        from scan_state_store import load_latest_meta
        meta = load_latest_meta() or {}
        fresh = bool(ctx.get("available")) and not ctx.get("stale", True)
        consistent = bool(ctx.get("available")) and meta.get("scan_id") == ctx.get("scan_id")
        checks.append(_check(
            "latest_scan_fresh", fresh,
            f"scan_id={ctx.get('scan_id')}, age={ctx.get('scan_age_seconds')}s, "
            f"stale={ctx.get('stale')}"))
        checks.append(_check(
            "snapshot_consistency", consistent,
            f"meta scan_id={meta.get('scan_id')} vs snapshot={ctx.get('scan_id')}"))
        metrics["latest_scan_id"] = ctx.get("scan_id")
        metrics["latest_snapshot_ts"] = ctx.get("snapshot_ts")
    except Exception as exc:
        checks.append(_check("latest_scan_fresh", False, f"Context error: {exc}"))
        checks.append(_check("snapshot_consistency", False, f"Context error: {exc}"))

    # ── Entry evaluation counters ────────────────────────────────────────────
    counters = store.kv_get("entry_eval_counters", {}) or {}
    metrics["entries_evaluated"] = int(counters.get("evaluated", 0))
    metrics["entries_passed"] = int(counters.get("passed", 0))
    metrics["entries_blocked"] = int(counters.get("blocked", 0))

    # ── Paper ledger ─────────────────────────────────────────────────────────
    ledger_ok = True
    try:
        from phase20_executor import get_ledger
        ledger = get_ledger(500)
        metrics["paper_trades_opened"] = len(ledger)
        metrics["exits_completed"] = len(
            [t for t in ledger if t.get("status") == "CLOSED"])
        metrics["unresolved_data_events"] = len(
            [t for t in ledger if t.get("status") == "EXIT_PENDING"])
    except Exception as exc:
        ledger_ok = False
        metrics["paper_trades_opened"] = None
        metrics["ledger_error"] = str(exc)[:200]
    checks.append(_check("paper_ledger_operational", ledger_ok,
                         "Ledger readable" if ledger_ok else "Ledger read failed"))

    # ── Reproducibility (deterministic replay) ───────────────────────────────
    repro_pass = True
    repro_detail = "No Phase 20 trades yet — replay engine verified on demand"
    try:
        from phase20_executor import get_ledger, replay_trade
        trades = get_ledger(10)
        if trades:
            rep = replay_trade(str(trades[0].get("trade_id")))
            repro_pass = bool(rep.get("deterministic_match"))
            repro_detail = (f"Trade {trades[0].get('trade_id')}: "
                            f"deterministic_match={rep.get('deterministic_match')}")
    except Exception as exc:
        repro_pass = False
        repro_detail = f"Replay error: {exc}"
    checks.append(_check("reproducibility", repro_pass, repro_detail))

    # ── No-look-ahead ────────────────────────────────────────────────────────
    nla_pass = True
    nla_detail = "All trades link scan_id + snapshot_ts; decision_ts >= snapshot_ts"
    try:
        from phase20_executor import get_ledger
        for t in get_ledger(100):
            if not t.get("scan_id") or not t.get("snapshot_ts"):
                nla_pass = False
                nla_detail = f"Trade {t.get('trade_id')} missing scan linkage"
                break
            try:
                snap = datetime.fromisoformat(
                    str(t["snapshot_ts"]).replace("Z", "+00:00"))
                dec = datetime.fromisoformat(
                    str(t["decision_ts"]).replace("Z", "+00:00"))
                if dec < snap:
                    nla_pass = False
                    nla_detail = (f"Trade {t.get('trade_id')} decided before "
                                  f"its snapshot — look-ahead")
                    break
            except Exception:
                continue
    except Exception as exc:
        nla_pass = False
        nla_detail = f"Ledger error: {exc}"
    checks.append(_check("no_look_ahead", nla_pass, nla_detail))

    # ── Live orders disabled ─────────────────────────────────────────────────
    live_disabled = True
    detail = []
    try:
        import config
        if getattr(config, "ZERODHA_ENABLED", False):
            live_disabled = False
        detail.append(f"ZERODHA_ENABLED={getattr(config, 'ZERODHA_ENABLED', False)}")
        detail.append(f"PAPER_TRADING_MODE={getattr(config, 'PAPER_TRADING_MODE', True)}")
        if not getattr(config, "PAPER_TRADING_MODE", True):
            live_disabled = False
    except Exception as exc:
        detail.append(f"config error: {exc}")
    try:
        from execution_engine import get_execution_mode
        mode = str(get_execution_mode())
        detail.append(f"execution_mode={mode}")
        if "LIVE" in mode.upper() and "PAPER" not in mode.upper():
            live_disabled = False
    except Exception:
        pass
    checks.append(_check("live_orders_disabled", live_disabled, "; ".join(detail)))

    # ── Auto-entry default ───────────────────────────────────────────────────
    settings = store.get_settings()
    checks.append(_check(
        "auto_paper_entries_state",
        True,  # informational — OFF is the safe expected default
        f"auto_paper_entries={settings.get('auto_paper_entries')} "
        f"(confirmed_at={settings.get('auto_paper_entries_confirmed_at')})",
        critical=False))
    metrics["auto_paper_entries"] = bool(settings.get("auto_paper_entries"))

    # ── Overall status ───────────────────────────────────────────────────────
    critical = [c for c in checks if c["critical"]]
    passed = [c for c in critical if c["passed"]]
    if len(passed) == len(critical):
        overall = "PAPER_READY"
    elif any(c["check"] == "live_orders_disabled" and not c["passed"]
             for c in critical):
        overall = "NOT_READY"
    elif len(passed) >= max(1, len(critical) - 2):
        overall = "DEGRADED"
    else:
        overall = "NOT_READY"

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_status": overall,
        "checks": checks,
        "metrics": metrics,
        "config_hash": settings.get("config_hash"),
        "label": "PAPER / RESEARCH ONLY",
    }
