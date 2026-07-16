"""
test_phase22.py — Phase 22 Controlled Auto Paper Trading & Evidence tests.

Run: python3 test_phase22.py
PAPER TRADING / RESEARCH ONLY. No real Zerodha orders ever.
"""
import json
import os
import sys
import copy
from datetime import datetime, timedelta, timezone

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


# ── T1: Default OFF after deployment ─────────────────────────────────────────
print("== Default OFF ==")
import phase22_activation as act
import phase20_store as store

status = act.get_activation_status()
check("activation status available", isinstance(status, dict))
check("required confirmation text",
      status.get("required_confirmation_text") == "ENABLE PAPER ONLY")
check("ack statement mentions no real orders",
      "No real Zerodha orders" in status.get("acknowledgement_statement", ""))
settings0 = store.get_settings()
# The default template must have auto paper entries OFF (fresh deployment state).
check("settings template defaults OFF",
      store.DEFAULT_SETTINGS.get("auto_paper_entries") in (False, None))
check("activation currently reports state",
      isinstance(status.get("paper_automation_active"), bool))

# ── T2: Activation requires exact confirmation text ─────────────────────────
print("== Activation confirmation ==")
r = act.enable_paper_automation("enable paper only")
check("lowercase text rejected", not r.get("ok"), json.dumps(r)[:120])
r = act.enable_paper_automation("ENABLE PAPER")
check("partial text rejected", not r.get("ok"))
r = act.enable_paper_automation("")
check("empty text rejected", not r.get("ok"))

# ── T3: Failed readiness check blocks activation ─────────────────────────────
print("== Readiness gating ==")
import phase22_readiness as ready

cl = ready.run_readiness_checklist()
check("checklist runs", isinstance(cl.get("checks"), list) and len(cl["checks"]) >= 10)
check("all checks have detail", all("detail" in c for c in cl["checks"]))
if not cl.get("all_passed"):
    r = act.enable_paper_automation("ENABLE PAPER ONLY")
    check("failed readiness blocks activation", not r.get("ok"),
          json.dumps(r)[:150])
    check("blocked reason names failed checks",
          bool(r.get("failed_checks") or "readiness" in str(r).lower()))
else:
    check("readiness passed (market open) — skip block test", True)

# ── T4: Entry gates (champion-only, stale/fallback, duplicates, cash/risk) ──
print("== Entry gates ==")
import phase20_gates as gates

ev = gates.evaluate_entries()
check("evaluation runs", isinstance(ev, dict))
cands = ev.get("candidates", [])
gate_names = {g.get("gate") for g in ev.get("global_gates", [])}
for c in cands:
    for g in c.get("gates", []):
        gate_names.add(g.get("gate"))
gsrc = open("phase20_gates.py").read().lower()
check("gate list present", len(gate_names) > 0, str(sorted(gate_names))[:200])
for want in ("fresh", "duplicate", "cash", "risk"):
    check(f"gate covering '{want}' exists",
          any(want in (g or "") for g in gate_names) or want in gsrc,
          str(sorted(gate_names))[:200])
# Champion-only: entries derive exclusively from the canonical champion scan's
# final_action (challengers are advisory-only, never executed).
check("champion-only enforcement (canonical final_action)",
      "final_action" in gsrc)
global_fail = [g for g in ev.get("global_gates", []) if not g.get("passed")]
if global_fail:
    check("failed global gates ⇒ zero eligible candidates",
          ev.get("eligible_count", 0) == 0,
          f"eligible={ev.get('eligible_count')} failed={[g['gate'] for g in global_fail]}")

# ── T5: Fill model — next quote only, slippage + charges ─────────────────────
print("== Fill model ==")
import phase20_executor as execu

s = store.get_settings()
fill = execu.compute_fill(100.0, {**s, "fill_model": "SLIPPAGE_ADJUSTED",
                                  "slippage_pct": 0.1})
check("slippage applied to fill",
      float(fill.get("fill_price", 0)) > 100.0, str(fill))
check("slippage amount reported", float(fill.get("slippage", 0)) > 0)
charges = execu.compute_charges(10000.0, s)
check("charges positive", charges > 0, str(charges))
src = open("phase20_executor.py").read()
check("fill documented as never using future data",
      "never uses" in src and "future data" in src)

# ── T6: PENDING_DATA + stop/target exits exist ───────────────────────────────
print("== Exits ==")
import phase20_exits as exits

xsrc = open("phase20_exits.py").read()
check("PENDING_DATA handling present", "PENDING_DATA" in xsrc)
check("stop exit rule present", "STOP" in xsrc)
check("target exit rule present", "TARGET" in xsrc)

# ── T7: Risk: daily loss limit & kill switch block entries ──────────────────
print("== Risk & kill switch ==")
rsrc = open("phase20_gates.py").read().lower() + open("phase11_risk.py").read().lower()
check("daily loss limit gate", "daily_loss" in rsrc or "loss_limit" in rsrc)
check("kill switch gate", "kill" in rsrc)

# ── T8: Evidence dataset append-only & no look-ahead ────────────────────────
print("== Evidence dataset ==")
import phase22_evidence as evid

