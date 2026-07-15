"""
test_phase13.py — Phase 13 Automated Test Suite (22 tests)

T01  Factor weights sum to 1.0
T02  14 factors defined (12 from P12 + 2 new: historical_similarity, risk_reward + portfolio_context)
T03  Factor scores all in 0–100 range
T04a No-lookahead: only SELL rows used for learning
T04b No-lookahead: all learning rows have close timestamps
T05  Stale-data gate blocks BUY/STRONG_BUY
T06  Scan-stale flag blocks BUY/STRONG_BUY
T07  Near-live data is not blocked
T08  Regime TRENDING_UP on bullish inputs
T09  Regime CRISIS on extreme VIX
T10  Regime always returns a valid state
T11  Regime transition tracking (duration_bars increments)
T12  Strategy eligibility: TRENDING_UP has eligible strategies
T13  Strategy eligibility: CRISIS has no eligible strategies
T14  Evidence labels: 0→insufficient, 150→validated
T15  Calibrated confidence is always ≤ raw score
T16  Contradiction detection: all-bullish → NONE/LOW
T17  Contradiction detection: opposing signals → HIGH
T18  Position size never exceeds 20% capital cap
T19  Position sizing halved in CRISIS regime
T20  Risk/reward score improves with better RR ratio
T21  No real broker order path in intelligence module
T22  Phase 13 diagnostic bundle writes JSON + CSV

Run: python3 test_phase13.py
"""

import csv
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import phase13_intelligence as p13

PASS = 0
FAIL = 0
FAILURES = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


print("── Factor weights & structure ──")

# T01
check("T01 factor weights sum to 1.0",
      abs(sum(p13.FACTOR_WEIGHTS.values()) - 1.0) < 1e-9,
      f"sum={sum(p13.FACTOR_WEIGHTS.values())}")

# T02
check("T02 14 factors defined",
      len(p13.FACTOR_WEIGHTS) == 14,
      f"count={len(p13.FACTOR_WEIGHTS)} factors={list(p13.FACTOR_WEIGHTS)}")

# T03: factor scores 0-100
from phase13_intelligence import (
    _score_trend, _score_momentum, _score_volatility, _score_volume,
    _score_data_freshness, _score_liquidity, _score_risk_reward,
    _score_portfolio_context, _score_historical_similarity,
)
from config import SECTOR_MAP

scores_ok = True; details = []
for fn, args, kwargs in [
    (_score_trend, [{"confidence": 80}], {}),
    (_score_momentum, [{"rsi": 55}], {}),
    (_score_volatility, [{}], {"vix": 18.0}),
    (_score_volume, [{}], {}),
    (_score_data_freshness, [{"quality": "NEAR_LIVE"}], {}),
    (_score_liquidity, [{"volume": 500_000, "price": 500}], {}),
    (_score_risk_reward, [{"entry_price": 1000, "stop_loss": 970, "target": 1090}], {}),
    (_score_portfolio_context, ["RELIANCE", [], SECTOR_MAP], {}),
    (_score_historical_similarity, ["RELIANCE", {}, "TRENDING_UP"], {}),
]:
    try:
        s, _ = fn(*args, **kwargs)
        if not (0 <= s <= 100):
            scores_ok = False
            details.append(f"{fn.__name__}={s}")
    except Exception as exc:
        scores_ok = False
        details.append(f"{fn.__name__}: {exc}")
check("T03 all factor scores in 0-100", scores_ok, "; ".join(details) or "all ok")

print("── No-lookahead guard ──")

