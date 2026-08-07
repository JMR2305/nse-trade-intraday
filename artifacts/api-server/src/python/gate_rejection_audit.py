"""
gate_rejection_audit.py — Risk gate rejection instrumentation (advisory).

Runs the Phase-20 entry gate evaluation against ALL symbols in the latest
canonical scan (not just BUY candidates) and tallies rejections per gate,
so operators can see exactly which rule is the primary bottleneck.

Read-only: uses evaluate_entries() which never places orders.

Usage: python gate_rejection_audit.py [--json]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any, Dict


def run_audit() -> Dict[str, Any]:
    from scan_state_store import load_latest_snapshot
    snap = load_latest_snapshot() or {}
    recs = snap.get("recommendations") or []
    all_symbols = sorted({r["symbol"] for r in recs if r.get("symbol")})

    from phase20_gates import evaluate_entries
    result = evaluate_entries(candidate_symbols=all_symbols) if all_symbols else evaluate_entries()

    global_gates = result.get("global_gates") or []
    candidates = result.get("candidates") or []

    failed_global = [g["gate"] for g in global_gates if not g.get("passed")]

    per_gate = Counter()
    first_blocker = Counter()   # the FIRST failed gate per candidate (ordering = gate list order)
    eligible = 0
    for c in candidates:
        failed = c.get("failed_gates") or []
        if not failed:
            eligible += 1
            continue
        for g in failed:
            per_gate[g] += 1
        first_blocker[failed[0]] += 1

    # Distribution of key metrics across all scan records (for calibration)
    def _dist(key: str):
        vals = sorted(float(r.get(key) or 0) for r in recs if r.get(key) is not None)
        if not vals:
            return None
        n = len(vals)
        return {
            "min": vals[0], "p25": vals[n // 4], "median": vals[n // 2],
            "p75": vals[(3 * n) // 4], "max": vals[-1], "n": n,
        }

    return {
        "scan_id": result.get("scan_id"),
        "snapshot_ts": result.get("snapshot_ts"),
        "market_state": result.get("market_state"),
        "candidates_entering": len(candidates),
        "eligible_remaining": eligible,
        "failed_global_gates": failed_global,
        "rejections_per_gate": dict(per_gate.most_common()),
        "primary_bottleneck_first_failure": dict(first_blocker.most_common()),
        "metric_distributions": {
            "confidence": _dist("confidence"),
            "opportunity_score": _dist("opportunity_score"),
            "technical_score": _dist("technical_score"),
            "risk_reward": _dist("risk_reward") or _dist("rr_ratio"),
        },
    }


if __name__ == "__main__":
    report = run_audit()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Scan: {report['scan_id']}  ts={report['snapshot_ts']}  market={report['market_state']}")
        print(f"Candidates entering : {report['candidates_entering']}")
        print(f"Eligible remaining  : {report['eligible_remaining']}")
        print(f"Failed GLOBAL gates : {', '.join(report['failed_global_gates']) or 'none'}")
        print("\nRejections per gate (a symbol can fail several):")
        for g, n in report["rejections_per_gate"].items():
            print(f"  {g:<28} {n}")
        print("\nPrimary bottleneck (first failed gate per symbol):")
        for g, n in report["primary_bottleneck_first_failure"].items():
            print(f"  {g:<28} {n}")
        print("\nMetric distributions (all scan records):")
        for k, d in report["metric_distributions"].items():
            if d:
                print(f"  {k:<18} min={d['min']:.1f} p25={d['p25']:.1f} med={d['median']:.1f} p75={d['p75']:.1f} max={d['max']:.1f} (n={d['n']})")
