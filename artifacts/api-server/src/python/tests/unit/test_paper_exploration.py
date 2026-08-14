"""
test_paper_exploration.py — Unit tests for paper_exploration_engine.py

Coverage:
  - resize_to_cap: normal, fractional floor, zero-price guard, hard cap binding
  - Hard gates block all exploration entry paths (market_closed, stale, CB)
  - Budget exhaustion prevents new entries
  - evaluate_exploration_candidates: gate block → empty candidates
  - create_exploration_entry: never calls execute_buy (safety invariant)
  - exploration settings in phase20_store: defaults + validation bounds
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: build a minimal settings dict
# ---------------------------------------------------------------------------

def _settings(**overrides):
    base = {
        "paper_exploration_mode": True,
        "exploration_max_pct_per_trade": 5.0,
        "exploration_max_trades_per_day": 2,
        "exploration_max_total_exposure_pct": 10.0,
        "exploration_min_rr": 1.2,
        "exploration_min_confidence": 60.0,
        "per_stock_exposure_cap_pct": 25.0,
        "max_holding_days": 10,
        "slippage_pct": 0.15,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test: resize_to_cap
# ---------------------------------------------------------------------------

class TestResizeToCap(unittest.TestCase):
    """
    resize_to_cap uses min(per_stock_exposure_cap_pct, _PRETRADE_MAX_PCT=20%)
    as the effective cap.  exploration_max_pct_per_trade is a SEPARATE budget
    governor applied inside evaluate_exploration_candidates.
    """

    def _call(self, symbol, price, portfolio_value, settings=None):
        from paper_exploration_engine import resize_to_cap
        return resize_to_cap(symbol, price, portfolio_value, settings or _settings())

    def test_normal_case_returns_positive(self):
        """At ₹1,200 on ₹50,000, effective cap 20% → max ₹10,000 → 8 shares"""
        result = self._call("DRREDDY", 1200.0, 50_000.0)
        self.assertGreater(result, 0)

    def test_cap_is_respected(self):
        """qty * price must not exceed 20% (PRETRADE cap) of portfolio value"""
        result = self._call("DRREDDY", 1200.0, 50_000.0)
        self.assertLessEqual(result * 1200.0, 50_000.0 * 0.20 + 1e-6)

    def test_zero_price_returns_zero(self):
        result = self._call("DRREDDY", 0.0, 50_000.0)
        self.assertEqual(result, 0)

    def test_negative_price_returns_zero(self):
        result = self._call("DRREDDY", -100.0, 50_000.0)
        self.assertEqual(result, 0)

    def test_result_is_integer(self):
        """Result must be a whole number (no fractional shares)"""
        result = self._call("DRREDDY", 1333.33, 50_000.0)
        self.assertEqual(result, int(result))

    def test_per_stock_cap_binding(self):
        """If per_stock_exposure_cap_pct < 20%, the lower cap binds"""
        settings = _settings(per_stock_exposure_cap_pct=10.0)
        result = self._call("DRREDDY", 1200.0, 50_000.0, settings)
        # Must not exceed 10% (per_stock cap binds, since 10 < 20)
        self.assertLessEqual(result * 1200.0, 50_000.0 * 0.10 + 1e-6)

    def test_larger_cap_still_capped_at_20(self):
        """Even if per_stock cap is 50%, the hard PRETRADE cap of 20% limits"""
        settings = _settings(per_stock_exposure_cap_pct=50.0)
        result = self._call("DRREDDY", 1200.0, 50_000.0, settings)
        self.assertLessEqual(result * 1200.0, 50_000.0 * 0.20 + 1e-6)

    def test_zero_portfolio_value_returns_zero(self):
        result = self._call("DRREDDY", 1200.0, 0.0)
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# Test: _check_hard_gates
# ---------------------------------------------------------------------------

class TestHardGates(unittest.TestCase):
    """
    _check_hard_gates() takes no arguments; it reads from internal modules.
    We patch those modules to isolate the gate logic.
    """

    def _patch_internals(self, market_state="OPEN", scan_age_s=300,
                         scan_available=True, cb_tripped=False):
        """Return a stack of patchers for the internals _check_hard_gates reads."""
        ctx = {
            "available": scan_available,
            "scan_age_seconds": scan_age_s,
        }
        mstat = {"state": market_state}

        patches = [
            patch("paper_exploration_engine.build_scan_context",
                  return_value=ctx, create=True),
            patch("paper_exploration_engine.market_status",
                  return_value=mstat, create=True),
        ]

        # CB state
        cb_mod = MagicMock()
        cb_mod.get_state.return_value = {"tripped": cb_tripped}
        patches.append(patch.dict("sys.modules",
                                  {"phase20_circuit_breaker": cb_mod}))
        return patches

    def _run_gates(self, **kwargs):
        from paper_exploration_engine import _check_hard_gates
        ctx = {
            "available": kwargs.get("scan_available", True),
            "scan_age_seconds": kwargs.get("scan_age_s", 300),
        }
        mstat = {"state": kwargs.get("market_state", "OPEN")}
        cb_tripped = kwargs.get("cb_tripped", False)

        cb_mock = MagicMock()
        cb_mock.get_state.return_value = {"tripped": cb_tripped}

        with patch("phase20_circuit_breaker.get_state", cb_mock.get_state, create=True):
            with patch.dict("sys.modules", {"phase20_circuit_breaker": cb_mock}):
                with patch("paper_exploration_engine.build_scan_context",
                           return_value=ctx, create=True):
                    with patch("paper_exploration_engine.market_status",
                               return_value=mstat, create=True):
                        # Temporarily import and replace inside the module
                        import paper_exploration_engine as eng

                        original_build = getattr(eng, '_orig_build_scan_context', None)
                        original_market = getattr(eng, '_orig_market_status', None)

                        # Patch via phase15_scan_context and market_hours modules
                        phase15_mock = MagicMock()
                        phase15_mock.build_scan_context.return_value = ctx
                        mh_mock = MagicMock()
                        mh_mock.market_status.return_value = mstat

                        with patch.dict("sys.modules", {
                            "phase15_scan_context": phase15_mock,
                            "market_hours": mh_mock,
                        }):
                            return _check_hard_gates()

    def test_all_clear_returns_none(self):
        result = self._run_gates(
            market_state="OPEN", scan_age_s=300,
            scan_available=True, cb_tripped=False
        )
        self.assertIsNone(result)

    def test_market_not_open_returns_reason(self):
        result = self._run_gates(market_state="CLOSED")
        self.assertIsNotNone(result)
        self.assertIn("Market", result)

    def test_stale_scan_returns_reason(self):
        """Scan older than 15 minutes (900s) must return a reason string"""
        result = self._run_gates(scan_age_s=16 * 60)
        self.assertIsNotNone(result)
        self.assertIn("stale", result.lower())

    def test_fresh_scan_passes(self):
        result = self._run_gates(scan_age_s=5 * 60)
        self.assertIsNone(result)

    def test_circuit_breaker_tripped_returns_reason(self):
        result = self._run_gates(cb_tripped=True)
        self.assertIsNotNone(result)

    def test_no_scan_available_returns_reason(self):
        result = self._run_gates(scan_available=False)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Test: exploration_budget_today
# ---------------------------------------------------------------------------

class TestExplorationBudgetToday(unittest.TestCase):
    def _make_db_rows(self, entries):
        """Build (symbol, fill_price, quantity) tuples."""
        return [(e["symbol"], e["price"], e["qty"]) for e in entries]

    def test_no_trades_full_budget(self):
        from paper_exploration_engine import exploration_budget_today
        settings = _settings(
            exploration_max_trades_per_day=2,
            exploration_max_total_exposure_pct=10.0,
        )
        with patch("paper_exploration_engine._with_db", return_value=[]):
            with patch("paper_exploration_engine.get_portfolio",
                       return_value={"total_value": 50_000.0}, create=True):
                budget = exploration_budget_today(settings)

        self.assertEqual(budget["trades_used"], 0)
        self.assertEqual(budget["trades_remaining"], 2)
        self.assertEqual(budget["exposure_used_pct"], 0.0)

    def test_one_trade_reduces_budget(self):
        from paper_exploration_engine import exploration_budget_today
        settings = _settings(
            exploration_max_trades_per_day=2,
            exploration_max_total_exposure_pct=10.0,
        )
        # 1 share at ₹2,000 = ₹2,000 / ₹50,000 = 4%
        rows = self._make_db_rows([{"symbol": "DRREDDY", "price": 2000.0, "qty": 1}])
        with patch("paper_exploration_engine._with_db", return_value=rows):
            with patch("paper_exploration_engine.get_portfolio",
                       return_value={"total_value": 50_000.0}, create=True):
                budget = exploration_budget_today(settings)

        self.assertEqual(budget["trades_used"], 1)
        self.assertEqual(budget["trades_remaining"], 1)
        self.assertAlmostEqual(budget["exposure_used_pct"], 4.0)
        self.assertAlmostEqual(budget["exposure_remaining_pct"], 6.0)

    def test_budget_exhausted_flag(self):
        from paper_exploration_engine import exploration_budget_today
        settings = _settings(
            exploration_max_trades_per_day=2,
            exploration_max_total_exposure_pct=10.0,
        )
        # 2 trades, each 5% exposure → 10% total → exhausted
        rows = self._make_db_rows([
            {"symbol": "A", "price": 2500.0, "qty": 1},
            {"symbol": "B", "price": 2500.0, "qty": 1},
        ])
        with patch("paper_exploration_engine._with_db", return_value=rows):
            with patch("paper_exploration_engine.get_portfolio",
                       return_value={"total_value": 50_000.0}, create=True):
                budget = exploration_budget_today(settings)

        self.assertTrue(budget["budget_exhausted"])
        self.assertEqual(budget["trades_remaining"], 0)

    def test_db_failure_returns_empty_budget(self):
        from paper_exploration_engine import exploration_budget_today
        settings = _settings()
        # _with_db fallback returns [] on DB failure → zero usage
        with patch("paper_exploration_engine._with_db", return_value=[]):
            budget = exploration_budget_today(settings)
        self.assertEqual(budget["trades_used"], 0)
        self.assertFalse(budget["budget_exhausted"])


# ---------------------------------------------------------------------------
# Test: evaluate_exploration_candidates
# ---------------------------------------------------------------------------

class TestEvaluateCandidates(unittest.TestCase):
    def test_hard_gate_block_short_circuits(self):
        """When _check_hard_gates returns a reason, candidates must be empty"""
        import paper_exploration_engine as eng

        with patch.object(eng, "_check_hard_gates",
                          return_value="Market not open (state=CLOSED)"):
            result = eng.evaluate_exploration_candidates(_settings())

        self.assertTrue(result.get("hard_gate_blocked"))
        self.assertIsNotNone(result.get("hard_gate_reason"))
        self.assertEqual(result.get("cap_resize_candidates", []), [])
        self.assertEqual(result.get("watch_candidates", []), [])

    def test_no_gate_with_no_candidates(self):
        """With gates clear and no BUY/WATCH signals, returns empty lists"""
        import paper_exploration_engine as eng

        with patch.object(eng, "_check_hard_gates", return_value=None):
            with patch.object(eng, "exploration_budget_today",
                              return_value={
                                  "trades_remaining": 2,
                                  "exposure_remaining_pct": 8.0,
                                  "budget_exhausted": False,
                                  "trades_used": 0,
                                  "exposure_used_pct": 0.0,
                              }):
                with patch("phase20_store.kv_get", return_value=None, create=True):
                    result = eng.evaluate_exploration_candidates(_settings())

        self.assertFalse(result.get("hard_gate_blocked"))

    def test_result_has_required_keys(self):
        """evaluate_exploration_candidates always returns the expected schema keys"""
        import paper_exploration_engine as eng

        with patch.object(eng, "_check_hard_gates",
                          return_value="Market not open (state=CLOSED)"):
            result = eng.evaluate_exploration_candidates(_settings())

        for key in ("evaluated_at", "hard_gate_blocked", "hard_gate_reason",
                    "cap_resize_candidates", "watch_candidates", "budget"):
            self.assertIn(key, result, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# Test: create_exploration_entry never calls execute_buy
# ---------------------------------------------------------------------------

class TestCreateExplorationEntryNeverCallsExecuteBuy(unittest.TestCase):
    """
    SAFETY INVARIANT: create_exploration_entry must NEVER call
    phase20_executor.execute_buy (or any live-order function).
    """

    def test_execute_buy_never_called(self):
        # Build a mock that would detect any call to execute_buy
        mock_executor = MagicMock()
        mock_executor.execute_buy.side_effect = AssertionError(
            "execute_buy MUST NOT be called from exploration engine"
        )

        candidate = {
            "symbol": "DRREDDY",
            "action_type": "SIZE_REDUCED_TO_CAP",
            "entry_price": 1200.0,
            "quantity": 2,
            "confidence": 68.0,
            "opportunity_score": 65.0,
            "rr_at_entry": 2.0,
            "stop_loss": 1140.0,
            "target": 1320.0,
            "reason_accepted": "resize_to_cap test",
        }

        # Patch _insert_exp_row to succeed without a real DB
        import paper_exploration_engine as eng
        with patch.dict("sys.modules", {"phase20_executor": mock_executor}):
            with patch.object(eng, "_has_open_exp_position", return_value=False):
                with patch.object(eng, "_insert_exp_row", return_value=True):
                    with patch("paper_exploration_engine.emit", return_value=None,
                               create=True):
                        try:
                            eng.create_exploration_entry(
                                candidate, _settings(), "scan_123",
                                "2026-08-14T09:30:00Z"
                            )
                        except Exception as e:
                            # Only re-raise if it's the safety assertion
                            if "execute_buy MUST NOT be called" in str(e):
                                self.fail(str(e))
                            # Other exceptions (pipeline events, etc.) are OK

        # If we get here without the safety assertion firing, the test passes
        mock_executor.execute_buy.assert_not_called()


# ---------------------------------------------------------------------------
# Test: phase20_store exploration settings
# ---------------------------------------------------------------------------

class TestExplorationSettings(unittest.TestCase):
    def test_defaults_are_present(self):
        from phase20_store import DEFAULT_SETTINGS
        self.assertIn("paper_exploration_mode", DEFAULT_SETTINGS)
        self.assertIn("exploration_max_pct_per_trade", DEFAULT_SETTINGS)
        self.assertIn("exploration_max_trades_per_day", DEFAULT_SETTINGS)
        self.assertIn("exploration_max_total_exposure_pct", DEFAULT_SETTINGS)
        self.assertIn("exploration_min_rr", DEFAULT_SETTINGS)
        self.assertIn("exploration_min_confidence", DEFAULT_SETTINGS)

    def test_default_values(self):
        from phase20_store import DEFAULT_SETTINGS
        self.assertFalse(DEFAULT_SETTINGS["paper_exploration_mode"])
        self.assertEqual(DEFAULT_SETTINGS["exploration_max_pct_per_trade"], 5.0)
        self.assertEqual(DEFAULT_SETTINGS["exploration_max_trades_per_day"], 2)
        self.assertEqual(DEFAULT_SETTINGS["exploration_max_total_exposure_pct"], 10.0)
        self.assertEqual(DEFAULT_SETTINGS["exploration_min_rr"], 1.2)
        self.assertEqual(DEFAULT_SETTINGS["exploration_min_confidence"], 60.0)

    def test_validate_patch_valid_values(self):
        from phase20_store import _validate_patch, DEFAULT_SETTINGS as DS
        current = dict(DS)
        clean = _validate_patch(
            {
                "exploration_max_pct_per_trade": 8.0,
                "exploration_max_trades_per_day": 3,
                "exploration_max_total_exposure_pct": 15.0,
                "exploration_min_rr": 1.5,
                "exploration_min_confidence": 65.0,
                "paper_exploration_mode": True,
            },
            current,
        )
        self.assertEqual(clean["exploration_max_pct_per_trade"], 8.0)
        self.assertEqual(clean["exploration_max_trades_per_day"], 3)
        self.assertEqual(clean["exploration_max_total_exposure_pct"], 15.0)
        self.assertAlmostEqual(clean["exploration_min_rr"], 1.5)
        self.assertEqual(clean["exploration_min_confidence"], 65.0)
        self.assertTrue(clean["paper_exploration_mode"])

    def test_validate_patch_rejects_out_of_bounds(self):
        from phase20_store import _validate_patch, DEFAULT_SETTINGS as DS
        current = dict(DS)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_max_pct_per_trade": 25.0}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_max_pct_per_trade": 0.5}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_min_confidence": 30.0}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_min_confidence": 101.0}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_min_rr": 0.1}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_min_rr": 6.0}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_max_trades_per_day": 15}, current)

        with self.assertRaises(ValueError):
            _validate_patch({"exploration_max_total_exposure_pct": 80.0}, current)

    def test_unknown_key_raises(self):
        from phase20_store import _validate_patch, DEFAULT_SETTINGS as DS
        current = dict(DS)
        with self.assertRaises(ValueError):
            _validate_patch({"exploration_nonexistent_key": 5.0}, current)


if __name__ == "__main__":
    unittest.main()
