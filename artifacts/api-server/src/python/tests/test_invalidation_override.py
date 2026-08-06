"""
Unit tests for decision_service._decide() — invalidation_override flag.

Covers two complementary test styles:

Script-style checks (sections 1–6)
  Run inline to give fast, labelled output.  Each check() call logs ✓/✗ and
  accumulates _passed / _failed so the standalone runner can exit non-zero.

Pytest-style functions (section 7)
  Standard pytest-discoverable test_* functions for CI and coverage reports.

Key behaviours under test:
  • fc=87 + single filter failure  → WATCH (high-confidence safety valve, task #387)
  • fc=87 + two filter failures    → AVOID (gate threshold met, task #387)
  • fc=87 + negative expectancy    → AVOID (no safety valve for fundamentals)
  • fc=40                          → AVOID with invalidation_override=False
  • invalidation_override=True     always has non-empty conditions listing the gate

Run from artifacts/api-server/src/python/:
    python -m pytest tests/test_invalidation_override.py -v
or standalone:
    python tests/test_invalidation_override.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Stub out modules that _decide() imports lazily ────────────────────────────
# market_data_engine.get_last_source must return "yfinance" so data_ok=True
# (without which the invalidation_override branch is never reached).
_mde = types.ModuleType("market_data_engine")
_mde.get_last_source = lambda sym: "yfinance"   # type: ignore[attr-defined]
sys.modules.setdefault("market_data_engine", _mde)

# adaptive_learning.current_market_regime must return a string.
_al = types.ModuleType("adaptive_learning")
_al.current_market_regime = lambda: "Neutral"   # type: ignore[attr-defined]
sys.modules.setdefault("adaptive_learning", _al)

# model_versioning / predictive_intelligence are only imported when
# model_weights is passed — we always pass None, so these stubs are just
# insurance.
for _mod in ("model_versioning", "predictive_intelligence"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

# ── Import the unit under test ─────────────────────────────────────────────
from decision_service import (  # noqa: E402
    _decide,
    BUY_CONF,
    RELIABLE_SAMPLE as RELIABLE,
)

# ── Script-style check infrastructure ────────────────────────────────────────
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


# ── Shared helpers ────────────────────────────────────────────────────────────

def _item(**overrides) -> dict:
    """Return a minimal scan-item dict that puts _decide on the happy path
    unless a specific override pushes it off.  All numeric defaults are chosen
    so that, absent overrides, the stock would reach STRONG_BUY."""
    base = {
        "stock": "TEST",
        "sector": "ENERGY",
        # Confidence — override to test different thresholds.
        "final_confidence": 87.0,
        "base_confidence": 87.0,
        "confidence": 87.0,
        # Expectancy positive so AVOID is only triggered by filter_passed=False.
        "historical_expectancy": 1.5,
        "historical_profit_factor": 1.8,
        "historical_win_rate": 0.60,
        "historical_trades": 30,
        "total_trades": 30,
        "rr_ratio": 2.5,
        "price": 100.0,
        "stop_loss": 95.0,
        "target": 112.5,
        # Risk filter — override to False to trigger the gate.
        "filter_passed": True,
        "filter_reasons": [],
        # Misc scanner fields (_decide accesses these but doesn't fail without them)
        "above_ema20": True,
        "above_ema50": True,
        "supertrend_dir": "UP",
        "rsi": 58.0,
        "macd_hist": 0.3,
        "volume_ratio": 1.4,
        "opportunity_score": 62.0,
        "best_regime": "Neutral",
        "live_signal": True,
        "learning_adjustment": 0.0,
        "similarity_adjustment": 0.0,
        "evidence_reliability": "VERY_LOW",
    }
    base.update(overrides)
    return base


def _call(item: dict):
    """Invoke _decide with no open positions, no trades, no model weights."""
    return _decide(item, positions={}, trades=[], model_weights=None)


# ── 1. STRONG_BUY gates for fc >= 85 ─────────────────────────────────────────
print("1. fc >= 85 → WATCH due to STRONG_BUY gate conditions")

# 1a. low_reliability
d = _call(_item(historical_trades=RELIABLE - 1))
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
d = _call(_item(historical_expectancy=0.8))
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
d = _call(_item(historical_profit_factor=1.3))
check("1c. pf=1.3: recommendation=WATCH",
      d["recommendation"] == "WATCH")
check("1c. pf=1.3: invalidation_override=True",
      d["invalidation_override"] is True)
check("1c. pf=1.3: conditions mention profit factor",
      any("profit factor" in c.lower() for c in d["invalidation_override_conditions"]),
      str(d["invalidation_override_conditions"]))

# 1d. rr < 2.0 at fc >= 85
d = _call(_item(rr_ratio=1.5, final_confidence=87.0, base_confidence=87.0, confidence=87.0))
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
d = _call(_item(filter_passed=False, filter_reasons=["volume_ratio 0.35× < 0.75× threshold"]))
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
d = _call(_item(historical_expectancy=-0.5))
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
d = _call(_item(filter_passed=False, filter_reasons=[]))
check("2c. filter_fail no reasons at fc=87: recommendation=WATCH (safety valve)",
      d["recommendation"] == "WATCH",
      f"got {d['recommendation']}")
check("2c. filter_fail no reasons at fc=87: invalidation_override=True",
      d["invalidation_override"] is True, str(d.get("invalidation_override")))

# 2d. Two simultaneous filter failures at fc=87 → threshold met → AVOID.
d = _call(_item(filter_passed=False,
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
d = _call(_item(final_confidence=80.0, base_confidence=80.0, confidence=80.0,
                  filter_passed=False,
                  filter_reasons=["volume_ratio 0.35× < 0.75× threshold"]))
check("2e. single filter fail at fc=80: recommendation=AVOID (strict gate below 85)",
      d["recommendation"] == "AVOID",
      f"got {d['recommendation']}")
check("2e. single filter fail at fc=80: invalidation_override=True",
      d["invalidation_override"] is True)

# 2f. Exactly STRONG_BUY_CONF boundary (fc=85.0): safety valve applies at >=85.
d = _call(_item(final_confidence=85.0, base_confidence=85.0, confidence=85.0,
                  filter_passed=False,
                  filter_reasons=["volume_ratio 0.35× < 0.75× threshold"]))
check("2f. single filter fail at fc=85.0 (boundary): recommendation=WATCH (safety valve)",
      d["recommendation"] == "WATCH",
      f"got {d['recommendation']}")
check("2f. fc=85.0 boundary: invalidation_override=True",
      d["invalidation_override"] is True)

# ── 3. Genuine low-confidence AVOID (NOT an override) ────────────────────────
print("3. fc < 75 → AVOID (low confidence, not an override)")

d = _call(_item(final_confidence=40.0, base_confidence=40.0, confidence=40.0,
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
d = _call(_item(final_confidence=80.0, base_confidence=80.0, confidence=80.0,
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
d = _call(_item(final_confidence=78.0, base_confidence=78.0, confidence=78.0,
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

d = _call(_item())  # default item → STRONG_BUY
check("5a. STRONG_BUY: invalidation_override=False",
      d["invalidation_override"] is False and d["recommendation"] == "STRONG_BUY",
      f"rec={d['recommendation']}, override={d.get('invalidation_override')}")

d = _call(_item(final_confidence=80.0, base_confidence=80.0, confidence=80.0,
                  historical_expectancy=0.5))   # BUY: fc in [75,85), exp>0, pf>1.2, rr>=2
check("5b. BUY: invalidation_override=False",
      d["invalidation_override"] is False and d["recommendation"] == "BUY",
      f"rec={d['recommendation']}, override={d.get('invalidation_override')}")

# ── 6. Data-unavailable case is NOT an override ───────────────────────────────
print("6. Data quality issues are NOT reported as override")

# Patch get_last_source to return "mock" for this test
orig = sys.modules["market_data_engine"].get_last_source
sys.modules["market_data_engine"].get_last_source = lambda sym: "mock"
d = _call(_item(final_confidence=87.0, base_confidence=87.0, confidence=87.0))
sys.modules["market_data_engine"].get_last_source = orig
check("6a. data_ok=False: recommendation=WATCH (data guard)",
      d["recommendation"] == "WATCH")
check("6a. data_ok=False: invalidation_override=False (data issue, not a gate override)",
      d["invalidation_override"] is False, str(d.get("invalidation_override")))

# ── 7. Pytest-style test functions ────────────────────────────────────────────
# These functions are discovered by pytest and verify the same invariants in a
# format that integrates with CI coverage reports.

def test_high_confidence_filter_blocked_sets_override():
    """
    fc=87 ≥ BUY_CONF (75) + single filter failure.
    The high-confidence safety valve (task #387) makes this WATCH not AVOID,
    but the override flag must still be set so the operator sees the badge.
    """
    result = _call(_item(
        final_confidence=87.0,
        base_confidence=87.0,
        filter_passed=False,
        filter_reasons=["volume below minimum threshold"],
    ))

    # Safety valve: single failure at fc >= 85 → WATCH (not AVOID).
    assert result["recommendation"] == "WATCH", (
        f"Expected WATCH (safety valve), got {result['recommendation']!r}"
    )
    assert result["invalidation_override"] is True, (
        "invalidation_override must be True when fc >= BUY_CONF and a gate blocked"
    )
    assert len(result["invalidation_override_conditions"]) > 0, (
        "invalidation_override_conditions must be non-empty so operators see why"
    )
    joined = " ".join(result["invalidation_override_conditions"]).lower()
    assert "volume" in joined or "risk filter" in joined or "filter" in joined, (
        f"Expected filter mention in conditions, got: {result['invalidation_override_conditions']}"
    )


def test_low_confidence_no_override():
    """
    fc=40 is below BUY_CONF (75): the override gate must not fire even though
    the stock ends up as AVOID due to low confidence.
    """
    result = _call(_item(
        final_confidence=40.0,
        base_confidence=40.0,
        filter_passed=True,
        historical_expectancy=1.0,
    ))

    assert result["recommendation"] == "AVOID", (
        f"Expected AVOID (low confidence), got {result['recommendation']!r}"
    )
    assert result["invalidation_override"] is False, (
        "invalidation_override must be False when fc < BUY_CONF"
    )
    assert result["invalidation_override_conditions"] == [], (
        "No conditions should be listed when override is not triggered"
    )


def test_override_absent_for_normal_buy():
    """A stock that legitimately reaches BUY must not carry the override flag."""
    result = _call(_item(
        final_confidence=78.0,
        base_confidence=78.0,
        filter_passed=True,
        historical_expectancy=1.2,
        historical_profit_factor=1.5,
        rr_ratio=2.2,
    ))

    assert result["recommendation"] in ("BUY", "STRONG_BUY", "WATCH"), (
        f"Unexpected recommendation: {result['recommendation']!r}"
    )
    assert result["invalidation_override"] is False, (
        "override must be absent for a stock that passes cleanly to BUY/WATCH"
    )


def test_override_conditions_reference_blocking_gate():
    """
    fc=87 + negative expectancy: negative expectancy forces AVOID regardless
    of the safety valve.  The override flag is set and conditions name the gate.
    """
    result = _call(_item(
        final_confidence=87.0,
        base_confidence=87.0,
        filter_passed=False,
        filter_reasons=["sector limit exceeded"],
        historical_expectancy=-0.5,
    ))

    # Negative expectancy always forces AVOID (no safety valve for fundamentals).
    assert result["recommendation"] == "AVOID", (
        f"Expected AVOID (negative expectancy), got {result['recommendation']!r}"
    )
    assert result["invalidation_override"] is True
    joined = " ".join(result["invalidation_override_conditions"]).lower()
    assert "expectancy" in joined or "sector" in joined or "filter" in joined or "risk" in joined, (
        f"Conditions don't mention a blocking gate: {result['invalidation_override_conditions']}"
    )


def test_buy_conf_boundary_strict_gate():
    """
    fc exactly equal to BUY_CONF (75) with filter_passed=False.
    Since 75 < STRONG_BUY_CONF (85) the safety valve does NOT apply:
    the gate is strict and the recommendation stays AVOID.
    """
    result = _call(_item(
        final_confidence=float(BUY_CONF),
        base_confidence=float(BUY_CONF),
        confidence=float(BUY_CONF),
        filter_passed=False,
        filter_reasons=["drawdown limit reached"],
    ))

    assert result["recommendation"] == "AVOID", (
        f"fc == BUY_CONF ({BUY_CONF}) is below the safety-valve threshold (85) "
        f"so strict gate applies; expected AVOID, got {result['recommendation']!r}"
    )
    assert result["invalidation_override"] is True, (
        f"fc == BUY_CONF ({BUY_CONF}) should trigger override"
    )


def test_two_filter_failures_still_avoid_at_high_confidence():
    """
    The safety valve only fires when failure_count < 2.
    Two simultaneous filter failures at fc=87 must still produce AVOID.
    """
    result = _call(_item(
        final_confidence=87.0,
        base_confidence=87.0,
        filter_passed=False,
        filter_reasons=["volume_ratio 0.25× < 0.75× threshold",
                        "opportunity_score 42 < 50 floor"],
    ))

    assert result["recommendation"] == "AVOID", (
        f"Two filter failures should bypass the safety valve; "
        f"expected AVOID, got {result['recommendation']!r}"
    )
    assert result["invalidation_override"] is True


# ── Main runner ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Script-style checks already ran at module level above.
    print(f"\n{'=' * 50}")
    print(f"Script checks: {_passed} passed, {_failed} failed")

    # Run pytest-style functions too.
    pytest_fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p_passed = p_failed = 0
    print("\nPytest-style functions:")
    for fn in pytest_fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            p_passed += 1
        except AssertionError as exc:
            print(f"  ✗ {fn.__name__} — {exc}")
            p_failed += 1

    total_failed = _failed + p_failed
    print(f"\nTotal: {_passed + p_passed} passed, {total_failed} failed")
    if total_failed:
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
