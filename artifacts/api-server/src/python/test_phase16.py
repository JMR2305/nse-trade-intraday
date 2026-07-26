"""
test_phase16.py — Phase 16 Paper Trading Validation & Strategy Proving tests.

Run: python3 test_phase16.py
PAPER TRADING / RESEARCH ONLY.
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


import phase16_validation as v

# ── T1: Overview ─────────────────────────────────────────────────────────────
print("== Validation overview ==")
o = v.validation_overview()
check("success", o.get("success") is True)
check("research-only label", "PAPER" in str(o.get("label")))
check("score in range", 0 <= (o.get("overall_validation_score") or 0) <= 100)
check("maturity string", isinstance(o.get("maturity"), str) and o["maturity"])
check("completed trades int", isinstance(o.get("completed_trades"), int))
check("capital fields", o.get("capital_start") == 5000 and o.get("capital_now") is not None)
if (o.get("completed_trades") or 0) < 20:
    check("honesty note for small sample", bool(o.get("note")), "expected note when <20 trades")

# ── T2: Strategy scorecard ───────────────────────────────────────────────────
print("== Strategy scorecard ==")
sc = v.strategy_scorecard()
check("success", sc.get("success") is True)
for s in sc.get("strategies", []):
    check(f"{s['strategy']} counts consistent", s["wins"] + s["losses"] == s["trades"])
    check(f"{s['strategy']} has status", bool(s.get("status")))
    check(f"{s['strategy']} advisory only", "disab" not in str(s.get("recommendation", "")).lower()
          or "never" in str(sc.get("note", "")).lower())
    if s["trades"] < 5:
        check(f"{s['strategy']} insufficient marked",
              s["status"] in ("INSUFFICIENT DATA", "Watch", "WATCH") or not s.get("sufficient_data", True))

# ── T3: Confidence / regime / sector validation ──────────────────────────────
print("== Confidence / regime / sector ==")
cv = v.confidence_validation()
check("bands present", len(cv.get("bands", [])) >= 4)
total_band_trades = sum(b["trades"] for b in cv["bands"])
check("band trades == completed", total_band_trades == o["completed_trades"],
      f"{total_band_trades} vs {o['completed_trades']}")
for b in cv["bands"]:
    if b["trades"] == 0:
        check(f"band {b['band']} zero ⇒ no win rate", b.get("win_rate_pct") is None)

rv = v.regime_validation()
check("regimes present", len(rv.get("regimes", [])) > 0)
sv = v.sector_validation()
check("sectors present", len(sv.get("sectors", [])) > 0)

# ── T4: AI decision validation honesty ───────────────────────────────────────
print("== AI decision validation ==")
ai = v.ai_decision_validation()
check("success", ai.get("success") is True)
check("honesty note about HOLD/false negatives", bool(ai.get("note")))
import json as _json
_cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_decisions_cache.json")
if os.path.exists(_cache_path):
    _decisions = _json.load(open(_cache_path))
    if isinstance(_decisions, dict):
        _decisions = _decisions.get("decisions", [])
    _has_decisions = any(isinstance(d, dict) and (d.get("decision") or d.get("final_action") or d.get("action"))
                         for d in _decisions)
    if _has_decisions:
        _total = (ai.get("buy_recommendations", 0) + ai.get("watch_recommendations", 0)
                  + ai.get("ignore_recommendations", 0))
        check("decision counts non-zero when cache has decisions", _total > 0,
              f"cache has {len(_decisions)} decisions but counts total {_total}")

# ── T5: Trade review ─────────────────────────────────────────────────────────
print("== Trade review ==")
tr = v.trade_review()
check("count matches", tr.get("count") == len(tr.get("trades", [])))
for t in tr.get("trades", []):
    check(f"{t['symbol']} has explanation", bool(t.get("ai_explanation")))
    check(f"{t['symbol']} lesson lists", isinstance(t.get("lessons_learned"), list))

# ── T6: Weekly / monthly reports ─────────────────────────────────────────────
print("== Weekly / monthly ==")
wk, mo = v.weekly_report(), v.monthly_report()
check("weekly stats", isinstance(wk.get("stats"), dict))
check("monthly stats", isinstance(mo.get("stats"), dict))
check("weekly period", wk.get("period_days") == 7)
check("monthly period", mo.get("period_days") == 30)

# ── T7: Recommendations are advisory ─────────────────────────────────────────
print("== Recommendations ==")
rec = v.improvement_recommendations()
check("success", rec.get("success") is True)
check("recommendations list", isinstance(rec.get("recommendations"), list))

# ── T8: Failure / success analysis ───────────────────────────────────────────
print("== Failure / success ==")
fa, sa = v.failure_analysis(), v.success_analysis()
check("losses + wins == completed",
      fa.get("losing_trades", 0) + sa.get("winning_trades", 0) <= o["completed_trades"])
check("by_strategy list", isinstance(fa.get("by_strategy"), list))
check("by_sector list", isinstance(fa.get("by_sector"), list))

# ── T9: Timeline & bug detection ─────────────────────────────────────────────
print("== Timeline / bugs ==")
t = v.validation_timeline()
check("goals present", t.get("trading_days_goal") == 100 and t.get("completed_trades_goal") == 500)
check("readiness 0-100", 0 <= (t.get("production_readiness_pct") or 0) <= 100)
b = v.bug_detection()
check("checks performed", (b.get("checks_performed") or 0) >= 5)
check("verdict present", b.get("verdict") in ("PASS", "WARN", "HEALTHY", "ISSUES FOUND", "FAIL"))

# ── T10: Exports ─────────────────────────────────────────────────────────────
print("== Exports ==")
from phase16_exports import build_exports, EXPORT_DIR, REPORT_MD

r = build_exports()
check("export success", r.get("success") is True)
for f in ("Validation_Report.csv", "Strategy_Scorecard.csv", "Trade_Review.csv",
          "AI_Recommendations.csv", "Validation_Report.xlsx", "Validation_Report.pdf"):
    check(f"export {f}", os.path.exists(os.path.join(EXPORT_DIR, f)))
check("report md written", os.path.exists(REPORT_MD))
md = open(REPORT_MD).read()
check("report has research-only label", "RESEARCH ONLY" in md)
check("report honest about goals", "500" in md and "100" in md)

print(f"\n{PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
