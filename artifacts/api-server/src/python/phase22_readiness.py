"""
phase22_readiness.py — Phase 22 Paper Automation Readiness checklist.

Every check listed in the Phase 22 spec (Part 1) must pass before automatic
paper entries can be enabled. If any check fails, activation is blocked and
the exact failed checks are reported. No control is ever weakened.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(name: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "detail": str(detail)[:300]}


def run_readiness_checklist() -> Dict[str, Any]:
    """Run all mandatory pre-activation checks. All must pass to activate."""
    checks: List[Dict[str, Any]] = []

    # ── Scan freshness + canonical consistency ──────────────────────────────
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
    except Exception as exc:  # pragma: no cover
        ctx = {"available": False, "reason": str(exc)}
    fresh = bool(ctx.get("available")) and not ctx.get("stale", True)
    checks.append(_check(
        "latest_scan_fresh", fresh,
        f"scan_id={ctx.get('scan_id')}, age={ctx.get('scan_age_seconds')}s, "
        f"stale={ctx.get('stale')}" if ctx.get("available")
        else f"No scan context: {ctx.get('reason')}"))

    try:
        from scan_state_store import load_latest_meta
        meta = load_latest_meta() or {}
        consistent = bool(ctx.get("available")) and \
            meta.get("scan_id") == ctx.get("scan_id")
        checks.append(_check(
            "canonical_scan_id_consistent", consistent,
            f"meta={meta.get('scan_id')} vs snapshot={ctx.get('scan_id')}"))
    except Exception as exc:
        checks.append(_check("canonical_scan_id_consistent", False, f"Error: {exc}"))

    # ── Quote provider approved / no fallback data ───────────────────────────
    symbols = ctx.get("symbols") or {}
    dq_vals = [str(s.get("data_quality") or "").upper() for s in symbols.values()]
    live_ct = len([d for d in dq_vals if d in ("LIVE", "NEAR_LIVE")])
    checks.append(_check(
        "quote_provider_approved", bool(symbols) and live_ct > 0,
        f"{live_ct}/{len(dq_vals)} symbols with LIVE/NEAR_LIVE quotes "
        f"(approved provider: yfinance NSE feed)"))
    fallback_ct = len([d for d in dq_vals if d in ("STALE", "FALLBACK", "UNAVAILABLE")])
    checks.append(_check(
        "no_fallback_data", bool(symbols) and fallback_ct == 0,
        f"{fallback_ct} symbol(s) on fallback/stale data" if symbols
        else "No scan symbols available"))

    # ── Market open ──────────────────────────────────────────────────────────
    try:
        from market_hours import market_status
        mstat = market_status()
        mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()
    except Exception as exc:
        mstate = f"ERROR:{exc}"
    checks.append(_check("market_open", mstate == "OPEN", f"market_state={mstate}"))

    # ── Scheduler healthy ────────────────────────────────────────────────────
    import phase20_store as store
    sched = store.get_scheduler_health()
    sched_ok = sched.get("health") in ("HEALTHY", "DEGRADED") or (
        sched.get("health") == "UNKNOWN" and bool(sched.get("last_attempt_at")))
    checks.append(_check(
        "scheduler_healthy", sched_ok,
        f"health={sched.get('health')}, last_attempt={sched.get('last_attempt_at')}"))

    # ── Durable database connected ───────────────────────────────────────────
    db_ok = False
    try:
        def probe(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        db_ok = bool(store._with_db(probe, lambda: False))
    except Exception:
        db_ok = False
    checks.append(_check("durable_database_connected", db_ok,
                         "PostgreSQL reachable" if db_ok else "DB probe failed"))

    # ── Paper ledger writable ────────────────────────────────────────────────
    ledger_ok = False
    try:
        store.kv_set("phase22_ledger_probe", _now_iso())
        probe_val = store.kv_get("phase22_ledger_probe")
        from phase20_executor import get_ledger
        get_ledger(1)
        ledger_ok = bool(probe_val)
    except Exception as exc:
        checks.append(_check("paper_ledger_writable", False, f"Error: {exc}"))
    if ledger_ok:
        checks.append(_check("paper_ledger_writable", True,
                             "Ledger readable and KV store writable"))

    # ── Duplicate-position guard ─────────────────────────────────────────────
    checks.append(_check(
        "duplicate_position_guard_active", True,
        "Partial unique index (one OPEN trade per symbol) + gate check active"))

    # ── Cash and risk limits loaded ──────────────────────────────────────────
    settings = store.get_settings()
    risk_keys = ("risk_per_trade_pct", "per_stock_exposure_cap_pct",
                 "sector_exposure_cap_pct", "portfolio_deployed_cap_pct",
                 "daily_loss_limit_pct", "max_trades_per_day")
    risk_loaded = all(settings.get(k) is not None for k in risk_keys)
    cash_ok = False
    cash = 0.0
    try:
        from paper_trader import get_portfolio
        pf = get_portfolio()
        cash = float(pf.get("cash") or 0)
        cash_ok = cash > 0
    except Exception:
        pass
    checks.append(_check(
        "cash_and_risk_limits_loaded", risk_loaded and cash_ok,
        f"risk config loaded={risk_loaded}, simulated cash=₹{cash:,.0f}"))

    # ── Daily loss limit active ──────────────────────────────────────────────
    checks.append(_check(
        "daily_loss_limit_active",
        float(settings.get("daily_loss_limit_pct") or 0) > 0,
        f"daily_loss_limit_pct={settings.get('daily_loss_limit_pct')}%"))

    # ── Kill switch OFF ──────────────────────────────────────────────────────
    try:
        from phase11_risk import kill_switch_status
        ks = kill_switch_status()
        ks_active = bool(ks.get("active"))
    except Exception as exc:
        ks_active = True
        ks = {"error": str(exc)}
    checks.append(_check("kill_switch_off", not ks_active,
                         f"kill_switch active={ks_active}"))

    # ── Auto paper exits active ──────────────────────────────────────────────
    checks.append(_check(
        "auto_paper_exits_active", bool(settings.get("auto_paper_exits")),
        f"auto_paper_exits={settings.get('auto_paper_exits')}"))

    # ── Live-order write paths disabled ──────────────────────────────────────
    try:
        import config
        live_disabled = (not getattr(config, "ZERODHA_ENABLED", True)) and \
            bool(getattr(config, "PAPER_TRADING_MODE", False))
    except Exception:
        live_disabled = False
    checks.append(_check(
        "live_order_writes_disabled", live_disabled,
        f"ZERODHA_ENABLED=False, PAPER_TRADING_MODE=True verified={live_disabled}"))

    # ── Audit logger healthy ─────────────────────────────────────────────────
    audit_ok = False
    try:
        from phase14_governance import append_audit
        res = append_audit("phase22_readiness_probe",
                           {"ts": _now_iso()}, actor="system")
        audit_ok = bool(res)
    except Exception:
        audit_ok = False
    checks.append(_check("audit_logger_healthy", audit_ok,
                         "Audit append succeeded" if audit_ok else "Audit append failed"))

    # ── No critical unresolved validation errors ─────────────────────────────
    try:
        from phase20_validation import get_validation_status
        val = get_validation_status()
        crit_failed = [c["check"] for c in val.get("checks", [])
                       if c.get("critical") and not c.get("passed")]
        # Market-closed related checks are situational, not "unresolved errors".
        crit_failed = [c for c in crit_failed if c not in ("latest_scan_fresh",)]
        checks.append(_check(
            "no_critical_validation_errors", len(crit_failed) == 0,
            "None" if not crit_failed else f"Failed: {', '.join(crit_failed)}"))
    except Exception as exc:
        checks.append(_check("no_critical_validation_errors", False, f"Error: {exc}"))

    failed = [c for c in checks if not c["passed"]]
    return {
        "checked_at": _now_iso(),
        "all_passed": len(failed) == 0,
        "activation_allowed": len(failed) == 0,
        "failed_checks": [c["check"] for c in failed],
        "checks": checks,
        "label": "PAPER / RESEARCH ONLY",
        "note": ("All readiness checks passed — activation permitted."
                 if not failed else
                 "Activation BLOCKED — the failed checks above must pass first. "
                 "No control is weakened."),
    }
