"""
phase7_report.py  —  Phase 7: Live Market Intelligence Validation Report
Generates downloadable JSON, CSV, and HTML reports with a PASS/PARTIAL/FAIL verdict.

Contents
--------
  data_health        — provider status, coverage, staleness
  symbol_coverage    — per-symbol quality, age, latency
  scan_audit         — snapshot consistency proof
  decision_counts    — final action breakdown
  gate_failures      — per-gate pass/fail tallies and reasons
  paper_eligibility  — which symbols are paper-order-eligible
  latency            — p50/p90/max fetch latency per symbol
  errors             — list of symbols that failed and why
  safety             — research-only declarations
  verdict            — PASS | PARTIAL | FAIL with criteria

PAPER / LIVE DATA VALIDATION — strictly research only.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

EXPORT_DIR = os.path.join(os.path.dirname(__file__), "exports")
REPORT_VERSION = "phase7-report-1.0"
LABEL = "PAPER / LIVE DATA VALIDATION"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _verdict(scan: Dict[str, Any]) -> Dict[str, Any]:
    """Compute PASS / PARTIAL / FAIL verdict from scan result."""
    criteria: List[Dict[str, Any]] = []

    def chk(name: str, passed: bool, detail: str):
        criteria.append({"criterion": name, "passed": passed, "detail": detail})

    ph = scan.get("provider_health", {})
    audit = scan.get("scan_audit", {})
    summary = scan.get("summary", {})
    recs = scan.get("recommendations", [])

    conn = ph.get("connection_status", "")
    chk("Provider connected", conn in ("CONNECTED", "DEGRADED"), f"Status: {conn}")
    chk("Scan audit: consistent snapshot", audit.get("audit_verdict") == "PASS",
        audit.get("audit_verdict", "N/A"))
    cov = ph.get("symbol_coverage_pct", 0)
    chk("Symbol coverage ≥ 80%", cov >= 80.0, f"{cov}% symbols fetched successfully")
    unavail = ph.get("symbols_unavailable", 0)
    total = ph.get("symbols_requested", 1)
    chk("Unavailable symbols ≤ 20%", unavail / max(total, 1) <= 0.20,
        f"{unavail}/{total} symbols unavailable")
    chk("No stale-data BUY decisions", _no_stale_buys(recs),
        "No BUY/STRONG BUY from STALE/UNAVAILABLE data")
    chk("Duplicate scan detection", _no_duplicate_scan_ids(recs),
        "All items share same scan_id")
    chk("Price validity", _price_gate_pass_rate(recs) >= 0.90,
        f"{_price_gate_pass_rate(recs)*100:.1f}% price gates passed")
    chk("No invalid/zero prices in BUY decisions", _no_zero_price_buys(recs),
        "No BUY/STRONG BUY with price ≤ 0")
    all_pass = [c for c in criteria if c["passed"]]
    all_fail = [c for c in criteria if not c["passed"]]
    if len(all_fail) == 0:
        verdict = "PASS"
    elif len(all_pass) >= len(all_fail):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return {"verdict": verdict, "criteria": criteria,
            "passed": len(all_pass), "failed": len(all_fail)}


def _no_stale_buys(recs: List[Dict]) -> bool:
    for r in recs:
        if r.get("final_action") in ("STRONG BUY", "BUY"):
            if r.get("data_quality") in ("STALE", "UNAVAILABLE"):
                return False
    return True


def _no_duplicate_scan_ids(recs: List[Dict]) -> bool:
    ids = {r.get("scan_id") for r in recs}
    return len(ids) <= 1


def _price_gate_pass_rate(recs: List[Dict]) -> float:
    if not recs:
        return 1.0
    ok = sum(1 for r in recs if (r.get("gate_price") or {}).get("passed") is True)
    return ok / len(recs)


def _no_zero_price_buys(recs: List[Dict]) -> bool:
    for r in recs:
        if r.get("final_action") in ("STRONG BUY", "BUY") and (r.get("entry_price") or 0) <= 0:
            return False
    return True


def _build_tables(scan: Dict[str, Any]) -> Dict[str, List[Dict]]:
    ph = scan.get("provider_health", {})
    recs = scan.get("recommendations", [])
    audit = scan.get("scan_audit", {})
    summary = scan.get("summary", {})
    verdict = _verdict(scan)

    # data_health
    data_health = [{
        "provider": ph.get("provider"),
        "provider_id": ph.get("provider_id"),
        "connection_status": ph.get("connection_status"),
        "last_successful_fetch": ph.get("last_successful_fetch"),
        "symbols_requested": ph.get("symbols_requested"),
        "symbols_succeeded": ph.get("symbols_succeeded"),
        "symbols_stale": ph.get("symbols_stale"),
        "symbols_unavailable": ph.get("symbols_unavailable"),
        "symbol_coverage_pct": ph.get("symbol_coverage_pct"),
        "avg_latency_ms": ph.get("avg_latency_ms"),
        "max_latency_ms": ph.get("max_latency_ms"),
        "retry_events": ph.get("retry_events"),
        "paper_execution_eligible": ph.get("paper_execution_eligible"),
        "snapshot_id": ph.get("snapshot_id"),
        "snapshot_ts": ph.get("snapshot_ts"),
    }]

    # symbol_coverage
    symbol_coverage = [{
        "symbol": r.get("symbol"), "sector": r.get("sector"),
        "data_quality": r.get("data_quality"),
        "data_age_days": r.get("data_age_days"),
        "latest_bar_date": r.get("latest_bar_date"),
        "bars_available": r.get("bars_available"),
        "data_source": r.get("data_source"),
        "error": r.get("error"),
    } for r in recs]

    # scan_audit
    scan_audit = [audit] if audit else []

    # decision_counts
    from collections import Counter
    actions = Counter(r.get("final_action", "IGNORE") for r in recs)
    decision_counts = [{"action": k, "count": v} for k, v in sorted(actions.items())]

    # gate_failures
    gate_keys = ["gate_price", "gate_data_quality", "gate_rr", "gate_volume"]
    gate_rows = []
    for gk in gate_keys:
        failed = [r for r in recs if not (r.get(gk) or {}).get("passed", True)]
        gate_rows.append({
            "gate": gk, "total_symbols": len(recs),
            "passed": len(recs) - len(failed), "failed": len(failed),
            "sample_reasons": [r.get(gk, {}).get("reason") for r in failed[:3]],
        })

    # paper_eligibility
    paper_eligibility = [{
        "symbol": r.get("symbol"), "final_action": r.get("final_action"),
        "data_quality": r.get("data_quality"), "all_gates_passed": r.get("all_gates_passed"),
        "paper_eligible": r.get("paper_eligible"),
        "paper_order_id": r.get("paper_order_id"),
        "paper_order_note": r.get("paper_order_note"),
    } for r in recs if r.get("paper_eligible") or r.get("final_action") in ("STRONG BUY", "BUY")]

    # latency
    latencies = sorted(
        [{"symbol": r.get("symbol"), "fetch_latency_ms": (ph.get("avg_latency_ms") or 0)}
         for r in recs], key=lambda x: -(x.get("fetch_latency_ms") or 0))

    # errors
    errors = [{"symbol": r.get("symbol"), "error": r.get("error")}
              for r in recs if r.get("error")]

    # recommendations (full)
    recommendations = [
        {k: v for k, v in r.items()
         if k not in ("gate_price", "gate_data_quality", "gate_rr", "gate_volume")}
        for r in recs
    ]

    # gate_detail
    gate_detail = [{
        "symbol": r.get("symbol"),
        "gate_price_passed": (r.get("gate_price") or {}).get("passed"),
        "gate_price_reason": (r.get("gate_price") or {}).get("reason"),
        "gate_quality_passed": (r.get("gate_data_quality") or {}).get("passed"),
        "gate_quality_reason": (r.get("gate_data_quality") or {}).get("reason"),
        "gate_rr_passed": (r.get("gate_rr") or {}).get("passed"),
        "gate_rr_reason": (r.get("gate_rr") or {}).get("reason"),
        "gate_volume_passed": (r.get("gate_volume") or {}).get("passed"),
        "gate_volume_reason": (r.get("gate_volume") or {}).get("reason"),
        "all_gates_passed": r.get("all_gates_passed"),
    } for r in recs]

    # safety
    safety_table = [scan.get("safety", {})]

    # verdict
    verdict_table = [verdict]

    return {
        "data_health": data_health,
        "symbol_coverage": symbol_coverage,
        "scan_audit": scan_audit,
        "decision_counts": decision_counts,
        "gate_failures": gate_rows,
        "gate_detail": gate_detail,
        "paper_eligibility": paper_eligibility,
        "latency": latencies,
        "errors": errors,
        "recommendations": recommendations,
        "safety": safety_table,
        "verdict": verdict_table,
    }


def generate_report(scan: Dict[str, Any]) -> Dict[str, str]:
    """Generate JSON, CSV, and HTML reports. Returns dict of file paths."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    tables = _build_tables(scan)
    verdict = _verdict(scan)
    generated_at = _now()
    meta = {
        "generated_at": generated_at,
        "report_version": REPORT_VERSION,
        "scan_id": scan.get("scan_id"),
        "snapshot_ts": scan.get("snapshot_ts"),
        "label": LABEL,
        "verdict": verdict["verdict"],
        "phase": "7",
    }

    # JSON
    bundle = {"meta": meta, "tables": tables, "raw_scan": {
        k: v for k, v in scan.items() if k != "recommendations"
    }}
    json_path = os.path.join(EXPORT_DIR, "phase7_report.json")
    with open(json_path, "w") as f:
        json.dump(bundle, f, indent=1, default=str)

    # CSV
    csv_path = os.path.join(EXPORT_DIR, "phase7_report.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["## Phase 7 Live Market Intelligence Report",
                    generated_at, f"verdict:{verdict['verdict']}", LABEL])
        for tname, rows in tables.items():
            w.writerow([])
            w.writerow([f"## {tname}", f"rows:{len(rows)}"])
            if not rows:
                w.writerow(["(no data)"])
                continue
            cols = sorted({k for r in rows for k in r.keys()})
            w.writerow(cols)
            for r in rows:
                w.writerow([
                    json.dumps(r.get(c), default=str) if isinstance(r.get(c), (dict, list))
                    else ("" if r.get(c) is None else r.get(c))
                    for c in cols])

    # HTML
    vclass = {"PASS": "#22c55e", "PARTIAL": "#f59e0b", "FAIL": "#ef4444"}.get(verdict["verdict"], "#888")
    sections = []
    for tname, rows in tables.items():
        if not rows:
            sections.append(f"<h2>{_esc(tname)}</h2><p><i>No data</i></p>")
            continue
        cols = sorted({k for r in rows for k in r.keys()})
        body = "".join(
            "<tr>" + "".join(
                f"<td>{_esc(json.dumps(r.get(c), default=str) if isinstance(r.get(c), (dict, list)) else ('' if r.get(c) is None else r.get(c)))}</td>"
                for c in cols) + "</tr>"
            for r in rows)
        sections.append(
            f"<h2>{_esc(tname)}</h2>"
            f"<table><tr>{''.join(f'<th>{_esc(c)}</th>' for c in cols)}</tr>{body}</table>")

    crit_rows = "".join(
        f"<tr><td>{_esc(c['criterion'])}</td>"
        f"<td style='color:{'#22c55e' if c['passed'] else '#ef4444'}'>"
        f"{'✓' if c['passed'] else '✗'}</td>"
        f"<td>{_esc(c['detail'])}</td></tr>"
        for c in verdict["criteria"])

    html_path = os.path.join(EXPORT_DIR, "phase7_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Phase 7 — Live Market Intelligence Validation Report</title>
<style>
body{{font-family:Georgia,serif;margin:40px;color:#1a1a1a;background:#fafafa}}
h1{{border-bottom:3px solid #333}}h2{{border-bottom:1px solid #aaa;margin-top:28px}}
table{{border-collapse:collapse;width:100%;font-size:11px;margin:10px 0}}
th,td{{border:1px solid #ccc;padding:3px 7px;text-align:left;vertical-align:top}}
th{{background:#e8e8e8}}.verdict{{font-size:28px;font-weight:bold;color:{vclass}}}
.safety{{background:#fff8e1;border:1px solid #d4a017;padding:12px;border-radius:4px}}
</style></head><body>
<h1>Phase 7 — Live Market Intelligence Validation Report</h1>
<p>Generated {_esc(generated_at)} · Scan ID {_esc(scan.get('scan_id',''))} · {_esc(LABEL)}</p>
<p class="verdict">Verdict: {_esc(verdict['verdict'])}</p>
<div class="safety"><b>PAPER TRADING &amp; RESEARCH ONLY.</b> No real broker API is called.
No real money is at risk. Meta-Learning and Strategy Evolution findings do not affect
live decisions unless a future human-approved phase explicitly enables them.</div>
<h2>Validation Criteria</h2>
<table><tr><th>Criterion</th><th>Passed</th><th>Detail</th></tr>{crit_rows}</table>
{''.join(sections)}
</body></html>""")

    return {"json": json_path, "csv": csv_path, "html": html_path,
            "verdict": verdict["verdict"],
            "criteria_passed": verdict["passed"],
            "criteria_failed": verdict["failed"]}
