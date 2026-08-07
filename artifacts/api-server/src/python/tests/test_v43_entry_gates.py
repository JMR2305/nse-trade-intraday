"""
test_v43_entry_gates.py — Focused per-gate PASS/FAIL tests for the three
V4.3 risk-tuning gates added to evaluate_entries() in phase20_gates.py.

Gates under test:
  max_concurrent_positions — blocks when open positions ≥ setting (0 = disabled)
  min_liquidity            — blocks when avg_volume/1000 < setting (0 = disabled);
                             skipped when no volume field in the scan record
  max_volatility           — blocks when ATR% > setting (0 = disabled); can
                             derive ATR% from atr_abs / entry_price; skipped
                             when no ATR data

All tests drive the real evaluate_entries() code path; none test helper
closures directly.
"""

import unittest
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── shared test harness ───────────────────────────────────────────────────────

def _run_evaluate(
    settings_override: dict,
    scan_symbols: dict | None = None,
    positions: list | None = None,
    cash: float = 500_000.0,
):
    """
    Run evaluate_entries() with controllable settings, scan records, and
    portfolio positions.  All external I/O is mocked.

    Args:
        settings_override: merged on top of DEFAULT_SETTINGS before returning
        scan_symbols:      dict of {SYM: scan_record} for the scan context;
                           defaults to a single BUY candidate "TESTCO"
        positions:         portfolio open positions list; each item should have
                           at least {symbol, quantity, current_price}
        cash:              portfolio cash balance

    Returns:
        The full evaluate_entries() dict.
    """
    import phase20_store as ps
    import phase15_scan_context
    import market_hours
    import scan_state_store
    import paper_trader
    import phase20_circuit_breaker
    import phase20_gates as g
    from phase20_store import DEFAULT_SETTINGS

    # Build a minimal but realistic scan record for TESTCO
    _default_rec = {
        "final_action":    "BUY",
        "entry_price":     1000.0,
        "stop_loss":       950.0,
        "target_price":    1100.0,
        "rr_ratio":        2.0,
        "confidence":      75.0,
        "opportunity_score": 65.0,
        "technical_score": 60.0,
        "data_quality":    "LIVE",
        "all_gates_passed": True,
        "strategy_name":   "momentum",
        "regime":          "TRENDING",
        "error":           False,
    }
    if scan_symbols is None:
        scan_symbols = {"TESTCO": dict(_default_rec)}

    positions = positions or []
    total_value = cash + sum(
        float(p.get("quantity", 0)) * float(p.get("current_price", 0))
        for p in positions
    )

    portfolio = {
        "cash":           cash,
        "total_value":    total_value or cash,
        "invested_value": total_value - cash,
        "positions":      positions,
    }

    scan_ctx = {
        "available":         True,
        "scan_id":           "test-scan-001",
        "snapshot_ts":       "2026-08-07T06:00:00Z",
        "scan_age_seconds":  30,
        "stale_after_seconds": 300,
        "stale":             False,
        "symbols":           scan_symbols,
    }

    # Merge settings_override on top of defaults
    merged_settings = dict(DEFAULT_SETTINGS)
    merged_settings.update(settings_override)

    def fake_with_db(fn, fallback):
        # Return the merged settings as if stored in DB
        return {k: merged_settings[k] for k in DEFAULT_SETTINGS}

    snapshot = {
        "scan_id": "test-scan-001",
        "safety": {"kite_connected": True, "data_provider": "zerodha"},
        "summary": {
            "data_quality_breakdown": {"LIVE": 5, "NEAR_LIVE": 0}
        },
    }

    with patch.object(ps, "_with_db", side_effect=fake_with_db), \
         patch("phase20_store.kv_get", return_value=None), \
         patch("phase20_store.kv_set"), \
         patch.object(phase15_scan_context, "build_scan_context",
                      return_value=scan_ctx), \
         patch.object(market_hours, "market_status",
                      return_value={"state": "OPEN"}), \
         patch.object(scan_state_store, "load_latest_meta",
                      return_value={"scan_id": "test-scan-001",
                                    "provider": "zerodha"}), \
         patch.object(scan_state_store, "load_latest_snapshot",
                      return_value=snapshot), \
         patch.object(paper_trader, "_load_state",
                      return_value={"trades": []}), \
         patch.object(paper_trader, "get_portfolio", return_value=portfolio), \
         patch.object(phase20_circuit_breaker, "get_state",
                      return_value={"tripped": False, "reasons": []}):
        result = g.evaluate_entries()
    return result


