"""
Unit tests for strategy_audit.py (Phase 2B — analysis only).

Run:  cd artifacts/api-server/src/python && python3 tests/test_strategy_audit.py
"""

import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import strategy_audit as sa
from execution_simulator import (
    CostModel, INTRABAR_CONSERVATIVE, EXIT_STOP, EXIT_TARGET, EXIT_TIME,
    EXIT_SIGNAL, EXIT_FORCED,
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mk_recs(prices: list[tuple], start="2024-01-01") -> list[dict]:
    """Build candle dicts (open, high, low, close) for walk_exit tests."""
    dates = pd.bdate_range(start, periods=len(prices))
    out = []
    for (o, h, l, c), d in zip(prices, dates):
        out.append({"date": str(d)[:10], "open": o, "high": h, "low": l,
                    "close": c, "volume": 1_000_000, "atr": 2.0})
    return out


def _fill(price=100.0, qty=100):
    return {"fill_price": price, "raw_open": price, "quantity": qty}


ZERO_CM = sa._scaled_cost_model(CostModel.from_dict({}), 0.0)
REAL_CM = CostModel.from_dict({})


def synth_symbol(seed: int, n: int = 520, trend: float = 0.0005) -> pd.DataFrame:
    """Synthetic OHLCV random walk with trend + cycles, then real indicators."""
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


# ── walk_exit mechanics ──────────────────────────────────────────────────────

def test_walk_exit():
    print("walk_exit mechanics:")
    # Stop hit intrabar on day 2
    recs = _mk_recs([(100, 101, 99, 100), (100, 102, 94, 96), (96, 97, 95, 96)])
    ex = sa.walk_exit(ZERO_CM, recs, 0, 2, _fill(), 95.0, 110.0, set(),
                      INTRABAR_CONSERVATIVE, 20)
    check("stop exit", ex["exit_reason"] == EXIT_STOP and ex["raw_exit_price"] == 95.0,
          str(ex))
    # Target hit
    recs = _mk_recs([(100, 101, 99, 100), (100, 112, 100, 111)])
    ex = sa.walk_exit(ZERO_CM, recs, 0, 1, _fill(), 90.0, 110.0, set(),
                      INTRABAR_CONSERVATIVE, 20)
    check("target exit", ex["exit_reason"] == EXIT_TARGET and ex["raw_exit_price"] == 110.0,
          str(ex))
    # Gap-down open below stop on entry day
    recs = _mk_recs([(88, 92, 87, 90)])
    ex = sa.walk_exit(ZERO_CM, recs, 0, 0, _fill(88.0), 95.0, 110.0, set(),
                      INTRABAR_CONSERVATIVE, 20)
    check("gap-open stop", ex["exit_reason"] == EXIT_STOP and ex["raw_exit_price"] == 88.0,
          str(ex))
    # Time exit after max_holding
    flat = _mk_recs([(100, 101, 99.5, 100)] * 6)
    ex = sa.walk_exit(ZERO_CM, flat, 0, 5, _fill(), 90.0, 120.0, set(),
                      INTRABAR_CONSERVATIVE, 3)
    check("time exit at cap", ex["exit_reason"] == EXIT_TIME and ex["holding_days"] == 3,
          str(ex))
    # Signal exit
    sig_day = flat[2]["date"]
    ex = sa.walk_exit(ZERO_CM, flat, 0, 5, _fill(), 90.0, 120.0, {sig_day},
                      INTRABAR_CONSERVATIVE, 20)
    check("signal exit", ex["exit_reason"] == EXIT_SIGNAL and ex["exit_date"] == sig_day,
          str(ex))
    # Forced close at window end
    ex = sa.walk_exit(ZERO_CM, flat, 0, 5, _fill(), 90.0, 120.0, set(),
                      INTRABAR_CONSERVATIVE, 0)
    check("forced close", ex["exit_reason"] == EXIT_FORCED, str(ex))
    # Trailing stop ratchets up and is hit
    up_then_down = _mk_recs([
        (100, 101, 99.5, 100), (101, 106, 100, 106), (106, 112, 105, 112),
        (112, 113, 104, 105), (105, 106, 104, 105)])
    ex = sa.walk_exit(ZERO_CM, up_then_down, 0, 4, _fill(), 96.0, 0.0, set(),
                      INTRABAR_CONSERVATIVE, 20, use_signal=False,
                      trail_atr_mult=2.0, entry_atr=2.0)
    check("trailing stop", ex["exit_reason"] == EXIT_STOP and ex["raw_exit_price"] == 108.0,
          str(ex))
    # Intrabar-flip robustness re-walk must preserve signal exits: with the
    # signal set passed through, optimistic vs conservative differ ONLY in
    # the same-candle rule, not in exit-type availability.
    flat2 = _mk_recs([(100, 101, 99.5, 100)] * 6)
    sig = {flat2[2]["date"]}
    from execution_simulator import INTRABAR_OPTIMISTIC
    ex_c = sa.walk_exit(ZERO_CM, flat2, 0, 5, _fill(), 90.0, 120.0, sig,
                        INTRABAR_CONSERVATIVE, 20)
    ex_o = sa.walk_exit(ZERO_CM, flat2, 0, 5, _fill(), 90.0, 120.0, sig,
                        INTRABAR_OPTIMISTIC, 20)
    check("flip keeps signal exits",
          ex_c["exit_reason"] == EXIT_SIGNAL == ex_o["exit_reason"]
          and ex_c["exit_date"] == ex_o["exit_date"], f"{ex_c} vs {ex_o}")
    # Break-even stop arms after +1×ATR and protects entry
    be = _mk_recs([
        (100, 101, 99.5, 100), (101, 104, 100, 103),   # close ≥ 102 arms BE
        (103, 104, 99, 100.5), (100, 101, 98, 99)])
    ex = sa.walk_exit(ZERO_CM, be, 0, 3, _fill(), 90.0, 200.0, set(),
                      INTRABAR_CONSERVATIVE, 20, breakeven_after_atr=1.0,
                      entry_atr=2.0)
    check("break-even stop", ex["exit_reason"] == EXIT_STOP
          and ex["raw_exit_price"] == 100.0, str(ex))


# ── §2 splits and §5 eligibility ─────────────────────────────────────────────

def _fake_trade(ret, snap_extra=None, regime="Bullish", exit_date="2024-06-01"):
    snap = {"close": 100, "ema9": 101, "ema20": 100, "ema50": 99, "ema200": 95,
            "dist_ema20_pct": 0.5, "dist_ema50_pct": 1.0, "dist_ema200_pct": 5.0,
            "rsi": 55, "adx": 22, "macd_hist": 0.1, "supertrend_dir": "UP",
            "volume_ratio": 1.0, "vwap": 99, "above_vwap": True,
            "atr_pct": 2.0, "atr": 2.0, "atr5": 1.9, "gap_pct": 0.0,
            "regime": regime, "sector": "IT"}
    snap.update(snap_extra or {})
    return {"return_pct": ret, "net_pnl": ret * 1000, "won": ret > 0,
            "win": ret > 0, "exit_date": exit_date, "entry_date": "2024-05-20",
            "holding_days": 5, "market_regime": regime, "sector": "IT",
            "snapshot": snap, "mae_pct": -1, "mfe_pct": 1,
            "exit_reason": EXIT_TARGET if ret > 0 else EXIT_STOP}


def test_condition_diagnostics():
    print("condition_diagnostics:")
    # Small sample → never USEFUL/HARMFUL
    trades = [_fake_trade(1.0, {"adx": 30}) for _ in range(5)] + \
             [_fake_trade(-1.0, {"adx": 10}) for _ in range(5)]
    rows = sa.condition_diagnostics(trades)
    adx_row = next(r for r in rows if "ADX" in r["condition"])
    check("small sample gated", adx_row["verdict"] == "INCONCLUSIVE"
          and not adx_row["reliable"], str(adx_row))
    # Large clean split → USEFUL
    trades = [_fake_trade(1.5, {"adx": 30}) for _ in range(40)] + \
             [_fake_trade(-1.0, {"adx": 10}) for _ in range(40)]
    rows = sa.condition_diagnostics(trades)
    adx_row = next(r for r in rows if "ADX" in r["condition"])
    check("clear split → USEFUL", adx_row["verdict"] == "USEFUL", str(adx_row))


def test_regime_eligibility():
    print("classify_strategy_regime:")
    st, why = sa.classify_strategy_regime([_fake_trade(1.0) for _ in range(3)])
    check("insufficient sample", st == sa.ST_INSUFFICIENT, why)
    st, why = sa.classify_strategy_regime([_fake_trade(1.0) for _ in range(30)])
    check("positive edge → ELIGIBLE", st == sa.ST_ELIGIBLE, why)
    st, why = sa.classify_strategy_regime([_fake_trade(-1.0) for _ in range(30)])
    check("negative edge → DISABLED", st == sa.ST_NEG_EDGE, why)
    st, why = sa.classify_strategy_regime([_fake_trade(0.01) for _ in range(30)])
    check("near-zero → WATCHLIST", st == sa.ST_WATCHLIST, why)


def test_cost_repricing():
    print("cost repricing:")
    t = {"quantity": 100, "raw_open": 100.0, "raw_exit_price": 105.0,
         "exit_date": "2024-06-01", "holding_days": 5}
    zero = sa._reprice_trade(t, ZERO_CM)
    real = sa._reprice_trade(t, REAL_CM)
    hi = sa._reprice_trade(t, sa._scaled_cost_model(REAL_CM, 1.5))
    check("zero-cost return = 5%", abs(zero["return_pct"] - 5.0) < 1e-6, str(zero))
    check("costs reduce return", zero["return_pct"] > real["return_pct"] > hi["return_pct"],
          f"{zero['return_pct']} vs {real['return_pct']} vs {hi['return_pct']}")


# ── End-to-end on synthetic data ─────────────────────────────────────────────

def test_end_to_end():
    print("run_strategy_audit end-to-end (synthetic):")
    sym_rows = {
        "AAA.NS": synth_symbol(1, trend=0.0012),
        "BBB.NS": synth_symbol(2, trend=0.0),
        "CCC.NS": synth_symbol(3, trend=-0.0006),
    }
    dates = list(sym_rows["AAA.NS"]["date"])
    n = len(dates)
    train_end_i = int(n * 0.65)
    windows = [{
        "label": "W1", "failed": False,
        "train_start": str(dates[0])[:10], "train_end": str(dates[train_end_i])[:10],
        "test_start": str(dates[train_end_i + 1])[:10], "test_end": str(dates[-1])[:10],
    }]
    regimes = ["Bullish", "Neutral Bullish", "Sideways", "High Volatility"]
    regime_by_date = {str(d)[:10]: regimes[i % len(regimes)]
                      for i, d in enumerate(dates)}
    test_dates = [str(d)[:10] for d in dates[train_end_i + 1:]]
    cfg = ValidationConfig.from_dict({"initial_capital": 5000})
    cm = CostModel.from_dict({})

    out = sa.run_strategy_audit(
        sym_rows, windows, regime_by_date, {"W1": test_dates}, cfg, cm,
        existing_overall={"A": {"total_return_pct": 1.0}},
        existing_cash={"A": 50.0}, random_seed=7)

    for key in ("scorecards", "entry_conditions", "exit_comparison",
                "loss_attribution", "holding_comparison", "regime_eligibility",
                "cost_sensitivity", "variants", "model_comparison",
                "recommendations", "final_report", "ef_selections", "safety"):
        check(f"payload has {key}", key in out, str(list(out.keys())))

    check("6 scorecards", len(out["scorecards"]) == 6)
    total_trades = sum(sc["metrics"]["total_trades"] for sc in out["scorecards"])
    check("audit produced trades", total_trades > 0, f"total={total_trades}")
    for xc in out["exit_comparison"]:
        check(f"exit alts A–G for {xc['strategy_id']}",
              [a["key"] for a in xc["alternatives"]] == list("ABCDEFG"))
        break
    check("model comparison has 6 rows",
          [r["model"] for r in out["model_comparison"]] == list("ABCDEF"),
          str([r["model"] for r in out["model_comparison"]]))
    recs_ok = all(r["recommendation"] in ("KEEP", "MODIFY", "DISABLE", "INCONCLUSIVE")
                  and r["reason"] for r in out["recommendations"])
    check("recommendations valid", recs_ok, str(out["recommendations"]))

    # Payload must be JSON-serializable and free of internal fields
    try:
        blob = json.dumps(out)
        check("payload JSON-serializable", True)
    except TypeError as e:
        blob = ""
        check("payload JSON-serializable", False, str(e))
    check("no _spec leak", "_spec" not in blob)
    check("no snapshot leak", '"snapshot"' not in blob)

    # Zero-cost expectancy must always beat +50%-cost expectancy
    for cs in out["cost_sensitivity"]:
        s = {r["multiplier"]: r for r in cs["scenarios"]}
        if s[0.0]["expectancy_pct"] is not None and s[1.5]["expectancy_pct"] is not None:
            check(f"cost monotonic ({cs['strategy_id']})",
                  s[0.0]["expectancy_pct"] >= s[1.5]["expectancy_pct"],
                  f"{s[0.0]['expectancy_pct']} vs {s[1.5]['expectancy_pct']}")

    # Every variant is a pure FILTER: test trades never exceed baseline
    for vo in out["variants"]:
        base_n = vo["baseline"]["trades"]
        for v in vo["variants"]:
            check(f"variant subset ({vo['strategy_id']}/{v['name']})",
                  v["test"]["trades"] <= base_n,
                  f"{v['test']['trades']} > {base_n}")

    q = out["final_report"]
    for k in ("q1_net_positive_edge", "q6_costs_main_cause", "q9_safe_to_deploy",
              "summary"):
        check(f"final report has {k}", bool(q.get(k)))


if __name__ == "__main__":
    test_walk_exit()
    test_condition_diagnostics()
    test_regime_eligibility()
    test_cost_repricing()
    test_end_to_end()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
