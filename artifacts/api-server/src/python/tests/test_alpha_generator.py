"""Tests for alpha_generator.py — Phase 5 Alpha Generation Engine."""
from __future__ import annotations
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alpha_generator as ag

# ── Tiny helpers ──────────────────────────────────────────────────────────────
_passed = 0
_failed = 0

def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {label}")
    else:
        _failed += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


# ── Synthetic trade factories ─────────────────────────────────────────────────

def _make_trade(
    sym="RELIANCE", sector="ENERGY", regime="Neutral Bullish",
    net_pnl=200.0, return_pct=4.0, holding_days=5,
    entry_date="2024-01-15", exit_date="2024-01-20",
    invested=5000.0,
    snap_overrides=None, window="W1",
):
    snap = {
        "close": 2400.0, "adx": 28.0, "atr_pct": 1.2,
        "volume_ratio": 2.0, "above_vwap": True,
        "rsi": 55.0, "macd_hist": 12.0,
    }
    if snap_overrides:
        snap.update(snap_overrides)
    return {
        "symbol": sym, "sector": sector, "market_regime": regime,
        "net_pnl": net_pnl, "return_pct": return_pct,
        "holding_days": holding_days,
        "entry_date": entry_date, "exit_date": exit_date,
        "invested": invested, "total_costs": 50.0,
        "snapshot": snap, "window": window,
        "strategy_id": "macd_cross",
    }


def _mixed_trades(n=60, base_win=True, window="W1"):
    """n trades, alternating win/loss, returns list."""
    trades = []
    for i in range(n):
        win = (i % 3 != 0)  # 2/3 winners
        trades.append(_make_trade(
            sym=f"SYM{i % 10}",
            sector=["CONSUMER", "INFRA", "IT", "BANKING"][i % 4],
            regime=["Bearish", "Neutral Bullish", "Neutral Bearish"][i % 3],
            net_pnl=300.0 if win else -150.0,
            return_pct=6.0 if win else -3.0,
            holding_days=(i % 10) + 1,
            entry_date=f"2024-{1 + i // 30:02d}-{(i % 28) + 1:02d}",
            exit_date=f"2024-{1 + i // 30:02d}-{min((i % 28) + 3, 28):02d}",
            snap_overrides={
                "adx": 20.0 + (i % 20),
                "atr_pct": 0.8 + (i % 4) * 0.6,
                "volume_ratio": 0.8 + (i % 4) * 0.5,
                "above_vwap": (i % 2 == 0),
            },
            window=window,
        ))
    return trades


# ── Fake window results ───────────────────────────────────────────────────────

_WINDOWS = [
    {
        "label": "W1", "window": 1, "failed": False,
        "train_start": "2023-01-01", "train_end": "2023-12-31",
        "test_start": "2024-01-01", "test_end": "2024-03-31",
    },
    {
        "label": "W2", "window": 2, "failed": False,
        "train_start": "2023-04-01", "train_end": "2024-03-31",
        "test_start": "2024-04-01", "test_end": "2024-06-30",
    },
]

_FAILED_WIN = {
    "label": "W_FAIL", "window": 3, "failed": True,
    "train_start": "2023-01-01", "train_end": "2023-12-31",
    "test_start": "2024-07-01", "test_end": "2024-09-30",
}


# ── Tests: _snap ──────────────────────────────────────────────────────────────
print("_snap:")
t = _make_trade()
check("snap returns adx", ag._snap(t, "adx") == 28.0)
check("snap missing key → default", ag._snap(t, "nonexistent", -1) == -1)
check("snap no snapshot → default", ag._snap({}, "adx", 99) == 99)
check("snap above_vwap True", ag._snap(t, "above_vwap", False) is True)


# ── Tests: _rs_outperforms_nifty ──────────────────────────────────────────────
print("_rs_outperforms_nifty:")
import pandas as pd
import numpy as np

def _fake_prices(n=80, start=100.0, drift=0.001):
    dates = pd.date_range("2023-10-01", periods=n, freq="B")
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + drift + np.random.normal(0, 0.01)))
    return pd.DataFrame({"Close": prices}, index=dates)

# Symbol outperforms NIFTY
sym_rows_rs = {"STRONG": _fake_prices(80, 100, 0.003)}
nifty_rs = _fake_prices(80, 100, 0.001)
check("rs: strong stock passes filter",
      ag._rs_outperforms_nifty(sym_rows_rs, nifty_rs, "STRONG", "2023-12-20"))

# Symbol underperforms NIFTY
sym_rows_weak = {"WEAK": _fake_prices(80, 100, -0.002)}
check("rs: weak stock fails filter",
      not ag._rs_outperforms_nifty(sym_rows_weak, nifty_rs, "WEAK", "2023-12-20"))

