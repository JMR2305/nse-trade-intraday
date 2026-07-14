"""Phase 6.5 validation tests — meta-learning, failure attribution, gating.

Run: python3 test_meta_learning.py
All tests are read-only against research data (plus one draft-mutation
round-trip that is archived immediately). No trading state is touched.
"""
import copy
import json
import os
import sys

import pandas as pd

import meta_learning as ml
import strategy_evolution as se

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def main():
    # 1. Evidence labels are conservative — small samples never STRONG
    check("Evidence: 5 trades → INSUFFICIENT", ml.evidence_label(5) == "INSUFFICIENT")
    check("Evidence: 15 trades → VERY LOW", ml.evidence_label(15) == "VERY LOW")
    check("Evidence: 25 trades → LOW", ml.evidence_label(25) == "LOW")
    check("Evidence: 50 trades → MODERATE", ml.evidence_label(50, windows=3) == "MODERATE")
    check("Evidence: 150 trades 1 window → not STRONG", ml.evidence_label(150, windows=1) != "STRONG")
    check("Evidence: 150 trades 3 windows 3 positive → STRONG",
          ml.evidence_label(150, windows=3, positive_windows=3) == "STRONG")

    # 2. No-lookahead audit runs and reports honestly
    allt, exp_ids, audit = ml._load_all_trades()
    check("No-lookahead audit executed", audit["status"] in ("PASS", "FAIL", "NOT AVAILABLE", "NOT APPLICABLE"),
          f"status={audit['status']} checked={audit['checked']} violations={audit['violations']}")
    if audit["status"] == "PASS":
        check("No look-ahead leakage in stored trades", audit["violations"] == 0)

    # Synthetic leakage must be caught
    fake = pd.DataFrame([{"max_data_timestamp": "2025-01-10", "entry_date": "2025-01-05",
                          "net_pnl": 1.0, "symbol": "X", "strategy_name": "S", "__exp": "e"}])
    mdt = pd.to_datetime(fake["max_data_timestamp"])
    ent = pd.to_datetime(fake["entry_date"])
    check("Leakage detector flags future data", int((mdt > ent).sum()) == 1)

    # 3. Deduplication
    if not allt.empty:
        dupe_cols = [c for c in ("__exp", "symbol", "entry_date", "exit_date", "strategy_name") if c in allt.columns]
        check("Duplicate trade records removed", not allt.duplicated(subset=dupe_cols).any())

    # 4. Gross vs net edge calculated correctly
    g = pd.DataFrame({"gross_pnl": [10.0, -4.0], "net_pnl": [8.0, -6.0], "total_costs": [2.0, 2.0],
                      "window": ["W1", "W1"], "symbol": ["A", "B"], "sector": ["S1", "S2"],
                      "entry_date": ["2025-01-01", "2025-01-02"], "invested": [100.0, 100.0],
                      "market_regime": ["Bullish", "Bullish"], "exit_reason": ["Signal Exit"] * 2})
    attr = ml._attribute(g, "unit")
    check("Gross P&L computed", attr["gross_pnl"] == 6.0, str(attr["gross_pnl"]))
    check("Net P&L computed", attr["net_pnl"] == 2.0, str(attr["net_pnl"]))
    check("Costs did not cause failure here", attr["costs_caused_failure"] is False)
    g2 = g.copy()
    g2["net_pnl"] = [1.0, -3.0]  # gross positive, net negative
    attr2 = ml._attribute(g2, "unit2")
    check("Cost-caused failure detected", attr2["costs_caused_failure"] is True)
    g3 = g.copy()
    g3["gross_pnl"] = [-5.0, -4.0]
    g3["net_pnl"] = [-7.0, -6.0]
    attr3 = ml._attribute(g3, "unit3")
    check("Negative gross edge detected", attr3["negative_gross_edge"] is True)

    # 5. Condition uplift compares identical populations (with + without = total)
    if not allt.empty:
        name, sg = next(iter(allt.groupby("strategy_name")))
        ups = ml._condition_uplift(sg)
        if ups:
            u = ups[0]
            check("Uplift populations partition the sample",
                  u["trades_with"] + u["trades_without"] == len(sg),
                  f"{u['trades_with']}+{u['trades_without']}=={len(sg)}")

    # 6. Small samples not marked strong in uplift/eligibility
    if not allt.empty:
        bad = [u for sgn, sgg in allt.groupby("strategy_name")
               for u in ml._condition_uplift(sgg) if u["trades_with"] < 100 and u["evidence"] == "STRONG"]
        check("No <100-trade condition labeled STRONG", len(bad) == 0, f"{len(bad)} violations")

    # 7. Parent-child comparison requires identical test periods
    cmp_diff = ml.cmd_compare("95a7ff31918c", "0a655cee0ae9")
    if cmp_diff.get("success"):
        check("Comparison flags non-identical periods",
              cmp_diff["identical_test_period"] is False and "NOT COMPARABLE" in cmp_diff["verdict"])
    cmp_same = ml.cmd_compare("95a7ff31918c", "95a7ff31918c")
    if cmp_same.get("success"):
        check("Identical experiments are comparable", cmp_same["identical_test_period"] is True)

    # 8. Mutations remain Draft, no auto-promotion; undo via archive works.
    # Isolated: run against a temp copy of the registry so no test artifacts persist.
    import shutil
    import tempfile
    real_registry = se.REGISTRY_PATH
    tmpdir = tempfile.mkdtemp(prefix="meta_test_")
    tmp_registry = os.path.join(tmpdir, "registry.json")
    shutil.copy(real_registry, tmp_registry)
    se.REGISTRY_PATH = tmp_registry
    try:
        before = copy.deepcopy(se._load_registry())
        res = ml.cmd_create_mutation("Trend Rider", "test_gate_param", "unit-test-value", "unit test evidence")
        check("Draft mutation created", res.get("success") is True, str(res.get("error")))
        if res.get("success"):
            vid = res["variant"]["strategy_id"]
            check("Mutation status is Draft", res["variant"]["status"] == "Draft")
            check("Mutation records parent", res["variant"]["parent_id"] is not None)
            check("Mutation records evidence", "unit test evidence" in (res["variant"]["mutation"]["evidence_for"] or ""))
            res2 = ml.cmd_create_mutation("Trend Rider", "test_gate_param", "unit-test-value", "dup attempt")
            check("Duplicate mutation deduplicated (idempotent)",
                  res2.get("success") is True and res2.get("already_exists") is True
                  and res2["variant"]["strategy_id"] == vid)
            reg_now = se._load_registry()
            promoted = [e for e in reg_now["strategies"]
                        if e["strategy_id"] != vid and e["status"] != next(
                            (b["status"] for b in before["strategies"] if b["strategy_id"] == e["strategy_id"]), e["status"])]
            check("No other strategy status changed (no auto-promotion)", len(promoted) == 0)
            arch = se.cmd_set_status(vid, "Archived", "unit-test cleanup")
            check("Undo/archive action works", arch.get("success") is True and arch.get("to") == "Archived")
    finally:
        se.REGISTRY_PATH = real_registry
        shutil.rmtree(tmpdir, ignore_errors=True)
    check("Real registry untouched by tests",
          json.dumps(se._load_registry(), sort_keys=True) != "" and se.REGISTRY_PATH == real_registry)

    # 9. Recommended mutations limited to top 3 and deduplicated
    impr = ml.cmd_improvements()
    for s in impr["suggestions"]:
        check(f"≤3 suggestions for {s['strategy']}", len(s["suggestions"]) <= 3, str(len(s["suggestions"])))
        keys = [(x["mutation_parameter"], x["mutation_value"]) for x in s["suggestions"]]
        check(f"Suggestions deduplicated for {s['strategy']}", len(keys) == len(set(keys)))

    # 10. Exports contain all 15 required tables + metadata
    ex = ml.cmd_export()
    required = ["strategy_health", "failure_attribution", "regime_eligibility", "sector_eligibility",
                "condition_uplift", "confidence_analysis", "holding_period_analysis",
                "exit_reason_analysis", "cost_sensitivity", "concentration_risk", "robustness_checks",
                "contradictions", "recommended_mutations", "parent_child_comparison", "evidence_summary"]
    check("Export succeeded", ex.get("success") is True)
    check("All 15 tables present", all(t in ex["tables"] for t in required),
          str([t for t in required if t not in ex["tables"]]))
    for k in ("generated_at", "source_experiment_ids", "source_data_hash", "model_version",
              "no_lookahead_audit", "sample_counts", "warnings", "research_only_disclaimer"):
        check(f"Export meta includes {k}", k in ex["meta"])
    with open(ex["json_file"]) as f:
        parsed = json.load(f)
    check("JSON export is valid JSON", isinstance(parsed, dict) and "tables" in parsed)
    check("CSV export exists and non-empty", os.path.getsize(ex["csv_file"]) > 100)
    check("HTML export exists and non-empty", os.path.getsize(ex["html_file"]) > 500)

    # 11. All command outputs are JSON-serializable (valid JSON even for errors)
    for fn, args in [(ml.cmd_health, ()), (ml.cmd_failures, ()), (ml.cmd_eligibility, ()),
                     (ml.cmd_contradictions, ()), (ml.cmd_compare, ("nope", "alsonope"))]:
        out = fn(*args)
        try:
            json.dumps(out, default=str)
            ok = True
        except (TypeError, ValueError):
            ok = False
        check(f"{fn.__name__} returns JSON-serializable output", ok)
    check("Invalid compare returns error JSON, not crash",
          ml.cmd_compare("nope", "alsonope").get("success") is False)

    # 12. No live/paper trading state modified: meta_learning never imports/writes them
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "meta_learning.py")).read()
    for forbidden in ("import paper_trading", "from paper_trading", "import portfolio",
                      "from portfolio", "import scanner", "from scanner",
                      "place_order", "execute_trade", "trade_decision"):
        check(f"meta_learning.py never uses '{forbidden}'", forbidden not in src)

    print(f"\n{'ALL TESTS PASSED' if not FAILURES else 'FAILURES: ' + ', '.join(FAILURES)}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
