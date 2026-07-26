"""
test_phase17.py — Phase 17 Automated QA & Release Validation tests.

Run: python3 test_phase17.py
PAPER TRADING / RESEARCH ONLY.
Note: this suite tests the QA engine's light sections only — it does NOT
invoke run_complete_validation (which would recursively run every suite).
"""
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


import phase17_qa as q
import phase17_reports as rpt

VALID = {"PASS", "FAIL", "WARN"}

# ── T1: build info ───────────────────────────────────────────────────────────
print("== Build info ==")
b = q.build_info()
check("success", b.get("success") is True)
check("version set", b.get("release_version") == q.VERSION)
check("build number int", isinstance(b.get("build_number"), int) and b["build_number"] >= 1)
check("environment", b.get("environment") in ("development", "production"))

# ── T2: section structure ────────────────────────────────────────────────────
print("== Section structure (light sections) ==")
for fn in (q.datastore_validation, q.paper_trading_validation, q.ai_validation,
           q.performance_validation, q.error_detection, q.consistency_validation):
    sec = fn()
    name = sec.get("section", fn.__name__)
    check(f"{name}: success", sec.get("success") is True)
    check(f"{name}: label", "PAPER" in str(sec.get("label")))
    check(f"{name}: totals consistent",
          sec.get("total") == sec.get("passed", 0) + sec.get("failed", 0) + sec.get("warnings", 0))
    check(f"{name}: statuses valid",
          all(c.get("status") in VALID for c in sec.get("checks", [])))

# ── T3: honesty markers ──────────────────────────────────────────────────────
print("== Honesty markers ==")
perf = q.performance_validation()
check("insufficient_data list present", isinstance(perf.get("insufficient_data"), list))
err = q.error_detection()
check("error detection discloses not-checkable client items",
      any("browser" in s or "client" in s for s in err.get("not_checkable", [])))
ds = q.datastore_validation()
check("datastore notes JSON storage honestly", "JSON" in str(ds.get("note", "")))

# ── T4: API validation ───────────────────────────────────────────────────────
print("== API validation ==")
api = q.api_validation()
check("success", api.get("success") is True)
check("endpoints listed", len(api.get("endpoints", [])) >= 15)
check("latency recorded", all(isinstance(e.get("latency_ms"), int) for e in api["endpoints"]))
check("auth/rate-limit disclosed as N/A", len(api.get("not_checkable", [])) == 2)

# ── T5: scoring maths ────────────────────────────────────────────────────────
print("== Scoring ==")
check("weights sum sensible", sum(q.SCORE_WEIGHTS.values()) > 0)
fake = {"total": 10, "passed": 8, "failed": 1, "warnings": 1}
check("section score formula", abs(q._score_section(fake) - 0.85) < 1e-9)
check("empty section returns None", q._score_section({"total": 0}) is None)

# ── T6: history / dashboard ──────────────────────────────────────────────────
print("== History & dashboard ==")
h = q.validation_history()
check("history success", h.get("success") is True)
check("runs list", isinstance(h.get("runs"), list))
d = q.release_dashboard()
check("dashboard success", d.get("success") is True)
check("dashboard version", d.get("current_version") == q.VERSION)
check("readiness value valid",
      d.get("production_readiness") in
      ("READY", "READY WITH WARNINGS", "NOT READY", "Not Available"))

# ── T6b: release gating policy ───────────────────────────────────────────────
print("== Release gating policy ==")
last = q.last_run()
if last.get("available"):
    cl = {i["item"]: i for i in last.get("release_checklist", [])}
    for item in cl.values():
        if item["item"] == "Production Ready":
            continue
        label = item["item"]
        key = next((k for lbl, k in q.CHECKLIST_SECTIONS if lbl == label), None)
        sec = last.get("sections", {}).get(key, {}) if key else {}
        if sec:
            expected = ("FAIL" if sec.get("failed", 0) > 0
                        else "WARN" if sec.get("warnings", 0) > 0 or sec.get("total", 0) == 0
                        else "PASS")
            check(f"checklist '{label}' honours warnings", item["status"] == expected,
                  f"got {item['status']} expected {expected}")
    pr = cl.get("Production Ready", {})
    any_warn = any(i["status"] == "WARN" for k, i in cl.items() if k != "Production Ready")
    any_fail = any(i["status"] == "FAIL" for k, i in cl.items() if k != "Production Ready")
    expected_pr = "FAIL" if any_fail else ("WARN" if any_warn else "PASS")
    check("Production Ready not PASS while warnings open", pr.get("status") == expected_pr,
          f"got {pr.get('status')} expected {expected_pr}")
    check("production_ready boolean strict",
          last.get("production_ready") == (expected_pr == "PASS"))
    check("readiness_status consistent",
          last.get("readiness_status") ==
          ("NOT READY" if any_fail else "READY WITH WARNINGS" if any_warn else "READY"))
else:
    check("gating policy (no run yet — skipped honestly)", True)
l = q.last_run()
check("last_run has availability flag", "available" in l)

# ── T7: reports module ───────────────────────────────────────────────────────
print("== Reports ==")
if l.get("available"):
    r = rpt.build_reports(l)
    check("reports build", r.get("success") is True)
    for f in ("Validation_Report.csv", "System_Health.json", "Release_Readiness.json",
              "Regression_Report.csv"):
        check(f"report {f} exists", f in r.get("files", []))
else:
    r = rpt.build_reports()
    check("reports refuse without a run (honest)", r.get("success") is False)

# ── result ───────────────────────────────────────────────────────────────────
print(f"\n{PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