# Missing symbol → permissive
check("rs: missing symbol → True",
      ag._rs_outperforms_nifty({}, nifty_rs, "MISSING", "2024-01-01"))

# None nifty_df → permissive
check("rs: None nifty → True",
      ag._rs_outperforms_nifty(sym_rows_rs, None, "STRONG", "2024-01-01"))

# Insufficient history → permissive
short_nifty = _fake_prices(5, 100, 0.001)
check("rs: short nifty history → True",
      ag._rs_outperforms_nifty(sym_rows_rs, short_nifty, "STRONG", "2023-12-20"))


# ── Tests: _build_candidates ─────────────────────────────────────────────────
print("_build_candidates:")
candidates = ag._build_candidates({}, None)
check("10 candidates defined", len(candidates) == 10)
ids = [c["id"] for c in candidates]
for cid in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"]:
    check(f"  candidate {cid} exists", cid in ids)

# Verify filter functions work
t_vol = _make_trade(snap_overrides={"volume_ratio": 2.5})
t_no_vol = _make_trade(snap_overrides={"volume_ratio": 0.8})
c1 = next(c for c in candidates if c["id"] == "C1")
check("C1 volume filter: passes ≥1.5", c1["filter_fn"](t_vol))
check("C1 volume filter: fails <1.5", not c1["filter_fn"](t_no_vol))

t_adx_high = _make_trade(snap_overrides={"adx": 30.0})
t_adx_low = _make_trade(snap_overrides={"adx": 15.0})
c2 = next(c for c in candidates if c["id"] == "C2")
check("C2 ADX filter: passes ≥25", c2["filter_fn"](t_adx_high))
check("C2 ADX filter: fails <25", not c2["filter_fn"](t_adx_low))

t_low_atr = _make_trade(snap_overrides={"atr_pct": 1.0})
t_high_atr = _make_trade(snap_overrides={"atr_pct": 2.5})
c3 = next(c for c in candidates if c["id"] == "C3")
check("C3 ATR filter: passes <1.5", c3["filter_fn"](t_low_atr))
check("C3 ATR filter: fails ≥1.5", not c3["filter_fn"](t_high_atr))

t_bearish = _make_trade(regime="Bearish")
t_bullish = _make_trade(regime="Bullish")
c4 = next(c for c in candidates if c["id"] == "C4")
check("C4 regime filter: passes Bearish", c4["filter_fn"](t_bearish))
check("C4 regime filter: fails Bullish", not c4["filter_fn"](t_bullish))

t_above_vwap = _make_trade(snap_overrides={"above_vwap": True})
t_below_vwap = _make_trade(snap_overrides={"above_vwap": False})
c5 = next(c for c in candidates if c["id"] == "C5")
check("C5 VWAP filter: passes above", c5["filter_fn"](t_above_vwap))
check("C5 VWAP filter: fails below", not c5["filter_fn"](t_below_vwap))

t_consumer = _make_trade(sector="CONSUMER")
t_it = _make_trade(sector="IT")
c7 = next(c for c in candidates if c["id"] == "C7")
check("C7 sector filter: passes CONSUMER", c7["filter_fn"](t_consumer))
check("C7 sector filter: passes INFRA", c7["filter_fn"](_make_trade(sector="INFRA")))
check("C7 sector filter: fails IT", not c7["filter_fn"](t_it))

t_short = _make_trade(holding_days=3)
t_long = _make_trade(holding_days=10)
c8 = next(c for c in candidates if c["id"] == "C8")
check("C8 duration filter: passes ≤5", c8["filter_fn"](t_short))
check("C8 duration filter: fails >5", not c8["filter_fn"](t_long))

# C9: volume + ADX
t_both = _make_trade(snap_overrides={"volume_ratio": 2.0, "adx": 28.0})
t_vol_only = _make_trade(snap_overrides={"volume_ratio": 2.0, "adx": 15.0})
c9 = next(c for c in candidates if c["id"] == "C9")
check("C9 vol+trend: passes both", c9["filter_fn"](t_both))
check("C9 vol+trend: fails vol-only", not c9["filter_fn"](t_vol_only))

# C10: volume + ADX + VWAP
t_triple = _make_trade(snap_overrides={"volume_ratio": 2.0, "adx": 28.0, "above_vwap": True})
t_no_vwap = _make_trade(snap_overrides={"volume_ratio": 2.0, "adx": 28.0, "above_vwap": False})
c10 = next(c for c in candidates if c["id"] == "C10")
check("C10 triple filter: passes all three", c10["filter_fn"](t_triple))
check("C10 triple filter: fails missing VWAP", not c10["filter_fn"](t_no_vwap))