def _get_gate(result: dict, symbol: str, gate_name: str):
    """Find a gate dict by name in the candidate's gate list, or None."""
    for c in result.get("candidates", []):
        if c["symbol"] == symbol:
            for g in c.get("gates", []):
                if g["gate"] == gate_name:
                    return g
    return None


# ── max_concurrent_positions ──────────────────────────────────────────────────

class TestMaxConcurrentPositions(unittest.TestCase):
    """
    Gate: max_concurrent_positions
    Enabled when setting > 0.
    Blocks a NEW position when open_count >= max_conc.
    Passes when open_count < max_conc.
    Passes for an existing position (sym already in positions).
    """

    def test_gate_absent_when_disabled(self):
        """Setting = 0 → gate must not appear at all."""
        result = _run_evaluate({"max_concurrent_positions": 0})
        gate = _get_gate(result, "TESTCO", "max_concurrent_positions")
        self.assertIsNone(gate,
                          "max_concurrent_positions gate must be absent when setting=0")

    def test_gate_passes_when_below_limit(self):
        """2 open positions, limit=5 → gate passes."""
        positions = [
            {"symbol": "A", "quantity": 10, "current_price": 100},
            {"symbol": "B", "quantity": 10, "current_price": 100},
        ]
        result = _run_evaluate(
            {"max_concurrent_positions": 5},
            positions=positions,
        )
        gate = _get_gate(result, "TESTCO", "max_concurrent_positions")
        self.assertIsNotNone(gate, "gate must be present when enabled")
        self.assertTrue(gate["passed"],
                        f"Expected PASS (2 open < limit 5); reason={gate['reason']}")

    def test_gate_fails_when_at_limit(self):
        """5 open positions, limit=5 → gate fails (at limit)."""
        positions = [
            {"symbol": f"SYM{i}", "quantity": 10, "current_price": 100}
            for i in range(5)
        ]
        result = _run_evaluate(
            {"max_concurrent_positions": 5},
            positions=positions,
        )
        gate = _get_gate(result, "TESTCO", "max_concurrent_positions")
        self.assertIsNotNone(gate)
        self.assertFalse(gate["passed"],
                         f"Expected FAIL (5 open = limit 5); reason={gate['reason']}")

    def test_gate_fails_when_over_limit(self):
        """6 open positions, limit=5 → gate fails (over limit)."""
        positions = [
            {"symbol": f"SYM{i}", "quantity": 10, "current_price": 100}
            for i in range(6)
        ]
        result = _run_evaluate(
            {"max_concurrent_positions": 5},
            positions=positions,
        )
        gate = _get_gate(result, "TESTCO", "max_concurrent_positions")
        self.assertIsNotNone(gate)
        self.assertFalse(gate["passed"],
                         f"Expected FAIL (6 open > limit 5); reason={gate['reason']}")

    def test_gate_passes_for_existing_position(self):
        """
        Symbol already in positions (adding-to-existing), limit=1 already at cap:
        the gate should pass because it is not opening a new position.
        """
        positions = [
            {"symbol": "TESTCO", "quantity": 10, "current_price": 100},
        ]
        result = _run_evaluate(
            {"max_concurrent_positions": 1},
            positions=positions,
        )
        gate = _get_gate(result, "TESTCO", "max_concurrent_positions")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS (adding to existing position); reason={gate['reason']}")

    def test_reason_includes_counts(self):
        """Gate reason should include open count and limit."""
        result = _run_evaluate(
            {"max_concurrent_positions": 3},
            positions=[{"symbol": "X", "quantity": 1, "current_price": 100}],
        )
        gate = _get_gate(result, "TESTCO", "max_concurrent_positions")
        self.assertIsNotNone(gate)
        self.assertIn("1", gate["reason"])   # open count
        self.assertIn("3", gate["reason"])   # limit


