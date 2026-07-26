"""
test_phase11.py — Phase 11 Institutional Risk Engine test suite.

Runs against isolated temp state files — never touches real state.json,
config, alerts or kill-switch files. Verifies:
  - all 8 pre-trade checks and verdict logic
  - dynamic position sizing math (reproducible, auditable)
  - portfolio dashboard payload
  - alerts generation + dedupe
  - kill switch trigger / acknowledge-to-resume / enforcement
  - execute_buy enforcement (blocked on REJECT, bypass for legacy/tests)
  - live execution remains disabled (phase 8 mode unchanged)
  - read-only guarantee for assessment paths
  - report files produced
"""

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import phase11_risk as rk
import paper_trader as pt

PASS = 0
FAIL = 0
FAILURES = []


def ok(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


# ── Isolated environment ─────────────────────────────────────────────────────

tmpdir = tempfile.mkdtemp(prefix="phase11_test_")
orig = {
    "STATE_FILE": rk.STATE_FILE, "CONFIG_FILE": rk.CONFIG_FILE,
    "KILL_SWITCH_FILE": rk.KILL_SWITCH_FILE, "ALERTS_FILE": rk.ALERTS_FILE,
    "SCAN_CACHE_FILE": rk.SCAN_CACHE_FILE, "MARKET_CACHE_FILE": rk.MARKET_CACHE_FILE,
    "EXPORT_DIR": rk.EXPORT_DIR,
}
rk.STATE_FILE = os.path.join(tmpdir, "state.json")
rk.CONFIG_FILE = os.path.join(tmpdir, "risk_config.json")
rk.KILL_SWITCH_FILE = os.path.join(tmpdir, "kill_switch.json")
rk.ALERTS_FILE = os.path.join(tmpdir, "alerts.json")
rk.SCAN_CACHE_FILE = os.path.join(tmpdir, "scan_cache.json")
rk.MARKET_CACHE_FILE = os.path.join(tmpdir, "market_cache.json")
rk.EXPORT_DIR = os.path.join(tmpdir, "exports")
NOW = datetime.now()


def write_state(cash=10000.0, positions=None, trades=None, pnl=None):
    with open(rk.STATE_FILE, "w") as f:
        json.dump({
            "cash": cash,
            "positions": positions or {},
            "trades": trades or [],
            "pnl_history": pnl or [{"timestamp": NOW.isoformat(), "value": cash}],
        }, f)


def write_scan(recs):
    with open(rk.SCAN_CACHE_FILE, "w") as f:
        json.dump({"recommendations": recs}, f)


def write_market(vix=15.0):
    with open(rk.MARKET_CACHE_FILE, "w") as f:
        json.dump({"vix": vix, "vix_category": "TEST"}, f)


write_state()
write_scan([])
write_market()

try:
    # ── Position sizing ──────────────────────────────────────────────────
    write_state(cash=10000.0)
    s = rk.position_size("TCS", price=100.0, stop_loss=95.0, confidence=70.0)
    # risk budget = 10000*1% = 100; conf 70 -> band [60,1.0] -> x1.0; /5 = 20
    # capital cap 20% = 2000/100 = 20 → recommended 20
    ok("sizing success", s["success"])
    ok("sizing qty capped by capital", s["recommended_quantity"] == 20, str(s["constraints"]))
    ok("sizing by_risk_budget", s["constraints"]["by_risk_budget"] == 20, str(s["constraints"]))
    ok("sizing audit steps present", len(s["audit_steps"]) >= 5)
    ok("sizing ATR honest", s["inputs"]["atr"] is None and "Not Available" in s["inputs"]["atr_note"])

    s2 = rk.position_size("TCS", price=100.0, stop_loss=95.0, confidence=70.0)
    ok("sizing reproducible", s["recommended_quantity"] == s2["recommended_quantity"]
       and s["constraints"] == s2["constraints"])

    slow = rk.position_size("TCS", price=100.0, stop_loss=95.0, confidence=30.0)
    ok("low confidence halves budget", slow["constraints"]["by_risk_budget"] == 10, str(slow["constraints"]))

    snone = rk.position_size("TCS", price=100.0, stop_loss=95.0, confidence=None)
    ok("no confidence -> conservative 0.5x", snone["constraints"]["by_risk_budget"] == 10)

    bad = rk.position_size("TCS", price=100.0, stop_loss=None)
    ok("no stop -> cannot size", not bad["success"] and bad["recommended_quantity"] == 0)
    bad2 = rk.position_size("TCS", price=100.0, stop_loss=105.0)
    ok("stop above price -> cannot size", not bad2["success"])

    # ── Pre-trade checks ─────────────────────────────────────────────────
    write_state(cash=10000.0)
    a = rk.assess_trade("TCS", 10, 100.0, 95.0, 70.0)
    ok("assess approve clean", a["verdict"] in ("APPROVE", "APPROVE_WITH_WARNINGS"), a["verdict"])
    ok("assess 8 checks", len(a["checks"]) == 8, str(len(a["checks"])))
    ok("assess echoes inputs", a["inputs"]["price"] == 100.0 and a["inputs"]["stop_loss"] == 95.0)

    # 1. max risk per trade: 100 qty x 5 = 500 = 5% of PV >> 1%
    a = rk.assess_trade("TCS", 100, 100.0, 95.0, 70.0)
    ok("max risk fail rejects", a["verdict"] == "REJECT" and "max_risk_per_trade" in a["hard_fails"], str(a["hard_fails"]))

    # 2. REDUCE when above recommended but within risk tolerance
    a = rk.assess_trade("TCS", 24, 100.0, 95.0, 70.0)
    # 24*5=120 → 1.2% <= 1.25% tolerance; recommended 20 → REDUCE
    ok("reduce verdict", a["verdict"] == "REDUCE" and a["recommended_quantity"] == 20,
       f"{a['verdict']} rec={a['recommended_quantity']} fails={a['hard_fails']}")

    # 3. liquidity from scan cache
    write_scan([{"symbol": "TCS", "sector": "IT", "volume_ratio": 0.1,
                 "data_age_days": 1.0, "calibrated_confidence": 70.0,
                 "entry_price": 100.0, "stop_loss": 95.0}])
    a = rk.assess_trade("TCS", 10, 100.0, 95.0, 70.0)
    liq = next(c for c in a["checks"] if c["check"] == "liquidity")
    ok("liquidity warn on low volume", liq["status"] == "WARN", str(liq))
    write_scan([])
    a = rk.assess_trade("TCS", 10, 100.0, 95.0, 70.0)
    liq = next(c for c in a["checks"] if c["check"] == "liquidity")
    ok("liquidity honest when unknown", "Not Available" in liq["detail"], str(liq))

    # 4. gap risk: stale data
    write_scan([{"symbol": "TCS", "sector": "IT", "volume_ratio": 1.0,
                 "data_age_days": 10.0, "entry_price": 100.0, "stop_loss": 95.0}])
    a = rk.assess_trade("TCS", 10, 100.0, 95.0, 70.0)
    gap = next(c for c in a["checks"] if c["check"] == "gap_risk")
    ok("gap risk warns on stale data", gap["status"] == "WARN", str(gap))
    # tight stop
    write_scan([])
    a = rk.assess_trade("TCS", 10, 100.0, 99.5, 70.0)
    gap = next(c for c in a["checks"] if c["check"] == "gap_risk")
    ok("gap risk warns on tight stop", gap["status"] == "WARN", str(gap))
    # VIX spike
    write_market(vix=30.0)
    a = rk.assess_trade("TCS", 10, 100.0, 95.0, 70.0)
    gap = next(c for c in a["checks"] if c["check"] == "gap_risk")
    ok("gap risk warns on VIX spike", gap["status"] == "WARN" and "VIX" in gap["detail"], str(gap))
    write_market(vix=15.0)

    # 5/6. sector & stock limits
    write_state(cash=2000.0, positions={"INFY": {"quantity": 30, "avg_price": 100.0}},
                trades=[{"symbol": "INFY", "action": "BUY", "quantity": 30, "price": 100.0,
                         "stop_loss": 95.0, "timestamp": NOW.isoformat()}])
    a = rk.assess_trade("TCS", 15, 100.0, 98.0, 70.0)  # IT+IT: 3000+1500 = 90% of 5000
    ok("sector limit enforced", "sector_exposure" in a["hard_fails"], str(a["hard_fails"]))
    a = rk.assess_trade("INFY", 15, 100.0, 98.0, 70.0)
    ok("stock concentration enforced", "stock_concentration" in a["hard_fails"], str(a["hard_fails"]))

    # 7. correlation proxy
    corr = next(c for c in rk.assess_trade("TCS", 1, 100.0, 98.0, 70.0)["checks"] if c["check"] == "correlation")
    ok("same-sector correlation warns", corr["status"] == "WARN" and corr["value"] == 0.7, str(corr))
    corr2 = next(c for c in rk.assess_trade("RELIANCE", 1, 100.0, 98.0, 70.0)["checks"] if c["check"] == "correlation")
    ok("cross-sector correlation passes", corr2["status"] == "PASS" and corr2["value"] == 0.25, str(corr2))
    ok("correlation labelled as proxy", "proxy" in corr["detail"].lower())

    # 8. portfolio heat
    write_state(cash=5000.0,
                positions={"INFY": {"quantity": 50, "avg_price": 100.0}},
                trades=[{"symbol": "INFY", "action": "BUY", "quantity": 50, "price": 100.0,
                         "stop_loss": 90.0, "timestamp": NOW.isoformat()}])
    # heat = 50*10 / 10000 = 5%; +TCS 10x5=50 → 0.5% → 5.5% < 6 PASS
    a = rk.assess_trade("TCS", 10, 100.0, 95.0, 70.0)
    heat = next(c for c in a["checks"] if c["check"] == "portfolio_heat")
    ok("heat computed", heat["status"] == "PASS" and abs(heat["value"] - 5.5) < 0.01, str(heat))
    a = rk.assess_trade("TCS", 25, 100.0, 90.0, 70.0)  # +2.5% → 7.5% > 6
    ok("heat limit enforced", "portfolio_heat" in a["hard_fails"], str(a["hard_fails"]))

    # unbounded risk positions excluded from heat but flagged
    write_state(cash=5000.0, positions={"WIPRO": {"quantity": 5, "avg_price": 100.0}}, trades=[])
    heat_pct, detail, unbounded = rk._portfolio_heat(rk._state(), 5500.0)
    ok("no-stop position excluded from heat", heat_pct == 0.0 and len(unbounded) == 1, f"{heat_pct} {unbounded}")

    # ── Dashboard ────────────────────────────────────────────────────────
    write_state(cash=5000.0,
                positions={"INFY": {"quantity": 20, "avg_price": 100.0}, "RELIANCE": {"quantity": 10, "avg_price": 100.0}},
                trades=[{"symbol": "INFY", "action": "BUY", "quantity": 20, "price": 100.0, "stop_loss": 95.0, "timestamp": NOW.isoformat()},
                        {"symbol": "RELIANCE", "action": "BUY", "quantity": 10, "price": 100.0, "stop_loss": 95.0, "timestamp": NOW.isoformat()}],
                pnl=[{"timestamp": (NOW - timedelta(days=2)).isoformat(), "value": 8500.0},
                     {"timestamp": (NOW - timedelta(hours=5)).isoformat(), "value": 8300.0},
                     {"timestamp": NOW.isoformat(), "value": 8000.0}])
    d = rk.portfolio_risk()
    ok("dashboard success", d["success"])
    ok("dashboard pv", d["portfolio_value"] == 8000.0, str(d["portfolio_value"]))
    ok("dashboard cash pct", d["cash_allocation_pct"] == 62.5, str(d["cash_allocation_pct"]))
    ok("dashboard sectors", {s["sector"] for s in d["sector_allocation"]} == {"IT", "ENERGY"})
    ok("dashboard corr matrix", d["correlation_matrix"]["matrix"][0]["correlations"]["INFY"] == 1.0)
    ok("dashboard corr labelled proxy", "proxy" in d["correlation_matrix"]["method"])
    ok("dashboard diversification 0-100", 0 <= (d["diversification_score"] or 0) <= 100)
    ok("dashboard exposures sorted", d["largest_exposures"][0]["symbol"] == "INFY")
    ok("dashboard heat", abs(d["portfolio_heat_pct"] - (150 / 8000 * 100)) < 0.01, str(d["portfolio_heat_pct"]))
    ok("dashboard budget usage", d["risk_budget"]["used_pct_of_budget"] > 0)
    # weekly window: peak 8500 → 8000 = 5.88%
    ok("dashboard weekly drawdown", abs(d["drawdowns"]["weekly"]["drawdown_pct"] - 5.88) < 0.05,
       str(d["drawdowns"]))
    ok("dashboard daily drawdown", d["drawdowns"]["daily"]["drawdown_pct"] is not None)
    d2 = rk.portfolio_risk()
    ok("dashboard reproducible", d["portfolio_heat_pct"] == d2["portfolio_heat_pct"]
       and d["diversification_score"] == d2["diversification_score"])

    # ── Alerts ───────────────────────────────────────────────────────────
    # daily loss: realized -400 today on pv 8000 = 5% > 3%
    rk.update_config({"auto_kill_switch": False})
    write_state(cash=8000.0, positions={},
                trades=[{"symbol": "INFY", "action": "SELL", "quantity": 10, "price": 60.0,
                         "pnl": -400.0, "timestamp": NOW.isoformat()}])
    al = rk.risk_alerts()
    types = {a["type"] for a in al["new_alerts"]}
    ok("daily loss alert", "DAILY_LOSS_LIMIT" in types, str(types))
    al2 = rk.risk_alerts()
    ok("alerts deduped", not any(a["type"] == "DAILY_LOSS_LIMIT" for a in al2["new_alerts"]))

    write_state(cash=1000.0, positions={"INFY": {"quantity": 50, "avg_price": 100.0}},
                trades=[{"symbol": "INFY", "action": "BUY", "quantity": 50, "price": 100.0,
                         "stop_loss": 95.0, "timestamp": NOW.isoformat()}])
    al = rk.risk_alerts()
    types = {a["type"] for a in al["new_alerts"]}
    ok("sector concentration alert", "SECTOR_CONCENTRATION" in types, str(types))
    ok("oversized position alert", "POSITION_OVERSIZED" in types, str(types))
    write_market(vix=30.0)
    al = rk.risk_alerts()
    ok("volatility spike alert", any(a["type"] == "VOLATILITY_SPIKE" for a in al["new_alerts"]), str(al["new_alerts"]))
    write_market(vix=15.0)

    # ── Kill switch ──────────────────────────────────────────────────────
    ks = rk.trigger_kill_switch("test: manual", source="manual")
    ok("kill switch triggers", ks["success"] and ks["kill_switch"]["active"])
    ok("kill switch simulated note", "SIMULATED" in ks["note"])
    a = rk.assess_trade("TCS", 1, 100.0, 95.0, 70.0)
    ok("kill switch rejects trades", a["verdict"] == "REJECT" and "Kill switch" in a["reason"])
    allowed, msg = rk.pre_trade_check("TCS", 1, 100.0, 95.0, 70.0)
    ok("pre_trade_check blocks on kill switch", not allowed and "Kill switch" in msg)
    r = rk.resume_trading(acknowledge=False)
    ok("resume requires acknowledgement", not r["success"] and "acknowledg" in r["error"].lower())
    r = rk.resume_trading(acknowledge=True)
    ok("resume with ack works", r["success"] and not r["kill_switch"]["active"])
    events = rk.kill_switch_status()["events"]
    ok("kill switch audit trail", [e["event"] for e in events] == ["TRIGGERED", "RESUMED"], str(events))

    # auto kill switch on daily loss
    rk.update_config({"auto_kill_switch": True})
    write_state(cash=8000.0, positions={},
                trades=[{"symbol": "X", "action": "SELL", "quantity": 1, "price": 1.0,
                         "pnl": -400.0, "timestamp": NOW.isoformat()}])
    d = rk.portfolio_risk()
    ok("auto kill switch on daily loss", d["kill_switch"]["active"] and d["auto_kill_triggered"], str(d["auto_kill_triggered"]))
    rk.resume_trading(acknowledge=True)

    # ── execute_buy enforcement ──────────────────────────────────────────
    # paper_trader reads portfolio state from Postgres (portfolio_store).
    # We mock _store.load_state / save_state so the test is DB-isolated.
    _clean_state = {"cash": 10000.0, "positions": {}, "trades": [], "pnl_history": []}
    with patch.object(pt._store, "load_state", return_value=_clean_state), \
         patch.object(pt._store, "save_state", lambda s: None):
        write_state(cash=10000.0)
        okd, msg = pt.execute_buy("TCS", 10, 100.0, reason="test", stop_loss_price=95.0, signal_confidence=70.0)
        ok("buy allowed when risk passes", okd, msg)
        write_state(cash=10000.0)
        okd, msg = pt.execute_buy("TCS", 100, 100.0, reason="test", stop_loss_price=95.0, signal_confidence=70.0)
        ok("buy blocked on REJECT", not okd and "RISK BLOCKED" in msg, msg)
        okd, msg = pt.execute_buy("TCS", 100, 100.0, reason="test", stop_loss_price=95.0,
                                  signal_confidence=70.0, bypass_risk=True)
        ok("bypass_risk skips enforcement", okd, msg)
        write_state(cash=10000.0)
        rk.trigger_kill_switch("test: block buys")
        okd, msg = pt.execute_buy("TCS", 5, 100.0, reason="test", stop_loss_price=95.0, signal_confidence=70.0)
        ok("buy blocked by kill switch", not okd and "Kill switch" in msg, msg)
        rk.resume_trading(acknowledge=True)

    # ── Reports ──────────────────────────────────────────────────────────
    write_state(cash=5000.0, positions={"INFY": {"quantity": 20, "avg_price": 100.0}},
                trades=[{"symbol": "INFY", "action": "BUY", "quantity": 20, "price": 100.0,
                         "stop_loss": 95.0, "timestamp": NOW.isoformat()}])
    for kind in rk.REPORT_KINDS:
        r = rk.risk_report(kind)
        ok(f"report {kind}", r["success"] and os.path.exists(r["file"]), str(r))
        ok(f"report {kind} has content", os.path.getsize(r["file"]) > 50)
    r = rk.risk_report("bogus")
    ok("report kind allowlisted", not r["success"] and "Unknown report kind" in r["error"])

    # ── Risk scores / approval cards / analytics ─────────────────────────
    rk.update_config({"max_sector_pct": 40.0})
    write_state(cash=5000.0, positions={"INFY": {"quantity": 20, "avg_price": 100.0}},
                trades=[{"symbol": "INFY", "action": "BUY", "quantity": 20, "price": 100.0,
                         "stop_loss": 95.0, "timestamp": NOW.isoformat()}])
    write_market(vix=15.0)
    good_rec = {"symbol": "RELIANCE", "sector": "ENERGY", "entry_price": 100.0, "stop_loss": 97.0,
                "target_price": 110.0, "rr_ratio": 3.3, "calibrated_confidence": 68.0,
                "opportunity_score": 70.0, "volume_ratio": 1.2, "data_age_days": 0.0,
                "adx": 35.0, "above_ema20": True, "above_ema50": True,
                "final_action": "BUY", "win_rate": 60.0, "profit_factor": 2.1,
                "data_quality": "LIVE", "snapshot_ts": NOW.isoformat()}
    weak_rec = {**good_rec, "symbol": "TCS", "sector": "IT", "adx": 8.0, "above_ema20": False,
                "above_ema50": False, "volume_ratio": 0.02, "data_age_days": 10.0,
                "stop_loss": 91.0, "final_action": "WATCH", "calibrated_confidence": 30.0}
    write_scan([good_rec, weak_rec])

    rs = rk.risk_score(good_rec, ["IT"], rk.get_config())
    ok("risk score 0-100", rs["overall_score"] is not None and 0 <= rs["overall_score"] <= 100, str(rs))
    ok("risk score band valid", rs["band"] in ("LOW", "MEDIUM", "HIGH", "EXTREME"))
    ok("event risk honest", rs["components"]["event_risk"]["score"] is None
       and "Not Available" in rs["components"]["event_risk"]["basis"])
    rs_weak = rk.risk_score(weak_rec, ["IT"], rk.get_config())
    ok("weak stock riskier", rs_weak["overall_score"] > rs["overall_score"],
       f"{rs_weak['overall_score']} vs {rs['overall_score']}")
    ok("risk score reproducible",
       rk.risk_score(good_rec, ["IT"], rk.get_config())["overall_score"] == rs["overall_score"])
    # weighted aggregation: matches explicit weighted avg renormalized over available components
    comps = {k: v["score"] for k, v in rs["components"].items() if v["score"] is not None}
    w = rk.RISK_SCORE_WEIGHTS
    expected = rk._r(sum(comps[k] * w[k] for k in comps) / sum(w[k] for k in comps))
    ok("risk score weighted+renormalized", rs["overall_score"] == expected,
       f"{rs['overall_score']} vs {expected}")
    # candidate without entry price → honest REJECT card, not dropped
    write_scan([good_rec, weak_rec, {"symbol": "NOPRICE", "sector": "IT", "entry_price": 0.0,
                                     "final_action": "AVOID"}])
    cp_all = rk.approval_cards()
    ok("all candidates get cards", len(cp_all["cards"]) == 3)
    np_card = next(c for c in cp_all["cards"] if c["symbol"] == "NOPRICE")
    ok("no-price candidate rejected honestly", np_card["verdict"] == "REJECT"
       and "Not Available" in np_card["explanation"] and np_card["risk_band"] == "Not Available")
    write_scan([good_rec, weak_rec])

    cp = rk.approval_cards()
    ok("approval cards built", cp["success"] and len(cp["cards"]) == 2)
    by_sym = {c["symbol"]: c for c in cp["cards"]}
    ok("approve for strong BUY candidate", by_sym["RELIANCE"]["verdict"] == "APPROVE", str(by_sym["RELIANCE"]["verdict"]))
    ok("watch/reject for weak candidate", by_sym["TCS"]["verdict"] in ("WATCH", "REJECT"))
    ok("card has explanation", len(by_sym["RELIANCE"]["explanation"]) > 10)
    ok("card sizing consistent",
       by_sym["RELIANCE"]["capital_required"] == rk._r(by_sym["RELIANCE"]["recommended_quantity"] * 100.0))
    ok("card max risk math", by_sym["RELIANCE"]["max_risk"] ==
       rk._r(by_sym["RELIANCE"]["recommended_quantity"] * 3.0), str(by_sym["RELIANCE"]["max_risk"]))
    ok("card reward math", by_sym["RELIANCE"]["expected_reward"] ==
       rk._r(by_sym["RELIANCE"]["recommended_quantity"] * 10.0))

    an = rk.risk_analytics()
    ok("analytics success", an["success"])
    ok("analytics utilization", an["portfolio"]["utilization_pct"] == rk._r(2000 / 7000 * 100))
    ok("analytics largest position", an["portfolio"]["largest_position"]["symbol"] == "INFY")
    ok("analytics daily risk", an["portfolio"]["daily_risk"] == 100.0, str(an["portfolio"]["daily_risk"]))
    ok("analytics max loss = invested", an["portfolio"]["max_possible_loss"] == 2000.0)
    ok("analytics heatmap colors", all(p["heat"] in ("GREEN", "YELLOW", "ORANGE", "RED") for p in an["positions"]))
    ok("analytics pie includes cash", any(x["name"] == "CASH" for x in an["charts"]["allocation_pie"]))
    ok("analytics risk distribution counts", sum(x["count"] for x in an["charts"]["risk_distribution"]) == 2)
    ok("analytics gauge", an["charts"]["utilization_gauge"]["value"] == an["portfolio"]["utilization_pct"])
    # no-stop position → daily risk honest, heat RED
    write_state(cash=5000.0, positions={"WIPRO": {"quantity": 5, "avg_price": 100.0}}, trades=[])
    an2 = rk.risk_analytics()
    ok("analytics honest daily risk without stops", "Not Available" in str(an2["portfolio"]["daily_risk"]))
    ok("no-stop position heat RED", an2["positions"][0]["heat"] == "RED")
    write_scan([])

    # ── Config ───────────────────────────────────────────────────────────
    c = rk.update_config({"max_sector_pct": 50.0})
    ok("config update", c["success"] and rk.get_config()["max_sector_pct"] == 50.0)
    c = rk.update_config({"nonsense_key": 1})
    ok("config rejects unknown keys", not c["success"])

    # ── Read-only guarantee & live execution stays off ───────────────────
    write_state(cash=7777.0)
    before = open(rk.STATE_FILE).read()
    rk.assess_trade("TCS", 5, 100.0, 95.0, 70.0)
    rk.portfolio_risk()
    rk.position_size("TCS", 100.0, 95.0, 70.0)
    after = open(rk.STATE_FILE).read()
    ok("assessment paths are read-only on state", before == after)

    p8cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase8_config.json")))
    mode = p8cfg.get("mode", "")
    ok("live execution remains disabled", "LIVE" not in str(mode).upper() or "PAPER" in str(mode).upper(),
       f"phase8 mode={mode}")

finally:
    for k, v in orig.items():
        setattr(rk, k, v)
    shutil.rmtree(tmpdir, ignore_errors=True)

print(f"\n{'=' * 60}")
print(f"Phase 11 test suite: {PASS} passed, {FAIL} failed")
for f in FAILURES:
    print(f"  FAIL: {f}")
print("=" * 60)
exit(0 if FAIL == 0 else 1)
