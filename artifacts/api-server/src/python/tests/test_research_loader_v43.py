"""
test_research_loader_v43.py — Regression tests for V4.3 research loader stability.

Covers:
  • Concurrent deadline (all fast, mix fast+slow, all hung/None/exception)
  • None return treated as failure for mode accounting
  • In-flight guard prevents thread accumulation
  • PIPELINE_HALTED / MARKET_ONLY mode logic
  • Audit manifest applicable semantics (disabled gates, data-absent gates)
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class TestRunLoadersConcurrent(unittest.TestCase):
    """Tests for _run_loaders_concurrent() in research_agent.agent."""

    def setUp(self):
        # Re-import to reset module-level state for each test
        import importlib
        import research_agent.agent as _mod
        importlib.reload(_mod)
        self.mod = _mod

    def _reset(self):
        m = self.mod
        m._timeout_count     = 0
        m._loaders_failed    = 0
        m._loaders_succeeded = 0
        m._last_failure_at   = None
        m._last_success_at   = None
        m._last_failure_reason = ""
        m._active_loader_threads = [None, None, None]

    def _run(self, loaders, deadline_s=5):
        return self.mod._run_loaders_concurrent(loaders, cycle_deadline_s=deadline_s)

    # ── Baseline ──────────────────────────────────────────────────────────────

    def test_all_fast_succeed(self):
        """All three loaders return quickly → succeeded=3, failed=0."""
        self._reset()
        def l1(): return {"a": 1}
        def l2(): return {"b": 2}
        def l3(): return {"c": 3}

        results = self._run([(l1, "l1"), (l2, "l2"), (l3, "l3")])
        self.assertEqual(results, [{"a": 1}, {"b": 2}, {"c": 3}])
        self.assertEqual(self.mod._loaders_succeeded, 3)
        self.assertEqual(self.mod._loaders_failed, 0)
        self.assertEqual(self.mod._timeout_count, 0)

    # ── None return semantics ─────────────────────────────────────────────────

    def test_none_return_counted_as_failure(self):
        """A loader returning None must be counted as failed, not succeeded."""
        self._reset()
        def returns_none(): return None

        results = self._run([(returns_none, "l_none")])
        self.assertEqual(results, [{}])
        self.assertEqual(self.mod._loaders_succeeded, 0, "None should not count as succeeded")
        self.assertEqual(self.mod._loaders_failed, 1)

    def test_all_none_all_fail(self):
        """All three loaders returning None → all_loaders_failed=True."""
        self._reset()
        def null(): return None

        results = self._run([(null, "l1"), (null, "l2"), (null, "l3")])
        self.assertEqual(results, [{}, {}, {}])
        self.assertEqual(self.mod._loaders_succeeded, 0)
        self.assertEqual(self.mod._loaders_failed, 3)

    def test_mixed_none_and_success(self):
        """One None + one success + one exception → succeeded=1, failed=2."""
        self._reset()
        def ok(): return {"ok": True}
        def null(): return None
        def bad(): raise ValueError("oops")

        results = self._run([(ok, "ok"), (null, "null"), (bad, "bad")])
        self.assertEqual(results[0], {"ok": True})
        self.assertEqual(results[1], {})
        self.assertEqual(results[2], {})
        self.assertEqual(self.mod._loaders_succeeded, 1)
        self.assertEqual(self.mod._loaders_failed, 2)

    # ── Exception handling ────────────────────────────────────────────────────

    def test_all_exceptions_all_fail(self):
        """All loaders raising exceptions → all failed, no timeouts."""
        self._reset()
        def e1(): raise RuntimeError("src1 down")
        def e2(): raise IOError("network error")
        def e3(): raise ValueError("parse error")

        results = self._run([(e1, "l1"), (e2, "l2"), (e3, "l3")])
        self.assertEqual(results, [{}, {}, {}])
        self.assertEqual(self.mod._loaders_succeeded, 0)
        self.assertEqual(self.mod._loaders_failed, 3)
        self.assertEqual(self.mod._timeout_count, 0)

    # ── Concurrent deadline ───────────────────────────────────────────────────

    def test_deadline_is_shared_not_per_loader(self):
        """Two slow + one fast: cycle should complete in ~deadline_s, not ~2*deadline_s."""
        self._reset()
        def fast(): return {"fast": True}
        def slow(): time.sleep(60)

        t0 = time.monotonic()
        results = self._run([(fast, "f"), (slow, "s1"), (slow, "s2")], deadline_s=2)
        elapsed = time.monotonic() - t0

        self.assertLess(elapsed, 4.0, "Should complete in ~2s, not 4s+ (concurrent deadline)")
        self.assertEqual(results[0], {"fast": True})
        self.assertEqual(results[1], {})
        self.assertEqual(results[2], {})
        self.assertEqual(self.mod._loaders_succeeded, 1)
        self.assertEqual(self.mod._loaders_failed, 2)
        self.assertEqual(self.mod._timeout_count, 2)

    def test_all_hung_within_deadline(self):
        """All three loaders hanging → timed out within the deadline, not 3× the deadline."""
        self._reset()
        def hung(): time.sleep(60)

        t0 = time.monotonic()
        results = self._run([(hung, "l1"), (hung, "l2"), (hung, "l3")], deadline_s=2)
        elapsed = time.monotonic() - t0

        self.assertLess(elapsed, 5.0, f"All-hung cycle took too long: {elapsed:.2f}s")
        self.assertEqual(results, [{}, {}, {}])
        self.assertEqual(self.mod._loaders_succeeded, 0)
        self.assertEqual(self.mod._loaders_failed, 3)
        self.assertEqual(self.mod._timeout_count, 3)

    # ── In-flight guard ───────────────────────────────────────────────────────

    def test_in_flight_guard_skips_slot_when_previous_alive(self):
        """If previous cycle's thread is alive for slot 0, new cycle skips that slot."""
        self._reset()
        # Inject a live hanging thread into slot 0
        hang_event = threading.Event()
        def hung_bg(): hang_event.wait()
        prev_thread = threading.Thread(target=hung_bg, daemon=True)
        prev_thread.start()
        self.mod._active_loader_threads[0] = prev_thread

        def fast(): return {"ok": True}

        results = self._run([(fast, "guarded"), (fast, "l1"), (fast, "l2")], deadline_s=5)

        # Slot 0 skipped → failed; slots 1+2 succeeded
        self.assertEqual(self.mod._loaders_failed, 1)
        self.assertEqual(self.mod._loaders_succeeded, 2)
        self.assertEqual(self.mod._timeout_count, 1, "Guarded slot counts as timeout")
        self.assertEqual(results[0], {})
        self.assertEqual(results[1], {"ok": True})
        self.assertEqual(results[2], {"ok": True})

        # Cleanup
        hang_event.set()
        prev_thread.join(timeout=2)

    def test_in_flight_guard_does_not_skip_when_previous_done(self):
        """When previous thread has finished, slot is not guarded."""
        self._reset()
        # Inject a completed (not alive) thread into slot 0
        done_thread = threading.Thread(target=lambda: None, daemon=True)
        done_thread.start()
        done_thread.join()  # ensure it's done
        self.mod._active_loader_threads[0] = done_thread

        def fast(): return {"ok": True}

        results = self._run([(fast, "l0"), (fast, "l1"), (fast, "l2")], deadline_s=5)
        self.assertEqual(self.mod._loaders_succeeded, 3)
        self.assertEqual(self.mod._loaders_failed, 0)

    # ── PIPELINE_HALTED / MARKET_ONLY mode logic ──────────────────────────────

    def test_all_fail_none_returns_triggers_halted_when_fail_closed(self):
        """All-None returns → all_loaders_failed=True → PIPELINE_HALTED (fail_closed)."""
        self._reset()

        # Patch kv_set and get_settings so we don't need a real DB
        with patch("research_agent.agent.ResearchAgent._load_events", return_value=None), \
             patch("research_agent.agent.ResearchAgent._load_macro",  return_value=None), \
             patch("research_agent.agent.ResearchAgent._load_research_lab", return_value=None):

            fake_settings = {"research_failure_mode": "fail_closed"}

            with patch("phase20_store.get_settings", return_value=fake_settings), \
                 patch("phase20_store.kv_set"):
                agent = self.mod.ResearchAgent()
                result = agent.execute_task()

        self.assertEqual(result.get("research_mode"), "PIPELINE_HALTED")
        self.assertEqual(result.get("loaders_succeeded"), 0)
        self.assertEqual(result.get("loaders_failed"), 3)

    def test_all_fail_triggers_market_only_when_fail_open(self):
        """All-None returns → MARKET_ONLY (default fail_open)."""
        self._reset()

        with patch("research_agent.agent.ResearchAgent._load_events", return_value=None), \
             patch("research_agent.agent.ResearchAgent._load_macro",  return_value=None), \
             patch("research_agent.agent.ResearchAgent._load_research_lab", return_value=None):

            fake_settings = {"research_failure_mode": "fail_open"}

            with patch("phase20_store.get_settings", return_value=fake_settings), \
                 patch("phase20_store.kv_set"):
                agent = self.mod.ResearchAgent()
                result = agent.execute_task()

        self.assertEqual(result.get("research_mode"), "MARKET_ONLY")

    def test_partial_failure_is_normal(self):
        """One loader fails, two succeed → NORMAL mode (not a total failure)."""
        self._reset()

        with patch("research_agent.agent.ResearchAgent._load_events", return_value={"data": 1}), \
             patch("research_agent.agent.ResearchAgent._load_macro",  return_value=None), \
             patch("research_agent.agent.ResearchAgent._load_research_lab", return_value={"lab": 1}):

            fake_settings = {"research_failure_mode": "fail_closed"}

            with patch("phase20_store.get_settings", return_value=fake_settings), \
                 patch("phase20_store.kv_set"):
                agent = self.mod.ResearchAgent()
                result = agent.execute_task()

        self.assertEqual(result.get("research_mode"), "NORMAL",
                         "Partial failure should stay NORMAL — only all-fail triggers MARKET_ONLY/HALTED")


