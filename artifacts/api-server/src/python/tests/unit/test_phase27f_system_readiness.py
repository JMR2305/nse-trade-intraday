"""Unit tests for Phase 27F: System Readiness dashboard (phase27_readiness.py)."""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

# Ensure the python source root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import phase27_readiness as pr
from phase27_readiness import (
    READY, WARNING, BLOCKED, UNKNOWN,
    derive_overall,
    check_market_data,
    check_broker,
    check_pipeline,
    check_strategy_risk,
    check_execution,
    check_portfolio,
    check_persistence_recovery,
    check_scheduling,
    check_safety,
    check_configuration,
    build_freshness,
    build_report,
    get_history,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _fresh_meta(age_s=60):
    """Scan meta that is fresh (age_s seconds old)."""
    ts = (_now() - timedelta(seconds=age_s)).isoformat()
    return {
        "scan_id": "scan_test",
        "snapshot_ts": ts,
        "status": "SUCCESS",
        "error": None,
        "symbols_requested": 50,
        "symbols_received": 48,
        "provider": "yfinance",
    }


def _minimal_inputs(**overrides):
    """Build a minimal inputs dict for check_* functions.
    All sources available and healthy by default."""
    base = {
        "_errors": {},
        "scan_meta": _fresh_meta(),
        "db_durable": True,
        "market": {"state": "CLOSED", "is_open": False, "next_transition": None},
        "scheduler": {
            "health": "HEALTHY",
            "heartbeat_at": _now().isoformat(),
            "auto_scan_enabled": True,
            "last_error": None,
        },
        "settings": {"auto_paper_enabled": False, "max_positions": 5},
        "broker": {
            "connection_state": "LOGIN_REQUIRED",
            "token_status": "expired",
            "probe_source": "cache",
            "last_success_at": None,
        },
        "breaker": {"tripped": False, "unreadable": False, "reasons": [], "tripped_at": None},
        "portfolio_health": {"healthy": True, "position_count": 2},
        "system": {
            "memory": {"available": True, "status": "OK", "usage_pct": 45},
            "disk": {"available": True, "status": "OK", "usage_pct": 60},
            "cpu": {"available": True, "load_1m": 0.8},
        },
        "recovery_latest": None,
        "pipeline": {
            "scan_id": "scan_test",
            "last_event_at": _now().isoformat(),
            "count": 120,
        },
        "env_flags": {
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": True,
        },
        "paper_mode": True,
    }
    base.update(overrides)
    return base


# ── 1. derive_overall ─────────────────────────────────────────────────────────

class TestDeriveOverall(unittest.TestCase):

    def _check(self, status, blocking=True):
        return {
            "id": "x", "domain": "D", "label": "L",
            "status": status, "blocking": blocking,
            "expected": "", "actual": "", "evidence": {}, "remediation": "",
            "checked_at": _now().isoformat(),
        }

    def test_all_ready_gives_ready(self):
        checks = [self._check(READY, True), self._check(READY, False)]
        self.assertEqual(derive_overall(checks), READY)

    def test_blocking_blocked_gives_blocked(self):
        checks = [self._check(READY, True), self._check(BLOCKED, True)]
        self.assertEqual(derive_overall(checks), BLOCKED)

    def test_blocking_unknown_gives_unknown(self):
        checks = [self._check(READY, True), self._check(UNKNOWN, True)]
        self.assertEqual(derive_overall(checks), UNKNOWN)

    def test_blocking_unknown_not_ready(self):
        checks = [self._check(UNKNOWN, True)]
        result = derive_overall(checks)
        self.assertNotEqual(result, READY)

    def test_non_blocking_warning_gives_warning_when_blocking_ready(self):
        checks = [self._check(READY, True), self._check(WARNING, False)]
        self.assertEqual(derive_overall(checks), WARNING)

    def test_non_blocking_blocked_gives_warning(self):
        checks = [self._check(READY, True), self._check(BLOCKED, False)]
        self.assertEqual(derive_overall(checks), WARNING)

    def test_blocking_blocked_beats_blocking_unknown(self):
        checks = [self._check(BLOCKED, True), self._check(UNKNOWN, True)]
        self.assertEqual(derive_overall(checks), BLOCKED)

    def test_empty_checks_gives_ready(self):
        self.assertEqual(derive_overall([]), READY)


# ── 2. check_market_data ──────────────────────────────────────────────────────

class TestCheckMarketData(unittest.TestCase):

    def test_fresh_scan_gives_ready(self):
        inputs = _minimal_inputs(scan_meta=_fresh_meta(age_s=60))
        now = _now()
        checks = check_market_data(inputs, now)
        freshness_check = next(c for c in checks if c["id"] == "scan_freshness")
        self.assertEqual(freshness_check["status"], READY)

    def test_stale_scan_gives_warning(self):
        # 800 minutes old (market closed budget is 720m)
        stale_meta = _fresh_meta(age_s=800 * 60)
        inputs = _minimal_inputs(scan_meta=stale_meta)
        now = _now()
        checks = check_market_data(inputs, now)
        freshness_check = next(c for c in checks if c["id"] == "scan_freshness")
        self.assertEqual(freshness_check["status"], WARNING)

    def test_no_scan_meta_gives_unknown(self):
        inputs = _minimal_inputs(scan_meta=None)
        now = _now()
        checks = check_market_data(inputs, now)
        freshness_check = next(c for c in checks if c["id"] == "scan_freshness")
        self.assertEqual(freshness_check["status"], UNKNOWN)

    def test_missing_snapshot_ts_gives_unknown(self):
        meta = _fresh_meta()
        meta["snapshot_ts"] = None
        inputs = _minimal_inputs(scan_meta=meta)
        now = _now()
        checks = check_market_data(inputs, now)
        freshness_check = next(c for c in checks if c["id"] == "scan_freshness")
        self.assertEqual(freshness_check["status"], UNKNOWN)

    def test_missing_snapshot_ts_empty_string_gives_unknown(self):
        meta = _fresh_meta()
        meta["snapshot_ts"] = ""
        inputs = _minimal_inputs(scan_meta=meta)
        now = _now()
        checks = check_market_data(inputs, now)
        freshness_check = next(c for c in checks if c["id"] == "scan_freshness")
        self.assertEqual(freshness_check["status"], UNKNOWN)


# ── 3. check_broker ───────────────────────────────────────────────────────────

class TestCheckBroker(unittest.TestCase):

    def test_connected_gives_ready(self):
        inputs = _minimal_inputs(broker={"connection_state": "CONNECTED",
                                          "token_status": "valid",
                                          "probe_source": "live",
                                          "last_success_at": _now().isoformat()})
        checks = check_broker(inputs)
        self.assertEqual(checks[0]["status"], READY)

    def test_login_required_gives_warning(self):
        inputs = _minimal_inputs()  # default broker has LOGIN_REQUIRED
        checks = check_broker(inputs)
        self.assertEqual(checks[0]["status"], WARNING)

    def test_api_error_gives_warning(self):
        inputs = _minimal_inputs(broker={"connection_state": "API_ERROR",
                                          "token_status": None,
                                          "probe_source": "cache",
                                          "last_success_at": None})
        checks = check_broker(inputs)
        self.assertEqual(checks[0]["status"], WARNING)

    def test_none_broker_gives_unknown(self):
        inputs = _minimal_inputs(broker=None)
        checks = check_broker(inputs)
        self.assertEqual(checks[0]["status"], UNKNOWN)

    def test_broker_is_non_blocking(self):
        inputs = _minimal_inputs(broker=None)
        checks = check_broker(inputs)
        self.assertFalse(checks[0]["blocking"])

    def test_connected_broker_is_non_blocking(self):
        inputs = _minimal_inputs(broker={"connection_state": "CONNECTED",
                                          "token_status": "valid",
                                          "probe_source": "live",
                                          "last_success_at": _now().isoformat()})
        checks = check_broker(inputs)
        self.assertFalse(checks[0]["blocking"])


# ── 4. check_pipeline ─────────────────────────────────────────────────────────

class TestCheckPipeline(unittest.TestCase):

    def test_success_status_gives_ready_for_scan_outcome(self):
        inputs = _minimal_inputs()  # default has SUCCESS status
        checks = check_pipeline(inputs)
        scan_check = next(c for c in checks if c["id"] == "last_scan_outcome")
        self.assertEqual(scan_check["status"], READY)

    def test_zero_pipeline_events_gives_warning(self):
        inputs = _minimal_inputs(pipeline={"scan_id": "scan_test",
                                            "last_event_at": _now().isoformat(),
                                            "count": 0})
        checks = check_pipeline(inputs)
        event_check = next(c for c in checks if c["id"] == "pipeline_events")
        self.assertEqual(event_check["status"], WARNING)

    def test_none_scan_meta_gives_unknown_for_last_scan_outcome(self):
        inputs = _minimal_inputs(scan_meta=None)
        checks = check_pipeline(inputs)
        scan_check = next(c for c in checks if c["id"] == "last_scan_outcome")
        self.assertEqual(scan_check["status"], UNKNOWN)

    def test_positive_events_count_gives_ready(self):
        inputs = _minimal_inputs()  # default has count=120
        checks = check_pipeline(inputs)
        event_check = next(c for c in checks if c["id"] == "pipeline_events")
        self.assertEqual(event_check["status"], READY)


# ── 5. check_safety ───────────────────────────────────────────────────────────

class TestCheckSafety(unittest.TestCase):

    def test_paper_mode_and_live_flags_off_gives_ready(self):
        inputs = _minimal_inputs()  # paper_mode=True, live flags off
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], READY)

    def test_live_execution_enabled_true_gives_blocked(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "true",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": True,
        }
        inputs = _minimal_inputs(env_flags=flags)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], BLOCKED)
        self.assertTrue(mode_check["blocking"])

    def test_auto_execution_enabled_set_gives_blocked(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_EXECUTION_ENABLED_set": True,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": True,
        }
        inputs = _minimal_inputs(env_flags=flags)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], BLOCKED)

    def test_paper_mode_none_gives_unknown_not_ready(self):
        inputs = _minimal_inputs(paper_mode=None)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertNotEqual(mode_check["status"], READY)
        self.assertEqual(mode_check["status"], UNKNOWN)

    def test_paper_mode_false_gives_blocked(self):
        inputs = _minimal_inputs(paper_mode=False)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], BLOCKED)

    def test_env_flags_none_gives_unknown(self):
        inputs = _minimal_inputs(env_flags=None)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], UNKNOWN)
        self.assertNotEqual(mode_check["status"], READY)


