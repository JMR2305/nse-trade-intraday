"""
test_phase10.py — Phase 10.1 Performance Analytics tests.

Run: python3 test_phase10.py
Uses live cached files read-only; also validates structure with synthetic
state via monkeypatched loaders where needed.
"""

from __future__ import annotations

import json
import os
import tempfile

import phase10_analytics as pa

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")


def approx(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


# ── Full payload structure ────────────────────────────────────────────────────
data = pa.performance_analytics()
check("success", data.get("success") is True)
check("label", data.get("label") == "PAPER / LIVE DATA VALIDATION")
check("initial_capital", data.get("initial_capital") == 5000.0)
for key in ["summary", "risk", "charts", "strategy_performance", "sector_performance",
            "best_worst", "ai_performance", "historical_trades", "benchmarks",
            "data_sufficiency"]:
    check(f"has_{key}", key in data)

s = data["summary"]
for key in ["total_return_pct", "today_return", "weekly_return", "monthly_return",
            "total_trades", "win_rate_pct", "profit_factor", "avg_winner",
            "avg_loser", "expectancy", "portfolio_value"]:
    check(f"summary.{key}", key in s)
check("summary.trades_count_nonneg", s["total_trades"] >= 0)
check("summary.win_rate_range", 0 <= (s["win_rate_pct"] or 0) <= 100)
check("summary.wins_losses_sum", s["wins"] + s["losses"] <= s["total_trades"])

r = data["risk"]
for key in ["max_drawdown_pct", "current_drawdown_pct", "sharpe", "sortino",
            "calmar", "volatility_pct", "beta", "risk_score", "risk_level"]:
    check(f"risk.{key}", key in r)
check("risk.score_range", 0 <= (r["risk_score"] or 0) <= 100)
check("risk.level_valid", r["risk_level"] in ("LOW", "MEDIUM", "HIGH"))
check("risk.dd_nonneg", (r["max_drawdown_pct"] or 0) >= 0)

c = data["charts"]
for key in ["equity_curve", "daily_pnl", "monthly_returns", "drawdown",
            "cumulative_profit", "win_loss"]:
    check(f"charts.{key}", key in c)
check("charts.equity_nonempty", len(c["equity_curve"]) >= 1)
check("charts.equity_fields", all("equity" in p and "date" in p for p in c["equity_curve"]))
check("charts.winloss_fields", "wins" in c["win_loss"] and "losses" in c["win_loss"])
check("charts.drawdown_len", len(c["drawdown"]) == len(c["equity_curve"]))

# Cumulative profit must be monotone-consistent with daily pnl
dp = c["daily_pnl"]
cp = c["cumulative_profit"]
check("charts.cum_len", len(cp) == len(dp))
if dp:
    total = sum(d["pnl"] for d in dp)
    check("charts.cum_total", approx(cp[-1]["cumulative_profit"], total), f"{cp[-1]} vs {total}")

sp = data["strategy_performance"]
check("strategy.universe", len(sp) >= 8)
names = [row["strategy"] for row in sp]
for want in pa.KNOWN_STRATEGIES:
    check(f"strategy.has_{want.replace(' ', '_')}", want in names)
for row in sp:
    check("strategy.row_fields", all(k in row for k in ["trades", "wins", "losses", "win_rate_pct", "avg_return_pct", "profit_factor", "total_profit"]))
    check("strategy.row_consistent", row["wins"] + row["losses"] <= row["trades"])

sec = data["sector_performance"]
sec_names = [row["sector"] for row in sec]
for want in pa.KNOWN_SECTORS:
    check(f"sector.has_{want}", want in sec_names)

bw = data["best_worst"]
if bw["best"]:
    check("best.positive", bw["best"]["pnl"] > 0)
    check("best.fields", all(k in bw["best"] for k in ["symbol", "entry", "exit", "holding_days", "return_pct", "pnl", "strategy"]))
if bw["worst"]:
    check("worst.negative", bw["worst"]["pnl"] < 0)
    check("worst.fields", all(k in bw["worst"] for k in ["symbol", "return_pct", "pnl", "reason", "holding_days"]))

ai = data["ai_performance"]
for key in ["prediction_accuracy_pct", "confidence_accuracy_pct", "avg_confidence",
            "avg_opportunity_score", "buy_signal_accuracy_pct", "sell_signal_accuracy_pct",
            "exit_signal_accuracy_pct", "avg_holding_days", "trade_quality_score",
            "learning_score", "estimated"]:
    check(f"ai.{key}", key in ai)

ht = data["historical_trades"]
for t in ht:
    check("hist.fields", all(k in t for k in ["date", "symbol", "strategy", "entry", "exit", "return_pct", "holding_days", "confidence", "opportunity_score", "outcome"]))
    check("hist.outcome", t["outcome"] in ("WIN", "LOSS", "FLAT"))
if len(ht) >= 2:
    check("hist.sorted_desc", ht[0]["date"] >= ht[-1]["date"])

bm = data["benchmarks"]
check("bench.count", len(bm) == 4)
bnames = [b["benchmark"] for b in bm]
for want in ["NIFTY 50", "Bank Nifty", "Equal Weight Portfolio", "Buy & Hold"]:
    check(f"bench.has_{want.replace(' ', '_')}", want in bnames)
for b in bm:
    check("bench.fields", all(k in b for k in ["benchmark_return_pct", "portfolio_return_pct", "outperformance_pct", "alpha", "beta"]))
    check("bench.outperf_consistent", approx(b["outperformance_pct"], (b["portfolio_return_pct"] or 0) - (b["benchmark_return_pct"] or 0), 0.05))

# ── Read-only guarantee ───────────────────────────────────────────────────────
before = open(pa.STATE_FILE).read() if os.path.exists(pa.STATE_FILE) else None
pa.performance_analytics()
after = open(pa.STATE_FILE).read() if os.path.exists(pa.STATE_FILE) else None
check("readonly.state_unchanged", before == after)

# ── Exports ───────────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
orig_export = pa.EXPORT_DIR
pa.EXPORT_DIR = tmp
try:
    ej = pa.export_analytics("json")
    check("export.json_ok", ej["success"] and os.path.exists(ej["file"]))
    check("export.json_valid", json.load(open(ej["file"])).get("success") is True)
    ec = pa.export_analytics("csv")
    check("export.csv_ok", ec["success"] and os.path.exists(ec["file"]))
    lines = open(ec["file"]).read().strip().splitlines()
    check("export.csv_header", lines[0].startswith("trade_id,date,symbol"))
    check("export.csv_rows", len(lines) - 1 == ec["rows"])
    es = pa.export_analytics("snapshot")
    check("export.snapshot_ok", es["success"] and os.path.exists(es["file"]))
    snap = json.load(open(es["file"]))
    check("export.snapshot_fields", all(k in snap for k in ["summary", "risk", "ai_performance", "benchmarks"]))
finally:
    pa.EXPORT_DIR = orig_export

# ── Synthetic-data math checks (isolated state) ───────────────────────────────
synth_state = {
    "cash": 5200.0,
    "positions": {},
    "trades": [
        {"id": "b1", "symbol": "AAA", "action": "BUY", "quantity": 10, "price": 100.0, "total": 1000.0, "timestamp": "2026-07-01T10:00:00"},
        {"id": "s1", "symbol": "AAA", "action": "SELL", "quantity": 10, "price": 110.0, "total": 1100.0, "timestamp": "2026-07-03T10:00:00", "entry_price": 100.0, "pnl": 100.0, "pnl_pct": 10.0, "exit_type": "TARGET_HIT"},
        {"id": "b2", "symbol": "BBB", "action": "BUY", "quantity": 10, "price": 50.0, "total": 500.0, "timestamp": "2026-07-04T10:00:00"},
        {"id": "s2", "symbol": "BBB", "action": "SELL", "quantity": 10, "price": 45.0, "total": 450.0, "timestamp": "2026-07-05T10:00:00", "entry_price": 50.0, "pnl": -50.0, "pnl_pct": -10.0, "exit_type": "STOP_LOSS"},
    ],
    "pnl_history": [],
}
tmpdir = tempfile.mkdtemp()
synth_file = os.path.join(tmpdir, "state.json")
json.dump(synth_state, open(synth_file, "w"))
orig_state_file = pa.STATE_FILE
orig_scan_file = pa.SCAN_CACHE_FILE
pa.STATE_FILE = synth_file
pa.SCAN_CACHE_FILE = os.path.join(tmpdir, "nope.json")
try:
    d2 = pa.performance_analytics()
    s2 = d2["summary"]
    check("synth.trades", s2["total_trades"] == 2)
    check("synth.win_rate", approx(s2["win_rate_pct"], 50.0))
    check("synth.profit_factor", approx(s2["profit_factor"], 2.0))
    check("synth.avg_winner", approx(s2["avg_winner"], 100.0))
    check("synth.avg_loser", approx(s2["avg_loser"], 50.0))
    check("synth.expectancy", approx(s2["expectancy"], 25.0))
    check("synth.total_return", approx(s2["total_return_pct"], 4.0))
    check("synth.holding_days", d2["historical_trades"][-1]["holding_days"] == 2)
    eq = d2["charts"]["equity_curve"]
    check("synth.equity_start_end", approx(eq[-1]["equity"], 5200.0))
    dd = d2["risk"]["max_drawdown_pct"]
    # Peak 5100 after win, then 5050 after loss => dd = 50/5100 = 0.98%
    check("synth.max_dd", approx(dd, 0.98, 0.05), f"got {dd}")
    check("synth.winloss", d2["charts"]["win_loss"] == {"wins": 1, "losses": 1})
    bw2 = d2["best_worst"]
    check("synth.best", bw2["best"]["symbol"] == "AAA")
    check("synth.worst", bw2["worst"]["symbol"] == "BBB")
finally:
    pa.STATE_FILE = orig_state_file
    pa.SCAN_CACHE_FILE = orig_scan_file

# ── Empty-state resilience ────────────────────────────────────────────────────
empty_file = os.path.join(tmpdir, "empty_state.json")
json.dump({"cash": 5000.0, "positions": {}, "trades": [], "pnl_history": []}, open(empty_file, "w"))
pa.STATE_FILE = empty_file
pa.SCAN_CACHE_FILE = os.path.join(tmpdir, "nope.json")
try:
    d3 = pa.performance_analytics()
    check("empty.success", d3["success"] is True)
    check("empty.trades", d3["summary"]["total_trades"] == 0)
    check("empty.win_rate", d3["summary"]["win_rate_pct"] == 0.0)
    check("empty.no_best", d3["best_worst"]["best"] is None)
    check("empty.strategies_listed", len(d3["strategy_performance"]) >= 8)
    check("empty.risk_ok", d3["risk"]["risk_level"] in ("LOW", "MEDIUM", "HIGH"))
finally:
    pa.STATE_FILE = orig_state_file
    pa.SCAN_CACHE_FILE = orig_scan_file

print("=" * 60)
print(f"Phase 10 tests: {PASS} passed, {FAIL} failed")
if FAILURES:
    for f in FAILURES:
        print("  FAIL:", f)
    raise SystemExit(1)
print("ALL PASS ✅")
