"""
Tests for the invalidation_override detection in decision_service._decide().

Covers:
  - fc >= 85 → WATCH due to low_reliability   (STRONG_BUY gate)
  - fc >= 85 → WATCH due to expectancy <= 1%  (STRONG_BUY gate)
  - fc >= 85 → WATCH due to pf < 1.5          (STRONG_BUY gate)
  - fc >= 85 → WATCH due to rr < 2:1          (STRONG_BUY gate)
  - fc >= 75 → AVOID due to filter_passed=False
  - fc >= 75 → AVOID due to negative expectancy
  - fc = 40  → AVOID (low confidence, NOT an override)
  - fc >= 75 → BUY   (no override — recommendation is actionable)
  - fc >= 75 → WATCH due to pf <= 1.2 (BUY gate, [75,85) range)
  - fc >= 75 → WATCH due to rr < 2:1  (BUY gate, [75,85) range)
  - fc >= 75 → WATCH but no data_ok   (data quality issue, NOT an override)

Run from src/python:  python tests/test_invalidation_override.py
"""
from __future__ import annotations
import sys, os, types, unittest
from pathlib import Path

# ── stub heavy dependencies before importing decision_service ─────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _stub(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m

_stub("market_data_engine", get_last_source=lambda sym: "yfinance")
_stub("adaptive_learning",  current_market_regime=lambda: "Neutral")
_stub("model_versioning",   get_active_version=lambda: {"version": 0, "weights": {}})
_stub("strategy_intelligence",
      get_live_intelligence=lambda: types.SimpleNamespace(
          rank_for_regime=lambda r: [],
          sizing_factor=lambda s, r: 1.0),
      normalize_regime=lambda r: r)
_stub("analyst_reasoning",
      build_analyst_view=lambda d, item, regime, now=None: {
          "analyst_summary": "", "current_observation": "",
          "historical_assessment": "", "decision_reasoning": "",
          "invalidation_conditions": [], "upgrade_conditions": [],
          "invalidation_met": 0, "upgrade_met": 0,
          "decision_state": "VALID",
          "decision_timestamp": "2024-01-01T09:00:00",
          "valid_until": None, "validity_note": "",
          "conflict_level": "NONE", "conflict_explanation": "",
          "missing_data_fields": [],
      })
_stub("confidence_calibration",
      get_or_fit_calibrator=lambda: None,
      calibrate_prediction=lambda cal, fc: {
          "raw_confidence": float(fc or 0),
          "calibrated_probability": float(fc or 0) / 100.0,
          "calibrated_confidence": float(fc or 0),
          "calibration_method": "identity",
          "calibration_version": 0,
      })
_stub("similarity_engine",
      annotate_items_with_evidence=lambda items, **kw: None)

import decision_service as ds  # noqa: E402 (imports after stubs)

# ── helpers ───────────────────────────────────────────────────────────────────

RELIABLE = ds.RELIABLE_SAMPLE          # 20
BUY_C    = ds.BUY_CONF                 # 75
SB_C     = ds.STRONG_BUY_CONF          # 85


def _item(**over) -> dict:
    """Minimal scanner item that produces a STRONG_BUY by default."""
    base = {
        "stock": "TATAMOTOR", "sector": "AUTO",
        "final_confidence": 87.0,
        "base_confidence": 87.0,
        "confidence": 87.0,
        "learning_adjustment": 0.0,
        "historical_expectancy": 2.5,
        "historical_profit_factor": 1.8,
        "historical_win_rate": 60.0,
        "historical_trades": RELIABLE + 5,   # reliable sample
        "total_trades": 10,
        "rr_ratio": 3.0,
        "price": 800.0,
        "entry_price": 800.0,
        "stop_loss": 770.0,
        "target": 890.0,
        "filter_passed": True,
        "filter_reasons": [],
        "volume_ratio": 1.1,
        "opportunity_score": 65.0,
        "above_ema20": True,
        "above_ema50": True,
        "live_signal": True,
    }
    base.update(over)
    return base


def _decide(item, positions=None, trades=None) -> dict:
    return ds._decide(item, positions or {}, trades or [])


# ── test cases ────────────────────────────────────────────────────────────────

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


# ── 1. STRONG_BUY gates for fc >= 85 ─────────────────────────────────────────
print("1. fc >= 85 → WATCH due to STRONG_BUY gate conditions")

# 1a. low_reliability
d = _decide(_item(historical_trades=RELIABLE - 1))
check("1a. low_reliability: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("1a. low_reliability: invalidation_override=True",
      d["invalidation_override"] is True, str(d.get("invalidation_override")))
