"""
test_high_conf_avoid_gate.py — Task #389

Confirms that HIGH_CONF_AVOID_GATE_MIN_FAILURES=2 produces the correct
recommendation and badge fields in decision_service._decide():

  Scenario A — fc=87, 1 filter failure  → WATCH  + invalidation_override=True
  Scenario B — fc=87, 2 filter failures → AVOID  + invalidation_override=True
  Scenario C — fc=70, 1 filter failure  → AVOID  (strict gate for lower fc)
  Scenario D — fc=87, no filter failure → STRONG_BUY (gate never fires)
  Scenario E — filter_passed=False, empty filter_reasons list (len=0)
               → max(1, 0)=1 failure → WATCH when fc>=85
  Scenario F — fc=87, negative expectancy → AVOID regardless (separate gate)
  Scenario G — invalidation_override_conditions populated on WATCH override
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_item(
    sym: str,
    fc: float,
    filter_passed: bool,
    filter_reasons: list,
    expectancy: float = 2.5,
    pf: float = 1.8,
    rr: float = 2.5,
    n_hist: int = 25,
) -> dict:
    """Minimal scan item that satisfies all gates except the ones under test."""
    return {
        "stock": sym,
        "final_confidence": fc,
        "base_confidence": fc,
        "confidence": fc,
        "learning_adjustment": 0.0,
        "historical_expectancy": expectancy,
        "historical_profit_factor": pf,
        "historical_win_rate": 0.65,
        "historical_trades": n_hist,
        "total_trades": 10,
        "rr_ratio": rr,
        "price": 1500.0,
        "filter_passed": filter_passed,
        "filter_reasons": filter_reasons,
        "similarity_adjustment": 0.0,
        "evidence_reliability": "MEDIUM",
        "similarity_evidence": None,
        "expected_holding_days": 10.0,
        "volume_ratio": 1.8,
        "live_signal": True,
        "sector": "Technology",
        "best_regime": "Bullish",
        "best_strategy_name": "Breakout",
        "best_strategy_id": "breakout_v1",
    }


def _call_decide(item: dict, positions: dict | None = None, trades: list | None = None):
    """
    Call decision_service._decide with the external modules mocked so
    data_ok=True (source == "yfinance") and regime = "Bullish".
    """
    with patch.dict(
        "sys.modules",
        {
            "market_data_engine": MagicMock(
                get_last_source=MagicMock(return_value="yfinance")
            ),
            "adaptive_learning": MagicMock(
                current_market_regime=MagicMock(return_value="Bullish")
            ),
            "confidence_calibration": MagicMock(
                side_effect=ImportError("stub")
            ),
        },
    ):
        import decision_service
        return decision_service._decide(
            item,
            positions or {},
            trades or [],
            regime_strength=60.0,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHighConfAvoidGate(unittest.TestCase):

    # ── Scenario A ──────────────────────────────────────────────────────────
    def test_single_filter_failure_high_conf_gives_watch(self):
        """
        fc=87 (>= STRONG_BUY_CONF=85) with exactly ONE filter failure
        must produce WATCH — not AVOID — because 1 < HIGH_CONF_AVOID_GATE_MIN_FAILURES (2).
        """
        item = _minimal_item(
            "WATCH_TEST",
            fc=87.0,
            filter_passed=False,
            filter_reasons=["volume_ratio 0.35 < 0.5 min"],
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "WATCH",
            f"Expected WATCH for fc=87 + 1 filter failure; got {d['recommendation']}. "
            f"reason={d['reason']}"
        )

    # ── Scenario B ──────────────────────────────────────────────────────────
    def test_two_filter_failures_high_conf_gives_avoid(self):
        """
        fc=87 with TWO simultaneous filter failures must produce AVOID —
        the gate fires because 2 >= HIGH_CONF_AVOID_GATE_MIN_FAILURES.
        """
        item = _minimal_item(
            "AVOID_TWO",
            fc=87.0,
            filter_passed=False,
            filter_reasons=[
                "volume_ratio 0.35 < 0.5 min",
                "RSI 78 > 70 overbought threshold",
            ],
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "AVOID",
            f"Expected AVOID for fc=87 + 2 filter failures; got {d['recommendation']}. "
            f"reason={d['reason']}"
        )

    # ── Scenario C ──────────────────────────────────────────────────────────
    def test_single_filter_failure_lower_conf_gives_avoid(self):
        """
        fc=70 (< STRONG_BUY_CONF=85) with one filter failure must still produce
        AVOID — the high-confidence valve does not apply below the threshold.
        """
        item = _minimal_item(
            "AVOID_LOW",
            fc=70.0,
            filter_passed=False,
            filter_reasons=["volume_ratio 0.35 < 0.5 min"],
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "AVOID",
            f"Expected AVOID for fc=70 + 1 filter failure; got {d['recommendation']}"
        )

    # ── Scenario D ──────────────────────────────────────────────────────────
    def test_no_filter_failure_high_conf_not_demoted(self):
        """
        fc=87 with filter_passed=True (no filter failure) must produce
        STRONG_BUY — the gate must NOT demote valid high-confidence setups.
        """
        item = _minimal_item(
            "STRONG_TEST",
            fc=87.0,
            filter_passed=True,
            filter_reasons=[],
            n_hist=25,  # >= RELIABLE_SAMPLE=20
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "STRONG_BUY",
            f"Expected STRONG_BUY for fc=87 + filter passed; got {d['recommendation']}"
        )

    # ── Scenario E ──────────────────────────────────────────────────────────
    def test_empty_filter_reasons_counts_as_one_failure(self):
        """
        filter_passed=False but filter_reasons=[] (empty list).
        max(1, len([])) == 1 failure → WATCH when fc >= 85.
        """
        item = _minimal_item(
            "EMPTY_REASONS",
            fc=87.0,
            filter_passed=False,
            filter_reasons=[],   # engine uses max(1, 0)=1
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "WATCH",
            f"Expected WATCH for fc=87 + empty filter_reasons; got {d['recommendation']}"
        )

    # ── Scenario F ──────────────────────────────────────────────────────────
    def test_negative_expectancy_forces_avoid_regardless_of_filter(self):
        """
        Negative expectancy is checked before the filter gate and always
        produces AVOID regardless of confidence or filter failure count.
        """
        item = _minimal_item(
            "NEG_EXP",
            fc=87.0,
            filter_passed=True,
            filter_reasons=[],
            expectancy=-0.5,
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "AVOID",
            f"Expected AVOID for negative expectancy; got {d['recommendation']}"
        )

    # ── Scenario G — invalidation_override flag ──────────────────────────────
    def test_invalidation_override_set_on_watch_gate(self):
        """
        When the high-confidence gate demotes to WATCH, invalidation_override
        must be True and invalidation_override_conditions must be non-empty,
        so the OVERRIDDEN-BY-GATE badge is rendered in the UI.
        """
        filter_reason = "volume_ratio 0.35 < 0.5 min"
        item = _minimal_item(
            "OVERRIDE_TEST",
            fc=87.0,
            filter_passed=False,
            filter_reasons=[filter_reason],
        )
        d = _call_decide(item)

        self.assertEqual(d["recommendation"], "WATCH")
        self.assertTrue(
            d["invalidation_override"],
            "invalidation_override must be True when WATCH is gate-imposed on fc>=75"
        )
        self.assertTrue(
            len(d["invalidation_override_conditions"]) > 0,
            "invalidation_override_conditions must be non-empty so the badge can display context"
        )

    # ── Scenario H — AVOID also sets invalidation_override ───────────────────
    def test_invalidation_override_set_on_avoid_two_failures(self):
        """
        Two filter failures at fc=87 → AVOID, and the invalidation_override
        flag must still be True (operator needs to know confidence was high).
        """
        item = _minimal_item(
            "AVOID_OVERRIDE",
            fc=87.0,
            filter_passed=False,
            filter_reasons=[
                "volume_ratio 0.35 < 0.5 min",
                "RSI 78 > 70 overbought threshold",
            ],
        )
        d = _call_decide(item)
        self.assertEqual(d["recommendation"], "AVOID")
        self.assertTrue(
            d["invalidation_override"],
            "invalidation_override must be True when AVOID gates a fc>=75 setup"
        )

    # ── Boundary: exactly at STRONG_BUY_CONF threshold (fc=85) ──────────────
    def test_exactly_at_threshold_fc85_single_failure_gives_watch(self):
        """
        fc=85.0 (exactly STRONG_BUY_CONF) with 1 failure must give WATCH —
        the condition is fc >= STRONG_BUY_CONF (inclusive).
        """
        item = _minimal_item(
            "BOUNDARY_85",
            fc=85.0,
            filter_passed=False,
            filter_reasons=["volume_ratio too low"],
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "WATCH",
            f"Expected WATCH at fc=85.0 + 1 failure; got {d['recommendation']}"
        )

    # ── Boundary: just below STRONG_BUY_CONF (fc=84.9) ──────────────────────
    def test_just_below_threshold_fc84_single_failure_gives_avoid(self):
        """
        fc=84.9 (just below STRONG_BUY_CONF=85) with 1 failure must give
        AVOID — the strict gate applies for fc < STRONG_BUY_CONF.
        """
        item = _minimal_item(
            "BOUNDARY_849",
            fc=84.9,
            filter_passed=False,
            filter_reasons=["volume_ratio too low"],
        )
        d = _call_decide(item)
        self.assertEqual(
            d["recommendation"], "AVOID",
            f"Expected AVOID at fc=84.9 + 1 failure; got {d['recommendation']}"
        )

    # ── Reason string for WATCH override contains filter context ─────────────
    def test_watch_reason_includes_filter_context(self):
        """
        The 'reason' field for the gated-WATCH case must mention the
        filter condition so operators see it in the table without expanding.
        """
        filter_reason = "volume_ratio 0.35 < 0.5 min"
        item = _minimal_item(
            "REASON_CHECK",
            fc=87.0,
            filter_passed=False,
            filter_reasons=[filter_reason],
        )
        d = _call_decide(item)
        self.assertEqual(d["recommendation"], "WATCH")
        self.assertIn(
            "risk filter caution",
            d["reason"].lower(),
            f"Expected 'risk filter caution' in reason; got: {d['reason']}"
        )

    # ── Constant value guard ──────────────────────────────────────────────────
    def test_constant_value(self):
        """
        HIGH_CONF_AVOID_GATE_MIN_FAILURES must be 2 — changing it would
        silently break the operator experience this task verifies.
        """
        import decision_service
        self.assertEqual(
            decision_service.HIGH_CONF_AVOID_GATE_MIN_FAILURES, 2,
            "HIGH_CONF_AVOID_GATE_MIN_FAILURES must remain 2 per calibration decision"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
