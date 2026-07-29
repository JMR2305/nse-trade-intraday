"""
test_live_readiness.py — Phase 6.5
Comprehensive unit tests for the Live Readiness & Operational Validation module.

Tests cover:
  - Feature flag (5)
  - Readiness models: scoring, grade, go/no-go (5)
  - System health checker (5)
  - Data quality checker (7)
  - Recovery checker (4)
  - Security checker (6)
  - Config checker (5)
  - API health checker (4)
  - Shared services API (7)
  - Export (2)
"""
import sys, os, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    trade_id="T001", symbol="RELIANCE", strategy="MOMENTUM",
    sector="Energy", regime="TRENDING_BULLISH",
    entry=2500.0, exit_p=2550.0, qty=10,
    pnl=500.0, pnl_pct=0.02,
    exit_reason="target", ai_conf=0.75, ai_rec="BUY",
    timestamp="2024-01-15T10:30:00",
):
    return {
        "trade_id": trade_id, "timestamp": timestamp,
        "symbol": symbol, "strategy": strategy,
        "market_regime": regime, "sector": sector,
        "entry_price": entry, "exit_price": exit_p,
        "quantity": qty, "holding_time_minutes": 45.0,
        "pnl": pnl, "pnl_pct": pnl_pct,
        "execution_quality_score": 85.0,
        "ai_confidence": ai_conf, "ai_recommendation": ai_rec,
        "exit_reason": exit_reason,
    }


def _small_set():
    return [_make_record(trade_id=f"T{i:03d}", pnl=500 if i % 2 == 0 else -300) for i in range(5)]


def _large_set(n=30):
    from datetime import datetime, timedelta
    base = datetime(2024, 1, 10)
    return [
        _make_record(
            trade_id=f"T{i:03d}",
            symbol=f"SYM{i % 5}",
            entry=1000.0 + i * 5,
            exit_p=1000.0 + i * 5 + (20 if i % 3 != 0 else -10),
            pnl=200.0 if i % 3 != 0 else -100.0,
            pnl_pct=0.02 if i % 3 != 0 else -0.01,
            exit_reason="target" if i % 3 != 0 else "stop_loss",
            timestamp=(base + timedelta(days=i)).isoformat(),
        )
        for i in range(n)
    ]


# ===========================================================================
# 1. Feature flag (5 tests)
# ===========================================================================

class TestFeatureFlag(unittest.TestCase):

    def setUp(self):
        os.environ.pop("READINESS_VALIDATION_ENABLED", None)

    def tearDown(self):
        os.environ.pop("READINESS_VALIDATION_ENABLED", None)

    def test_disabled_by_default(self):
        from live_readiness.readiness_models import is_enabled
        self.assertFalse(is_enabled())

    def test_enabled_when_set(self):
        os.environ["READINESS_VALIDATION_ENABLED"] = "true"
        from live_readiness.readiness_models import is_enabled
        self.assertTrue(is_enabled())

    def test_summary_disabled(self):
        from live_readiness.shared_services import get_summary
        self.assertEqual(get_summary()["status"], "DISABLED")

    def test_report_disabled(self):
        from live_readiness.shared_services import get_report
        self.assertEqual(get_report()["status"], "DISABLED")

    def test_all_endpoints_disabled(self):
        from live_readiness.shared_services import (
            get_summary, get_system, get_data, get_recovery, get_security, get_report
        )
        for fn in [get_summary, get_system, get_data, get_recovery, get_security, get_report]:
            self.assertEqual(fn()["status"], "DISABLED")


# ===========================================================================
# 2. Readiness models: scoring, grade, go/no-go (5 tests)
# ===========================================================================