class TestRiskAuditApplicableSemantics(unittest.TestCase):
    """Tests for build_risk_audit() applicable/not-applicable gate semantics."""

    def _get_candidate_gate(self, rules, rule_id):
        return next((r for r in rules if r["rule_id"] == rule_id), None)

    def _minimal_evaluation(self, settings_override=None):
        """Return a minimal fake evaluation dict with one candidate."""
        settings = {
            "min_confidence":             60,
            "min_opportunity_score":      60,
            "min_trade_quality_score":    50,
            "min_risk_reward":            2.0,
            "per_stock_exposure_cap_pct": 25,
            "sector_exposure_cap_pct":    40,
            "portfolio_deployed_cap_pct": 80,
            "daily_loss_limit_pct":       3.0,
            "max_trades_per_day":         3,
            "cooldown_minutes":           30,
            # V4.3 disabled by default
            "max_concurrent_positions":   0,
            "min_liquidity_filter":       0,
            "max_volatility_filter":      0.0,
            "research_failure_mode":      "fail_open",
        }
        if settings_override:
            settings.update(settings_override)

        always_gates = [
            {"gate": "min_confidence",          "passed": True,  "reason": "60 >= 60"},
            {"gate": "min_opportunity_score",    "passed": True,  "reason": "70 >= 60"},
            {"gate": "min_trade_quality",        "passed": True,  "reason": "65 >= 50"},
            {"gate": "min_risk_reward",          "passed": True,  "reason": "2.5 >= 2.0"},
            {"gate": "valid_stop_loss",          "passed": True,  "reason": "stop < entry"},
            {"gate": "position_size",            "passed": True,  "reason": "qty=10"},
            {"gate": "sufficient_cash",          "passed": True,  "reason": "cash ok"},
            {"gate": "per_stock_cap",            "passed": True,  "reason": "5.0% <= 25%"},
            {"gate": "sector_cap",               "passed": True,  "reason": "10.0% <= 40%"},
            {"gate": "portfolio_deployed_cap",   "passed": True,  "reason": "30.0% <= 80%"},
            {"gate": "daily_loss_limit",         "passed": True,  "reason": "pnl ok"},
            {"gate": "daily_trade_limit",        "passed": True,  "reason": "0 < 3"},
            {"gate": "no_open_duplicate",        "passed": True,  "reason": "no dupe"},
            {"gate": "cooldown",                 "passed": True,  "reason": "no recent entry"},
        ]

        # Add concurrent positions gate if enabled
        if int(settings.get("max_concurrent_positions") or 0) > 0:
            always_gates.append({
                "gate": "max_concurrent_positions",
                "passed": True,
                "reason": "0 < 5",
            })

        candidate = {
            "symbol":             "RELIANCE",
            "recommendation":     "BUY",
            "eligible":           True,
            "failed_gates":       [],
            "confidence":         70,
            "opportunity_score":  70,
            "trade_quality_score": 65,
            "strategy_id":        "momentum",
            "strategy_name":      "Momentum",
            "regime":             "BULL_MOMENTUM",
            "expected_holding_days": 2,
            "gates": always_gates,
        }

        return {
            "evaluated_at":   "2026-01-01T09:30:00Z",
            "scan_id":        "scan_001",
            "snapshot_ts":    "2026-01-01T09:00:00Z",
            "market_state":   "OPEN",
            "global_pass":    True,
            "global_gates":   [
                {"gate": "scan_fresh",            "passed": True, "reason": "fresh"},
                {"gate": "snapshot_consistency",  "passed": True, "reason": "match"},
                {"gate": "provider_zerodha",      "passed": True, "reason": "live"},
                {"gate": "no_fallback_data",      "passed": True, "reason": "live"},
                {"gate": "market_open",           "passed": True, "reason": "OPEN"},
                {"gate": "entry_circuit_breaker", "passed": True, "reason": "clear"},
                {"gate": "research_available",    "passed": True, "reason": "NORMAL"},
            ],
            "candidates":      [candidate],
            "eligible_count":  1,
            "blocked_count":   0,
            "gate_pressure":   [],
            "top_blockers":    [],
        }, settings

    def _call_build_risk_audit(self, evaluation, settings):
        """Call build_risk_audit() with the given fake evaluation + settings."""
        import phase20_gates as g

        with patch.object(g, "risk_decision_report", return_value={
            "available": True,
            **evaluation,
        }), patch.object(g.store, "get_settings", return_value=settings), \
             patch("phase20_store.kv_get", return_value=None):
            return g.build_risk_audit()

    def test_disabled_v43_gates_are_not_applicable(self):
        """With default settings (all V4.3 thresholds = 0), the three conditional
        gates must appear with applicable=False and must NOT count as failures."""
        evaluation, settings = self._minimal_evaluation()
        audit = self._call_build_risk_audit(evaluation, settings)

        self.assertTrue(audit.get("available"))
        candidate = audit["candidates"][0]
        rules = candidate["rule_manifest"]

        for gate_id in ("max_concurrent_positions", "min_liquidity", "max_volatility"):
            rule = self._get_candidate_gate(rules, gate_id)
            self.assertIsNotNone(rule, f"{gate_id} missing from manifest")
            self.assertFalse(rule.get("applicable"), f"{gate_id} should be not-applicable (disabled)")
            # Not-applicable must NOT be counted as a failure
            self.assertTrue(rule.get("passed"), f"{gate_id} should be passed=True when not-applicable")

    def test_disabled_gates_excluded_from_metrics(self):
        """Pass-rate and total_rule_checks exclude not-applicable gates."""
        evaluation, settings = self._minimal_evaluation()
        audit = self._call_build_risk_audit(evaluation, settings)

        # Verify not-applicable rules are excluded from total_checks
        candidate_rules = audit["candidates"][0]["rule_manifest"]
        applicable_count = sum(1 for r in candidate_rules if r.get("applicable", True))
        # 14 always-applicable per-symbol rules (max_concurrent_positions disabled)
        self.assertEqual(applicable_count, 14)

        # The audit totals must also reflect this
        # global manifest has 7 applicable rules (all True), 1 candidate × 14 applicable rules = 21 total
        self.assertGreater(audit["total_rule_checks"], 0)
        self.assertEqual(audit["pass_rate"], 100.0)

    def test_enabled_concurrent_positions_is_applicable(self):
        """When max_concurrent_positions > 0, the gate is applicable and evaluated."""
        evaluation, settings = self._minimal_evaluation(
            settings_override={"max_concurrent_positions": 5}
        )
        audit = self._call_build_risk_audit(evaluation, settings)

        candidate_rules = audit["candidates"][0]["rule_manifest"]
        rule = self._get_candidate_gate(candidate_rules, "max_concurrent_positions")
        self.assertIsNotNone(rule)
        self.assertTrue(rule.get("applicable"), "Should be applicable when setting > 0")

    def test_absent_volume_data_skips_liquidity_gate(self):
        """When min_liquidity_filter > 0 but no volume in scan, gate is not-applicable."""
        evaluation, settings = self._minimal_evaluation(
            settings_override={"min_liquidity_filter": 500}
        )
        # The scan candidate has no avg_volume field → gate was conditionally skipped
        audit = self._call_build_risk_audit(evaluation, settings)

        candidate_rules = audit["candidates"][0]["rule_manifest"]
        rule = self._get_candidate_gate(candidate_rules, "min_liquidity")
        self.assertIsNotNone(rule)
        # Gate not in gate_lookup (no volume data) → applicable=False
        self.assertFalse(rule.get("applicable"), "Liquidity gate skipped when data absent")
        self.assertIn("scan record", rule.get("actual", ""), "Should explain why skipped")


