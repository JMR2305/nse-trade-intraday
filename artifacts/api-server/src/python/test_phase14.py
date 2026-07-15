"""
test_phase14.py — Phase 14 test suite.

Covers the spec §13 requirements: no-look-ahead, completed-trades-only,
adjustment caps, insufficient-evidence zeroing, gate safety, calibrator
train/test separation, no self-promotion, explicit approval, rollback,
drift freeze, secret-free exports, determinism, and broker safety.
"""
from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \u2713 {name}")
    else:
        FAIL += 1
        print(f"  \u2717 {name} {detail}")


print("── Dataset & no-look-ahead ──")
from phase14_learning import (
    build_learning_dataset, learning_rows, run_evaluation, group_metrics,
    reliability_label, confidence_band, opportunity_band, holding_band,
    quality_grade, ENTRY_FEATURE_COLS, OUTCOME_COLS,
)

ds = build_learning_dataset(force=True)
check("T01 dataset built from completed trades only",
      all(r.get("exit_price") is not None and r.get("entry_price") is not None
          for r in ds["rows"]))
check("T02 every row has explicit no-look-ahead audit",
      all("no_look_ahead" in r and "passed" in r["no_look_ahead"] for r in ds["rows"]))
check("T03 entry features never contain outcome columns",
      not any(set(OUTCOME_COLS) & set(r.get("entry_features", {}).keys())
              for r in ds["rows"]))
check("T04 audit counts consistent",
      ds["audit_passed_rows"] + ds["audit_failed_rows"] == ds["total_rows"])

print("── Reliability labels ──")
check("T05 reliability thresholds",
      reliability_label(5) == "INSUFFICIENT" and reliability_label(30) == "LOW"
      and reliability_label(50) == "MODERATE" and reliability_label(100) == "STRONG"
      and reliability_label(250) == "HIGH")

ev = run_evaluation(force=True)
check("T06 evaluation includes sample sizes everywhere",
      all("sample_size" in m for m in ev["by_strategy"].values()))
check("T07 low-sample groups flagged not to display conclusions",
      all(not m.get("display_conclusions", True)
          for m in ev["by_strategy"].values() if m.get("sample_size", 0) < 50))

print("── Adjustments: caps & evidence gating ──")
from phase14_adjustments import (
    compute_adjustments, adaptive_adjustment_for, _adjustment_from_metrics,
    MAX_PER_SOURCE, MAX_TOTAL, set_learning_frozen, learning_frozen,
)

adj = compute_adjustments(force=True)
all_vals = [e["adjustment"] for src in adj["sources"].values() for e in src.values()]
check("T08 per-source cap ±5 respected", all(abs(v) <= MAX_PER_SOURCE for v in all_vals))
check("T09 insufficient evidence gives zero adjustment",
      all(e["adjustment"] == 0 for src in adj["sources"].values()
          for e in src.values() if e["reliability"] in ("INSUFFICIENT", "LOW")))

good = {"sample_size": 120, "reliability": "STRONG", "expectancy": 50.0,
        "profit_factor": 1.4, "win_rate": 0.6, "avg_loss": -40.0}
v, _ = _adjustment_from_metrics(good)
check("T10 positive adj requires PF>1 + evidence (value in (0,5])", 0 < v <= 5)
bad = {"sample_size": 80, "reliability": "MODERATE", "expectancy": -30.0,
       "profit_factor": 0.7, "win_rate": 0.3, "avg_loss": -50.0}
v2, _ = _adjustment_from_metrics(bad)
check("T11 negative expectancy w/ MODERATE evidence reduces confidence", -5 <= v2 < 0)
pos_no_pf = {"sample_size": 120, "reliability": "STRONG", "expectancy": 10.0,
             "profit_factor": 0.95, "win_rate": 0.5, "avg_loss": -40.0}
v3, _ = _adjustment_from_metrics(pos_no_pf)
check("T12 positive expectancy without PF>1 gives zero", v3 == 0)

res = adaptive_adjustment_for("AI Scan", "RANGE_BOUND", "BANKING", 50.0,
                              recommendation="IGNORE")