# ── Tests: _window_consistency ────────────────────────────────────────────────
print("_window_consistency:")
trades_w1 = _mixed_trades(30, window="W1")
trades_w2 = _mixed_trades(20, window="W2")
all_trades = trades_w1 + trades_w2
cons = ag._window_consistency(all_trades, _WINDOWS, 5000.0)
check("consistency has per_window", "per_window" in cons)
check("consistency has 2 windows", len(cons["per_window"]) == 2)
check("positive_windows is integer", isinstance(cons["positive_windows"], int))
check("pct_positive 0-100", 0 <= cons["pct_positive"] <= 100)
check("failed windows excluded",
      ag._window_consistency([], [_FAILED_WIN], 5000.0)["total_windows"] == 0)


# ── Tests: _regime_breakdown ──────────────────────────────────────────────────
print("_regime_breakdown:")
bd = ag._regime_breakdown(trades_w1, 5000.0)
check("regime_breakdown is list", isinstance(bd, list))
check("each row has regime key", all("regime" in r for r in bd))
check("each row has trades", all("trades" in r for r in bd))
check("each row has expectancy_pct", all("expectancy_pct" in r for r in bd))


# ── Tests: _concentration ────────────────────────────────────────────────────
print("_concentration:")
conc_all = ag._concentration(all_trades)
check("top_stock present", "top_stock" in conc_all)
check("top_sector present", "top_sector" in conc_all)
check("top5_trade_share_pct 0-100", 0 <= conc_all["top5_trade_share_pct"] <= 100)
check("top_stock_share_pct 0-100", 0 <= conc_all["top_stock_share_pct"] <= 100)
check("empty trades → zeroes", ag._concentration([])["top5_trade_share_pct"] == 0.0)


# ── Tests: _candidate_verdict ─────────────────────────────────────────────────
print("_candidate_verdict:")

def _cons(pos_wins=1, tot=2):
    return {"positive_windows": pos_wins, "total_windows": tot,
            "pct_positive": round(pos_wins / max(tot, 1) * 100, 1)}

# KEEP: all gates pass
m_good = {"trades": 50, "expectancy_pct": 0.5, "profit_factor": 1.3,
          "max_drawdown_pct": 30.0, "win_rate": 55.0}
c_good = {"top5_trade_share_pct": 40.0}
v_keep = ag._candidate_verdict(m_good, _cons(2, 2), c_good)
check("all-good → KEEP", v_keep["verdict"] == ag.VERDICT_KEEP)
check("all-good → no failed checks", v_keep["failed_count"] == 0)

# REJECT: too few trades
m_tiny = {**m_good, "trades": 5}
v_tiny = ag._candidate_verdict(m_tiny, _cons(), c_good)
check("tiny sample → REJECT", v_tiny["verdict"] == ag.VERDICT_REJECT)

# REJECT: negative expectancy
m_neg = {**m_good, "expectancy_pct": -0.1}
v_neg = ag._candidate_verdict(m_neg, _cons(), c_good)
check("negative exp → REJECT", v_neg["verdict"] == ag.VERDICT_REJECT)

# REJECT: PF < 1.0
m_bad_pf = {**m_good, "profit_factor": 0.85}
v_bad_pf = ag._candidate_verdict(m_bad_pf, _cons(), c_good)
check("PF < 1.0 → REJECT", v_bad_pf["verdict"] == ag.VERDICT_REJECT)

# INCONCLUSIVE: some gates fail
m_mid = {**m_good, "profit_factor": 1.05}
v_mid = ag._candidate_verdict(m_mid, _cons(), c_good)
check("low PF → INCONCLUSIVE", v_mid["verdict"] == ag.VERDICT_INCONCLUSIVE)
check("INCONCLUSIVE has failed list", len(v_mid["failed"]) > 0)

# Checks structure
check("verdict has checks list", isinstance(v_keep["checks"], list))
check("each check has passed field", all("passed" in c for c in v_keep["checks"]))
check("each check has check field", all("check" in c for c in v_keep["checks"]))
check("passed + failed = total checks",
      v_keep["passed_count"] + v_keep["failed_count"] == len(v_keep["checks"]))


# ── Tests: _sector_breakdown ──────────────────────────────────────────────────
print("_sector_breakdown:")
sb = ag._sector_breakdown(all_trades, 5000.0)
check("sector_breakdown is list", isinstance(sb, list))
check("each row has sector key", all("sector" in r for r in sb))
check("sorted by expectancy desc",
      all(sb[i]["expectancy_pct"] >= sb[i+1]["expectancy_pct"] for i in range(len(sb)-1)))


# ── Tests: run_alpha_generation (synthetic, no I/O) ──────────────────────────
print("run_alpha_generation (synthetic):")