class TestReadinessModels(unittest.TestCase):

    def test_category_score_all_pass(self):
        from live_readiness.readiness_models import ReadinessCheck, compute_category_score, PASS
        checks = [
            ReadinessCheck("c1", "C1", PASS, True, "ok", "SystemHealth"),
            ReadinessCheck("c2", "C2", PASS, False, "ok", "SystemHealth"),
        ]
        self.assertEqual(compute_category_score(checks), 100.0)

    def test_category_score_mixed(self):
        from live_readiness.readiness_models import ReadinessCheck, compute_category_score, PASS, WARN, FAIL
        checks = [
            ReadinessCheck("c1", "C1", PASS, True, "ok", "SystemHealth"),
            ReadinessCheck("c2", "C2", WARN, False, "warn", "SystemHealth"),
            ReadinessCheck("c3", "C3", FAIL, False, "fail", "SystemHealth"),
        ]
        # (1.0 + 0.5 + 0.0) / 3 * 100 = 50
        self.assertAlmostEqual(compute_category_score(checks), 50.0)

    def test_health_grade_thresholds(self):
        from live_readiness.readiness_models import health_grade
        self.assertEqual(health_grade(95), "A+")
        self.assertEqual(health_grade(82), "A")
        self.assertEqual(health_grade(70), "B")
        self.assertEqual(health_grade(55), "C")
        self.assertEqual(health_grade(30), "D")

    def test_go_no_go_ready(self):
        from live_readiness.readiness_models import go_no_go, READY
        result = go_no_go(85.0, 0)
        self.assertEqual(result, READY)

    def test_go_no_go_not_ready_on_critical(self):
        from live_readiness.readiness_models import go_no_go, NOT_READY
        result = go_no_go(90.0, 1)  # high score but critical failure
        self.assertEqual(result, NOT_READY)


# ===========================================================================
# 3. System health checker (5 tests)
# ===========================================================================

class TestSystemHealthChecker(unittest.TestCase):

    def test_returns_dict_with_checks(self):
        from live_readiness.system_health_checker import check_system_health
        r = check_system_health()
        self.assertIn("checks", r)
        self.assertIsInstance(r["checks"], list)

    def test_score_bounded(self):
        from live_readiness.system_health_checker import check_system_health
        r = check_system_health()
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_latency_ms_non_negative(self):
        from live_readiness.system_health_checker import check_system_health
        r = check_system_health()
        self.assertGreaterEqual(r["latency_ms"], 0.0)

    def test_check_counts_consistent(self):
        from live_readiness.system_health_checker import check_system_health
        r = check_system_health()
        self.assertEqual(r["total_checks"], len(r["checks"]))
        self.assertEqual(r["passed"] + r["warnings"] + r["failures"], r["total_checks"])

    def test_every_check_has_required_keys(self):
        from live_readiness.system_health_checker import check_system_health
        r = check_system_health()
        for c in r["checks"]:
            for key in ("name", "label", "status", "required", "detail", "category"):
                self.assertIn(key, c)


# ===========================================================================
# 4. Data quality checker (7 tests)
# ===========================================================================

class TestDataQualityChecker(unittest.TestCase):

    def _run_with_records(self, records):
        import live_readiness.data_quality_checker as dqc
        original = dqc._get_records
        dqc._get_records = lambda: records
        try:
            return dqc.check_data_quality()
        finally:
            dqc._get_records = original

    def test_empty_records_all_warn(self):
        r = self._run_with_records([])
        self.assertEqual(r["total_records"], 0)
        # Most checks should be WARN on empty
        statuses = [c["status"] for c in r["checks"]]
        self.assertIn("WARN", statuses)

    def test_score_bounded(self):
        r = self._run_with_records(_large_set())
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_no_duplicates_in_clean_data(self):
        r = self._run_with_records(_large_set())
        dup_check = next(c for c in r["checks"] if c["name"] == "duplicate_trades")
        self.assertEqual(dup_check["status"], "PASS")

    def test_duplicate_detected(self):
        records = _large_set()
        records.append(_make_record(trade_id="T000"))  # duplicate of T000
        r = self._run_with_records(records)
        dup_check = next(c for c in r["checks"] if c["name"] == "duplicate_trades")
        self.assertEqual(dup_check["status"], "WARN")

    def test_fifo_consistency_valid_data(self):
        r = self._run_with_records(_large_set())
        fifo_check = next(c for c in r["checks"] if c["name"] == "fifo_consistency")
        self.assertEqual(fifo_check["status"], "PASS")

    def test_required_fields_present(self):
        r = self._run_with_records(_large_set())
        field_check = next(c for c in r["checks"] if c["name"] == "required_fields")
        self.assertEqual(field_check["status"], "PASS")

    def test_check_counts_consistent(self):
        r = self._run_with_records(_small_set())
        self.assertEqual(r["passed"] + r["warnings"] + r["failures"], r["total_checks"])


# ===========================================================================
# 5. Recovery checker (4 tests)
# ===========================================================================