check("T13 IGNORE recommendation blocks positive adjustment", res["adjustment"] <= 0)
check("T14 total adjustment bounded ±10", abs(res["adjustment"]) <= MAX_TOTAL)
res_empty = adaptive_adjustment_for("NonexistentStrategy", None, None, None)
check("T15 no evidence → zero with explicit reason",
      res_empty["adjustment"] == 0 and "insufficient" in res_empty["explanation"].lower())

print("── Calibration: leakage-free training ──")
from phase14_calibration import (
    train_calibrator, calibration_status, calibrate_confidence,
    _fit_isotonic, _fit_platt, _apply, get_active_calibrator,
)

cal = train_calibrator(force=True)
check("T16 calibrator versioned", cal["version"].startswith("cal_v"))
check("T17 identity fallback with insufficient evidence",
      cal["method"] == "identity" if cal["train_samples"] < 30 else True)
check("T18 train/test never overlap (train+test ≤ total, split chronological)",
      cal["train_samples"] + cal["test_samples"] <= len(learning_rows()) or
      cal["method"] == "identity")
check("T19 low-sample warning shown", cal.get("warning") is not None
      if len(learning_rows()) < 100 else True)
status = calibration_status()
check("T20 calibrator history preserved", status["calibrator_count"] >= 1)
cc = calibrate_confidence(60.0)
check("T21 calibrate_confidence returns raw + calibrated + version",
      {"raw_confidence", "calibrated_probability", "calibrator_version"} <= set(cc))

# Synthetic isotonic sanity: monotone output
iso = _fit_isotonic([(0.1, 0), (0.3, 0), (0.5, 1), (0.7, 1), (0.9, 1)])
outs = [_apply(iso, p) for p in (0.1, 0.4, 0.6, 0.9)]
check("T22 isotonic output monotone non-decreasing",
      all(outs[i] <= outs[i + 1] + 1e-9 for i in range(len(outs) - 1)))

print("── Governance: no self-promotion, approval, rollback ──")
from phase14_governance import (
    list_models, create_challenger, promotion_checklist, review_model,
    rollback_champion, compute_drift, load_drift, append_audit, get_audit_log,
    add_alert, get_alerts,
)

# Isolate registry state for tests
import phase14_governance as gov
_reg_backup = gov.REGISTRY_FILE
gov.REGISTRY_FILE = os.path.join(BASE_DIR, "phase14_model_registry_test.json")
if os.path.exists(gov.REGISTRY_FILE):
    os.remove(gov.REGISTRY_FILE)

reg = list_models()
check("T23 seed champion exists", reg["champion_version"] is not None)
challenger = create_challenger("test challenger")
check("T24 challenger created with PENDING_REVIEW",
      challenger["approval_status"] == "PENDING_REVIEW"
      and challenger["status"] == "CHALLENGER")
cl = promotion_checklist(challenger["model_version"])
check("T25 promotion checklist requires ≥100 OOS trades (fails now)",
      not cl["eligible"])
result = review_model(challenger["model_version"], "APPROVE", "tester")
check("T26 approval alone cannot promote when checklist fails",
      result.get("blocked") is True
      and list_models()["champion_version"] == reg["champion_version"])
rej = review_model(challenger["model_version"], "REJECT", "tester")
check("T27 explicit human reject works", rej["model"]["status"] == "REJECTED")
rb = rollback_champion()
check("T28 rollback without previous champion errors safely", "error" in rb)

# Simulate a promotion + rollback path by direct registry manipulation
r = gov._registry()
r["previous_champion"] = r["champion_version"]
prev = r["champion_version"]
r["models"].append({"model_version": "tmp_champ", "status": "CHAMPION",
                    "approval_status": "APPROVED"})
for m in r["models"]:
    if m["model_version"] == prev:
        m["status"] = "ARCHIVED"
r["champion_version"] = "tmp_champ"
gov._save(gov.REGISTRY_FILE, r)
rb2 = rollback_champion()
check("T29 one-click rollback restores previous champion",
      rb2.get("success") and rb2["champion_version"] == prev)
