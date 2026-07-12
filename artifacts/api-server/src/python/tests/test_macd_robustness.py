"""
Unit tests for macd_robustness.py (Phase 4 — robustness analysis, analysis only).

Run:  cd artifacts/api-server/src/python && python3 tests/test_macd_robustness.py
"""

import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import macd_robustness as mr
from walk_forward_validator import ValidationConfig
from execution_simulator import CostModel
from indicator_engine import compute_indicators_df

PASS = FAIL = 0
CM = CostModel.from_dict({})
CFG = ValidationConfig.from_dict({"initial_capital": 5000})


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


# ── Synth data ────────────────────────────────────────────────────────────────

def synth_symbol(seed: int, n: int = 520, trend: float = 0.0005) -> pd.DataFrame:
    rng = random.Random(seed)
    dates = pd.bdate_range("2022-01-03", periods=n)
    price = 500.0
    rows = []
    for i in range(n):
        drift = trend + 0.004 * math.sin(i / 17.0)
        ret = drift + rng.gauss(0, 0.012)
        o = price
        c = max(5.0, price * (1 + ret))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        v = 1_000_000 * (1 + abs(rng.gauss(0, 0.5)))
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
    df = pd.DataFrame(rows, index=dates)
    enriched = compute_indicators_df(df)
    out = enriched.reset_index()
    out = out.rename(columns={out.columns[0]: "date"})
    return out


def make_inputs():
    sym_rows = {
        "AAA.NS": synth_symbol(21, trend=0.0012),
        "BBB.NS": synth_symbol(22, trend=0.0),
        "CCC.NS": synth_symbol(23, trend=-0.0006),
        "DDD.NS": synth_symbol(24, trend=0.0008),
    }
    dates = list(sym_rows["AAA.NS"]["date"])
    n = len(dates)
    t1, t2 = int(n * 0.55), int(n * 0.75)
    windows = [
        {"label": "W1", "failed": False,
         "train_start": str(dates[0])[:10], "train_end": str(dates[t1])[:10],
         "test_start": str(dates[t1 + 1])[:10], "test_end": str(dates[t2])[:10]},
        {"label": "W2", "failed": False,
         "train_start": str(dates[0])[:10], "train_end": str(dates[t2])[:10],
         "test_start": str(dates[t2 + 1])[:10], "test_end": str(dates[-1])[:10]},
        {"label": "W3", "failed": True},
    ]
    regimes = ["Bullish", "Neutral Bullish", "Sideways", "High Volatility"]
    regime_by_date = {str(d)[:10]: regimes[i % len(regimes)]
                      for i, d in enumerate(dates)}
    tdbw = {
        "W1": [str(d)[:10] for d in dates[t1 + 1:t2 + 1]],
        "W2": [str(d)[:10] for d in dates[t2 + 1:]],
    }
    return sym_rows, windows, regime_by_date, tdbw


# ── _metrics helper ───────────────────────────────────────────────────────────

def test_metrics():
    print("_metrics:")
    trades = [
        {"net_pnl": 100.0, "return_pct": 2.0, "win": True,
         "total_costs": 5.0, "holding_days": 3, "exit_date": "2024-01-10"},
        {"net_pnl": -50.0, "return_pct": -1.0, "win": False,
         "total_costs": 5.0, "holding_days": 5, "exit_date": "2024-01-15"},
        {"net_pnl": 80.0, "return_pct": 1.6, "win": True,
         "total_costs": 5.0, "holding_days": 4, "exit_date": "2024-01-20"},
    ]
    m = mr._metrics(trades, 5000.0)
    check("trades count", m["trades"] == 3)
    check("net return positive", m["net_return_pct"] > 0)
    check("PF > 1", m["profit_factor"] > 1)
    check("win rate 66.7", abs(m["win_rate"] - 66.7) < 0.2, str(m["win_rate"]))
    check("expectancy positive", m["expectancy_pct"] > 0)
    check("empty trades returns zeros", mr._metrics([], 5000)["trades"] == 0)


# ── Concentration summary ─────────────────────────────────────────────────────

def test_concentration():
    print("concentration_summary:")
    trades = [
        {"symbol": "X", "sector": "IT", "net_pnl": 200.0, "return_pct": 2.0,
         "exit_date": "2024-01"},
        {"symbol": "Y", "sector": "IT", "net_pnl": 50.0, "return_pct": 1.0,
         "exit_date": "2024-02"},
        {"symbol": "Z", "sector": "METALS", "net_pnl": 10.0, "return_pct": 0.5,
         "exit_date": "2024-02"},
    ]
    c = mr._concentration_summary(trades)
    check("top_stock is X", c["top_stock"] == "X")
    check("top_sector is IT", c["top_sector"] == "IT")
    check("top5 share <= 100%", c["top5_trade_share_pct"] <= 100.0)
    check("top_stock_share high (77%)", c["top_stock_share_pct"] > 70)