class _FakeCfg:
    initial_capital = 5000.0
    max_holding_days = 20
    intrabar_rule = "conservative"
    random_seed = 42

class _FakeCost:
    pass

# Build minimal sym_rows for _span_idx
# We'll mock audit_window_pass to avoid real data fetch
import unittest.mock as mock

def _fake_audit_window_pass(strat, sym_recs, test_span, regime_by_date,
                             cost_model, cfg, label, collect_alternatives=False):
    """Return synthetic MACD trades tagged with the window label."""
    trades = _mixed_trades(40, window=label)
    return {"baseline": trades, "alternatives": {}}

fake_sym_rows = {
    "TRENT": pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=400, freq="B"),
        "Close": [2000 + i for i in range(400)],
        "Open": [1990 + i for i in range(400)],
        "High": [2020 + i for i in range(400)],
        "Low":  [1980 + i for i in range(400)],
        "Volume": [100000] * 400,
    }),
}

with mock.patch("alpha_generator.audit_window_pass", side_effect=_fake_audit_window_pass):
    result = ag.run_alpha_generation(
        sym_rows=fake_sym_rows,
        window_results=_WINDOWS,
        regime_by_date={},
        test_dates_by_window={},
        cfg=_FakeCfg(),
        cost_model=_FakeCost(),
        nifty_df=None,
        progress_cb=lambda msg: None,
    )

check("result has safety", "safety" in result)
check("result has total_oos_trades", "total_oos_trades" in result)
check("result has windows_evaluated", "windows_evaluated" in result)
check("result has baseline", "baseline" in result)
check("result has candidates", "candidates" in result)
check("result has comparison_table", "comparison_table" in result)
check("result has recommendation_summary", "recommendation_summary" in result)
check("10 candidates", len(result["candidates"]) == 10)
check("windows_evaluated = 2", result["windows_evaluated"] == 2)

# Validate each candidate
for cand in result["candidates"]:
    check(f"  {cand['id']} has verdict",
          cand["verdict"] in (ag.VERDICT_KEEP, ag.VERDICT_INCONCLUSIVE, ag.VERDICT_REJECT))
    check(f"  {cand['id']} has metrics", "metrics" in cand)
    check(f"  {cand['id']} has window_consistency", "window_consistency" in cand)
    check(f"  {cand['id']} has regime_breakdown", "regime_breakdown" in cand)
    check(f"  {cand['id']} has concentration", "concentration" in cand)
    check(f"  {cand['id']} has filters", len(cand["filters"]) >= 1)

# Comparison table
tbl = result["comparison_table"]
check("comparison_table has 11 rows (baseline + 10)", len(tbl) == 11)
check("first row is baseline", tbl[0]["is_baseline"])
check("all rows have expectancy_pct", all("expectancy_pct" in r for r in tbl))

# Recommendation summary
recs = result["recommendation_summary"]
check("recommendation_summary has 10 entries", len(recs) == 10)
check("each rec has status", all("status" in r for r in recs))
check("each rec has reason", all("reason" in r for r in recs))
statuses = {r["status"] for r in recs}
check("statuses are valid verdicts",
      statuses.issubset({ag.VERDICT_KEEP, ag.VERDICT_INCONCLUSIVE, ag.VERDICT_REJECT}))

# Serializable
try:
    json.dumps(result)
    check("JSON-serializable", True)
except Exception as e:
    check("JSON-serializable", False, str(e))

# No-trade empty case
with mock.patch("alpha_generator.audit_window_pass",
                return_value={"baseline": [], "alternatives": {}}):
    empty = ag.run_alpha_generation(
        fake_sym_rows, _WINDOWS, {}, {}, _FakeCfg(), _FakeCost(), None, None
    )
check("empty result has safety", "safety" in empty)
check("empty result has error key", "error" in empty)

# Progress callbacks called
log = []
with mock.patch("alpha_generator.audit_window_pass", side_effect=_fake_audit_window_pass):
    ag.run_alpha_generation(
        fake_sym_rows, _WINDOWS, {}, {}, _FakeCfg(), _FakeCost(), None,
        progress_cb=log.append,
    )
check("progress callbacks fired", len(log) >= 5)
check("phase 5 in first log", any("Phase 5" in m for m in log))

# Deterministic
with mock.patch("alpha_generator.audit_window_pass", side_effect=_fake_audit_window_pass):
    r2 = ag.run_alpha_generation(
        fake_sym_rows, _WINDOWS, {}, {}, _FakeCfg(), _FakeCost(), None, None)
check("deterministic results",
      result["total_oos_trades"] == r2["total_oos_trades"])

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    sys.exit(1)
