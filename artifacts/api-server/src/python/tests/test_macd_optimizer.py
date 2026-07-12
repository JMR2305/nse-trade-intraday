"""
Unit tests for macd_optimizer.py (Phase 3 — MACD optimization, analysis only).

Run:  cd artifacts/api-server/src/python && python3 tests/test_macd_optimizer.py
"""

import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import macd_optimizer as mo
from execution_simulator import (
    CostModel, side_costs, EXIT_STOP, EXIT_TARGET, EXIT_TIME, EXIT_SIGNAL,
    EXIT_FORCED,
)
from indicator_engine import compute_indicators_df
from walk_forward_validator import ValidationConfig

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


CM = CostModel.from_dict({})
CFG = ValidationConfig.from_dict({"initial_capital": 5000})


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mk_recs(prices: list[tuple], start="2024-01-01") -> list[dict]:
    dates = pd.bdate_range(start, periods=len(prices))
    out = []
    for (o, h, l, c), d in zip(prices, dates):
        out.append({"date": str(d)[:10], "open": o, "high": h, "low": l,
                    "close": c, "volume": 1_000_000, "atr": 2.0})
    return out


def _mk_trade(recs: list[dict], sym="XX.NS", entry_pos=1, stop=96.0,
              target=110.0, atr=2.0, sig=None) -> dict:
    """A minimal baseline trade record shape as produced by
    audit_window_pass — only the fields rewalk_exit actually uses."""
    qty = 10
    price = recs[entry_pos]["open"]
    return {
        "entry_date": recs[entry_pos]["date"], "entry_price": price,
        "raw_open": price, "quantity": qty, "gap_pct": 0.0,
        "buy_costs": side_costs(CM, price * qty, "buy"),
        "market_regime": "Bullish", "sector": "IT",
        "snapshot": {"close": 100.0},
        "_spec": {"sym": sym, "entry_pos": entry_pos, "end": len(recs) - 1,
                  "stop": stop, "target": target, "entry_atr": atr,
                  "sig": sig or set()},
    }


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


# ── rewalk_exit ──────────────────────────────────────────────────────────────

def test_rewalk_exit():
    print("rewalk_exit:")
    # Flat drift down then flat: tight stop should trigger, loose should not.
    prices = [(100, 101, 99, 100)] + \
             [(100 - i, 101 - i, 98.4 - i, 99.5 - i) for i in range(12)]
    recs = _mk_recs(prices)
    sym_recs = {"XX.NS": recs}
    t = _mk_trade(recs, stop=50.0, target=500.0)   # neither would ever hit

    tight = mo.rewalk_exit(t, sym_recs, CM, CFG, "atr_stop", 0.5)   # 100-1=99
    loose = mo.rewalk_exit(t, sym_recs, CM, CFG, "atr_stop", 3.0)   # 100-6=94
    check("tight ATR stop exits at stop", tight["exit_reason"] == EXIT_STOP,
          tight["exit_reason"])
    check("tight stop exits earlier",
          tight["holding_days"] <= loose["holding_days"],
          f"{tight['holding_days']} vs {loose['holding_days']}")

    timed = mo.rewalk_exit(t, sym_recs, CM, CFG, "time", 2)
    check("time exit caps holding at 2 days", timed["holding_days"] <= 2
          and timed["exit_reason"] in (EXIT_TIME, EXIT_FORCED),
          f"{timed['holding_days']} {timed['exit_reason']}")

    # Rising series: dynamic RR target = close + m*(close-stop)
    up = [(100, 101, 99, 100)] + \
         [(100 + i, 102 + i, 99 + i, 101 + i) for i in range(15)]
    recs_u = _mk_recs(up)
    sr_u = {"XX.NS": recs_u}
    tu = _mk_trade(recs_u, stop=98.0, target=999.0)
    rr = mo.rewalk_exit(tu, sr_u, CM, CFG, "rr", 2.0)   # target 100+2*2=104
    check("dynamic RR hits computed target", rr["exit_reason"] == EXIT_TARGET
          and abs(rr["raw_exit_price"] - 104.0) < 1e-6,
          f"{rr['exit_reason']} @ {rr['raw_exit_price']}")

    trail = mo.rewalk_exit(tu, sr_u, CM, CFG, "trailing", 1.5)
    check("trailing never exits at fixed target",
          trail["exit_reason"] != EXIT_TARGET, trail["exit_reason"])

    part = mo.rewalk_exit(tu, sr_u, CM, CFG, "partial", 1.0)
    check("partial booking returns a full trade record",
          "return_pct" in part and "total_costs" in part, str(part.keys()))

    # Entry identity preserved
    check("entry unchanged by re-walk",
          tight["entry_price"] == t["entry_price"]
          and tight["quantity"] == t["quantity"]
          and tight["entry_date"] == t["entry_date"])


# ── Verdicts ─────────────────────────────────────────────────────────────────