class TestRecoveryChecker(unittest.TestCase):

    def test_returns_expected_keys(self):
        from live_readiness.recovery_checker import check_recovery
        r = check_recovery()
        for key in ("checks", "score", "recovery_health"):
            self.assertIn(key, r)

    def test_score_bounded(self):
        from live_readiness.recovery_checker import check_recovery
        r = check_recovery()
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_recovery_health_valid_value(self):
        from live_readiness.recovery_checker import check_recovery
        r = check_recovery()
        self.assertIn(r["recovery_health"], ("STRONG", "ADEQUATE", "WEAK"))

    def test_check_counts_consistent(self):
        from live_readiness.recovery_checker import check_recovery
        r = check_recovery()
        self.assertEqual(r["passed"] + r["warnings"] + r["failures"], r["total_checks"])


# ===========================================================================
# 6. Security checker (6 tests)
# ===========================================================================

class TestSecurityChecker(unittest.TestCase):

    def tearDown(self):
        for k in ("AUTO_EXECUTION_ENABLED", "LIVE_ORDERS_ENABLED", "DEBUG"):
            os.environ.pop(k, None)

    def test_advisory_only_flags_pass_by_default(self):
        from live_readiness.security_checker import check_security
        r = check_security()
        flag_check = next(c for c in r["checks"] if c["name"] == "advisory_only_flags")
        self.assertEqual(flag_check["status"], "PASS")

    def test_advisory_only_fails_when_auto_exec_set(self):
        os.environ["AUTO_EXECUTION_ENABLED"] = "true"
        from live_readiness.security_checker import check_security
        r = check_security()
        flag_check = next(c for c in r["checks"] if c["name"] == "advisory_only_flags")
        self.assertEqual(flag_check["status"], "FAIL")

    def test_debug_mode_warn_when_enabled(self):
        os.environ["DEBUG"] = "true"
        from live_readiness.security_checker import check_security
        r = check_security()
        debug_check = next(c for c in r["checks"] if c["name"] == "debug_mode_disabled")
        self.assertEqual(debug_check["status"], "WARN")

    def test_score_bounded(self):
        from live_readiness.security_checker import check_security
        r = check_security()
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_security_level_valid_value(self):
        from live_readiness.security_checker import check_security
        r = check_security()
        self.assertIn(r["security_level"], ("STRONG", "ADEQUATE", "WEAK"))

    def test_check_counts_consistent(self):
        from live_readiness.security_checker import check_security
        r = check_security()
        self.assertEqual(r["passed"] + r["warnings"] + r["failures"], r["total_checks"])

    def test_runtime_managed_keys_excluded_from_weak_value_check(self):
        """PGPASSWORD and other Replit-managed keys must never trigger a false-positive FAIL,
        even when their value happens to look like a weak placeholder string."""
        import live_readiness.security_checker as sc
        # Temporarily inject a value that would trip the weak-value check on any non-managed key
        original = os.environ.get("PGPASSWORD")
        try:
            os.environ["PGPASSWORD"] = "password"   # worst-case weak value
            r = sc.check_security()
            weak_check = next(c for c in r["checks"] if c["name"] == "secrets_not_exposed")
            # Must still PASS — PGPASSWORD is runtime-managed and excluded
            self.assertEqual(weak_check["status"], "PASS",
                msg="PGPASSWORD with value 'password' must not trigger secrets_not_exposed FAIL")
        finally:
            if original is None:
                os.environ.pop("PGPASSWORD", None)
            else:
                os.environ["PGPASSWORD"] = original

    def test_non_managed_weak_key_still_fails(self):
        """A non-managed env var with a weak value MUST still be caught."""
        import live_readiness.security_checker as sc
        original = os.environ.get("APP_SECRET_KEY")
        try:
            os.environ["APP_SECRET_KEY"] = "secret"  # weak placeholder
            r = sc.check_security()
            weak_check = next(c for c in r["checks"] if c["name"] == "secrets_not_exposed")
            self.assertEqual(weak_check["status"], "FAIL",
                msg="A non-managed key with value 'secret' must trigger secrets_not_exposed FAIL")
        finally:
            if original is None:
                os.environ.pop("APP_SECRET_KEY", None)
            else:
                os.environ["APP_SECRET_KEY"] = original


# ===========================================================================
# 7. Config checker (5 tests)
# ===========================================================================

