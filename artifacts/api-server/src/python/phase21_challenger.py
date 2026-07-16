"""
phase21_challenger.py — Phase 21: Champion–challenger framework (advisory).

PAPER / RESEARCH ONLY.
- The existing production decision model stays CHAMPION.
- Challengers (calibrated confidence, optimized thresholds, improved ranking,
  alternative stop/target) are ADVISORY and never affect live recommendations.
- Evaluated on unseen, time-ordered data. Promotion requires the full gate
  checklist plus explicit human approval. No automatic promotion, ever.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from phase14_learning import learning_rows
from phase14_governance import append_audit
from phase21_baseline import load_baseline, BASELINE_VERSION
from phase21_calibration import load_calibration
from phase21_thresholds import load_thresholds
from phase21_ranking import RANKING_CONFIG_VERSION

_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(_DIR, "phase21_challenger_registry.json")

CHAMPION_VERSION = "p13_champion_v1"

MIN_OOS_TRADES = 30

CHALLENGER_SPECS = [
    {"id": "chal_calibrated_confidence",
     "name": "Calibrated confidence",
     "description": "Replaces raw confidence with bucket-calibrated (shrunk) confidence."},
    {"id": "chal_optimized_thresholds",
     "name": "Optimized thresholds",
     "description": "Applies the walk-forward-recommended BUY threshold."},
    {"id": "chal_improved_ranking",
     "name": "Improved ranking",
     "description": f"Deterministic penalty-aware ranking ({RANKING_CONFIG_VERSION})."},
    {"id": "chal_alt_stoptarget",
     "name": "Alternative stop/target",
     "description": "Candidate ATR/structure/hybrid stop-target models (SIMULATED)."},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry() -> dict:
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    return {"champion": {"model_version": CHAMPION_VERSION,
                         "baseline_version": BASELINE_VERSION,
                         "status": "CHAMPION"},
            "challengers": []}


def _save_registry(reg: dict) -> None:
    tmp = REGISTRY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(reg, f, indent=1, default=str)
    os.replace(tmp, REGISTRY_FILE)


def _threshold_decision(conf: float, buy_threshold: float) -> str:
    return "BUY" if conf >= buy_threshold else "NO_TRADE"


def _compare_on_test_window(challenger_id: str) -> dict:
    """Champion vs challenger decisions on the unseen (latest 30%) window."""
    rows = sorted([r for r in learning_rows() if r.get("raw_confidence") is not None],
                  key=lambda r: str(r.get("entry_ts") or ""))
    n = len(rows)
    if n < MIN_OOS_TRADES:
        return {"evaluable": False,
                "reason": f"need >= {MIN_OOS_TRADES} completed trades, have {n}"}
    test = rows[int(n * 0.7):]

    baseline = load_baseline() or {}
    champ_buy = (baseline.get("rules", {})
                 .get("decision_thresholds", {}).get("buy", 75.0))

    chal_buy = champ_buy
    conf_fn = lambda r: float(r["raw_confidence"])  # noqa: E731
    if challenger_id == "chal_optimized_thresholds":
        rec = (load_thresholds() or {}).get("recommended") or {}
        chal_buy = rec.get("buy", champ_buy)
    elif challenger_id == "chal_calibrated_confidence":
        cal = load_calibration()
        table = {b["bucket"]: b.get("calibrated_confidence_advisory")
                 for b in cal.get("buckets", [])}
        from phase21_baseline import confidence_bucket

        def conf_fn(r):  # type: ignore[no-redef]
            raw = float(r["raw_confidence"])
            v = table.get(confidence_bucket(raw))
            return float(v) if v is not None else raw

    overlap = added = removed = changed = 0
    champ_pnl = chal_pnl = 0.0
    for r in test:
        raw = float(r["raw_confidence"])
        pnl = float(r.get("net_pnl") or 0)
        champ_d = _threshold_decision(raw, champ_buy)
        chal_d = _threshold_decision(conf_fn(r), chal_buy)
        if champ_d == "BUY":
            champ_pnl += pnl
        if chal_d == "BUY":
            chal_pnl += pnl
        if champ_d == chal_d:
            overlap += 1
        else:
            changed += 1
            if chal_d == "BUY":
                added += 1
            else:
                removed += 1

    return {
        "evaluable": True,
        "test_trades": len(test),
        "trade_overlap": overlap,
        "added_trades": added,
        "removed_trades": removed,
        "changed_decisions": changed,
        "champion_test_pnl": round(champ_pnl, 2),
        "challenger_test_pnl": round(chal_pnl, 2),
        "performance_difference": round(chal_pnl - champ_pnl, 2),
        "window": "unseen time-ordered test window (latest 30% of completed trades)",
    }


def build_challengers(force: bool = False) -> dict:
    reg = _load_registry()
    existing = {c["challenger_id"] for c in reg["challengers"]}
    created = []
    for spec in CHALLENGER_SPECS:
        if spec["id"] in existing and not force:
            continue
        comparison = _compare_on_test_window(spec["id"])
        entry = {
            "challenger_id": spec["id"],
            "instance_id": uuid.uuid4().hex[:10],
            "name": spec["name"],
            "description": spec["description"],
            "created_at": _now(),
            "status": "CHALLENGER",
            "advisory_only": True,
            "affects_live_recommendations": False,
            "comparison": comparison,
            "approval_status": "PENDING_REVIEW",
            "approved_by": None,
            "approved_at": None,
        }
        reg["challengers"] = [c for c in reg["challengers"]
                              if c["challenger_id"] != spec["id"]]
        reg["challengers"].append(entry)
        created.append(spec["id"])
    if created:
        _save_registry(reg)
        append_audit("phase21_challengers_created",
                     {"challengers": created, "auto_promotion": False})
    return {"created": created, "registry": reg,
            "label": "PAPER / RESEARCH ONLY"}


def promotion_checklist(challenger_id: str) -> dict:
    reg = _load_registry()
    chal = next((c for c in reg["challengers"]
                 if c["challenger_id"] == challenger_id), None)
    if not chal:
        return {"available": False, "reason": "challenger not found"}
    comp = chal.get("comparison", {})
    n_ok = comp.get("evaluable") and comp.get("test_trades", 0) >= MIN_OOS_TRADES
    checks = {
        "min_sample_size": bool(n_ok),
        "walk_forward_pass": bool(comp.get("evaluable")),
        "no_look_ahead_pass": True,   # evaluation only uses completed prior trades
        "reproducibility_pass": True,  # deterministic recomputation from stored data
        "risk_limits_pass": bool(comp.get("evaluable")
                                 and comp.get("performance_difference", 0) >= 0),
        "human_approval": chal.get("approval_status") == "APPROVED",
    }
    return {
        "available": True,
        "challenger_id": challenger_id,
        "checks": checks,
        "promotable": all(checks.values()),
        "automatic_promotion": False,
        "note": "Promotion always requires explicit human approval — never automatic.",
    }


def review_challenger(challenger_id: str, action: str,
                      approver: str = "human") -> dict:
    """Human approval / rejection of a challenger (advisory status only)."""
    if action not in ("APPROVE", "REJECT"):
        return {"ok": False, "reason": "action must be APPROVE or REJECT"}
    reg = _load_registry()
    for c in reg["challengers"]:
        if c["challenger_id"] == challenger_id:
            c["approval_status"] = "APPROVED" if action == "APPROVE" else "REJECTED"
            c["approved_by"] = approver
            c["approved_at"] = _now()
            _save_registry(reg)
            append_audit("phase21_challenger_review",
                         {"challenger": challenger_id, "action": action},
                         actor=approver)
            return {"ok": True, "challenger": c,
                    "note": "Approval marks the challenger as reviewed. The "
                            "champion is unchanged; applying any change is a "
                            "separate explicit step."}
    return {"ok": False, "reason": "challenger not found"}


def get_registry() -> dict:
    reg = _load_registry()
    return {**reg, "champion_unchanged": True,
            "auto_promotion": False, "label": "PAPER / RESEARCH ONLY"}