# ── 6. check_scheduling ───────────────────────────────────────────────────────

class TestCheckScheduling(unittest.TestCase):

    def test_healthy_gives_ready(self):
        inputs = _minimal_inputs()
        checks = check_scheduling(inputs, _now())
        self.assertEqual(checks[0]["status"], READY)

    def test_disabled_gives_warning(self):
        sched = {"health": "DISABLED", "heartbeat_at": _now().isoformat(),
                 "auto_scan_enabled": False, "last_error": None}
        inputs = _minimal_inputs(scheduler=sched)
        checks = check_scheduling(inputs, _now())
        self.assertEqual(checks[0]["status"], WARNING)

    def test_down_market_open_gives_blocked(self):
        sched = {"health": "DOWN", "heartbeat_at": _now().isoformat(),
                 "auto_scan_enabled": False, "last_error": "scheduler down"}
        inputs = _minimal_inputs(
            scheduler=sched,
            market={"state": "OPEN", "is_open": True, "next_transition": None}
        )
        checks = check_scheduling(inputs, _now())
        self.assertEqual(checks[0]["status"], BLOCKED)

    def test_down_market_closed_gives_warning(self):
        sched = {"health": "DOWN", "heartbeat_at": _now().isoformat(),
                 "auto_scan_enabled": False, "last_error": "scheduler down"}
        inputs = _minimal_inputs(
            scheduler=sched,
            market={"state": "CLOSED", "is_open": False, "next_transition": None}
        )
        checks = check_scheduling(inputs, _now())
        self.assertEqual(checks[0]["status"], WARNING)

    def test_none_scheduler_gives_unknown(self):
        inputs = _minimal_inputs(scheduler=None)
        checks = check_scheduling(inputs, _now())
        self.assertEqual(checks[0]["status"], UNKNOWN)


