"""
test_phase21.py — Phase 21 Strategy Calibration & Signal Quality tests.

Run: python3 test_phase21.py
PAPER TRADING / RESEARCH ONLY.
"""
import json
import os
import sys

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# ── T1: Baseline freeze & integrity ──────────────────────────────────────────
print("== Baseline ==")
from phase21_baseline import (freeze_baseline, load_baseline,
                              verify_baseline_integrity, BASELINE_FILE)

fz = freeze_baseline()
check("freeze idempotent", fz.get("already_frozen") in (True, False))
base = load_baseline()
check("baseline loaded", isinstance(base, dict) and bool(base))
check("baseline has version", base.get("baseline_version") == "phase21_baseline_v1")
check("baseline has thresholds", "decision_thresholds" in base.get("rules", {}))
integ = verify_baseline_integrity()
check("integrity intact", integ.get("intact") is True, str(integ))
fz2 = freeze_baseline()
check("second freeze does not overwrite", fz2.get("already_frozen") is True)
check("baseline file read-only", not os.access(BASELINE_FILE, os.W_OK))

# ── T2: Calibration ──────────────────────────────────────────────────────────
print("== Calibration ==")
from phase21_calibration import run_calibration, MIN_BUCKET_SAMPLE

cal = run_calibration(force=True)
check("no look-ahead documented", bool(cal.get("no_look_ahead")))
check("has evaluation_date", bool(cal.get("evaluation_date")))
buckets = cal.get("buckets", [])
check("6 buckets", len(buckets) == 6, str(len(buckets)))
for b in buckets:
    if b["trades"] < MIN_BUCKET_SAMPLE:
        check(f"bucket {b['bucket']} insufficient marked",
              b["status"] == "INSUFFICIENT", b["status"])
check("advisory only — raw conf untouched",
      cal.get("raw_confidence_untouched") is True)
cal2 = run_calibration(force=True)
check("calibration deterministic",
      json.dumps(cal.get("buckets"), sort_keys=True)
      == json.dumps(cal2.get("buckets"), sort_keys=True))

# ── T3: Threshold optimization ───────────────────────────────────────────────
print("== Thresholds ==")
from phase21_thresholds import run_threshold_optimization

th = run_threshold_optimization(force=True)
check("auto_applied False", th.get("auto_applied") is False)
check("requires human approval", th.get("requires_human_approval") is True)
check("status valid", th.get("status") in
      ("INSUFFICIENT_EVIDENCE", "NO_CHANGE_RECOMMENDED",
       "CANDIDATE_READY_FOR_REVIEW"), str(th.get("status")))
if th.get("status") == "INSUFFICIENT_EVIDENCE":
    check("no recommendation on insufficient evidence",
          th.get("recommended") is None)
for c in th.get("candidates", []):
    check(f"candidate buy {c['threshold_set']['buy']} has walk-forward split",
          "train" in c and "test" in c)

# ── T4: Regime matrix ────────────────────────────────────────────────────────
print("== Regime matrix ==")
from phase21_regime import run_regime_matrix

rm = run_regime_matrix(force=True)
check("auto_applied False", rm.get("auto_applied") is False)
pairs = rm.get("pairs", [])
check("pairs present", len(pairs) > 0)
VALID = {"ELIGIBLE", "CONDITIONAL", "WATCHLIST", "DISABLED", "INSUFFICIENT_DATA"}
for p in pairs:
    check(f"{p['strategy']}×{p['regime']} classification valid",
          p["classification"] in VALID, p["classification"])
    if p["sample_size"] < rm.get("min_sample", 10):
        check(f"{p['strategy']}×{p['regime']} small sample ⇒ INSUFFICIENT_DATA",
              p["classification"] == "INSUFFICIENT_DATA", p["classification"])
    check(f"{p['strategy']}×{p['regime']} advisory", p.get("advisory_only") is True)

# ── T5: Stop/target quality ──────────────────────────────────────────────────
print("== Stop/target ==")
from phase21_stoptarget import run_stoptarget_analysis

st = run_stoptarget_analysis(force=True)
check("historical trades never rewritten",
      st.get("historical_trades_rewritten") is False)
check("counterfactual labeled SIMULATED",
      st.get("counterfactual_label") == "SIMULATED")
if st.get("trades_with_full_excursion_data", 0) == 0:
    flagged = [t for t in st.get("per_trade", [])
               if t.get("stop_too_tight") or t.get("stop_too_loose")]
    check("no fabricated flags without MAE/MFE data", len(flagged) == 0,
          str(len(flagged)))