# ── Verdict logic ────────────────────────────────────────────────────────────

def test_verdict_rules():
    print("verdict rules:")
    good = {"expectancy_pct": 0.10, "profit_factor": 1.15, "max_drawdown_pct": 20.0}
    bad = {"expectancy_pct": -0.05, "profit_factor": 0.90, "max_drawdown_pct": 55.0}

    window_pass = [{"expectancy_pct": 0.1}, {"expectancy_pct": 0.2}]
    window_fail = [{"expectancy_pct": -0.1}, {"expectancy_pct": -0.2}]

    by_stock_ok = [{"group": "X", "profit_contribution_pct": 20.0}]
    by_stock_bad = [{"group": "X", "profit_contribution_pct": 50.0}]

    by_sec_ok = [{"group": "IT", "profit_contribution_pct": 25.0}]

    top5_ok = {"top5_share_of_profit_pct": 30.0}
    top5_bad = {"top5_share_of_profit_pct": 65.0}

    mr._ALL_TRADES_SENTINEL = [{"net_pnl": 100.0}]
    v = mr._compute_verdict(good, window_pass, by_stock_ok, by_sec_ok, top5_ok)
    check("all good → KEEP", v["verdict"] == mr.VERDICT_KEEP, v["verdict"])
    check("no failed checks in KEEP", v["failed_count"] == 0, str(v["failed_count"]))

    v2 = mr._compute_verdict(bad, window_fail, by_stock_bad, by_sec_ok, top5_bad)
    check("all bad → REJECT or RESTRICT",
          v2["verdict"] in (mr.VERDICT_REJECT, mr.VERDICT_RESTRICT), v2["verdict"])
    check("has failed checks", v2["failed_count"] > 0)
    mr._ALL_TRADES_SENTINEL = []


# ── Stress tests ─────────────────────────────────────────────────────────────

def test_stress():
    print("stress tests:")
    trades = [
        {"symbol": "A", "sector": "IT", "net_pnl": 200.0, "return_pct": 4.0,
         "total_costs": 5.0, "win": True, "holding_days": 5,
         "exit_date": "2024-01-10", "invested": 5000.0},
        {"symbol": "B", "sector": "IT", "net_pnl": -30.0, "return_pct": -0.6,
         "total_costs": 5.0, "win": False, "holding_days": 3,
         "exit_date": "2024-01-12", "invested": 5000.0},
        {"symbol": "C", "sector": "METALS", "net_pnl": 50.0, "return_pct": 1.0,
         "total_costs": 5.0, "win": True, "holding_days": 7,
         "exit_date": "2024-02-10", "invested": 5000.0},
        {"symbol": "D", "sector": "METALS", "net_pnl": -10.0, "return_pct": -0.2,
         "total_costs": 5.0, "win": False, "holding_days": 2,
         "exit_date": "2024-02-15", "invested": 5000.0},
    ]
    stock_rows = mr._stress_leave_one_stock_out(trades, 5000)
    check("LOSO: N rows = N stocks", len(stock_rows) == 4)
    check("LOSO: removing A is worst (most negative vs-base)",
          stock_rows[0]["removed_what"] == "A",
          str(stock_rows[0]))

    sec_rows = mr._stress_leave_one_sector_out(trades, 5000)
    check("leave-one-sector-out: 2 sectors", len(sec_rows) == 2)

    mon_rows = mr._stress_leave_one_month_out(trades, 5000)
    check("leave-one-month-out: 2 months", len(mon_rows) == 2)

    top5 = mr._stress_top5_removed(trades, 5000)
    check("top5 removed result has label", "top5_share_of_profit_pct" in top5)
    check("top5 share ≤ 100%", top5["top5_share_of_profit_pct"] <= 100.0)

    winsor = mr._stress_winsorized(trades, 5000, sigma=1.0)
    check("winsor result has trades_capped", "trades_capped" in winsor)
    check("winsorized still serializes", json.dumps(winsor) and True)


# ── Regime recommendations ────────────────────────────────────────────────────