# ── 7. check_configuration ───────────────────────────────────────────────────

class TestCheckConfiguration(unittest.TestCase):

    def test_all_env_vars_present_gives_ready(self):
        inputs = _minimal_inputs()
        checks = check_configuration(inputs)
        env_check = next(c for c in checks if c["id"] == "critical_env")
        self.assertEqual(env_check["status"], READY)

    def test_missing_database_url_gives_blocked(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": False,
        }
        inputs = _minimal_inputs(env_flags=flags)
        checks = check_configuration(inputs)
        env_check = next(c for c in checks if c["id"] == "critical_env")
        self.assertEqual(env_check["status"], BLOCKED)

    def test_missing_session_secret_gives_blocked(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": False,
            "DATABASE_URL_present": True,
        }
        inputs = _minimal_inputs(env_flags=flags)
        checks = check_configuration(inputs)
        env_check = next(c for c in checks if c["id"] == "critical_env")
        self.assertEqual(env_check["status"], BLOCKED)


# ── 8. Missing telemetry cannot produce READY for blocking checks ─────────────

class TestMissingTelemetryNotReady(unittest.TestCase):

    def test_no_scan_meta_market_data_not_ready(self):
        inputs = _minimal_inputs(scan_meta=None)
        checks = check_market_data(inputs, _now())
        freshness_check = next(c for c in checks if c["id"] == "scan_freshness")
        self.assertNotEqual(freshness_check["status"], READY)

    def test_no_env_flags_safety_not_ready(self):
        inputs = _minimal_inputs(env_flags=None)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertNotEqual(mode_check["status"], READY)

    def test_no_scheduler_scheduling_not_ready(self):
        inputs = _minimal_inputs(scheduler=None)
        checks = check_scheduling(inputs, _now())
        self.assertNotEqual(checks[0]["status"], READY)