def test_verdicts():
    print("verdicts:")
    base = {"trades": 100, "expectancy_pct": 0.10, "profit_factor": 1.2,
            "net_return_pct": 10.0, "sharpe_ratio": 0.5,
            "max_drawdown_pct": 10.0}

    v, r = mo._trade_level_verdict({"trades": 5, "expectancy_pct": 1.0,
                                    "profit_factor": 2.0}, base)
    check("tiny sample → INSUFFICIENT", v == mo.VERDICT_INSUFFICIENT, v)

    v, _ = mo._trade_level_verdict({"trades": 50, "expectancy_pct": 0.12,
                                    "profit_factor": 1.2}, base)
    check("below margin → REJECTED", v == mo.VERDICT_REJECTED, v)

    v, _ = mo._trade_level_verdict({"trades": 50, "expectancy_pct": 0.30,
                                    "profit_factor": 0.9}, base)
    check("worse PF → REJECTED", v == mo.VERDICT_REJECTED, v)

    v, _ = mo._trade_level_verdict({"trades": 50, "expectancy_pct": 0.30,
                                    "profit_factor": 1.3}, base)
    check("clear improvement → ACCEPTED", v == mo.VERDICT_ACCEPTED, v)

    v, _ = mo._trade_level_verdict({"trades": 50, "expectancy_pct": -0.30,
                                    "profit_factor": 1.3}, base)
    check("negative expectancy → REJECTED", v == mo.VERDICT_REJECTED, v)

    v, _ = mo._portfolio_verdict({"trades": 50, "sharpe_ratio": 0.8,
                                  "max_drawdown_pct": 9.0,
                                  "net_return_pct": 11.0}, base)
    check("better Sharpe → ACCEPTED", v == mo.VERDICT_ACCEPTED, v)

    v, _ = mo._portfolio_verdict({"trades": 50, "sharpe_ratio": 0.5,
                                  "max_drawdown_pct": 6.0,
                                  "net_return_pct": 9.8}, base)
    check("much lower drawdown, similar return → ACCEPTED",
          v == mo.VERDICT_ACCEPTED, v)

    v, _ = mo._portfolio_verdict({"trades": 50, "sharpe_ratio": 0.4,
                                  "max_drawdown_pct": 12.0,
                                  "net_return_pct": 8.0}, base)
    check("no improvement → REJECTED", v == mo.VERDICT_REJECTED, v)


# ── Entry filter definitions ─────────────────────────────────────────────────

def test_entry_filters():
    print("entry filter predicates:")
    snap = {"adx": 22.0, "atr_pct": 3.0, "volume_ratio": 1.3,
            "macd_hist": 0.08, "close": 100.0, "ema50": 105.0,
            "ema200": 95.0, "regime": "Bullish"}
    by_id = {f["id"]: f for f in mo.ENTRY_FILTER_DEFS}
    check("adx 22 passes ≥20 fails ≥25",
          by_id["adx_strength"]["pred"](snap, 20.0)
          and not by_id["adx_strength"]["pred"](snap, 25.0))
    check("atr 3% passes cap 3.5 fails cap 2.5",
          by_id["atr_volatility_cap"]["pred"](snap, 3.5)
          and not by_id["atr_volatility_cap"]["pred"](snap, 2.5))
    check("volume 1.3 passes 1.2 fails 1.5",
          by_id["volume_confirmation"]["pred"](snap, 1.2)
          and not by_id["volume_confirmation"]["pred"](snap, 1.5))
    check("hist 0.08 (=0.08% of 100) passes 0.05 fails 0.10",
          by_id["crossover_quality"]["pred"](snap, 0.05)
          and not by_id["crossover_quality"]["pred"](snap, 0.10))
    check("trend alignment: above EMA200 with EMA50>EMA200",
          by_id["trend_alignment"]["pred"](snap, 1.0))
    snap2 = dict(snap, close=90.0)
    check("trend alignment fails below EMA200",
          not by_id["trend_alignment"]["pred"](snap2, 1.0))


# ── End-to-end on synthetic data ─────────────────────────────────────────────