# ── min_liquidity ─────────────────────────────────────────────────────────────

class TestMinLiquidity(unittest.TestCase):
    """
    Gate: min_liquidity
    Enabled when setting > 0.
    Reads avg_volume (shares/day) → compares vol/1000 against threshold (k-shares).
    Falls back to avg_daily_volume, then volume.
    Skipped (not added to gates) when no volume field is present in the scan record.
    """

    def _make_scan(self, volume_field: str | None, volume_value: float | None) -> dict:
        rec = {
            "final_action":    "BUY",
            "entry_price":     1000.0,
            "stop_loss":       950.0,
            "target_price":    1100.0,
            "rr_ratio":        2.0,
            "confidence":      75.0,
            "opportunity_score": 65.0,
            "technical_score": 60.0,
            "data_quality":    "LIVE",
            "all_gates_passed": True,
            "strategy_name":   "momentum",
            "regime":          "TRENDING",
            "error":           False,
        }
        if volume_field and volume_value is not None:
            rec[volume_field] = volume_value
        return {"TESTCO": rec}

    def test_gate_absent_when_disabled(self):
        """Setting = 0 → gate must not appear at all."""
        result = _run_evaluate(
            {"min_liquidity_filter": 0},
            scan_symbols=self._make_scan("avg_volume", 1_000_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNone(gate, "min_liquidity gate must be absent when setting=0")

    def test_gate_passes_when_volume_above_threshold(self):
        """avg_volume = 600k shares, threshold = 500k → 600 >= 500 → PASS."""
        result = _run_evaluate(
            {"min_liquidity_filter": 500.0},
            scan_symbols=self._make_scan("avg_volume", 600_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNotNone(gate, "gate must be present when enabled and volume present")
        self.assertTrue(gate["passed"],
                        f"Expected PASS (600k >= 500k); reason={gate['reason']}")

    def test_gate_fails_when_volume_below_threshold(self):
        """avg_volume = 200k shares, threshold = 500k → 200 < 500 → FAIL."""
        result = _run_evaluate(
            {"min_liquidity_filter": 500.0},
            scan_symbols=self._make_scan("avg_volume", 200_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNotNone(gate)
        self.assertFalse(gate["passed"],
                         f"Expected FAIL (200k < 500k); reason={gate['reason']}")

    def test_gate_passes_when_exactly_at_threshold(self):
        """avg_volume exactly at threshold → PASS (>= not >)."""
        result = _run_evaluate(
            {"min_liquidity_filter": 300.0},
            scan_symbols=self._make_scan("avg_volume", 300_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS (300k == threshold 300k); reason={gate['reason']}")

    def test_gate_skipped_when_no_volume_in_record(self):
        """No volume field at all → gate must not appear (no false positives)."""
        result = _run_evaluate(
            {"min_liquidity_filter": 500.0},
            scan_symbols=self._make_scan(None, None),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNone(gate,
                          "min_liquidity gate must be skipped when no volume data")

    def test_fallback_to_avg_daily_volume(self):
        """Falls back to avg_daily_volume when avg_volume is absent."""
        result = _run_evaluate(
            {"min_liquidity_filter": 500.0},
            scan_symbols=self._make_scan("avg_daily_volume", 600_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS via avg_daily_volume fallback; reason={gate['reason']}")

    def test_fallback_to_volume(self):
        """Falls back to volume field when avg_volume and avg_daily_volume are absent."""
        result = _run_evaluate(
            {"min_liquidity_filter": 100.0},
            scan_symbols=self._make_scan("volume", 150_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS via volume fallback; reason={gate['reason']}")

    def test_reason_shows_k_units(self):
        """Gate reason should display volume in thousands."""
        result = _run_evaluate(
            {"min_liquidity_filter": 500.0},
            scan_symbols=self._make_scan("avg_volume", 400_000),
        )
        gate = _get_gate(result, "TESTCO", "min_liquidity")
        self.assertIsNotNone(gate)
        # 400_000 / 1000 = 400k
        self.assertIn("400", gate["reason"])
        self.assertIn("500", gate["reason"])


# ── max_volatility ────────────────────────────────────────────────────────────

class TestMaxVolatility(unittest.TestCase):
    """
    Gate: max_volatility
    Enabled when setting > 0.
    Reads atr_pct directly, or atr_percent, or derives (atr_abs / entry) * 100.
    Blocks when atr_pct > max_volatility_filter.
    Skipped when no ATR data is present.
    """

    def _make_scan(self, extra: dict) -> dict:
        rec = {
            "final_action":    "BUY",
            "entry_price":     1000.0,
            "stop_loss":       950.0,
            "target_price":    1100.0,
            "rr_ratio":        2.0,
            "confidence":      75.0,
            "opportunity_score": 65.0,
            "technical_score": 60.0,
            "data_quality":    "LIVE",
            "all_gates_passed": True,
            "strategy_name":   "momentum",
            "regime":          "TRENDING",
            "error":           False,
        }
        rec.update(extra)
        return {"TESTCO": rec}

    def test_gate_absent_when_disabled(self):
        """Setting = 0 → gate must not appear at all."""
        result = _run_evaluate(
            {"max_volatility_filter": 0.0},
            scan_symbols=self._make_scan({"atr_pct": 2.0}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNone(gate, "max_volatility gate must be absent when setting=0")

    def test_gate_passes_when_atr_below_max(self):
        """atr_pct = 2.5%, max = 5.0% → PASS."""
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr_pct": 2.5}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS (2.5% < 5.0%); reason={gate['reason']}")

    def test_gate_fails_when_atr_above_max(self):
        """atr_pct = 7.0%, max = 5.0% → FAIL."""
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr_pct": 7.0}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertFalse(gate["passed"],
                         f"Expected FAIL (7.0% > 5.0%); reason={gate['reason']}")

    def test_gate_passes_exactly_at_threshold(self):
        """atr_pct exactly at max → PASS (<= not <)."""
        result = _run_evaluate(
            {"max_volatility_filter": 3.0},
            scan_symbols=self._make_scan({"atr_pct": 3.0}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS (3.0% == max 3.0%); reason={gate['reason']}")

    def test_reads_atr_percent_field(self):
        """Falls back to atr_percent when atr_pct is absent."""
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr_percent": 2.0}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS via atr_percent; reason={gate['reason']}")

    def test_derives_atr_pct_from_atr_abs(self):
        """
        atr_abs = 30.0, entry = 1000.0 → atr_pct = 3.0%.
        max_volatility_filter = 5.0 → PASS.
        """
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr_abs": 30.0}),  # 30/1000 = 3%
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS (derived atr_pct=3.0% < 5.0%); reason={gate['reason']}")

    def test_derives_atr_pct_from_atr_abs_fail(self):
        """
        atr_abs = 80.0, entry = 1000.0 → atr_pct = 8.0%.
        max_volatility_filter = 5.0 → FAIL.
        """
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr_abs": 80.0}),  # 80/1000 = 8%
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertFalse(gate["passed"],
                         f"Expected FAIL (derived atr_pct=8.0% > 5.0%); reason={gate['reason']}")

    def test_gate_skipped_when_no_atr_data(self):
        """No atr_pct, atr_percent, or atr_abs → gate must not appear."""
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNone(gate,
                          "max_volatility gate must be skipped when no ATR data")

    def test_derives_from_atr_field_alias(self):
        """atr field (alternative alias) is used when atr_abs is absent."""
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr": 20.0}),  # 20/1000 = 2%
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertTrue(gate["passed"],
                        f"Expected PASS via atr alias; reason={gate['reason']}")

    def test_reason_shows_pct_values(self):
        """Gate reason should display actual and max ATR% values."""
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols=self._make_scan({"atr_pct": 3.5}),
        )
        gate = _get_gate(result, "TESTCO", "max_volatility")
        self.assertIsNotNone(gate)
        self.assertIn("3.50", gate["reason"])
        self.assertIn("5.00", gate["reason"])


# ── Gate results reflected in eligible / failed_gates ────────────────────────

class TestGateResultReflectedInEligibility(unittest.TestCase):
    """
    When a V4.3 gate fails, the candidate's eligible flag is False and the
    gate name appears in failed_gates.
    """

    def _first_candidate(self, result):
        return result["candidates"][0]

    def test_max_concurrent_fail_marks_ineligible(self):
        positions = [{"symbol": f"S{i}", "quantity": 1, "current_price": 100}
                     for i in range(3)]
        result = _run_evaluate(
            {"max_concurrent_positions": 3},
            positions=positions,
        )
        c = self._first_candidate(result)
        self.assertFalse(c["eligible"])
        self.assertIn("max_concurrent_positions", c["failed_gates"])

    def test_min_liquidity_fail_marks_ineligible(self):
        rec = {
            "final_action": "BUY", "entry_price": 1000.0, "stop_loss": 950.0,
            "target_price": 1100.0, "rr_ratio": 2.0, "confidence": 75.0,
            "opportunity_score": 65.0, "technical_score": 60.0,
            "data_quality": "LIVE", "all_gates_passed": True,
            "strategy_name": "momentum", "regime": "TRENDING", "error": False,
            "avg_volume": 50_000,  # 50k < threshold 500k
        }
        result = _run_evaluate(
            {"min_liquidity_filter": 500.0},
            scan_symbols={"TESTCO": rec},
        )
        c = self._first_candidate(result)
        self.assertFalse(c["eligible"])
        self.assertIn("min_liquidity", c["failed_gates"])

    def test_max_volatility_fail_marks_ineligible(self):
        rec = {
            "final_action": "BUY", "entry_price": 1000.0, "stop_loss": 950.0,
            "target_price": 1100.0, "rr_ratio": 2.0, "confidence": 75.0,
            "opportunity_score": 65.0, "technical_score": 60.0,
            "data_quality": "LIVE", "all_gates_passed": True,
            "strategy_name": "momentum", "regime": "TRENDING", "error": False,
            "atr_pct": 8.0,  # 8% > max 5%
        }
        result = _run_evaluate(
            {"max_volatility_filter": 5.0},
            scan_symbols={"TESTCO": rec},
        )
        c = self._first_candidate(result)
        self.assertFalse(c["eligible"])
        self.assertIn("max_volatility", c["failed_gates"])

    def test_all_three_gates_can_pass_simultaneously(self):
        """All three enabled and all conditions met → candidate remains eligible
        (modulo other gates that are independent of V4.3 logic)."""
        rec = {
            "final_action": "BUY", "entry_price": 1000.0, "stop_loss": 950.0,
            "target_price": 1100.0, "rr_ratio": 2.0, "confidence": 75.0,
            "opportunity_score": 65.0, "technical_score": 60.0,
            "data_quality": "LIVE", "all_gates_passed": True,
            "strategy_name": "momentum", "regime": "TRENDING", "error": False,
            "avg_volume": 700_000,  # 700k >= 500k → PASS
            "atr_pct": 3.0,         # 3.0% <= 5.0% → PASS
        }
        result = _run_evaluate(
            {
                "max_concurrent_positions": 5,   # 0 open < 5 → PASS
                "min_liquidity_filter":    500.0, # 700k >= 500k → PASS
                "max_volatility_filter":   5.0,  # 3.0% <= 5.0% → PASS
            },
            scan_symbols={"TESTCO": rec},
        )
        c = self._first_candidate(result)
        v43_failed = [g for g in c["failed_gates"]
                      if g in ("max_concurrent_positions", "min_liquidity", "max_volatility")]
        self.assertEqual(v43_failed, [],
                         f"No V4.3 gates should fail when all conditions met; got {v43_failed}")


if __name__ == "__main__":
    unittest.main()