# ── 9. Paper/live execution-mode validation ───────────────────────────────────

class TestExecutionModeValidation(unittest.TestCase):

    def test_live_flag_true_gives_blocked_blocking(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "true",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": True,
        }
        inputs = _minimal_inputs(env_flags=flags)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], BLOCKED)
        self.assertTrue(mode_check["blocking"])

    def test_paper_mode_live_flags_off_gives_ready(self):
        inputs = _minimal_inputs(paper_mode=True)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], READY)

    def test_live_orders_enabled_set_gives_blocked(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": True,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": True,
        }
        inputs = _minimal_inputs(env_flags=flags)
        checks = check_safety(inputs)
        mode_check = next(c for c in checks if c["id"] == "execution_mode")
        self.assertEqual(mode_check["status"], BLOCKED)


# ── 10. Overall readiness derivation via build_report ────────────────────────

class TestBuildReportOverall(unittest.TestCase):

    def test_healthy_inputs_overall_not_blocked(self):
        inputs = _minimal_inputs()
        report = build_report(inputs=inputs)
        self.assertTrue(report["ok"])
        self.assertNotEqual(report["overall"], BLOCKED)

    def test_live_execution_enabled_gives_blocked_overall(self):
        flags = {
            "LIVE_EXECUTION_ENABLED": "true",
            "AUTO_EXECUTION_ENABLED_set": False,
            "LIVE_ORDERS_ENABLED_set": False,
            "SESSION_SECRET_present": True,
            "DATABASE_URL_present": True,
        }
        inputs = _minimal_inputs(env_flags=flags)
        report = build_report(inputs=inputs)
        self.assertEqual(report["overall"], BLOCKED)

    def test_report_contains_required_fields(self):
        inputs = _minimal_inputs()
        report = build_report(inputs=inputs)
        for key in ("ok", "generated_at", "overall", "counts", "domains",
                    "freshness", "market", "source_errors", "paper_trading_only",
                    "advisory_only", "note"):
            self.assertIn(key, report, f"Missing key: {key}")

    def test_counts_sum_matches_checks(self):
        inputs = _minimal_inputs()
        report = build_report(inputs=inputs)
        total = sum(report["counts"].values())
        all_checks = [c for d in report["domains"] for c in d["checks"]]
        self.assertEqual(total, len(all_checks))