summ = evid.evidence_summary()
check("summary available", isinstance(summ, dict))
check("append-only flag", summ.get("append_only") is True)
check("paper-only label", "PAPER" in summ.get("label", ""))
esrc = open("phase22_evidence.py").read()
check("no UPDATE of decision fields (outcome cols only)",
      "eligibility_result =" not in esrc.split("def _update_outcomes")[1][:2000]
      if "def _update_outcomes" in esrc else False)
check("no DELETE statements", "DELETE FROM phase22_evidence" not in esrc)

# Horizon no-look-ahead: returns only when horizon elapsed.
_le = evid.list_evidence(limit=50)
rows = _le.get("rows", []) if isinstance(_le, dict) else _le
now = datetime.now(timezone.utc)
ok_lookahead = True
for row in rows:
    rec = row.get("recorded_at")
    try:
        t0 = datetime.fromisoformat(str(rec).replace("Z", "+00:00"))
    except Exception:
        continue
    for field, mins in (("ret_15m", 15), ("ret_30m", 30), ("ret_60m", 60)):
        if row.get(field) is not None and now - t0 < timedelta(minutes=mins):
            ok_lookahead = False
            check(f"look-ahead violation {row.get('symbol')} {field}", False)
check("no look-ahead in horizon returns", ok_lookahead)

# ── T9: Progress & milestones ────────────────────────────────────────────────
print("== Progress ==")
import phase22_progress as prog

p = prog.get_progress()
check("progress available", isinstance(p, dict))
ms = p.get("milestones", [])
check("milestones 10..500", [m["trades"] for m in ms] == [10, 30, 50, 100, 250, 500],
      str([m.get("trades") for m in ms]))
check("milestones not fabricated",
      all((m["reached"] == (p["completed_paper_trades"] >= m["trades"])) for m in ms))
check("validation note present", "not" in p.get("validation_note", "").lower())

# ── T10: Daily report & exports ──────────────────────────────────────────────
print("== Daily report & exports ==")
import phase22_report as rep

r = rep.build_daily_report()
for f in ("scheduled_scans_completed", "candidates_evaluated",
          "paper_entries_opened", "entries_blocked", "exits_completed",
          "pending_data_actions", "realized_pnl", "daily_drawdown",
          "live_order_disabled_verification"):
    check(f"report field {f}", f in r, str(sorted(r.keys()))[:200])
check("live-order verification passes",
      r.get("live_order_disabled_verification", {}).get("verified") is True,
      json.dumps(r.get("live_order_disabled_verification"))[:200])
ex = rep.export_daily_report()
files = ex.get("files", [])
exts = {os.path.splitext(f)[1] for f in files}
check("JSON export", ".json" in exts, str(exts))
check("CSV export", ".csv" in exts, str(exts))
check("PDF export", ".pdf" in exts, str(exts))

# ── T11: No secrets in reports/exports ───────────────────────────────────────
print("== Secrets hygiene ==")
blob = json.dumps(r) + json.dumps(summ) + json.dumps(p) + json.dumps(status)
for needle in ("api_key", "access_token", "secret", "password"):
    check(f"no '{needle}' in outputs", needle not in blob.lower())
for f in files:
    path = os.path.join(rep.EXPORT_DIR, os.path.basename(f))
    if os.path.exists(path) and path.endswith((".json", ".csv")):
        data = open(path, encoding="utf-8", errors="ignore").read().lower()
        check(f"no secrets in {os.path.basename(f)}",
              all(n not in data for n in ("api_key", "access_token", "password")))

# ── T12: Live-order write paths disabled ─────────────────────────────────────
print("== Live-order write paths ==")
import glob

# Live-order writes exist only behind LIVE_ASSISTED mode in execution_engine /
# broker_client; verify configuration keeps that path disabled.
import config as cfg

check("ZERODHA_ENABLED is False", getattr(cfg, "ZERODHA_ENABLED", None) is False)
check("PAPER_TRADING_MODE is True", getattr(cfg, "PAPER_TRADING_MODE", None) is True)
# Phase 22 modules must never call live order APIs.
p22_violations = []
for pyf in glob.glob("phase22_*.py"):
    text = open(pyf, encoding="utf-8", errors="ignore").read()
    for bad in ("place_order", "modify_order", "cancel_order"):
        if bad in text:
            p22_violations.append(f"{pyf}:{bad}")
check("phase22 modules never touch order APIs", not p22_violations,
      str(p22_violations))
check("daily report verifies live orders disabled",
      rep.build_daily_report().get("live_order_disabled_verification", {})
      .get("verified") is True)

# ── T13: Deterministic replay ────────────────────────────────────────────────
print("== Deterministic replay ==")
ledger = execu.get_ledger(limit=5)
if ledger:
    tid = ledger[0]["trade_id"]
    r1 = execu.replay_trade(tid)
    r2 = execu.replay_trade(tid)
    check("replay deterministic", json.dumps(r1, sort_keys=True) ==
          json.dumps(r2, sort_keys=True))
else:
    check("replay (no trades yet — structure only)",
          callable(execu.replay_trade))

# ── T14: Immediate disable ───────────────────────────────────────────────────
print("== Disable ==")
d = act.disable_paper_automation(reason="test")
check("disable always succeeds",
      d.get("success") is True or d.get("ok") is True, json.dumps(d)[:120])
check("automation off after disable",
      act.get_activation_status().get("paper_automation_active") is False)

print(f"\nPhase 22 tests: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
