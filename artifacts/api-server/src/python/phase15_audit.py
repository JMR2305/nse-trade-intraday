"""
phase15_audit.py — Phase 15: Scan Audit Logging

Every scan produces a detailed audit record: timestamp, duration, stocks
processed, strategies executed, signals generated, warnings, errors,
learning events, risk checks, and a decision summary.

Records are appended to phase15_audit_log.json (bounded).
PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from phase15_scan_context import _load, SCAN_CACHE

_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_LOG = os.path.join(_DIR, "phase15_audit_log.json")
MAX_RECORDS = 100


def _load_log() -> List[Dict[str, Any]]:
    data = _load(AUDIT_LOG)
    return data if isinstance(data, list) else []


def record_scan_audit() -> Dict[str, Any]:
    """Build (or refresh) the audit record for the current canonical scan."""
    scan = _load(SCAN_CACHE)
    if not scan:
        return {"success": False, "reason": "No canonical scan cache to audit"}

    recs = scan.get("recommendations", [])
    valid = [r for r in recs if not r.get("error")]
    warnings: List[str] = []
    errors: List[str] = []
    for r in recs:
        if r.get("error"):
            errors.append(f"{r.get('symbol')}: {r['error']}")
        for g in ("gate_price", "gate_data_quality", "gate_rr", "gate_volume"):
            gate = r.get(g) or {}
            if not gate.get("passed", True) and not r.get("error"):
                warnings.append(f"{r.get('symbol')}: {gate.get('reason')}")

    strategies = sorted({r.get("strategy_name") for r in valid if r.get("strategy_name")})
    summary = scan.get("summary", {})

    # Learning events (best-effort, read-only)
    learning_events: List[str] = []
    try:
        from phase14_adjustments import learning_frozen
        if learning_frozen().get("frozen"):
            learning_events.append("Adaptive learning FROZEN (drift guard active)")
        else:
            learning_events.append("Adaptive learning active (bounded, human-governed)")
    except Exception:
        pass

    risk_checks = {
        "quality_gates_applied": True,
        "rr_gate_applied": True,
        "volume_gate_applied": True,
        "stale_cap_applied": True,
        "gate_failures": len(warnings),
    }

    record = {
        "audit_id": f"a15_{scan.get('scan_id')}",
        "scan_id": scan.get("scan_id"),
        "timestamp": scan.get("snapshot_ts"),
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_s": scan.get("duration_s"),
        "stocks_processed": len(recs),
        "stocks_valid": len(valid),
        "strategies_executed": strategies,
        "signals_generated": {
            "strong_buy": summary.get("strong_buy_count", 0),
            "buy": summary.get("buy_count", 0),
            "watch": summary.get("watch_count", 0),
            "ignore": summary.get("ignore_count", 0),
        },
        "warnings": warnings[:50],
        "warning_count": len(warnings),
        "errors": errors[:50],
        "error_count": len(errors),
        "learning_events": learning_events,
        "risk_checks": risk_checks,
        "decision_summary": (
            f"{summary.get('strong_buy_count', 0)} STRONG BUY, {summary.get('buy_count', 0)} BUY, "
            f"{summary.get('watch_count', 0)} WATCH, {summary.get('ignore_count', 0)} IGNORE "
            f"across {len(recs)} stocks; best {summary.get('best_stock')} "
            f"({summary.get('best_stock_score')}); avg score {summary.get('avg_opportunity_score')}"),
        "label": "PAPER / RESEARCH ONLY",
    }

    log = _load_log()
    log = [e for e in log if e.get("scan_id") != record["scan_id"]]
    log.append(record)
    log = log[-MAX_RECORDS:]
    try:
        with open(AUDIT_LOG, "w") as f:
            json.dump(log, f, indent=2, default=str)
    except Exception:
        pass
    return {"success": True, "record": record, "total_records": len(log)}


def list_scan_audits(limit: int = 20) -> Dict[str, Any]:
    log = _load_log()
    return {"success": True, "count": len(log),
            "records": list(reversed(log))[:limit],
            "label": "PAPER / RESEARCH ONLY"}