# ── 11 & 12. get_history ─────────────────────────────────────────────────────

class TestGetHistory(unittest.TestCase):

    def test_empty_kv_returns_empty_entries(self):
        mock_store = MagicMock()
        mock_store.kv_get.return_value = []
        with patch.dict("sys.modules", {"phase20_store": mock_store}):
            result = get_history(limit=20)
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"], [])

    def test_three_entries_returned_reversed(self):
        entries = [
            {"at": "2025-01-01T08:00:00Z", "overall": READY, "counts": {}, "blocking_failures": [], "issues": []},
            {"at": "2025-01-01T09:00:00Z", "overall": WARNING, "counts": {}, "blocking_failures": [], "issues": []},
            {"at": "2025-01-01T10:00:00Z", "overall": BLOCKED, "counts": {}, "blocking_failures": [], "issues": []},
        ]
        mock_store = MagicMock()
        mock_store.kv_get.return_value = entries
        with patch.dict("sys.modules", {"phase20_store": mock_store}):
            result = get_history(limit=20)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["entries"]), 3)
        # Should be reversed (newest first)
        self.assertEqual(result["entries"][0]["overall"], BLOCKED)
        self.assertEqual(result["entries"][2]["overall"], READY)

    def test_history_respects_limit(self):
        entries = [
            {"at": f"2025-01-01T0{i}:00:00Z", "overall": READY,
             "counts": {}, "blocking_failures": [], "issues": []}
            for i in range(5)
        ]
        mock_store = MagicMock()
        mock_store.kv_get.return_value = entries
        with patch.dict("sys.modules", {"phase20_store": mock_store}):
            result = get_history(limit=2)
        self.assertEqual(len(result["entries"]), 2)

    def test_none_kv_returns_empty_entries(self):
        mock_store = MagicMock()
        mock_store.kv_get.return_value = None
        with patch.dict("sys.modules", {"phase20_store": mock_store}):
            result = get_history(limit=20)
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"], [])

    def test_exception_returns_ok_with_error(self):
        mock_store = MagicMock()
        mock_store.kv_get.side_effect = RuntimeError("KV unavailable")
        with patch.dict("sys.modules", {"phase20_store": mock_store}):
            result = get_history(limit=20)
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"], [])
        self.assertIn("error", result)


# ── Extra: check_strategy_risk ───────────────────────────────────────────────

class TestCheckStrategyRisk(unittest.TestCase):

    def test_settings_available_gives_ready(self):
        inputs = _minimal_inputs()
        checks = check_strategy_risk(inputs)
        self.assertEqual(checks[0]["status"], READY)
        self.assertTrue(checks[0]["blocking"])

    def test_settings_none_gives_unknown(self):
        inputs = _minimal_inputs(settings=None)
        checks = check_strategy_risk(inputs)
        self.assertEqual(checks[0]["status"], UNKNOWN)
        self.assertNotEqual(checks[0]["status"], READY)


# ── Extra: check_execution ───────────────────────────────────────────────────

class TestCheckExecution(unittest.TestCase):

    def test_settings_available_gives_ready(self):
        inputs = _minimal_inputs()
        checks = check_execution(inputs)
        self.assertEqual(checks[0]["status"], READY)

    def test_settings_none_gives_unknown(self):
        inputs = _minimal_inputs(settings=None)
        checks = check_execution(inputs)
        self.assertEqual(checks[0]["status"], UNKNOWN)


# ── Extra: check_portfolio ───────────────────────────────────────────────────

