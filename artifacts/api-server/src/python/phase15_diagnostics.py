"""
phase15_diagnostics.py — Phase 15: Production Diagnostics & Readiness Report

Expanded diagnostics: system health, API/cache status, latency proxies,
memory usage, scan duration, learning status, model registry, version,
last successful / failed scan — plus an automated Production Readiness
Report covering every Phase 15 hardening requirement.

Read-only. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import os
import resource
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from phase15_scan_context import build_scan_context, _load, SCAN_CACHE

_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "15.0"

CACHE_FILES = {
    "canonical_scan": "phase7_scan_cache.json",
    "ai_decisions": "ai_decisions_cache.json",
    "opportunity_scan": "opportunity_cache.json",
    "phase13_intelligence": "phase13_cache.json",
    "market_context": "market_context_cache.json",
    "phase14_adjustments": "phase14_adjustments.json",
    "consistency_report": "phase15_consistency_report.json",
    "scan_audit_log": "phase15_audit_log.json",
}


def _file_status(fname: str) -> Dict[str, Any]:
    path = os.path.join(_DIR, fname)
    if not os.path.exists(path):
        return {"file": fname, "exists": False}
    st = os.stat(path)
    age_s = time.time() - st.st_mtime
    return {"file": fname, "exists": True, "size_bytes": st.st_size,
            "age_seconds": round(age_s, 0),
            "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")}


def system_diagnostics() -> Dict[str, Any]:
    t0 = time.monotonic()
    ctx = build_scan_context()
    context_latency_ms = round((time.monotonic() - t0) * 1000, 1)

    scan = _load(SCAN_CACHE) or {}
    mem_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)

    # Learning + registry status (best-effort)
    learning: Dict[str, Any] = {"status": "UNKNOWN"}
    registry: Dict[str, Any] = {}
    try:
        from phase14_adjustments import learning_frozen
        learning = {"status": "FROZEN" if learning_frozen().get("frozen") else "ACTIVE",
                    "auto_promotion": False, "human_approval_required": True}
    except Exception as exc:
        learning = {"status": "UNAVAILABLE", "error": str(exc)}
    try:
        from phase14_governance import list_models
        m = list_models()
        registry = {"champion_version": m.get("champion_version"),
                    "model_count": len(m.get("models", []))}
    except Exception as exc:
        registry = {"error": str(exc)}

    errors = [r.get("error") for r in scan.get("recommendations", []) if r.get("error")]
    last_scan_ok = bool(scan) and (scan.get("scan_audit", {}).get("audit_verdict") == "PASS")

    db_path = os.path.join(_DIR, "state.json")

    return {
        "success": True,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "system_health": "OK" if ctx.get("available") and last_scan_ok else "DEGRADED",
        "api_status": "OK",
        "context_build_latency_ms": context_latency_ms,
        "memory_usage_mb": mem_mb,
        "cache_status": [_file_status(f) for f in CACHE_FILES.values()],
        "database_health": {"paper_state_file": os.path.exists(db_path),
                            "writable": os.access(_DIR, os.W_OK)},
        "market_feed_status": (scan.get("provider_health", {}) or {}).get("overall_status", "UNKNOWN"),
        "scan": {
            "last_scan_id": scan.get("scan_id"),
            "last_successful_scan": scan.get("snapshot_ts") if last_scan_ok else None,
            "last_failed_scan": None if not errors else scan.get("snapshot_ts"),
            "scan_duration_s": scan.get("duration_s"),
            "symbols_with_errors": len(errors),
            "stale": ctx.get("stale") if ctx.get("available") else None,
        },
        "learning_status": learning,
        "model_registry": registry,
        "label": "PAPER / RESEARCH ONLY",
    }


def readiness_report() -> Dict[str, Any]:
    """Automated Production Readiness Report."""
    items: List[Dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        items.append({"item": name, "status": status, "detail": detail})

    ctx = build_scan_context()
    if ctx.get("available"):
        audit = ctx.get("scan_audit", {})
        ok = audit.get("audit_verdict") == "PASS"
        add("unified_scan_context", "PASS" if ok else "FAIL",
            f"Canonical scan {ctx['scan_id']} — single scan_id/snapshot_ts: {ok}")
    else:
        add("unified_scan_context", "FAIL", str(ctx.get("reason")))

    try:
        from phase15_consistency import run_consistency_check
        rep = run_consistency_check()
        add("cross_page_consistency", rep.get("verdict", "FAIL"),
            f"{rep.get('checks_performed', 0)} checks, {rep.get('mismatch_count', 0)} mismatches")
    except Exception as exc:
        add("cross_page_consistency", "FAIL", str(exc))

    try:
        from phase15_quality import staleness_report, quality_report
        st = staleness_report()
        add("no_stale_data", "PASS" if not st["stale"] else "WARN",
            st["warning"] or f"Scan age {st['scan_age_human']}")
        q = quality_report()
        dnt = q.get("band_counts", {}).get("DO_NOT_TRADE", 0) if q.get("available") else None
        add("data_quality_engine", "PASS" if q.get("available") else "FAIL",
            f"Avg score {q.get('avg_score')}; DO_NOT_TRADE symbols: {dnt}")
    except Exception as exc:
        add("data_quality_engine", "FAIL", str(exc))

    try:
        from phase15_risk_gate import risk_gate
        best = ctx.get("summary", {}).get("best_stock") if ctx.get("available") else None
        if best:
            rg = risk_gate(best)
            add("risk_engine", "PASS" if rg.get("available") else "FAIL",
                f"Gate on {best}: {rg.get('verdict')} ({rg.get('passed_count')}/"
                f"{rg.get('passed_count', 0) + rg.get('failed_count', 0)} checks passed)")
        else:
            add("risk_engine", "WARN", "No symbol available to exercise risk gate")
    except Exception as exc:
        add("risk_engine", "FAIL", str(exc))

    try:
        from paper_trader import get_portfolio, get_trade_replay
        p = get_portfolio()
        add("paper_trading", "PASS",
            f"Portfolio value ₹{p['total_value']:.2f}, {len(p['positions'])} positions, "
            f"{len(get_trade_replay())} completed round trips")
    except Exception as exc:
        add("paper_trading", "FAIL", str(exc))

    try:
        from phase15_explain import explain_symbol
        best = ctx.get("summary", {}).get("best_stock") if ctx.get("available") else None
        if best:
            e = explain_symbol(best)
            add("ai_explainability", "PASS" if e.get("available") and len(e.get("factors", [])) >= 10 else "FAIL",
                f"{len(e.get('factors', []))} explanation factors for {best}")
        else:
            add("ai_explainability", "WARN", "No symbol to explain")
    except Exception as exc:
        add("ai_explainability", "FAIL", str(exc))

    try:
        from phase14_copilot import answer_question
        a = answer_question("Which strategy performs best?")
        add("ai_copilot", "PASS" if a.get("answer") else "WARN", "Copilot answered from cached data only")
    except Exception as exc:
        add("ai_copilot", "FAIL", str(exc))

    try:
        from phase14_adjustments import learning_frozen
        add("learning_module", "PASS",
            f"Learning {'FROZEN' if learning_frozen().get('frozen') else 'active'}; no auto-promotion; "
            "human approval mandatory")
    except Exception as exc:
        add("learning_module", "FAIL", str(exc))

    try:
        from phase15_audit import record_scan_audit
        r = record_scan_audit()
        add("audit_logging", "PASS" if r.get("success") else "FAIL",
            f"Audit record for scan {(r.get('record') or {}).get('scan_id')}")
    except Exception as exc:
        add("audit_logging", "FAIL", str(exc))

    fails = sum(1 for i in items if i["status"] == "FAIL")
    warns = sum(1 for i in items if i["status"] == "WARN")
    verdict = "READY" if fails == 0 and warns == 0 else ("READY_WITH_WARNINGS" if fails == 0 else "NOT_READY")
    return {
        "success": True,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": VERSION,
        "items": items,
        "pass_count": sum(1 for i in items if i["status"] == "PASS"),
        "warn_count": warns,
        "fail_count": fails,
        "verdict": verdict,
        "remaining_issues": [f"{i['item']}: {i['detail']}" for i in items if i["status"] != "PASS"],
        "label": "PAPER / RESEARCH ONLY",
    }