class TestConfigChecker(unittest.TestCase):

    def test_returns_feature_flags(self):
        from live_readiness.config_checker import check_config
        r = check_config()
        self.assertIn("feature_flags", r)
        self.assertIsInstance(r["feature_flags"], dict)

    def test_feature_flags_boolean_values(self):
        from live_readiness.config_checker import check_config
        r = check_config()
        for k, v in r["feature_flags"].items():
            self.assertIsInstance(v, bool)

    def test_config_checksum_is_string(self):
        from live_readiness.config_checker import check_config
        r = check_config()
        self.assertIsInstance(r["config_checksum"], str)
        self.assertEqual(len(r["config_checksum"]), 8)  # MD5 truncated to 8 chars

    def test_score_bounded(self):
        from live_readiness.config_checker import check_config
        r = check_config()
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_check_counts_consistent(self):
        from live_readiness.config_checker import check_config
        r = check_config()
        self.assertEqual(r["passed"] + r["warnings"] + r["failures"], r["total_checks"])


# ===========================================================================
# 8. API health checker (4 tests)
# ===========================================================================

class TestAPIHealthChecker(unittest.TestCase):

    def test_returns_expected_keys(self):
        from live_readiness.api_health_checker import check_api_health
        r = check_api_health()
        for key in ("checks", "score", "error_rate"):
            self.assertIn(key, r)

    def test_error_rate_bounded(self):
        from live_readiness.api_health_checker import check_api_health
        r = check_api_health()
        self.assertGreaterEqual(r["error_rate"], 0.0)
        self.assertLessEqual(r["error_rate"], 1.0)

    def test_score_bounded(self):
        from live_readiness.api_health_checker import check_api_health
        r = check_api_health()
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_checks_have_required_keys(self):
        from live_readiness.api_health_checker import check_api_health
        r = check_api_health()
        for c in r["checks"]:
            for key in ("name", "label", "status", "category"):
                self.assertIn(key, c)


# ===========================================================================
# 9. Shared services API (7 tests)
# ===========================================================================

class TestSharedServicesAPI(unittest.TestCase):

    def setUp(self):
        os.environ["READINESS_VALIDATION_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("READINESS_VALIDATION_ENABLED", None)

    def test_summary_returns_enabled(self):
        from live_readiness.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")

    def test_summary_has_verdict(self):
        from live_readiness.shared_services import get_summary
        r = get_summary()
        self.assertIn("verdict", r)
        from live_readiness.readiness_models import READY, READY_WARN, NOT_READY
        self.assertIn(r["verdict"], (READY, READY_WARN, NOT_READY))

    def test_summary_score_bounded(self):
        from live_readiness.shared_services import get_summary
        r = get_summary()
        self.assertGreaterEqual(r["readiness_score"], 0.0)
        self.assertLessEqual(r["readiness_score"], 100.0)

    def test_system_endpoint_has_broker(self):
        from live_readiness.shared_services import get_system
        r = get_system()
        self.assertIn("broker_readiness", r)
        self.assertTrue(r["broker_readiness"]["paper_trading_only"])
        self.assertTrue(r["broker_readiness"]["live_orders_never_placed"])

    def test_data_endpoint_has_both_sections(self):
        from live_readiness.shared_services import get_data
        r = get_data()
        self.assertIn("data_quality", r)
        self.assertIn("api_health", r)

    def test_report_has_cicd_hook(self):
        from live_readiness.shared_services import get_report
        r = get_report()
        self.assertIn("cicd_integration", r)
        self.assertFalse(r["cicd_integration"]["enabled"])

    def test_advisory_only_always_true(self):
        from live_readiness.shared_services import get_summary, get_report
        for fn in [get_summary, get_report]:
            r = fn()
            self.assertTrue(r.get("advisory_only"))


# ===========================================================================
# 10. Export (2 tests)
# ===========================================================================

class TestExport(unittest.TestCase):

    def setUp(self):
        os.environ["READINESS_VALIDATION_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("READINESS_VALIDATION_ENABLED", None)

    def test_export_csv_returns_string(self):
        from live_readiness.shared_services import export_summary_csv
        csv_data = export_summary_csv()
        self.assertIsInstance(csv_data, str)

    def test_export_json_is_valid_json(self):
        import json
        from live_readiness.shared_services import export_full_json
        json_data = export_full_json()
        self.assertIsInstance(json_data, str)
        parsed = json.loads(json_data)
        self.assertIsInstance(parsed, dict)


if __name__ == "__main__":
    unittest.main()