def test_end_to_end():
    print("run_macd_optimization end-to-end (synthetic):")
    sym_rows = {
        "AAA.NS": synth_symbol(11, trend=0.0012),
        "BBB.NS": synth_symbol(12, trend=0.0),
        "CCC.NS": synth_symbol(13, trend=-0.0006),
        "DDD.NS": synth_symbol(14, trend=0.0008),
    }
    dates = list(sym_rows["AAA.NS"]["date"])
    n = len(dates)
    t1 = int(n * 0.55)
    t2 = int(n * 0.75)
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
    msgs = []
    out = mo.run_macd_optimization(sym_rows, windows, regime_by_date, tdbw,
                                   CFG, CM, progress_cb=msgs.append)

    for key in ("strategy_id", "safety", "methodology", "windows_evaluated",
                "baseline", "comparison_table", "combined",
                "recommended_config", "report"):
        check(f"payload has {key}", key in out, str(list(out.keys())))
    check("MACD only", out["strategy_id"] == "macd_cross")
    check("2 valid windows evaluated", out["windows_evaluated"] == 2,
          str(out["windows_evaluated"]))
    check("progress reported", len(msgs) >= 3, str(msgs))

    table = out["comparison_table"]
    n_filters = len(mo.ENTRY_FILTER_DEFS) + 1          # + regime gate
    n_exits = len(mo.EXIT_TEST_DEFS)
    n_risk = len(mo.RISK_VARIANT_DEFS)
    check(f"comparison table has {n_filters + n_exits + n_risk} rows",
          len(table) == n_filters + n_exits + n_risk, str(len(table)))

    cats = {r["category"] for r in table}
    check("all 3 categories present",
          cats == {"entry_filter", "exit", "risk_management"}, str(cats))
    check("every row has a verdict + reason",
          all(r["verdict"] in (mo.VERDICT_ACCEPTED, mo.VERDICT_REJECTED,
                               mo.VERDICT_INSUFFICIENT) and r["reason"]
              for r in table))
    for col in ("net_return_pct", "profit_factor", "win_rate", "sharpe_ratio",
                "max_drawdown_pct", "expectancy_pct", "trades", "total_costs"):
        check(f"every row has {col}", all(col in r for r in table))

    base_n = out["baseline"]["trade_level"]["trades"]
    check("baseline produced trades", base_n > 0, str(base_n))
    for r in table:
        if r["category"] == "entry_filter":
            check(f"filter {r['id']} never ADDS entries",
                  r["trades"] <= base_n, f"{r['trades']} > {base_n}")
        if r["category"] == "exit":
            check(f"exit {r['id']} keeps identical entries",
                  r["trades"] == base_n, f"{r['trades']} != {base_n}")

    # Train-only selection: every selected param comes from the candidates
    fd_by_id = {f["id"]: f for f in mo.ENTRY_FILTER_DEFS}
    xd_by_id = {x["id"]: x for x in mo.EXIT_TEST_DEFS}
    for r in table:
        pool = fd_by_id.get(r["id"]) or xd_by_id.get(r["id"])
        if pool is None:
            continue
        for pw in r["params_by_window"]:
            check(f"{r['id']} param {pw['param']} from candidate set",
                  pw["param"] is None or pw["param"] in pool["candidates"],
                  str(pw))

    rc = out["recommended_config"]
    check("recommendation has explicit adopt flag", isinstance(rc["adopted"], bool))
    check("recommendation statement matches flag",
          ("RECOMMENDED for continued paper validation" in rc["status"])
          == rc["adopted"], rc["status"])
    if not rc["adopted"]:
        check("non-adoption keeps baseline",
              "baseline" in rc["status"].lower(), rc["status"])
    accepted_ids = {a["id"] for a in out["report"]["accepted"]}
    check("recommended filters are all accepted",
          all(f["id"] in accepted_ids for f in rc["entry_filters"]))
    rules = [f.get("rule", "") for f in rc["entry_filters"]] + \
            ([rc["exit"].get("rule", "")] if rc.get("exit") else [])
    check("no unformatted {p} placeholders in recommended rules",
          all("{p" not in s for s in rules), str(rules))
    check("combined carries selection-bias caveat",
          out["combined"].get("validation_caveat") == mo.COMBINED_CAVEAT
          and rc.get("validation_caveat") == mo.COMBINED_CAVEAT)
    if rc["adopted"]:
        check("adoption is only ever provisional/exploratory",
              "PROVISIONALLY" in rc["status"], rc["status"])

    # JSON-safety: no internal fields may leak
    try:
        blob = json.dumps(out)
        check("payload JSON-serializable", True)
    except TypeError as e:
        blob = ""
        check("payload JSON-serializable", False, str(e))
    check("no _spec leak", "_spec" not in blob)
    check("no snapshot leak", '"snapshot"' not in blob)

    # Determinism
    out2 = mo.run_macd_optimization(sym_rows, windows, regime_by_date, tdbw,
                                    CFG, CM)
    check("deterministic", json.dumps(out, sort_keys=True)
          == json.dumps(out2, sort_keys=True))

    # Portfolio risk hooks actually bind
    span = {}
    for sym, rows in sym_rows.items():
        idx = [i for i, d in enumerate(rows["date"])
               if str(dates[t1 + 1])[:10] <= str(d)[:10] <= str(dates[t2])[:10]]
        if len(idx) >= 5:
            span[sym] = (idx[0], idx[-1])
    sym_recs = {sym: rows.to_dict("records") for sym, rows in sym_rows.items()}
    base_risk = dict(mo.BASE_RISK)
    r_base = mo.simulate_macd_portfolio(sym_recs, span, tdbw["W1"],
                                        regime_by_date, CM, CFG, base_risk)
    tight = dict(mo.BASE_RISK, max_exposure_pct=20.0, sector_cap=1)
    r_tight = mo.simulate_macd_portfolio(sym_recs, span, tdbw["W1"],
                                         regime_by_date, CM, CFG, tight)
    check("risk limits block or match entries",
          len(r_tight["trades"]) <= len(r_base["trades"])
          or r_tight["blocked_by_risk"] > 0,
          f"{len(r_tight['trades'])} vs {len(r_base['trades'])}")
    check("equity curve covers every test day",
          len(r_base["equity_curve"]) == len(tdbw["W1"]))


if __name__ == "__main__":
    test_rewalk_exit()
    test_verdicts()
    test_entry_filters()
    test_end_to_end()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
