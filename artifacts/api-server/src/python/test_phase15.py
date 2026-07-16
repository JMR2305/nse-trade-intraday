"""
test_phase15.py — Phase 15 Production Hardening & Stabilization tests.

Run: python3 test_phase15.py
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


# ── T1: Unified scan context ─────────────────────────────────────────────────
print("== Scan context ==")
from phase15_scan_context import build_scan_context, symbol_context, STALE_AFTER_S

ctx = build_scan_context()
check("context available", ctx.get("available") is True, str(ctx.get("reason")))
if ctx.get("available"):
    check("has scan_id", bool(ctx.get("scan_id")))
    check("has snapshot_ts", bool(ctx.get("snapshot_ts")))
    check("stale flag is bool", isinstance(ctx.get("stale"), bool))
    check("stale threshold 90min", STALE_AFTER_S == 5400)
    syms = ctx.get("symbols", {})
    check("symbols present", len(syms) > 0)
    first = next(iter(syms.values()))
    for f in ("final_action", "effective_action", "entry_price", "stop_loss",
              "target_price", "rr_ratio", "opportunity_score"):
        check(f"symbol field {f}", f in first)
    if ctx.get("stale"):
        buys = [s for s in syms.values() if s["effective_action"] in ("BUY", "STRONG_BUY")]
        check("stale ⇒ no effective BUY", len(buys) == 0, f"{len(buys)} BUYs while stale")
    sc = symbol_context(next(iter(syms)))
    check("symbol_context works", sc.get("available") is True and sc.get("symbol") in syms)
    check("unknown symbol handled", symbol_context("NOSUCHSYM").get("available") is False)

# ── T2: Data quality & staleness ─────────────────────────────────────────────
print("== Quality & staleness ==")
from phase15_quality import score_symbol, quality_report, staleness_report, _band as band_for

check("band 97 EXCELLENT", band_for(97) == "EXCELLENT")
check("band 92 GOOD", band_for(92) == "GOOD")
check("band 85 WARNING", band_for(85) == "WARNING")
check("band 70 DO_NOT_TRADE", band_for(70) == "DO_NOT_TRADE")

qr = quality_report()
check("quality report available", qr.get("available") is True)
if qr.get("available"):
    check("quality symbols scored", len(qr.get("symbols", [])) > 0)
    s0 = qr["symbols"][0]
    check("score in range", 0 <= s0["data_quality_score"] <= 100)
    check("band present", s0.get("band") in ("EXCELLENT", "GOOD", "WARNING", "DO_NOT_TRADE"))
    check("components listed", len(s0.get("components", [])) > 0)
    dnt = [s for s in qr["symbols"] if s["band"] == "DO_NOT_TRADE"]
    check("DO_NOT_TRADE not tradeable", all(not s["tradeable"] for s in dnt))

st = staleness_report()
check("staleness has stale flag", isinstance(st.get("stale"), bool))
check("stale disables BUY", st.get("buy_recommendations_disabled") == st.get("stale"))

# ── T3: Consistency ──────────────────────────────────────────────────────────
print("== Consistency ==")
from phase15_consistency import run_consistency_check, REPORT_FILE

cr = run_consistency_check()
check("consistency ran", cr.get("checked_at") is not None)
if cr.get("available"):
    check("checks performed", cr.get("checks_performed", 0) > 0)
    check("verdict valid", cr.get("verdict") in ("PASS", "WARN", "FAIL"))
    check("hard+stale == total",
          cr.get("hard_mismatch_count", 0) + cr.get("stale_source_count", 0)
          == cr.get("mismatch_count", -1))
    check("consistent iff no hard errors",
          cr.get("consistent") == (cr.get("hard_mismatch_count", 0) == 0))
check("report file written", os.path.exists(REPORT_FILE))

# Regression: missing required fields (scan_id/decision/status) must be flagged,
# never silently skipped (false-green guard).
import json as _json
from phase15_consistency import AI_DECISIONS_CACHE

if cr.get("available") and os.path.exists(AI_DECISIONS_CACHE):
    with open(AI_DECISIONS_CACHE) as _f:
        _orig = _f.read()
    try:
        _items = _json.loads(_orig)
        _tampered = False
        if isinstance(_items, list) and _items:
            _items[0].pop("scan_id", None)
            _items[0].pop("decision", None)
            with open(AI_DECISIONS_CACHE, "w") as _f:
                _json.dump(_items, _f)
            _tampered = True
        if _tampered:
            cr2 = run_consistency_check()
            _missing = [m for m in cr2.get("mismatches", [])
                        if m.get("field") in ("scan_id", "decision")
                        and m.get("source_value") is None]
            check("missing scan_id/decision flagged", len(_missing) >= 2)
            check("missing fields break PASS", cr2.get("verdict") != "PASS"
                  or cr2.get("hard_mismatch_count", 0) > 0)
    finally:
        with open(AI_DECISIONS_CACHE, "w") as _f:
            _f.write(_orig)
        run_consistency_check()  # restore clean report

# ── T4: Explainability ───────────────────────────────────────────────────────
print("== Explainability ==")
from phase15_explain import explain_symbol, explain_all

ea = explain_all()
if ea.get("available"):
    check("explanations for all", len(ea.get("items", [])) > 0)
    sym = ea["items"][0]["symbol"]
    ex = explain_symbol(sym)
    check("explain available", ex.get("available") is True)
    check("has factors", len(ex.get("factors", [])) >= 5)
    check("factors have assessment", all("assessment" in f for f in ex["factors"]))
    check("has headline", bool(ex.get("headline")))
    check("stale downgrade consistent",
          (not ex.get("stale")) or ex.get("effective_decision") not in ("BUY", "STRONG_BUY"))
check("unknown symbol explain", explain_symbol("NOSUCHSYM").get("available") is False)

# ── T5: Risk gate ────────────────────────────────────────────────────────────
print("== Risk gate ==")
from phase15_risk_gate import risk_gate

if ctx.get("available"):
    sym = next(iter(ctx["symbols"]))
    rg = risk_gate(sym)
    check("risk gate available", rg.get("available") is True)
    checks_list = rg.get("checks", [])
    check("≥8 checks", len(checks_list) >= 8, f"got {len(checks_list)}")
    names = {c["check"] for c in checks_list}
    for req in ("max_daily_loss", "risk_per_trade", "max_exposure", "data_quality", "stale_data"):
        check(f"check {req} present", req in names)
    check("every check has reason", all(c.get("reason") for c in checks_list))
    check("verdict consistent",
          (rg.get("verdict") == "CLEARED") == all(c["passed"] for c in checks_list))

# ── T6: Trade record extensions ──────────────────────────────────────────────
print("== Trade records ==")
from paper_trader import estimate_broker_charges, estimate_slippage

c = estimate_broker_charges(1000.0, "BUY")
s = estimate_broker_charges(1000.0, "SELL")
check("buy charges > sell (stamp duty)", c > s)
check("charges positive & sane", 0 < c < 10)
check("slippage 0.05%", estimate_slippage(1000.0) == 0.5)

# ── T7: Audit + diagnostics + readiness ──────────────────────────────────────
print("== Audit / diagnostics / readiness ==")
from phase15_audit import record_scan_audit, list_scan_audits
from phase15_diagnostics import system_diagnostics, readiness_report

ra = record_scan_audit()
check("audit recorded", ra.get("success") is True, str(ra))
la = list_scan_audits(5)
check("audit list", len(la.get("records", [])) >= 1)
a0 = la["records"][0]
for f in ("scan_id", "duration_s", "stocks_processed", "warning_count"):
    check(f"audit field {f}", f in a0)

diag = system_diagnostics()
check("diagnostics version 15.0", diag.get("version") == "15.0")
for f in ("system_health", "cache_status", "memory_usage_mb", "learning_status"):
    check(f"diag field {f}", f in diag)

rr = readiness_report()
check("readiness items", len(rr.get("items", [])) >= 8)
check("readiness statuses valid",
      all(i["status"] in ("PASS", "WARN", "FAIL") for i in rr["items"]))
check("overall verdict present", rr.get("verdict") in ("READY", "READY_WITH_WARNINGS", "NOT_READY"))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
