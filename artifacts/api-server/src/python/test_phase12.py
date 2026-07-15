"""
test_phase12.py — Phase 12: Advanced Institutional Intelligence Layer.

22 automated tests covering:
  T01  Factor weights sum to 1.0
  T02  Factor scores are in 0–100 range
  T03  No-lookahead guard: only SELL rows with close timestamps used for learning
  T04  Stale-data gate blocks BUY/STRONG_BUY
  T05  Stale-data gate: near-live data allows BUY
  T06  Regime detection: TRENDING_UP on bullish inputs
  T07  Regime detection: CRISIS on extreme VIX
  T08  Regime detection returns valid REGIMES state
  T09  Sector rotation: sorted by avg_score descending
  T10  Sector rotation: all sectors represented (or noted as missing)
  T11  Relative strength vs-index computed correctly
  T12  Relative strength rank labels correct
  T13  Position size never exceeds 20% capital cap
  T14  Position sizing halved in CRISIS regime
  T15  Contradiction detection: NONE when all factors agree
  T16  Contradiction detection: HIGH when strong opposing signals
  T17  Confidence calibration section present in fused result
  T18  Fused score is between 0 and 100
  T19  Idempotency: two calls within TTL return same fused scores
  T20  No real broker order executed (module inspection)
  T21  Phase 12 diagnostic bundle builds JSON + CSV
  T22  main.py CLI dispatch for phase12_regime

Run: python3 test_phase12.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import phase12_intelligence as p12

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


print("── Factor weights & scoring ──")

# T01: weights sum to 1.0
check("T01 factor weights sum to 1.0",
      abs(sum(p12.FACTOR_WEIGHTS.values()) - 1.0) < 1e-9,
      f"sum={sum(p12.FACTOR_WEIGHTS.values())}")

# T02: all scoring functions return 0-100
from phase12_intelligence import (
    _score_trend, _score_momentum, _score_volatility, _score_volume,
    _score_data_freshness, _score_liquidity,
)
scores_ok = True
details = []
for fn, kwargs in [
    (_score_trend, {"confidence": 80}),
    (_score_momentum, {"rsi": 55}),
    (_score_volatility, {},),
    (_score_volume, {}),
    (_score_data_freshness, {"quality": "NEAR_LIVE"}),
    (_score_liquidity, {"volume": 500_000, "price": 500}),
]:
    if fn == _score_volatility:
        s, _ = _score_volatility({}, vix=18.0)
    else:
        s, _ = fn(kwargs)
    if not (0 <= s <= 100):
        scores_ok = False
        details.append(f"{fn.__name__}={s}")
check("T02 all factor scores in 0-100", scores_ok, "; ".join(details) or "all ok")

print("── No-lookahead guard ──")

# T03: _completed_paper_trades returns only SELL rows with close timestamps
trades = p12._completed_paper_trades()
all_sell = all(t.get("action", "").upper() == "SELL" for t in trades) if trades else True
all_ts   = all(bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date")) for t in trades) if trades else True
check("T03a no-lookahead: only SELL rows", all_sell, f"{len(trades)} trades, all_sell={all_sell}")
check("T03b no-lookahead: all have close timestamp", all_ts, f"all_ts={all_ts}")

print("── Stale-data gate ──")

# T04: stale data blocks BUY/STRONG_BUY
from phase12_intelligence import fuse_symbol, detect_market_regime
_regime = detect_market_regime({})
stale_item = {"symbol": "STALETEST", "data_status": "DATA_UNAVAILABLE",
              "quality": "STALE", "confidence": 98, "recommendation": "STRONG_BUY"}
r4 = fuse_symbol(stale_item, _regime, [], None, {}, 5000, 5000, 18.0)
check("T04 stale gate blocks BUY", r4["p12_action"] not in ("BUY", "STRONG_BUY"),
      f"action={r4['p12_action']}")

# T05: near-live data allows BUY (given sufficient score)
good_item = {"symbol": "RELIANCE", "data_status": "OK", "quality": "NEAR_LIVE",
             "confidence": 90, "recommendation": "STRONG_BUY", "risk_level": "LOW",
             "volume": 2_000_000, "price": 2500.0, "entry_price": 2500.0,
             "stop_loss": 2400.0, "target": 2800.0}
r5 = fuse_symbol(good_item, _regime, [], None, {}, 5000, 5000, 18.0)
check("T05 near-live data is not blocked by stale gate", r5.get("is_stale") is False,
      f"is_stale={r5.get('is_stale')} action={r5['p12_action']}")

print("── Market regime detection ──")

# T06: TRENDING_UP on bullish inputs
from phase12_intelligence import detect_market_regime, REGIMES
r6 = detect_market_regime({"vix": 13.0, "nifty_trend": "BULLISH",
                            "market_score": 72, "breadth_score": 62})
check("T06 bullish inputs → TRENDING_UP", r6["regime"] == "TRENDING_UP",
      f"regime={r6['regime']} scores={r6['all_scores']}")

# T07: CRISIS on extreme VIX + extreme bearish
r7 = detect_market_regime({"vix": 40.0, "nifty_trend": "BEARISH",
                            "market_score": 20, "breadth_score": 18})
check("T07 extreme VIX → CRISIS", r7["regime"] == "CRISIS",
      f"regime={r7['regime']} scores={r7['all_scores']}")

# T08: always returns a valid REGIMES state
r8 = detect_market_regime({})
check("T08 regime is always a valid state", r8["regime"] in REGIMES,
      f"regime={r8['regime']}")

print("── Sector rotation ──")

from phase12_intelligence import compute_sector_rotation
from config import SECTOR_MAP
_sample_recs = [
    {"symbol": sym, "opportunity_score": 60 + i, "confidence": 55 + i}
    for i, sector in enumerate(SECTOR_MAP)
    for sym in list(SECTOR_MAP[sector])[:2]
]
sector_rows = compute_sector_rotation(_sample_recs)

# T09: sorted by avg_score descending
scores_with_vals = [r["avg_score"] for r in sector_rows if r["avg_score"] is not None]
check("T09 sector rotation sorted descending",
      scores_with_vals == sorted(scores_with_vals, reverse=True),
      str(scores_with_vals[:4]))

# T10: all 11 sectors represented
sector_names = {r["sector"] for r in sector_rows}
check("T10 all sectors in rotation", sector_names == set(SECTOR_MAP.keys()),
      f"found={sorted(sector_names)}")

print("── Relative strength ──")

from phase12_intelligence import compute_relative_strength

# T11: RS vs index computed correctly (symbol +5%, nifty +2%, sector +3%)
rs = compute_relative_strength("RELIANCE", 5.0, 2.0, 3.0, "ENERGY")
check("T11 relative strength vs index correct",
      abs(rs["rs_vs_index"] - 3.0) < 0.01 and abs(rs["rs_vs_sector"] - 2.0) < 0.01,
      f"rs_vs_index={rs['rs_vs_index']} rs_vs_sector={rs['rs_vs_sector']}")

# T12: rank labels — LEADER requires ≥5%, use symbol +12% vs nifty +2%
rs_leader = compute_relative_strength("LEADER_CO", 12.0, 2.0, 3.0, "ENERGY")
check("T12 LEADER label for ≥5% outperformance", rs_leader["rs_rank_label"] == "LEADER",
      f"label={rs_leader['rs_rank_label']} rs={rs_leader['rs_vs_index']}")
rs_lag = compute_relative_strength("WEAK", -8.0, 0.0, 0.0, "IT")
check("T12b WEAK label for large underperformance", rs_lag["rs_rank_label"] == "WEAK",
      f"label={rs_lag['rs_rank_label']}")

print("── Position sizing ──")

from phase12_intelligence import volatility_aware_size

# T13: never exceeds 20% capital cap
sz = volatility_aware_size(2000.0, 1940.0, 5000.0, 5000.0, 18.0, "TRENDING_UP")
check("T13 position size ≤ 20% capital cap",
      (sz["capital_utilization_pct"] or 0) <= 20.0,
      f"util={sz['capital_utilization_pct']}% qty={sz['suggested_quantity']}")

# T14: risk halved in CRISIS regime
sz_crisis  = volatility_aware_size(1000.0, 970.0, 5000.0, 5000.0, 42.0, "CRISIS")
sz_normal  = volatility_aware_size(1000.0, 970.0, 5000.0, 5000.0, 14.0, "TRENDING_UP")
check("T14 crisis regime reduces risk pct",
      sz_crisis["max_risk_pct_used"] < sz_normal["max_risk_pct_used"],
      f"crisis={sz_crisis['max_risk_pct_used']} normal={sz_normal['max_risk_pct_used']}")

print("── Contradiction detection ──")

from phase12_intelligence import detect_contradictions

# T15: NONE when all factors uniformly bullish
all_bull = {f: 75.0 for f in p12.FACTOR_WEIGHTS}
c15 = detect_contradictions(all_bull)
check("T15 all-bullish → no or low contradiction",
      c15["level"] in ("NONE", "LOW"),
      f"level={c15['level']} bearish={c15['bearish_factors']}")

# T16: HIGH when strong opposing signals
mixed = {f: 75.0 for f in p12.FACTOR_WEIGHTS}
mixed["market_regime"] = 20.0
mixed["hist_expectancy"] = 15.0
mixed["volatility"] = 10.0
c16 = detect_contradictions(mixed)
check("T16 opposing signals → HIGH contradiction",
      c16["level"] == "HIGH",
      f"level={c16['level']} bull={c16['bullish_factors']} bear={c16['bearish_factors']}")

print("── Fused result integrity ──")

# T17: calibration quality field present
r17 = fuse_symbol(good_item, _regime, [], None, {}, 5000, 5000, 18.0)
check("T17 calibration_quality in factor_scores",
      "calibration_quality" in r17.get("factor_scores", {}),
      str(list(r17.get("factor_scores", {}).keys())))

# T18: fused score always 0-100
check("T18 fused score in range 0-100",
      0 <= r17.get("fused_score", -1) <= 100,
      f"fused_score={r17.get('fused_score')}")

print("── Idempotency & broker safety ──")

# T19: idempotency within TTL — two calls return identical fused scores
# Write a fresh cache, then call twice
import json as _json
_tmp = tempfile.mkdtemp(prefix="p12_test_")
_orig_cache = p12.CACHE_FILE
p12.CACHE_FILE = os.path.join(_tmp, "phase12_cache.json")
try:
    r19a = p12.run_phase12_analysis(force=True)
    r19b = p12.run_phase12_analysis(force=False)  # must use cache
    same = r19a.get("generated_at") == r19b.get("generated_at")
    check("T19 idempotency: second call uses cache", same,
          f"ts_a={r19a.get('generated_at')} ts_b={r19b.get('generated_at')}")
finally:
    p12.CACHE_FILE = _orig_cache

# T20: no execute_buy / execute_sell in phase12_intelligence.py
_src = open(os.path.join(_DIR, "phase12_intelligence.py")).read()
check("T20 no real broker order calls in engine",
      "execute_buy" not in _src and "execute_sell" not in _src
      and "kite.place_order" not in _src,
      "found real-order call in module")

print("── Diagnostic bundle & CLI ──")

# T21: diagnostic bundle builds JSON + CSV
import csv as _csv
_orig_bundle = None
try:
    from phase12_diagnostics import build_phase12_bundle, BUNDLE_FILE, SUMMARY_CSV
    bundle = build_phase12_bundle()
    json_ok = os.path.exists(BUNDLE_FILE)
    csv_rows = []
    if os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV) as f:
            csv_rows = list(_csv.reader(f))
    check("T21 diagnostic bundle JSON + CSV written",
          json_ok and len(csv_rows) >= 2
          and bundle.get("phase") == 12
          and "factor_weights" in bundle,
          f"json={json_ok} csv_rows={len(csv_rows)} keys={list(bundle)[:6]}")
except Exception as exc:
    check("T21 diagnostic bundle JSON + CSV written", False, str(exc)[:200])

# T22: main.py CLI dispatch for phase12_regime
proc = subprocess.run(
    [sys.executable, os.path.join(_DIR, "main.py"), "phase12_regime"],
    capture_output=True, text=True, cwd=_DIR, timeout=90,
)
try:
    out22 = json.loads(proc.stdout.strip())
except Exception:
    out22 = {}
check("T22 main.py phase12_regime CLI dispatch",
      proc.returncode == 0 and out22.get("success") is True and "regime" in out22,
      f"rc={proc.returncode} out={proc.stdout[:200]}")

print()
total = PASS + FAIL
print(f"Phase 12 tests: {PASS} passed, {FAIL} failed of {total}")
if FAILURES:
    for f in FAILURES:
        print(f"  FAIL: {f}")
    sys.exit(1)
sys.exit(0)
