"""
test_phase9.py — Phase 9: AI Copilot, Alerts & Explainability tests.

Runs against the real cached scan/market/state files (read-only) plus
temp-file isolation for alert/history persistence tests.

Run: python3 test_phase9.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import copilot_engine as ce

PASS = 0
FAIL = 0
FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


# ── Isolate persistence files so tests don't pollute real state ───────────────
_tmp = tempfile.mkdtemp(prefix="phase9_test_")
ce.ALERTS_FILE = os.path.join(_tmp, "alerts.json")
ce.CONF_HISTORY_FILE = os.path.join(_tmp, "conf_history.json")
_real_dir = ce._DIR


def cleanup():
    shutil.rmtree(_tmp, ignore_errors=True)


# ── 1. Copilot summary ────────────────────────────────────────────────────────
print("1. copilot_summary")
s = ce.copilot_summary()
check("summary success", s.get("success") is True)
check("has market regime", "regime" in s.get("market", {}))
check("has sentiment", "sentiment" in s.get("market", {}))
check("has portfolio", "cash" in s.get("portfolio", {}))
check("portfolio risk level valid", s["portfolio"]["risk_level"] in ("LOW", "MEDIUM", "HIGH"))
check("has risks list", isinstance(s.get("risks"), list) and len(s["risks"]) > 0)
check("has avoid list", isinstance(s.get("avoid"), list))
check("avoid has reasons", all("reason" in a for a in s.get("avoid", [])))
check("has voice_text", isinstance(s.get("voice_text"), str) and len(s["voice_text"]) > 20)
check("has label", s.get("label") == "PAPER / LIVE DATA VALIDATION")
check("has scan_id (no look-ahead: cached scan)", s.get("scan_id") is not None)
if s.get("best_opportunity"):
    check("best opportunity has symbol", bool(s["best_opportunity"].get("symbol")))
    check("best opportunity has confidence", "confidence" in s["best_opportunity"])
if s.get("highest_confidence_trade"):
    check("highest confidence trade has symbol", bool(s["highest_confidence_trade"].get("symbol")))

# ── 2. Alerts: generation, dedup, persistence ────────────────────────────────
print("2. alerts")
# Seed confidence history twice with modified data to trigger confidence alerts
ce.record_confidence_snapshot()
hist = ce._load(ce.CONF_HISTORY_FILE, [])
check("snapshot recorded", len(hist) == 1)
r2 = ce.record_confidence_snapshot()
check("snapshot idempotent per scan_id", r2.get("recorded") is False)

# Fake a previous snapshot with lower confidence to trigger CONFIDENCE_INCREASED
if hist:
    prev = json.loads(json.dumps(hist[0]))
    prev["scan_id"] = "prev_scan_x"
    for st in prev.get("stocks", [])[:3]:
        if st.get("confidence") is not None:
            st["confidence"] = max(0, st["confidence"] - 15)
    ce._save(ce.CONF_HISTORY_FILE, [prev] + hist)

a = ce.generate_alerts()
check("alerts success", a.get("success") is True)
check("alerts persisted", os.path.exists(ce.ALERTS_FILE))
n_first = a.get("new_alerts", 0)
a2 = ce.generate_alerts()
check("alerts dedup on second run", a2.get("new_alerts") == 0,
      f"expected 0 new, got {a2.get('new_alerts')}")

all_alerts = ce._load_alerts()
for al in all_alerts:
    check(f"alert {al['type']} has required fields",
          all(k in al for k in ("alert_id", "ts", "type", "severity", "category",
                                "reason", "confidence", "action_recommendation", "read")),
          str(al.keys()))
    check(f"alert {al['type']} severity valid", al["severity"] in ("INFO", "WARNING", "CRITICAL"))
    check(f"alert {al['type']} category valid", al["category"] in ("trade", "risk", "market", "ai"))
    break  # structural check on first alert is representative
if all_alerts:
    check("all severities valid", all(x["severity"] in ("INFO", "WARNING", "CRITICAL") for x in all_alerts))
    check("all unread initially", all(x["read"] is False for x in all_alerts))

# ── list_alerts sections ─────────────────────────────────────────────────────
print("3. notification center")
la = ce.list_alerts()
check("list success", la.get("success") is True)
check("has sections", all(k in la.get("sections", {}) for k in
      ("today", "unread", "risk_alerts", "market_alerts", "ai_suggestions", "trade_alerts")))
check("unread count matches", la.get("unread_count") == len(all_alerts))

# mark read: single then all
if all_alerts:
    first_id = all_alerts[0]["alert_id"]
    mr = ce.mark_alerts_read(first_id)
    check("mark single read", mr.get("marked_read") == 1)
    mr2 = ce.mark_alerts_read("all")
    check("mark all read", mr2.get("unread_remaining") == 0)

# ── 4. Daily briefing ─────────────────────────────────────────────────────────
print("4. daily_briefing")
b = ce.daily_briefing()
check("briefing success", b.get("success") is True)
check("briefing greeting", b.get("greeting", "").startswith("Good"))
check("briefing market summary", "regime" in b.get("market_summary", {}))
check("briefing has sectors", isinstance(b.get("top_sectors"), list))
check("briefing has opportunities", isinstance(b.get("opportunities"), list))
check("briefing portfolio summary", "cash" in b.get("portfolio_summary", {}))
check("briefing risk assessment", b.get("risk_assessment") in ("LOW", "MEDIUM", "HIGH"))
check("briefing volatility", "category" in b.get("expected_volatility", {}))
check("briefing economic events placeholder",
      b.get("economic_events", [{}])[0].get("status") == "PLACEHOLDER")
check("briefing voice_text", len(b.get("voice_text", "")) > 40)
check("briefing lines list", isinstance(b.get("briefing_lines"), list) and len(b["briefing_lines"]) >= 4)

# ── 5. Trade explanations ─────────────────────────────────────────────────────
print("5. trade explanations")
te = ce.trade_explanations(limit=5)
check("explanations success", te.get("success") is True)
check("explanations returned", len(te.get("explanations", [])) > 0)
if te.get("explanations"):
    e = te["explanations"][0]
    for field in ("symbol", "action", "indicators_supporting", "indicators_against",
                  "risk", "expected_holding_period_days", "historical_win_rate",
                  "expected_reward_pct", "voice_text"):
        check(f"explanation has {field}", field in e, str(e.keys()))
    check("risk valid", e["risk"] in ("LOW", "MEDIUM", "HIGH"))
    check("indicators are lists", isinstance(e["indicators_supporting"], list)
          and isinstance(e["indicators_against"], list))
    # single-symbol variant
    single = ce.trade_explanation(e["symbol"])
    check("single explanation success", single.get("success") is True)
    check("single explanation matches", single["explanation"]["symbol"] == e["symbol"])

check("explanation for unknown symbol fails cleanly",
      ce.trade_explanation("ZZZNOTREAL").get("success") is False)

# ── 6. Why not buy? ───────────────────────────────────────────────────────────
print("6. why_not")
recs = ce._recs()
ignored = [r for r in recs if r.get("final_action") == "IGNORE"]
if ignored:
    wn = ce.why_not(ignored[0]["symbol"])
    check("why_not success", wn.get("success") is True)
    check("why_not has reasons", len(wn.get("reasons", [])) > 0)
    check("why_not has missing confirmations list", isinstance(wn.get("missing_confirmations"), list))
    check("why_not has failed_rules list", isinstance(wn.get("failed_rules"), list))
    check("why_not voice_text", len(wn.get("voice_text", "")) > 10)
check("why_not unknown symbol fails cleanly", ce.why_not("ZZZNOTREAL").get("success") is False)

# ── 7. Watchlist insights ─────────────────────────────────────────────────────
print("7. watchlist insights")
wi = ce.watchlist_insights()
check("watchlist success", wi.get("success") is True)
check("watchlist insights list", isinstance(wi.get("insights"), list))
for ins in wi.get("insights", []):
    if ins.get("available"):
        for field in ("trend", "momentum", "strength", "confidence",
                      "estimated_upside_pct", "estimated_downside_pct",
                      "risk", "holding_period_days"):
            check(f"insight {ins['symbol']} has {field}", field in ins, str(ins.keys()))
        check(f"insight {ins['symbol']} trend valid", ins["trend"] in ("UP", "DOWN", "MIXED"))
        break  # representative

# ── 8. Confidence history ─────────────────────────────────────────────────────
print("8. confidence history")
ch = ce.confidence_history()
check("history success", ch.get("success") is True)
check("history has series", len(ch.get("series", [])) >= 1)
sr = ch["series"][-1]
for field in ("avg_confidence", "avg_opportunity_score", "trade_quality_pct", "buy_count"):
    check(f"series has {field}", field in sr)
if recs:
    sym = recs[0]["symbol"]
    chs = ce.confidence_history(sym)
    check("symbol series returned", "symbol_series" in chs)
    check("symbol series has confidence", "confidence" in chs["symbol_series"][-1])

# ── 9. Voice-ready text everywhere ────────────────────────────────────────────
print("9. voice-ready")
check("summary voice_text", "voice_text" in s)
check("briefing voice_text", "voice_text" in b)
if te.get("explanations"):
    check("explanation voice_text", "voice_text" in te["explanations"][0])

# ── 10. Export + safety ───────────────────────────────────────────────────────
print("10. export & safety")
ex_json = ce.export_phase9("json")
check("json export success", ex_json.get("success") is True)
check("json export file exists", os.path.exists(ex_json.get("file", "")))
ex_csv = ce.export_phase9("csv")
check("csv export success", ex_csv.get("success") is True)
check("csv export file exists", os.path.exists(ex_csv.get("file", "")))
check("csv summaries file exists", os.path.exists(ex_csv.get("summaries_file", "")))
with open(ex_csv["file"]) as f:
    header = f.readline()
    check("csv has alert columns", "alert_id" in header and "severity" in header)

# Safety: engine never mutates scan cache or paper state
scan_before = json.dumps(ce._scan().get("scan_id"))
state_before = json.dumps(ce._state().get("cash"))
ce.copilot_summary(); ce.daily_briefing(); ce.generate_alerts()
check("scan cache unchanged (read-only)", json.dumps(ce._scan().get("scan_id")) == scan_before)
check("paper state unchanged (read-only)", json.dumps(ce._state().get("cash")) == state_before)

# No look-ahead: summary uses cached scan snapshot ts, never future data
check("summary bound to cached snapshot", s.get("snapshot_ts") == ce._scan().get("snapshot_ts"))

cleanup()

print(f"\n{'='*60}\nPhase 9 tests: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f_ in FAILURES:
        print(f"  - {f_}")
    sys.exit(1)
print("ALL PASS ✅")