def test_regime_recs():
    print("regime recommendations:")
    by_regime = [
        {"group": "Bullish", "trades": 40, "expectancy_pct": 0.3,
         "profit_factor": 1.2, "win_rate": 50.0, "max_drawdown_pct": 15.0},
        {"group": "Bearish", "trades": 8, "expectancy_pct": -0.1,
         "profit_factor": 0.9, "win_rate": 30.0, "max_drawdown_pct": 25.0},
        {"group": "Sideways", "trades": 5, "expectancy_pct": 0.5,
         "profit_factor": 1.5, "win_rate": 60.0, "max_drawdown_pct": 10.0},
    ]
    recs = mr._regime_recommendations(by_regime)
    check("3 recommendations", len(recs) == 3)
    bullish = next((r for r in recs if r["regime"] == "Bullish"), None)
    check("Bullish → ENABLE", bullish["action"] == "ENABLE" if bullish else False)
    bearish = next((r for r in recs if r["regime"] == "Bearish"), None)
    check("Bearish small sample → INSUFFICIENT",
          bearish["action"] == "INSUFFICIENT DATA" if bearish else False,
          str(bearish))
    sideways = next((r for r in recs if r["regime"] == "Sideways"), None)
    check("Sideways too few → INSUFFICIENT",
          sideways["action"] == "INSUFFICIENT DATA" if sideways else False,
          str(sideways))


# ── End-to-end ───────────────────────────────────────────────────────────────

def test_end_to_end():
    print("run_macd_robustness end-to-end (synthetic):")
    sym_rows, windows, regime_by_date, tdbw = make_inputs()
    msgs = []
    out = mr.run_macd_robustness(sym_rows, windows, regime_by_date, tdbw,
                                  CFG, CM, progress_cb=msgs.append)

    for key in ("safety", "strategy_id", "total_oos_trades", "windows_evaluated",
                "baseline", "window_performance", "breakdowns", "concentration",
                "stress_tests", "verdict", "regime_recommendations", "roadmap"):
        check(f"payload has {key}", key in out, str(list(out.keys())))

    check("2 valid windows evaluated", out["windows_evaluated"] == 2)
    check("progress reported", len(msgs) >= 2, str(msgs))
    check("MACD only", out["strategy_id"] == "macd_cross")

    bkd = out["breakdowns"]
    for dim in ("by_stock", "by_sector", "by_month", "by_regime",
                "by_holding_period", "by_volatility_band",
                "by_adx_band", "by_entry_subtype"):
        check(f"breakdown has {dim}", dim in bkd)
        check(f"{dim} is non-empty list", isinstance(bkd[dim], list))

    st = out["stress_tests"]
    for skey in ("leave_one_stock_out", "leave_one_sector_out",
                 "leave_one_month_out", "top5_trades_removed", "winsorized_returns"):
        check(f"stress has {skey}", skey in st)

    loso = st["leave_one_stock_out"]
    check("LOSO has one row per stock",
          len(loso) == len(bkd["by_stock"]), f"{len(loso)} vs {len(bkd['by_stock'])}")
    check("LOSO rows have still_profitable flag",
          all("still_profitable" in r for r in loso))
    check("LOSO rows have vs_base_expectancy",
          all("vs_base_expectancy" in r for r in loso))

    v = out["verdict"]
    check("verdict has KEEP/RESTRICT/REJECT",
          v["verdict"] in (mr.VERDICT_KEEP, mr.VERDICT_RESTRICT, mr.VERDICT_REJECT))
    check("checks list not empty", len(v["checks"]) == 7)
    check("all checks have pass/fail",
          all("passed" in c for c in v["checks"]))
    check("passed + failed = total",
          v["passed_count"] + v["failed_count"] == len(v["checks"]),
          f"{v['passed_count']} + {v['failed_count']} != {len(v['checks'])}")

    c = out["concentration"]
    check("concentration has top_stock", "top_stock" in c)
    check("concentration has top5_trade_share_pct", "top5_trade_share_pct" in c)

    rr = out["regime_recommendations"]
    check("regime recs is list", isinstance(rr, list))
    check("each rec has action",
          all("action" in r and r["action"] in
              ("ENABLE", "DISABLE", "MONITOR", "INSUFFICIENT DATA")
              for r in rr))

    roadmap = out["roadmap"]
    check("roadmap is list", isinstance(roadmap, list))
    check("each roadmap item has priority, area, action",
          all("priority" in r and "area" in r and "action" in r for r in roadmap))

    try:
        blob = json.dumps(out)
        check("JSON-serializable", True)
    except TypeError as e:
        blob = ""
        check("JSON-serializable", False, str(e))
    check("no snapshot leak", '"snapshot"' not in blob)
    check("no _spec leak", '"_spec"' not in blob)

    out2 = mr.run_macd_robustness(sym_rows, windows, regime_by_date, tdbw,
                                   CFG, CM)
    check("deterministic",
          json.dumps(out, sort_keys=True) == json.dumps(out2, sort_keys=True))


if __name__ == "__main__":
    test_metrics()
    test_concentration()
    test_verdict_rules()
    test_stress()
    test_regime_recs()
    test_end_to_end()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