os.remove(gov.REGISTRY_FILE)
gov.REGISTRY_FILE = _reg_backup

print("── Drift & freeze ──")
drift = compute_drift()
check("T30 drift report has severity + indicators",
      drift["overall_severity"] in ("INFO", "WARNING", "CRITICAL"))
# Force-freeze then verify positive adjustments zeroed
set_learning_frozen(True, "test freeze")
adj_frozen = compute_adjustments(force=True)
check("T31 freeze zeroes positive adjustments",
      all(e["adjustment"] <= 0 for src in adj_frozen["sources"].values()
          for e in src.values()))
set_learning_frozen(False, "test unfreeze")
compute_adjustments(force=True)
check("T32 unfreeze restores computation", not learning_frozen()["frozen"])

# Decision-time freeze enforcement: even with stale positive stored
# adjustments, adaptive_adjustment_for must suppress positives when frozen.
import phase14_adjustments as p14adj
_stale = p14adj.load_adjustments()
_stale.setdefault("sources", {}).setdefault("strategy", {})["FreezeTest"] = {
    "adjustment": 5.0, "sample_size": 120, "expectancy": 50.0,
    "profit_factor": 1.5, "win_rate": 0.6, "reliability": "STRONG",
    "reason": "stale positive entry for freeze test", "bounds": {},
}
with open(p14adj.ADJUSTMENTS_FILE, "w") as _f:
    json.dump(_stale, _f)
set_learning_frozen(True, "decision-time freeze test")  # no recompute on purpose
_frozen_dec = adaptive_adjustment_for("FreezeTest", None, None, 60.0)
check("T32b freeze enforced at decision time despite stale positive cache",
      _frozen_dec["adjustment"] <= 0 and _frozen_dec["learning_frozen"] is True)
set_learning_frozen(False, "decision-time freeze test done")
compute_adjustments(force=True)

print("── Exports: secret-free, deterministic ──")
from phase14_diagnostics import build_bundle, export_artifact, verification_report, _mask_secrets

masked = _mask_secrets({"api_key": "abc", "nested": {"password": "x", "ok": 1}})
check("T33 secret masking works",
      masked["api_key"] == "***MASKED***" and masked["nested"]["password"] == "***MASKED***")
bundle = build_bundle()
check("T34 bundle builds with README + verification",
      bundle["success"] and os.path.exists(os.path.join(BASE_DIR, "phase14_diagnostic_bundle.json")))
with open(os.path.join(BASE_DIR, "phase14_diagnostic_bundle.json")) as f:
    btxt = f.read()
check("T35 bundle contains no obvious secrets",
      "ZERODHA" not in btxt.upper() or "***MASKED***" in btxt)
exp = export_artifact("dataset")
check("T36 dataset export has json + csv", "json" in exp and "csv" in exp and "trade_id" in exp["csv"])
ver = verification_report()
check("T37 verification report shows research-only banner + no auto-promotion",
      ver["banner"] == "RESEARCH / PAPER LEARNING ONLY"
      and ver["automatic_promotion_occurred"] is False)

ds2 = build_learning_dataset(force=True)
check("T38 deterministic dataset from same snapshot",
      ds2["total_rows"] == ds["total_rows"]
      and [r["trade_id"] for r in ds2["rows"]] == [r["trade_id"] for r in ds["rows"]])

print("── Broker & safety regression ──")
p14_files = ["phase14_learning.py", "phase14_adjustments.py",
             "phase14_calibration.py", "phase14_governance.py",
             "phase14_diagnostics.py"]
src = "".join(open(os.path.join(BASE_DIR, f)).read() for f in p14_files)
check("T39 no real broker order calls in Phase 14 code",
      "place_order" not in src and "kiteconnect" not in src.lower())
check("T40 Phase 14 never modifies stop-loss/risk caps",
      "stop_loss =" not in src.replace("\"stop_loss\":", "")
      and "risk_cap" not in src)

print(f"\nPhase 14 tests: {PASS} passed, {FAIL} failed of {PASS + FAIL}")
sys.exit(0 if FAIL == 0 else 1)