check("1a. low_reliability: conditions mention thin sample",
      any("thin" in c.lower() or "sample" in c.lower() or "historical" in c.lower()
          for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))
check("1a. low_reliability: conditions NOT generic 'blocking condition met'",
      d["invalidation_override_conditions"] != ["blocking condition met"],
      str(d["invalidation_override_conditions"]))

# 1b. expectancy <= 1.0 (STRONG_BUY requires > 1%)
d = _decide(_item(historical_expectancy=0.8))
check("1b. exp=0.8%: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("1b. exp=0.8%: invalidation_override=True",
      d["invalidation_override"] is True)
check("1b. exp=0.8%: conditions mention expectancy",
      any("expectancy" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))
check("1b. exp=0.8%: conditions mention STRONG BUY (not just BUY)",
      any("strong" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# 1c. pf < 1.5
d = _decide(_item(historical_profit_factor=1.3))
check("1c. pf=1.3: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("1c. pf=1.3: invalidation_override=True",
      d["invalidation_override"] is True)
check("1c. pf=1.3: conditions mention profit factor",
      any("profit factor" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# 1d. rr < 2.0 at fc >= 85
d = _decide(_item(rr_ratio=1.5, final_confidence=87.0, base_confidence=87.0, confidence=87.0))
check("1d. rr=1.5 at fc=87: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("1d. rr=1.5 at fc=87: invalidation_override=True",
      d["invalidation_override"] is True)
check("1d. rr=1.5 at fc=87: conditions mention R:R",
      any("r:r" in c.lower() or "risk" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# ── 2. AVOID overrides and high-confidence safety valve ──────────────────────
print("2. filter gate behaviour — AVOID override and high-confidence safety valve")

# 2a. Single filter failure at fc=87 → safety valve fires → WATCH not AVOID.
#     The operator still sees the setup via the OVERRIDDEN-BY-GATE badge.
d = _decide(_item(filter_passed=False, filter_reasons=["volume_ratio 0.35× < 0.75× threshold"]))
check("2a. single filter fail at fc=87: recommendation=WATCH (safety valve)",
      d["recommendation"] == "WATCH",
      f"got {d['recommendation']}")
check("2a. single filter fail at fc=87: invalidation_override=True",
      d["invalidation_override"] is True, str(d.get("invalidation_override")))
check("2a. single filter fail at fc=87: conditions contain filter reason",
      any("volume" in c.lower() or "filter" in c.lower()
          for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# 2b. Negative expectancy at fc=87 is always AVOID (no safety valve for fundamentals).
d = _decide(_item(historical_expectancy=-0.5))
check("2b. exp=-0.5%: recommendation=AVOID (no safety valve for negative expectancy)",
      d["recommendation"] == "AVOID",
      f"got {d['recommendation']}")
check("2b. exp=-0.5%: invalidation_override=True",
      d["invalidation_override"] is True)
check("2b. exp=-0.5%: conditions mention negative expectancy",
      any("expectancy" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# 2c. Empty filter_reasons with filter_passed=False at fc=87 → still safety valve
#     (failure count = max(1, 0) = 1 < HIGH_CONF_AVOID_GATE_MIN_FAILURES=2).
d = _decide(_item(filter_passed=False, filter_reasons=[]))
check("2c. filter_fail no reasons at fc=87: recommendation=WATCH (safety valve)",
      d["recommendation"] == "WATCH",
      f"got {d['recommendation']}")
check("2c. filter_fail no reasons at fc=87: invalidation_override=True",
      d["invalidation_override"] is True, str(d.get("invalidation_override")))

# 2d. Two simultaneous filter failures at fc=87 → threshold met → AVOID.
d = _decide(_item(filter_passed=False,
                  filter_reasons=["volume_ratio 0.25× < 0.75× threshold",
                                  "opportunity_score 42 < 50 floor"]))
check("2d. two filter fails at fc=87: recommendation=AVOID (gate justified)",
      d["recommendation"] == "AVOID",
      f"got {d['recommendation']}")
check("2d. two filter fails at fc=87: invalidation_override=True",
      d["invalidation_override"] is True)
check("2d. two filter fails at fc=87: conditions list non-empty",
      len(d["invalidation_override_conditions"]) >= 1,
      str(d["invalidation_override_conditions"]))

# 2e. Single filter failure at fc=80 (below STRONG_BUY_CONF) → strict gate → AVOID.
d = _decide(_item(final_confidence=80.0, base_confidence=80.0, confidence=80.0,
                  filter_passed=False,
                  filter_reasons=["volume_ratio 0.35× < 0.75× threshold"]))
check("2e. single filter fail at fc=80: recommendation=AVOID (strict gate below 85)",
      d["recommendation"] == "AVOID",
      f"got {d['recommendation']}")
check("2e. single filter fail at fc=80: invalidation_override=True",
      d["invalidation_override"] is True)

# 2f. Exactly STRONG_BUY_CONF boundary (fc=85.0): safety valve applies at >=85.
d = _decide(_item(final_confidence=85.0, base_confidence=85.0, confidence=85.0,
                  filter_passed=False,
                  filter_reasons=["volume_ratio 0.35× < 0.75× threshold"]))
check("2f. single filter fail at fc=85.0 (boundary): recommendation=WATCH (safety valve)",
      d["recommendation"] == "WATCH",
      f"got {d['recommendation']}")
check("2f. fc=85.0 boundary: invalidation_override=True",
      d["invalidation_override"] is True)

# ── 3. Genuine low-confidence AVOID (NOT an override) ────────────────────────
print("3. fc < 75 → AVOID (low confidence, not an override)")

d = _decide(_item(final_confidence=40.0, base_confidence=40.0, confidence=40.0,
                  historical_expectancy=2.5, filter_passed=True))
check("3a. fc=40: recommendation=AVOID",
      d["recommendation"] == "AVOID")
check("3a. fc=40: invalidation_override=False (NOT an override)",
      d["invalidation_override"] is False, str(d.get("invalidation_override")))
check("3a. fc=40: conditions list is empty",
      d["invalidation_override_conditions"] == [],
      str(d["invalidation_override_conditions"]))

# ── 4. BUY gates for fc in [75, 85) ──────────────────────────────────────────
print("4. fc in [75, 85) → WATCH due to BUY sub-condition gates")

# 4a. pf <= 1.2 blocks BUY
d = _decide(_item(final_confidence=80.0, base_confidence=80.0, confidence=80.0,
                  historical_profit_factor=1.1))
check("4a. pf=1.1, fc=80: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("4a. pf=1.1, fc=80: invalidation_override=True",
      d["invalidation_override"] is True)
check("4a. pf=1.1, fc=80: conditions mention profit factor for BUY (not STRONG BUY)",
      any("profit factor" in c.lower() and "buy" in c.lower()
          for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))
check("4a. pf=1.1, fc=80: conditions do NOT mention STRONG BUY",
      not any("strong" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# 4b. rr < 2.0 blocks BUY
d = _decide(_item(final_confidence=78.0, base_confidence=78.0, confidence=78.0,
                  rr_ratio=1.8, historical_profit_factor=1.5))
check("4b. rr=1.8, fc=78: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("4b. rr=1.8, fc=78: invalidation_override=True",
      d["invalidation_override"] is True)
check("4b. rr=1.8, fc=78: conditions mention R:R for BUY",
      any("r:r" in c.lower() or "risk" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# ── 5. No override when recommendation is actionable ─────────────────────────
print("5. Actionable recommendations have invalidation_override=False")

d = _decide(_item())  # default item → STRONG_BUY
check("5a. STRONG_BUY: invalidation_override=False",
      d["invalidation_override"] is False and d["recommendation"] == "STRONG_BUY",
      f"rec={d['recommendation']}, override={d.get('invalidation_override')}")

d = _decide(_item(final_confidence=80.0, base_confidence=80.0, confidence=80.0,
                  historical_expectancy=0.5))   # BUY: fc in [75,85), exp>0, pf>1.2, rr>=2
check("5b. BUY: invalidation_override=False",
      d["invalidation_override"] is False and d["recommendation"] == "BUY",
      f"rec={d['recommendation']}, override={d.get('invalidation_override')}")

# ── 6. Data-unavailable case is NOT an override ───────────────────────────────
print("6. Data quality issues are NOT reported as override")

# Patch get_last_source to return "mock" for this test
orig = sys.modules["market_data_engine"].get_last_source
sys.modules["market_data_engine"].get_last_source = lambda sym: "mock"
d = _decide(_item(final_confidence=87.0, base_confidence=87.0, confidence=87.0))
sys.modules["market_data_engine"].get_last_source = orig
check("6a. data_ok=False: recommendation=WATCH (data guard)",
      d["recommendation"] == "WATCH")
check("6a. data_ok=False: invalidation_override=False (data issue, not a gate override)",
      d["invalidation_override"] is False, str(d.get("invalidation_override")))

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'=' * 50}")
print(f"Results: {_passed} passed, {_failed} failed")
if _failed:
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
