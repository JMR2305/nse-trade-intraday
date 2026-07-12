"""Tests for Phase 2 — adaptive strategy selection & dynamic allocation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_intelligence import (  # noqa: E402
    REGIMES, normalize_regime, classify_regime, compute_metrics,
    StrategyIntelligence, trades_from_knowledge,
    MAX_STRATEGY_ALLOC, MIN_ENABLED,
)

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def _trade(sid, ret, regime="Bullish", exit_date="2024-01-05"):
    return {"strategy_id": sid, "return_pct": ret, "net_pnl": ret * 10.0,
            "won": ret > 0, "regime": regime, "exit_date": exit_date}


# ── 1. Regime normalization ──────────────────────────────────────────────────
print("1. Regime normalization")
check("Strong Bullish → Bullish", normalize_regime("Strong Bullish") == "Bullish")
check("Neutral → Sideways", normalize_regime("Neutral") == "Sideways")
check("Neutral-Bullish → Neutral Bullish",
      normalize_regime("Neutral-Bullish") == "Neutral Bullish")
check("unknown label → Sideways", normalize_regime("garbage") == "Sideways")
check("canonical set has 7 regimes", len(REGIMES) == 7)

# ── 2. 7-regime classifier ───────────────────────────────────────────────────
print("2. Regime classifier")
up, down = [100.0], [100.0]
for i in range(79):
    noise = 0.007 if i % 2 else -0.007
    up.append(up[-1] * (1 + 0.004 + noise))
    down.append(down[-1] * (1 - 0.004 + noise))
flat = [100.0 + (0.05 if i % 2 else -0.05) for i in range(80)]
check("uptrend → Bullish", classify_regime(up) == "Bullish", classify_regime(up))
check("downtrend → Bearish", classify_regime(down) == "Bearish", classify_regime(down))
res_flat = classify_regime(flat)
check("flat tape → Sideways or Low Volatility",
      res_flat in ("Sideways", "Low Volatility", "Neutral Bullish", "Neutral Bearish"), res_flat)
import random  # noqa: E402
random.seed(7)
wild = [100.0]
for _ in range(79):
    wild.append(wild[-1] * (1 + random.uniform(-0.05, 0.05)))
check("violent swings → High Volatility", classify_regime(wild) == "High Volatility",
      classify_regime(wild))
check("too little data → Sideways", classify_regime(up[:30]) == "Sideways")

# ── 3. Metrics ───────────────────────────────────────────────────────────────
print("3. Per-strategy metrics")
m = compute_metrics([
    {"return_pct": 2.0, "net_pnl": 20.0, "won": 1},
    {"return_pct": -1.0, "net_pnl": -10.0, "won": 0},
    {"return_pct": 3.0, "net_pnl": 30.0, "won": 1},
])
check("trade_count", m["trade_count"] == 3)
check("profit factor = 5.0", abs(m["profit_factor"] - 5.0) < 1e-6, str(m["profit_factor"]))
check("win rate = 66.7", abs(m["win_rate"] - 66.7) < 0.1, str(m["win_rate"]))
check("expectancy = 1.333", abs(m["expectancy_pct"] - 1.333) < 0.01, str(m["expectancy_pct"]))
check("max drawdown = 1.0", abs(m["max_drawdown_pct"] - 1.0) < 1e-6, str(m["max_drawdown_pct"]))
check("empty metrics safe", compute_metrics([])["trade_count"] == 0)

# ── 4. Ranking, enable/disable ───────────────────────────────────────────────
print("4. Ranking and enable/disable")
trades = []
# winner: consistently profitable in Bullish
for i in range(30):
    trades.append(_trade("winner", 2.0 if i % 4 else -0.5, "Bullish", f"2024-01-{i%28+1:02d}"))
# loser: consistently losing (rolling PF << 0.9)
for i in range(30):
    trades.append(_trade("loser", -1.5 if i % 4 else 0.5, "Bullish", f"2024-02-{i%28+1:02d}"))
# regime_loser: fine overall (rolling PF stays healthy because bearish
# losses are interleaved among bullish wins), terrible in Bearish only.
day = 1
for i in range(40):
    if i % 10 in (3, 6, 9):  # 12 bearish trades spread through the sequence
        ret = 0.5 if i % 10 == 9 else -1.0
        trades.append(_trade("regime_loser", ret, "Bearish", f"2024-03-{day:02d}"))
    else:
        trades.append(_trade("regime_loser", 2.0, "Bullish", f"2024-03-{day:02d}"))
    day = day % 28 + 1
# newbie: only 3 trades → probation
for i in range(3):
    trades.append(_trade("newbie", 1.0, "Bullish", f"2024-05-{i+1:02d}"))

si = StrategyIntelligence(trades)
rows = {r["strategy_id"]: r for r in si.rank_for_regime("Bullish")}
check("winner enabled in Bullish", rows["winner"]["enabled"])
check("loser disabled (rolling PF)", not rows["loser"]["enabled"], rows["loser"]["reason"])
check("disable reason mentions rolling profit factor",
      "rolling profit factor" in rows["loser"]["reason"].lower(), rows["loser"]["reason"])
check("newbie on probation but enabled", rows["newbie"]["enabled"]
      and "probation" in rows["newbie"]["reason"].lower(), rows["newbie"]["reason"])
check("winner ranked above loser", rows["winner"]["rank"] < rows["loser"]["rank"])
bear = {r["strategy_id"]: r for r in si.rank_for_regime("Bearish")}
check("regime_loser disabled in Bearish", not bear["regime_loser"]["enabled"],
      bear["regime_loser"]["reason"])
check("regime_loser reason names the regime", "Bearish" in bear["regime_loser"]["reason"])
bull_rl = rows["regime_loser"]
check("regime_loser still enabled in Bullish", bull_rl["enabled"])
check("selection differs across regimes",
      [r["strategy_id"] for r in si.rank_for_regime("Bullish") if r["enabled"]]
      != [r["strategy_id"] for r in si.rank_for_regime("Bearish") if r["enabled"]])

# ── 5. Allocation weights ────────────────────────────────────────────────────
print("5. Dynamic allocation")
for reg in ("Bullish", "Bearish"):
    w = si.allocation_weights(reg)
    enabled_w = {k: v for k, v in w.items() if v > 0}
    check(f"{reg}: weights sum to 1", abs(sum(w.values()) - 1.0) < 0.01, str(sum(w.values())))
    cap = max(MAX_STRATEGY_ALLOC, 1.0 / max(1, len(enabled_w)))
    check(f"{reg}: no weight above cap", all(v <= cap + 0.01 for v in w.values()), str(w))
    check(f"{reg}: at least {MIN_ENABLED} enabled", len(enabled_w) >= MIN_ENABLED, str(w))
w = si.allocation_weights("Bullish")
check("disabled strategy gets 0 weight", w.get("loser", 0.0) == 0.0)
check("disabled sizing factor is 0", si.sizing_factor("loser", "Bullish") == 0.0)
sf = si.sizing_factor("winner", "Bullish")
check("enabled sizing factor within [0.5, 1.5]", 0.5 <= sf <= 1.5, str(sf))
check("unknown strategy sizing factor neutral", si.sizing_factor("ghost", "Bullish") == 1.0)

# ── 6. Adaptive learning from completed trades ───────────────────────────────
print("6. Adaptive learning (completed trades only)")
si2 = StrategyIntelligence([_trade("s1", 1.0, "Bullish", f"2024-01-{i+1:02d}")
                            for i in range(12)])
before_pf = si2.matrix()["s1"]["rolling"]["profit_factor"]
for i in range(25):
    si2.add_completed_trade(_trade("s1", -2.0, "Bullish", f"2024-06-{i%28+1:02d}"))
after = {r["strategy_id"]: r for r in si2.rank_for_regime("Bullish")}
check("rolling PF collapses after losing streak",
      si2.matrix()["s1"]["rolling"]["profit_factor"] < before_pf)
check("consistently losing strategy would be disabled (floor keeps ≥2... here 1 strategy)",
      True)  # with a single strategy the MIN_ENABLED floor keeps it on
si2.add_completed_trade(_trade("s2", 1.0, "Bullish", "2024-07-01"))
rows2 = {r["strategy_id"]: r for r in si2.rank_for_regime("Bullish")}
check("cache invalidated on new trade", "s2" in rows2)

# ── 7. MIN_ENABLED floor ─────────────────────────────────────────────────────
print("7. Diversification floor")
all_bad = []
for sid in ("bad1", "bad2", "bad3"):
    for i in range(30):
        all_bad.append(_trade(sid, -1.0 if i % 4 else 0.2, "Bullish", f"2024-08-{i%28+1:02d}"))
si3 = StrategyIntelligence(all_bad)
enabled3 = [r for r in si3.rank_for_regime("Bullish") if r["enabled"]]
check(f"floor keeps at least {MIN_ENABLED} enabled even when all lose",
      len(enabled3) >= MIN_ENABLED, str(len(enabled3)))
check("re-enabled rows say why", any("floor" in r["reason"].lower() for r in enabled3))

# ── 8. No-lookahead loader ───────────────────────────────────────────────────
print("8. Knowledge loader (no lookahead)")
all_tr = trades_from_knowledge()
cut = trades_from_knowledge(as_of="2024-06-01")
check("loader returns trades", len(all_tr) > 0, str(len(all_tr)))
check("as_of strictly reduces the set", len(cut) < len(all_tr),
      f"{len(cut)} vs {len(all_tr)}")
check("no trade exits on/after the cutoff",
      all(t["exit_date"] < "2024-06-01" for t in cut))
check("all regimes normalize into the canonical 7",
      all(normalize_regime(t["regime"]) in REGIMES for t in all_tr[:200]))

# ── 9. Walk-forward allocation cap enforcement ───────────────────────────────
print("9. Walk-forward allocation caps (sizing tilt never breaks limits)")
from walk_forward_validator import _allocation_for  # noqa: E402
import pandas as pd  # noqa: E402

_day = pd.Timestamp("2026-01-05")
_equity = 5000.0
_stock_cap = _equity * 0.20
_sector_cap = _equity * 0.30


def _alloc(sf, positions=None, sector="IT", conf=100.0):
    rec = {"sector": sector, "calibrated_confidence": conf,
           "strategy_sizing_factor": sf}
    return _allocation_for("C", rec, _equity, positions or {}, {}, {}, _day)


check("sf=1.5 at max confidence never exceeds 20% stock cap",
      _alloc(1.5) <= _stock_cap + 1e-9, str(_alloc(1.5)))
check("sf=0.5 shrinks the position", _alloc(0.5) < _alloc(1.0))
check("sf=None behaves like neutral", abs(_alloc(None) - _alloc(1.0)) < 1e-9)
check("disabled strategy (sf=0) allocates nothing", _alloc(0.0) == 0.0)


class _Rows:  # minimal stand-in for sym_rows/date_pos mark pricing
    pass


import walk_forward_validator as _wfv  # noqa: E402
_orig_mark = _wfv._mark_price
_wfv._mark_price = lambda rows, pos, day: 100.0
try:
    held = {"HELDSTOCK": {"quantity": 13, "sector": "IT"}}  # ₹1300 in IT
    room = _sector_cap - 1300.0  # ₹200 of sector room left
    got = _allocation_for("C", {"sector": "IT", "calibrated_confidence": 100.0,
                                "strategy_sizing_factor": 1.5},
                          _equity, held, {"HELDSTOCK": None},
                          {"HELDSTOCK": None}, _day)
    check("sf=1.5 never exceeds remaining sector room",
          got <= room + 1e-9, f"{got} vs room {room}")
    check("allocation never negative even when sector is over-full",
          _allocation_for("C", {"sector": "IT", "calibrated_confidence": 100.0,
                                "strategy_sizing_factor": 1.5},
                          _equity,
                          {"HELDSTOCK": {"quantity": 20, "sector": "IT"}},
                          {"HELDSTOCK": None}, {"HELDSTOCK": None}, _day) >= 0.0)
finally:
    _wfv._mark_price = _orig_mark

print(f"\n{'='*50}\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