# ── T6: Ranking determinism ──────────────────────────────────────────────────
print("== Ranking ==")
from phase21_ranking import run_ranking, FACTOR_CAP

r1 = run_ranking()
if r1.get("available"):
    r2 = run_ranking()
    o1 = [i["symbol"] for i in r1["items"]]
    o2 = [i["symbol"] for i in r2["items"]]
    check("ranking deterministic (same scan → same order)", o1 == o2)
    check("factor cap 0.35", FACTOR_CAP == 0.35)
    for i in r1["items"][:10]:
        contribs = i.get("contributions", {})
        over = {k: v for k, v in contribs.items() if v > FACTOR_CAP + 1e-9}
        check(f"{i['symbol']} no factor exceeds cap", not over, str(over))
        check(f"{i['symbol']} BUY gates untouched",
              i.get("buy_gates_untouched") is True)
    scores = [i["rank_score"] for i in r1["items"]]
    check("sorted by rank_score desc", scores == sorted(scores, reverse=True))
else:
    check("ranking unavailable is explicit", "reason" in r1 or "note" in r1)

# ── T7: Explanations ─────────────────────────────────────────────────────────
print("== Explanations ==")
from phase21_explain import explain_all, explain_trade

ea = explain_all()
if ea.get("available"):
    items = ea.get("items", [])
    check("explanations generated", len(items) > 0)
    it = items[0]
    check("rule-based generator", str(it.get("generator", "")).startswith("rule_based"))
    check("evidence-backed", it.get("evidence_backed") is True)
    for r in it.get("reasons", []):
        check(f"reason has evidence factor ({r.get('evidence_factor')})",
              bool(r.get("evidence_factor")))
    single = explain_trade(it["symbol"])
    check("single explain matches symbol", single.get("symbol") == it["symbol"])
unknown = explain_trade("NOSUCHSYM123")
check("unknown symbol handled", unknown.get("available") is False)

# ── T8: Champion–challenger ──────────────────────────────────────────────────
print("== Champion–challenger ==")
from phase21_challenger import (build_challengers, get_registry,
                                promotion_checklist)

build_challengers(force=True)
reg = get_registry()
check("champion unchanged", reg.get("champion_unchanged") is True)
check("auto promotion disabled", reg.get("auto_promotion") in (False, "DISABLED"))
chals = reg.get("challengers", [])
check("4 challengers", len(chals) == 4, str(len(chals)))
for c in chals:
    check(f"{c['challenger_id']} advisory", c.get("advisory_only") is True)
    check(f"{c['challenger_id']} does not affect live recs",
          c.get("affects_live_recommendations") is False)
    cmp_ = c.get("comparison", {})
    if not cmp_.get("evaluable"):
        check(f"{c['challenger_id']} unevaluable has reason",
              bool(cmp_.get("reason")))
if chals:
    pc = promotion_checklist(chals[0]["challenger_id"])
    check("promotion checklist has checks", len(pc.get("checks", [])) > 0)
    check("checklist never auto-promotes", pc.get("auto_promoted") is not True)

# ── T9: Scorecard & safety invariants ────────────────────────────────────────
print("== Scorecard ==")
from phase21_scorecard import build_scorecard

sc = build_scorecard()
check("auto paper entries OFF", sc.get("auto_paper_entries") == "OFF")
check("live orders DISABLED", sc.get("live_orders") == "DISABLED")
check("paper approval ≠ live approval",
      sc.get("approved_for_paper_test_is_not_live_approval") is True)
check("reproducibility result present", bool(sc.get("reproducibility_result")))
check("no-look-ahead result present", bool(sc.get("no_look_ahead_result")))
check("readiness status present", bool(sc.get("readiness_status")))

# ── T10: Exports ─────────────────────────────────────────────────────────────
print("== Exports ==")
from phase21_exports import build_phase21_exports, EXPORT_DIR

ex = build_phase21_exports()
files = ex.get("files", [])
check("export produced files", len(files) > 0)
exts = {os.path.splitext(f)[1] for f in files}
check("JSON export", ".json" in exts, str(exts))
check("CSV export", ".csv" in exts, str(exts))
check("PDF export", ".pdf" in exts, str(exts))
for f in files:
    check(f"export exists: {f}",
          os.path.exists(os.path.join(EXPORT_DIR, os.path.basename(f))))

print(f"\nPhase 21 tests: {PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
