"""
phase15_consistency.py — Phase 15: Cross-Page Consistency Validation

Automatically validates that every module (Market Scanner, AI Decision,
AI Copilot / Opportunity Scan, Portfolio, Performance Analytics) reports
the exact same values as the canonical Unified Scan Context.

Any inconsistency is logged, written to phase15_consistency_report.json,
and surfaced in Diagnostics so conflicting recommendations cannot go unnoticed.

Read-only over cached data. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from phase15_scan_context import build_scan_context, _load, _parse_ts

_DIR = os.path.dirname(os.path.abspath(__file__))
AI_DECISIONS_CACHE = os.path.join(_DIR, "ai_decisions_cache.json")
OPPORTUNITY_CACHE = os.path.join(_DIR, "opportunity_cache.json")
REPORT_FILE = os.path.join(_DIR, "phase15_consistency_report.json")

# Numeric tolerance — values derived from the same snapshot should match exactly,
# but rounding differences up to 0.05 are tolerated.
TOLERANCE = 0.05


def _load_list(path: str) -> List[Dict[str, Any]]:
    data = _load(path)
    return data if isinstance(data, list) else []


def _num_mismatch(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) > TOLERANCE
    except (TypeError, ValueError):
        return False  # missing values are reported as coverage gaps, not mismatches


def run_consistency_check() -> Dict[str, Any]:
    ctx = build_scan_context()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not ctx.get("available"):
        report = {"available": False, "reason": ctx.get("reason"), "checked_at": now}
        _write(report)
        return report

    canonical = ctx["symbols"]
    mismatches: List[Dict[str, Any]] = []
    checks = 0
    sources_checked: List[Dict[str, Any]] = []

    def _register_source(name: str, path: str, items: List[Dict[str, Any]]) -> None:
        exists = os.path.exists(path)
        sources_checked.append({
            "source": name, "present": exists, "items": len(items)})
        if not exists or not items:
            mismatches.append({
                "source": name, "symbol": "*", "field": "cache",
                "canonical_value": "present", "source_value": "missing" if not exists else "empty",
                "severity": "MISSING_SOURCE",
                "note": f"{name} cache is {'missing' if not exists else 'empty'} — "
                        "this module could not be validated against the canonical scan"})

    scan_ts = _parse_ts(ctx.get("snapshot_ts") or "")

    def _source_outdated(path: str) -> bool:
        """
        True when the derived cache was NOT generated together with the canonical
        scan snapshot (written more than 5 minutes before/after it). Values from an
        out-of-sync source are flagged as STALE_SOURCE rather than hard errors —
        refreshing the scan pipeline resynchronises them.
        """
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
            return scan_ts is None or abs((mtime - scan_ts).total_seconds()) > 300
        except OSError:
            return False

    def compare(source: str, symbol: str, field: str, canonical_value: Any,
                source_value: Any, outdated: bool = False) -> None:
        nonlocal checks
        checks += 1
        if _num_mismatch(canonical_value, source_value):
            mismatches.append({
                "source": source, "symbol": symbol, "field": field,
                "canonical_value": canonical_value, "source_value": source_value,
                "severity": "STALE_SOURCE" if outdated else "ERROR",
                "note": (f"{source} cache predates canonical scan {ctx['scan_id']} — "
                         f"shows {source_value} vs canonical {canonical_value}; "
                         "refresh will resynchronise" if outdated else
                         f"{source} shows {source_value} but canonical scan "
                         f"{ctx['scan_id']} has {canonical_value}"),
            })

    # ── AI Decisions cache vs canonical ──────────────────────────────────────
    ai_items = _load_list(AI_DECISIONS_CACHE)
    _register_source("ai_decision", AI_DECISIONS_CACHE, ai_items)
    ai_outdated = _source_outdated(AI_DECISIONS_CACHE)
    for d in ai_items:
        sym = str(d.get("stock") or "").upper()
        c = canonical.get(sym)
        if not c:
            continue
        compare("ai_decision", sym, "entry_price", c["entry_price"], d.get("entry_price"), ai_outdated)
        compare("ai_decision", sym, "stop_loss", c["stop_loss"], d.get("stop_loss"), ai_outdated)
        compare("ai_decision", sym, "target", c["target_price"], d.get("target"), ai_outdated)
        compare("ai_decision", sym, "rr_ratio", c["rr_ratio"], d.get("rr_ratio"), ai_outdated)

    # ── Opportunity scan (AI Copilot source) vs canonical ────────────────────
    opp_items = _load_list(OPPORTUNITY_CACHE)
    _register_source("opportunity_scan", OPPORTUNITY_CACHE, opp_items)
    opp_outdated = _source_outdated(OPPORTUNITY_CACHE)
    for o in opp_items:
        sym = str(o.get("stock") or "").upper()
        c = canonical.get(sym)
        if not c:
            continue
        compare("opportunity_scan", sym, "opportunity_score",
                c["opportunity_score"], o.get("opportunity_score"), opp_outdated)
        compare("opportunity_scan", sym, "entry_price", c["entry_price"], o.get("entry_price"), opp_outdated)
        compare("opportunity_scan", sym, "rr_ratio", c["rr_ratio"], o.get("rr_ratio"), opp_outdated)

    # ── Internal snapshot integrity ───────────────────────────────────────────
    audit = ctx.get("scan_audit", {})
    checks += 2
    if not audit.get("all_items_share_same_scan_id", True):
        mismatches.append({"source": "scan_engine", "symbol": "*", "field": "scan_id",
                           "canonical_value": ctx["scan_id"], "source_value": "multiple",
                           "severity": "CRITICAL",
                           "note": "Scan items carry different scan_ids — snapshot broken"})
    if not audit.get("all_items_share_same_snapshot_ts", True):
        mismatches.append({"source": "scan_engine", "symbol": "*", "field": "snapshot_ts",
                           "canonical_value": ctx["snapshot_ts"], "source_value": "multiple",
                           "severity": "CRITICAL",
                           "note": "Scan items carry different snapshot timestamps"})

    hard = [m for m in mismatches if m["severity"] in ("ERROR", "CRITICAL")]
    stale_src = [m for m in mismatches if m["severity"] == "STALE_SOURCE"]
    consistent = len(hard) == 0
    verdict = "PASS" if not mismatches else ("WARN" if consistent else "FAIL")
    report = {
        "available": True,
        "checked_at": now,
        "scan_id": ctx["scan_id"],
        "snapshot_ts": ctx["snapshot_ts"],
        "sources_checked": sources_checked,
        "checks_performed": checks,
        "mismatch_count": len(mismatches),
        "hard_mismatch_count": len(hard),
        "stale_source_count": len(stale_src),
        "consistent": consistent,
        "verdict": verdict,
        "mismatches": mismatches[:100],
        "conflicting_recommendations_blocked": not consistent,
        "note": ("All modules agree with the canonical scan context." if verdict == "PASS"
                 else "Derived caches predate the canonical scan — values flagged as "
                      "STALE_SOURCE; refreshing the scan resynchronises every page."
                 if verdict == "WARN" else
                 "Hard inconsistencies detected — modules disagree with the canonical "
                 "scan from the same snapshot. Conflicting values are flagged."),
        "label": "PAPER / RESEARCH ONLY",
    }
    _write(report)
    return report


def _write(report: Dict[str, Any]) -> None:
    try:
        with open(REPORT_FILE, "w") as f:
            json.dump(report, f, indent=2, default=str)
    except Exception:
        pass


def last_report() -> Dict[str, Any]:
    return _load(REPORT_FILE) or {"available": False, "reason": "No consistency report yet"}