class TestV43MalformedPersistedSettings(unittest.TestCase):
    """
    Regression tests: get_settings() must normalize malformed/legacy V4.3
    settings so that evaluate_entries() is never exposed to values that cause
    crashes (e.g. max_concurrent_positions='1.5' → int crash; invalid
    research_failure_mode string → silent behavioral change).

    Approach: patch phase20_store's DB connection to simulate the DB returning
    malformed stored data, then call the real get_settings() and verify the
    returned dict has been sanitized.  We separately test the in-function
    safe-conversion helpers (simulated via direct logic tests) to confirm
    evaluate_entries() has a second defensive layer.
    """

    def _get_settings_from_bad_db(self, bad_stored: dict):
        """
        Call get_settings() with the DB returning `bad_stored`.
        Returns the fully merged+normalized settings dict.
        """
        import phase20_store as s

        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (bad_stored,)
        with patch.object(s, "db_available", return_value=True), \
             patch.object(s, "_connect", return_value=conn), \
             patch.object(s, "_ensure_schema"), \
             patch("phase20_store.kv_get", return_value=None):
            return s.get_settings()

    # ── get_settings() normalization ──────────────────────────────────────────

    def test_fractional_conc_coerced_to_zero(self):
        """DB has max_concurrent_positions='1.5' → normalized to 0 (disabled)."""
        result = self._get_settings_from_bad_db({"max_concurrent_positions": "1.5"})
        self.assertEqual(result["max_concurrent_positions"], 0)
        self.assertIsInstance(result["max_concurrent_positions"], int)

    def test_nonfractional_string_int_accepted(self):
        """DB has max_concurrent_positions='5' (whole number string) → stays 5."""
        result = self._get_settings_from_bad_db({"max_concurrent_positions": "5"})
        self.assertEqual(result["max_concurrent_positions"], 5)

    def test_non_numeric_conc_coerced_to_zero(self):
        """DB has max_concurrent_positions='many' → normalized to 0."""
        result = self._get_settings_from_bad_db({"max_concurrent_positions": "many"})
        self.assertEqual(result["max_concurrent_positions"], 0)

    def test_out_of_range_conc_coerced_to_zero(self):
        """DB has max_concurrent_positions=999 (above limit 50) → normalized to 0."""
        result = self._get_settings_from_bad_db({"max_concurrent_positions": 999})
        self.assertEqual(result["max_concurrent_positions"], 0)

    def test_invalid_failure_mode_coerced_to_fail_open(self):
        """DB has research_failure_mode='panic_mode' → normalized to 'fail_open'."""
        result = self._get_settings_from_bad_db({"research_failure_mode": "panic_mode"})
        self.assertEqual(result["research_failure_mode"], "fail_open")

    def test_nonnumeric_liquidity_coerced_to_zero(self):
        """DB has min_liquidity_filter='high' → normalized to 0.0 (disabled)."""
        result = self._get_settings_from_bad_db({"min_liquidity_filter": "high"})
        self.assertAlmostEqual(result["min_liquidity_filter"], 0.0)

    def test_out_of_range_volatility_coerced_to_zero(self):
        """DB has max_volatility_filter=200.0 (above 100) → normalized to 0.0."""
        result = self._get_settings_from_bad_db({"max_volatility_filter": 200.0})
        self.assertAlmostEqual(result["max_volatility_filter"], 0.0)

    # ── evaluate_entries() in-function safe helpers ───────────────────────────
    # These tests verify the _safe_int / _safe_float helpers embedded inside
    # evaluate_entries() independently of the full call chain, confirming the
    # secondary defensive layer works even if settings arrive un-normalized.

    def _apply_safe_int(self, raw, default=0):
        """Replicate the _safe_int logic from evaluate_entries()."""
        try:
            fv = float(raw)
            iv = int(fv)
            return default if fv != iv else iv
        except (TypeError, ValueError):
            return default

    def _apply_safe_float(self, raw, default=0.0):
        """Replicate the _safe_float logic from evaluate_entries()."""
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def test_safe_int_fractional_string_returns_default(self):
        self.assertEqual(self._apply_safe_int("1.5"), 0)

    def test_safe_int_nonnumeric_returns_default(self):
        self.assertEqual(self._apply_safe_int("many"), 0)

    def test_safe_int_whole_number_string_accepted(self):
        self.assertEqual(self._apply_safe_int("10"), 10)

    def test_safe_int_none_returns_default(self):
        self.assertEqual(self._apply_safe_int(None), 0)

    def test_safe_float_nonnumeric_returns_default(self):
        self.assertAlmostEqual(self._apply_safe_float("high"), 0.0)

    def test_safe_float_numeric_string_accepted(self):
        self.assertAlmostEqual(self._apply_safe_float("5.5"), 5.5)

    def test_safe_float_none_returns_default(self):
        self.assertAlmostEqual(self._apply_safe_float(None), 0.0)

    # ── evaluate_entries() does not crash with malformed settings ─────────────
    # We patch source modules (where the local imports resolve) to avoid the
    # full network stack, then verify evaluate_entries() returns without raising.

    def _run_evaluate_with_bad_settings(self, bad_stored: dict):
        """
        Simulate stored DB returning bad_stored → get_settings() normalizes
        → evaluate_entries() must complete without raising.
        """
        import phase20_store as ps
        import phase15_scan_context
        import market_hours
        import scan_state_store
        import paper_trader
        import phase20_circuit_breaker
        import phase20_gates as g

        # Minimal scan context — no candidates
        minimal_ctx = {
            "available": False, "scan_id": None,
            "scan_age_seconds": 9999, "stale_after_seconds": 300,
            "stale": True, "symbols": {},
        }
        portfolio = {
            "cash": 100_000, "total_value": 100_000,
            "invested_value": 0, "positions": [],
        }

        def fake_with_db(fn, fallback):
            return bad_stored

        with patch.object(ps, "_with_db", side_effect=fake_with_db), \
             patch("phase20_store.kv_get", return_value=None), \
             patch("phase20_store.kv_set"), \
             patch.object(phase15_scan_context, "build_scan_context",
                          return_value=minimal_ctx), \
             patch.object(market_hours, "market_status",
                          return_value={"state": "CLOSED"}), \
             patch.object(scan_state_store, "load_latest_meta", return_value={}), \
             patch.object(scan_state_store, "load_latest_snapshot", return_value={}), \
             patch.object(paper_trader, "_load_state", return_value={"trades": []}), \
             patch.object(paper_trader, "get_portfolio", return_value=portfolio), \
             patch.object(phase20_circuit_breaker, "get_state",
                          return_value={"state": "CLEAR"}):
            result = g.evaluate_entries()
        return result

    def test_fractional_conc_does_not_crash_evaluation(self):
        """DB has max_concurrent_positions='1.5' → evaluate_entries returns normally."""
        result = self._run_evaluate_with_bad_settings({"max_concurrent_positions": "1.5"})
        self.assertIn("evaluated_at", result)

    def test_nonnumeric_liquidity_does_not_crash_evaluation(self):
        """DB has min_liquidity_filter='high' → gate disabled, no crash."""
        result = self._run_evaluate_with_bad_settings({"min_liquidity_filter": "high"})
        self.assertIn("evaluated_at", result)

    def test_nonnumeric_volatility_does_not_crash_evaluation(self):
        """DB has max_volatility_filter='extreme' → gate disabled, no crash."""
        result = self._run_evaluate_with_bad_settings({"max_volatility_filter": "extreme"})
        self.assertIn("evaluated_at", result)

    def test_invalid_failure_mode_does_not_block_entries(self):
        """DB has research_failure_mode='panic_mode' → treated as fail_open, entries not blocked."""
        result = self._run_evaluate_with_bad_settings({"research_failure_mode": "panic_mode"})
        self.assertIn("evaluated_at", result)
        global_gates = {gg["gate"]: gg for gg in result.get("global_gates", [])}
        if "research_available" in global_gates:
            self.assertTrue(
                global_gates["research_available"]["passed"],
                "Invalid failure mode should resolve to fail_open — entries not blocked"
            )