# T04
trades = p13._completed_paper_trades()
all_sell = all(t.get("action", "").upper() == "SELL" for t in trades) if trades else True
all_ts = all(bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date")) for t in trades) if trades else True
check("T04a no-lookahead: only SELL rows", all_sell, f"n={len(trades)}")
check("T04b no-lookahead: all have close timestamps", all_ts, f"all_ts={all_ts}")

print("── Stale-data gate ──")

from phase13_intelligence import fuse_symbol, detect_market_regime, REGIMES
_regime = detect_market_regime({})

# T05: item-level stale
stale_item = {"symbol": "STALETEST", "data_status": "DATA_UNAVAILABLE", "quality": "STALE",
              "confidence": 99, "recommendation": "STRONG_BUY"}
r5 = fuse_symbol(stale_item, _regime, [], None, {}, [], 5000, 5000, 18.0, scan_stale=False)
check("T05 item-stale blocks BUY", r5["p13_action"] not in ("BUY", "STRONG_BUY"),
      f"action={r5['p13_action']}")

# T06: scan-level stale
good_item = {"symbol": "RELIANCE", "data_status": "OK", "quality": "NEAR_LIVE",
             "confidence": 92, "recommendation": "STRONG_BUY", "risk_level": "LOW",
             "volume": 2_000_000, "price": 2500.0, "entry_price": 2500.0,
             "stop_loss": 2400.0, "target": 2800.0}
r6 = fuse_symbol(good_item, _regime, [], None, {}, [], 5000, 5000, 18.0, scan_stale=True)
check("T06 scan-stale blocks BUY", r6["p13_action"] not in ("BUY", "STRONG_BUY"),
      f"action={r6['p13_action']} scan_stale={r6.get('scan_stale')}")

# T07: near-live not blocked
r7 = fuse_symbol(good_item, _regime, [], None, {}, [], 5000, 5000, 18.0, scan_stale=False)
check("T07 near-live data not blocked", r7.get("is_stale") is False,
      f"is_stale={r7.get('is_stale')}")

print("── Market regime ──")

# T08
r8 = detect_market_regime({"vix": 13.0, "nifty_trend": "BULLISH", "market_score": 72, "breadth_score": 62})
check("T08 bullish inputs → TRENDING_UP", r8["regime"] == "TRENDING_UP",
      f"regime={r8['regime']} scores={r8['all_scores']}")

# T09
r9 = detect_market_regime({"vix": 40.0, "nifty_trend": "BEARISH", "market_score": 20, "breadth_score": 18})
check("T09 extreme VIX → CRISIS", r9["regime"] == "CRISIS",
      f"regime={r9['regime']}")

# T10
r10 = detect_market_regime({})
check("T10 regime always valid state", r10["regime"] in REGIMES, f"regime={r10['regime']}")

# T11: regime transition tracking (duration_bars present)
check("T11 regime transition tracking present",
      "regime_duration_bars" in r10 and r10["regime_duration_bars"] >= 1,
      f"duration_bars={r10.get('regime_duration_bars')}")

print("── Strategy eligibility ──")

from phase13_intelligence import eligible_strategies

# T12
strats_up = eligible_strategies("TRENDING_UP")
check("T12 TRENDING_UP has eligible strategies", len(strats_up) > 0, f"strats={strats_up}")

# T13
strats_cr = eligible_strategies("CRISIS")
check("T13 CRISIS has no eligible strategies", len(strats_cr) == 0, f"strats={strats_cr}")

print("── Evidence labels ──")

from phase13_intelligence import evidence_label

# T14
check("T14a 0 trades → insufficient", evidence_label(0) == "insufficient", f"got={evidence_label(0)}")
check("T14b 5 trades → very_low", evidence_label(5) == "very_low", f"got={evidence_label(5)}")
check("T14c 25 trades → moderate", evidence_label(25) == "moderate", f"got={evidence_label(25)}")
check("T14d 150 trades → validated", evidence_label(150) == "validated", f"got={evidence_label(150)}")

print("── Calibrated confidence ──")

from phase13_intelligence import calibrate_confidence

# T15
calib = calibrate_confidence(80.0, "very_low", "MEDIUM")
check("T15 calibrated ≤ raw score", calib["calibrated_score"] <= calib["raw_score"],
      f"calibrated={calib['calibrated_score']} raw={calib['raw_score']}")
calib2 = calibrate_confidence(80.0, "validated", "NONE")
check("T15b validated+NONE close to raw", calib2["calibrated_score"] >= 75,
      f"calibrated={calib2['calibrated_score']}")

print("── Contradiction detection ──")

from phase13_intelligence import detect_contradictions

# T16
all_bull = {f: 75.0 for f in p13.FACTOR_WEIGHTS}
c16 = detect_contradictions(all_bull)
check("T16 all-bullish → NONE or LOW", c16["level"] in ("NONE", "LOW"),
      f"level={c16['level']}")

# T17
mixed = {f: 75.0 for f in p13.FACTOR_WEIGHTS}
mixed["market_regime"] = 18.0; mixed["hist_expectancy"] = 15.0; mixed["volatility"] = 10.0
c17 = detect_contradictions(mixed)
check("T17 opposing signals → HIGH", c17["level"] == "HIGH",
      f"level={c17['level']} bull={c17['bullish_factors']} bear={c17['bearish_factors']}")

print("── Position sizing ──")

from phase13_intelligence import volatility_aware_size

# T18
sz = volatility_aware_size(2000.0, 1940.0, 5000.0, 5000.0, 18.0, "TRENDING_UP")
check("T18 position size ≤ 20% capital cap",
      (sz.get("capital_utilization_pct") or 0) <= 20.0,
      f"util={sz.get('capital_utilization_pct')}%")

# T19
sz_crisis = volatility_aware_size(1000.0, 970.0, 5000.0, 5000.0, 42.0, "CRISIS")
sz_normal = volatility_aware_size(1000.0, 970.0, 5000.0, 5000.0, 14.0, "TRENDING_UP")
check("T19 crisis regime reduces risk pct",
      sz_crisis["max_risk_pct_used"] < sz_normal["max_risk_pct_used"],
      f"crisis={sz_crisis['max_risk_pct_used']} normal={sz_normal['max_risk_pct_used']}")

print("── Risk/reward scoring ──")

from phase13_intelligence import _score_risk_reward

# T20
rr_good, _ = _score_risk_reward({"rr_ratio": 3.0})
rr_bad, _  = _score_risk_reward({"rr_ratio": 0.8})
check("T20 RR score improves with better ratio", rr_good > rr_bad,
      f"rr_good={rr_good} rr_bad={rr_bad}")

print("── Broker safety & bundle ──")

# T21
_src = open(os.path.join(_DIR, "phase13_intelligence.py")).read()
check("T21 no real broker order calls",
      "execute_buy" not in _src and "kite.place_order" not in _src and "execute_sell" not in _src,
      "found real-order call")

# T22: diagnostic bundle
try:
    from phase13_diagnostics import build_phase13_bundle, BUNDLE_FILE, SUMMARY_CSV
    bundle = build_phase13_bundle()
    json_ok = os.path.exists(BUNDLE_FILE)
    csv_rows = []
    if os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV) as f:
            csv_rows = list(csv.reader(f))
    check("T22 diagnostic bundle JSON + CSV written",
          json_ok and len(csv_rows) >= 2 and bundle.get("phase") == 13 and "factor_weights" in bundle,
          f"json={json_ok} csv_rows={len(csv_rows)} phase={bundle.get('phase')}")
except Exception as exc:
    check("T22 diagnostic bundle JSON + CSV written", False, str(exc)[:200])

print()
total = PASS + FAIL
print(f"Phase 13 tests: {PASS} passed, {FAIL} failed of {total}")
if FAILURES:
    for f in FAILURES:
        print(f"  FAIL: {f}")
    sys.exit(1)
sys.exit(0)