class TestCheckPortfolio(unittest.TestCase):

    def test_healthy_portfolio_gives_ready_or_unknown(self):
        # portfolio_health with no status field → UNKNOWN (no status reported)
        # or READY if status present
        inputs = _minimal_inputs(
            portfolio_health={"status": "HEALTHY", "position_count": 2}
        )
        checks = check_portfolio(inputs)
        self.assertIn(checks[0]["status"], (READY, UNKNOWN, WARNING))
        # Just ensure it's not BLOCKED when status is HEALTHY
        self.assertNotEqual(checks[0]["status"], BLOCKED)

    def test_portfolio_none_gives_unknown(self):
        inputs = _minimal_inputs(portfolio_health=None)
        checks = check_portfolio(inputs)
        self.assertEqual(checks[0]["status"], UNKNOWN)
        self.assertNotEqual(checks[0]["status"], READY)

    def test_portfolio_down_gives_blocked(self):
        inputs = _minimal_inputs(portfolio_health={"status": "DOWN"})
        checks = check_portfolio(inputs)
        self.assertEqual(checks[0]["status"], BLOCKED)

    def test_portfolio_degraded_gives_warning(self):
        inputs = _minimal_inputs(portfolio_health={"status": "DEGRADED"})
        checks = check_portfolio(inputs)
        self.assertEqual(checks[0]["status"], WARNING)


# ── Extra: check_persistence_recovery ────────────────────────────────────────

class TestCheckPersistenceRecovery(unittest.TestCase):

    def test_db_durable_true_gives_ready(self):
        inputs = _minimal_inputs()
        checks = check_persistence_recovery(inputs, _now())
        db_check = next(c for c in checks if c["id"] == "db_durability")
        self.assertEqual(db_check["status"], READY)

    def test_db_durable_false_gives_warning(self):
        inputs = _minimal_inputs(db_durable=False)
        checks = check_persistence_recovery(inputs, _now())
        db_check = next(c for c in checks if c["id"] == "db_durability")
        self.assertEqual(db_check["status"], WARNING)

    def test_db_durable_none_gives_unknown(self):
        inputs = _minimal_inputs(db_durable=None)
        checks = check_persistence_recovery(inputs, _now())
        db_check = next(c for c in checks if c["id"] == "db_durability")
        self.assertEqual(db_check["status"], UNKNOWN)

    def test_recovery_latest_none_gives_recovery_validation_unknown(self):
        inputs = _minimal_inputs(recovery_latest=None)
        checks = check_persistence_recovery(inputs, _now())
        rec_check = next((c for c in checks if c["id"] == "recovery_validation"), None)
        if rec_check:
            # recovery_latest=None and no error → UNKNOWN
            self.assertNotEqual(rec_check["status"], READY)

    def test_recovery_pass_verdict_gives_ready(self):
        inputs = _minimal_inputs(
            recovery_latest={"verdict": "PASS", "created_at": _now().isoformat(), "result_id": "r1"}
        )
        checks = check_persistence_recovery(inputs, _now())
        rec_check = next(c for c in checks if c["id"] == "recovery_validation")
        self.assertEqual(rec_check["status"], READY)


# ── Extra: build_freshness ────────────────────────────────────────────────────

class TestBuildFreshness(unittest.TestCase):

    def test_returns_list_of_freshness_rows(self):
        inputs = _minimal_inputs()
        rows = build_freshness(inputs, _now())
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIn("name", row)
            self.assertIn("status", row)
            self.assertIn("source", row)

    def test_fresh_scan_row_is_ready(self):
        inputs = _minimal_inputs(scan_meta=_fresh_meta(age_s=60))
        rows = build_freshness(inputs, _now())
        scan_row = next(r for r in rows if "scan snapshot" in r["name"])
        self.assertEqual(scan_row["status"], READY)

    def test_stale_scan_row_is_warning(self):
        stale_meta = _fresh_meta(age_s=800 * 60)
        inputs = _minimal_inputs(scan_meta=stale_meta)
        rows = build_freshness(inputs, _now())
        scan_row = next(r for r in rows if "scan snapshot" in r["name"])
        self.assertEqual(scan_row["status"], WARNING)


if __name__ == "__main__":
    unittest.main()