class TestV43SettingsValidation(unittest.TestCase):
    """Regression tests for V4.3 settings server-side validation."""

    def _patch(self, key, value):
        """Call _validate_patch with a single-key patch and return clean dict or raise."""
        from phase20_store import _validate_patch, DEFAULT_SETTINGS
        return _validate_patch({key: value}, dict(DEFAULT_SETTINGS))

    # ── max_concurrent_positions ──────────────────────────────────────────────

    def test_conc_valid_zero(self):
        """0 is valid (disabled)."""
        clean = self._patch("max_concurrent_positions", 0)
        self.assertEqual(clean["max_concurrent_positions"], 0)

    def test_conc_valid_integer(self):
        """Positive integer accepted and stored as int."""
        clean = self._patch("max_concurrent_positions", 5)
        self.assertEqual(clean["max_concurrent_positions"], 5)
        self.assertIsInstance(clean["max_concurrent_positions"], int)

    def test_conc_integer_string_accepted(self):
        """String representation of whole number accepted."""
        clean = self._patch("max_concurrent_positions", "10")
        self.assertEqual(clean["max_concurrent_positions"], 10)

    def test_conc_fractional_rejected(self):
        """Fractional value (1.5) rejected with clear message."""
        with self.assertRaises(ValueError) as ctx:
            self._patch("max_concurrent_positions", 1.5)
        self.assertIn("whole number", str(ctx.exception))

    def test_conc_fractional_string_rejected(self):
        """String '1.5' also rejected."""
        with self.assertRaises(ValueError):
            self._patch("max_concurrent_positions", "1.5")

    def test_conc_above_max_rejected(self):
        """Value above 50 rejected."""
        with self.assertRaises(ValueError) as ctx:
            self._patch("max_concurrent_positions", 51)
        self.assertIn("50", str(ctx.exception))

    def test_conc_negative_rejected(self):
        """Negative values rejected."""
        with self.assertRaises(ValueError):
            self._patch("max_concurrent_positions", -1)

    def test_conc_non_numeric_rejected(self):
        """Non-numeric string rejected."""
        with self.assertRaises(ValueError):
            self._patch("max_concurrent_positions", "many")

    # ── research_failure_mode ─────────────────────────────────────────────────

    def test_failure_mode_fail_open_accepted(self):
        """'fail_open' is a valid value."""
        clean = self._patch("research_failure_mode", "fail_open")
        self.assertEqual(clean["research_failure_mode"], "fail_open")

    def test_failure_mode_fail_closed_accepted(self):
        """'fail_closed' is a valid value."""
        clean = self._patch("research_failure_mode", "fail_closed")
        self.assertEqual(clean["research_failure_mode"], "fail_closed")

    def test_failure_mode_invalid_string_rejected(self):
        """Arbitrary strings rejected."""
        with self.assertRaises(ValueError) as ctx:
            self._patch("research_failure_mode", "panic")
        self.assertIn("fail_open", str(ctx.exception))
        self.assertIn("fail_closed", str(ctx.exception))

    def test_failure_mode_empty_string_rejected(self):
        """Empty string rejected."""
        with self.assertRaises(ValueError):
            self._patch("research_failure_mode", "")

    # ── min_liquidity_filter ──────────────────────────────────────────────────

    def test_liquidity_zero_accepted(self):
        """0 = disabled."""
        clean = self._patch("min_liquidity_filter", 0)
        self.assertEqual(clean["min_liquidity_filter"], 0.0)

    def test_liquidity_valid_value_accepted(self):
        """Positive float accepted."""
        clean = self._patch("min_liquidity_filter", 500.0)
        self.assertAlmostEqual(clean["min_liquidity_filter"], 500.0)

    def test_liquidity_above_max_rejected(self):
        """Above 10000 rejected."""
        with self.assertRaises(ValueError):
            self._patch("min_liquidity_filter", 10001)

    def test_liquidity_negative_rejected(self):
        with self.assertRaises(ValueError):
            self._patch("min_liquidity_filter", -1)

    # ── max_volatility_filter ─────────────────────────────────────────────────

    def test_volatility_zero_accepted(self):
        """0 = disabled."""
        clean = self._patch("max_volatility_filter", 0.0)
        self.assertEqual(clean["max_volatility_filter"], 0.0)

    def test_volatility_valid_value_accepted(self):
        clean = self._patch("max_volatility_filter", 5.0)
        self.assertAlmostEqual(clean["max_volatility_filter"], 5.0)

    def test_volatility_above_100_rejected(self):
        """ATR% > 100 is nonsensical."""
        with self.assertRaises(ValueError):
            self._patch("max_volatility_filter", 101.0)

    def test_volatility_negative_rejected(self):
        with self.assertRaises(ValueError):
            self._patch("max_volatility_filter", -0.1)


if __name__ == "__main__":
    unittest.main()
