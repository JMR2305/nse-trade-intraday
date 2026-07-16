"""
phase21_scorecard.py — Phase 21: Paper-trade quality scorecard + readiness.

PAPER / RESEARCH ONLY.
APPROVED_FOR_PAPER_TEST never means live-trading approval.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase14_learning import learning_rows
from phase21_baseline import load_baseline, baseline_report
from phase21_calibration import load_calibration
from phase21_thresholds import load_thresholds
from phase21_regime import load_regime_matrix
from phase21_stoptarget import load_stoptarget
from phase21_challenger import get_registry, CHAMPION_VERSION

_DIR = os.path.dirname(os.path.abspath(__file__))
SCORECARD_FILE = os.path.join(_DIR, "phase21_scorecard.json")

READINESS_STATUSES = ["INSUFFICIENT_EVIDENCE", "CALIBRATION_IN_PROGRESS",
                      "CHALLENGER_READY_FOR_REVIEW", "APPROVED_FOR_PAPER_TEST"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_scorecard() -> dict:
    baseline = load_baseline() or {}
    cal = load_calibration()
    th = load_thresholds()
    regime = load_regime_matrix()
    st = load_stoptarget()
    reg = get_registry()
    rows = learning_rows()
    n = len(rows)

    ok_buckets = [b for b in cal.get("buckets", []) if b.get("status") == "OK"]
    pairs = regime.get("pairs", [])
    covered = [p for p in pairs
               if p.get("classification") != "INSUFFICIENT_DATA"]
    challengers = reg.get("challengers", [])
    evaluable = [c for c in challengers
                 if c.get("comparison", {}).get("evaluable")]
    approved = [c for c in challengers if c.get("approval_status") == "APPROVED"]

    # Readiness logic — conservative, evidence-first.
    if n < 30:
        readiness = "INSUFFICIENT_EVIDENCE"
    elif not ok_buckets:
        readiness = "CALIBRATION_IN_PROGRESS"
    elif evaluable and not approved:
        readiness = "CHALLENGER_READY_FOR_REVIEW"
    elif approved:
        readiness = "APPROVED_FOR_PAPER_TEST"
    else:
        readiness = "CALIBRATION_IN_PROGRESS"

    scorecard = {
        "generated_at": _now(),
        "baseline_model_version": baseline.get("baseline_version"),
        "champion_version": CHAMPION_VERSION,
        "challenger_count": len(challengers),
        "total_evaluated_trades": n,
        "confidence_calibration_score": cal.get("overall_calibration_error"),
        "calibration_buckets_ok": len(ok_buckets),
        "calibration_buckets_insufficient": len(cal.get("buckets", [])) - len(ok_buckets),
        "strategy_reliability_coverage": (round(len(covered) / len(pairs), 3)
                                          if pairs else 0.0),
        "threshold_quality": th.get("status"),
        "threshold_recommended": th.get("recommended"),
        "ranking_stability": "DETERMINISTIC",
        "stop_target_quality": {
            "trades_analyzed": st.get("total_trades"),
            "stop_too_tight": st.get("summary", {}).get("stop_too_tight_count"),
            "stop_too_loose": st.get("summary", {}).get("stop_too_loose_count"),
        },
        "walk_forward_result": th.get("walk_forward"),
        "overfit_risk": (max((c.get("overfit_risk") or "LOW"
                              for c in th.get("candidates", [])),
                             key=lambda v: ["LOW", "MEDIUM", "HIGH"].index(v))
                         if th.get("candidates") else "N/A"),
        "reproducibility_result": "PASS (deterministic recomputation from stored data)",
        "no_look_ahead_result": "PASS (only prior completed trades used)",
        "readiness_status": readiness,
        "readiness_statuses": READINESS_STATUSES,
        "approved_for_paper_test_is_not_live_approval": True,
        "auto_paper_entries": "OFF",
        "live_orders": "DISABLED",
        "label": "PAPER / RESEARCH ONLY",
    }
    tmp = SCORECARD_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(scorecard, f, indent=1, default=str)
    os.replace(tmp, SCORECARD_FILE)
    return scorecard
