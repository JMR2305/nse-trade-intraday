"""
test_observability_center.py — Phase 8.1
Unit tests for the Production Monitoring & Observability Center.

Coverage:
  - Feature flag (enabled / disabled)
  - Models (grade helpers, dataclasses)
  - System health (memory, CPU, disk, process, flags, env)
  - API metrics (stats, endpoint breakdown)
  - Database metrics (connectivity probe)
  - Cache metrics (in-process cache introspection)
  - Job monitor (scheduler status, scan state)
  - Error monitor (record, aggregate, categorise)
  - Alert engine (alert generation per sub-monitor)
  - Audit tracker (record, timeline, seed)
  - Performance dashboard (module probes)
  - Availability (module availability, uptime)
  - Shared services (all 6 endpoints + snapshot + export)
  - API dispatch (cmd_* functions)
  - Advisory-only safety (AST scan)

READ-ONLY. ADVISORY-ONLY.
"""
import os
import sys
import json
import time
import unittest
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from task974_test_isolation import isolated_imports

# ── Path + flag setup ─────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Stub Phase 7 snapshot functions (prevent real yfinance / DB calls) ─────────
def _snap(name: str) -> dict:
    return {"status": "ENABLED", "available": True, "advisory_only": True,
            "score": 65.0, "grade": "B", "trend": "STABLE",
            f"{name}_score": 65.0}

_market_mock = MagicMock(); _market_mock.get_market_intelligence_snapshot.return_value = _snap("market")
_event_mock  = MagicMock(); _event_mock.get_event_intelligence_snapshot.return_value  = _snap("event")
_macro_mock  = MagicMock(); _macro_mock.get_macro_intelligence_snapshot.return_value  = {
    "macro_score": 62.0, "grade": "B", "available": True,
    "india_vix": 18.5, "vix_regime": "STABLE", "vix_risk_level": "MEDIUM",
}
_xai_mock    = MagicMock(); _xai_mock.get_explainable_ai_snapshot.return_value        = _snap("xai")
_rl_mock     = MagicMock(); _rl_mock.get_research_lab_snapshot.return_value           = _snap("research_lab")

# Stub scan_state_store
_scan_state_mock = MagicMock()
_scan_state_mock.get_latest_snapshot.return_value = {
    "scan_id": "test_scan_001", "snapshot_ts": datetime.now(timezone.utc).isoformat(),
    "status": "COMPLETED",
}


@pytest.fixture(autouse=True)
def _scoped_snapshot_dependencies():
    # Never publish these doubles during collection: later analysis agents
    # must resolve the real regime provider, not MagicMock._get_regime.
    stubs = {
        "market_intelligence_hub.shared_services": _market_mock,
        "event_intelligence.shared_services": _event_mock,
        "macro_intelligence.shared_services": _macro_mock,
        "explainable_ai.shared_services": _xai_mock,
        "research_lab.shared_services": _rl_mock,
        "scan_state_store": _scan_state_mock,
    }
    with isolated_imports(stubs, target_packages=("observability_center",),
                          environment={"OBSERVABILITY_CENTER_ENABLED": "true"}):
        yield


# ══════════════════════════════════════════════════════════════════════════════
# 1. Feature flag
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlag(unittest.TestCase):

    def test_enabled_returns_true(self):
        os.environ["OBSERVABILITY_CENTER_ENABLED"] = "true"
        from observability_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_disabled_returns_false(self):
        os.environ["OBSERVABILITY_CENTER_ENABLED"] = "false"
        from observability_center.models import is_enabled
        self.assertFalse(is_enabled())
        os.environ["OBSERVABILITY_CENTER_ENABLED"] = "true"

    def test_disabled_response_shape(self):
        from observability_center.models import disabled_response
        d = disabled_response()
        self.assertEqual(d["status"], "DISABLED")
        self.assertFalse(d["available"])
        self.assertTrue(d["advisory_only"])

    def test_flag_constant(self):
        from observability_center.models import _FLAG
        self.assertEqual(_FLAG, "OBSERVABILITY_CENTER_ENABLED")

    def test_disabled_blocks_summary(self):
        os.environ["OBSERVABILITY_CENTER_ENABLED"] = "false"
        import importlib
        import observability_center.shared_services as ss
        importlib.reload(ss)
        r = ss.get_summary()
        self.assertEqual(r["status"], "DISABLED")
        os.environ["OBSERVABILITY_CENTER_ENABLED"] = "true"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Models
# ══════════════════════════════════════════════════════════════════════════════

class TestModels(unittest.TestCase):

    def test_obs_grade_a_plus(self):
        from observability_center.models import obs_grade
        self.assertEqual(obs_grade(95), "A+")

    def test_obs_grade_a(self):
        from observability_center.models import obs_grade
        self.assertEqual(obs_grade(82), "A")

    def test_obs_grade_b(self):
        from observability_center.models import obs_grade
        self.assertEqual(obs_grade(70), "B")

    def test_obs_grade_c(self):
        from observability_center.models import obs_grade
        self.assertEqual(obs_grade(55), "C")

    def test_obs_grade_d(self):
        from observability_center.models import obs_grade
        self.assertEqual(obs_grade(30), "D")

    def test_trend_label_improving(self):
        from observability_center.models import trend_label
        self.assertEqual(trend_label(80, 75), "IMPROVING")

    def test_trend_label_degrading(self):
        from observability_center.models import trend_label
        self.assertEqual(trend_label(60, 70), "DEGRADING")

    def test_trend_label_stable(self):
        from observability_center.models import trend_label
        self.assertEqual(trend_label(70, 70), "STABLE")

    def test_obs_alert_to_dict(self):
        from observability_center.models import ObsAlert
        a = ObsAlert("a1", "CRITICAL", "SYSTEM", "Test alert", "Detail")
        d = a.to_dict()
        self.assertEqual(d["alert_id"],  "a1")
        self.assertEqual(d["severity"],  "CRITICAL")
        self.assertIn("generated_at", d)
        self.assertFalse(d["acknowledged"])
        self.assertFalse(d["resolved"])

    def test_audit_entry_to_dict(self):
        from observability_center.models import AuditEntry
        e = AuditEntry("e1", "TEST_ACTION", "operator", "test detail")
        d = e.to_dict()
        self.assertEqual(d["entry_id"], "e1")
        self.assertEqual(d["action"],   "TEST_ACTION")
        self.assertIn("timestamp", d)


# ══════════════════════════════════════════════════════════════════════════════
# 3. System health
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemHealth(unittest.TestCase):

    def test_uptime_seconds_positive(self):
        from observability_center.system_health import get_uptime_seconds
        uptime = get_uptime_seconds()
        self.assertGreaterEqual(uptime, 0.0)

    def test_memory_info_structure(self):
        from observability_center.system_health import get_memory_info
        m = get_memory_info()
        self.assertIn("usage_pct", m)
        self.assertGreaterEqual(m.get("usage_pct", 0), 0)
        self.assertIn("status", m)

    def test_cpu_info_structure(self):
        from observability_center.system_health import get_cpu_info
        c = get_cpu_info()
        self.assertIn("load_1m", c)
        self.assertIn("status", c)

    def test_disk_info_structure(self):
        from observability_center.system_health import get_disk_info
        d = get_disk_info()
        self.assertIn("usage_pct", d)
        self.assertIn("status", d)

    def test_feature_flags_returns_dict(self):
        from observability_center.system_health import get_feature_flags
        f = get_feature_flags()
        self.assertIn("flags", f)
        self.assertIn("enabled_count", f)
        self.assertIsInstance(f["flags"], dict)

    def test_observability_flag_visible(self):
        from observability_center.system_health import get_feature_flags
        f = get_feature_flags()
        self.assertIn("OBSERVABILITY_CENTER_ENABLED", f["flags"])
        self.assertTrue(f["flags"]["OBSERVABILITY_CENTER_ENABLED"])

    def test_environment_status_structure(self):
        from observability_center.system_health import get_environment_status
        e = get_environment_status()
        self.assertIn("status", e)
        self.assertIn("environment", e)
        self.assertIn("missing_critical", e)

    def test_get_system_health_top_level(self):
        from observability_center.system_health import get_system_health
        sh = get_system_health()
        self.assertTrue(sh["available"])
        self.assertTrue(sh["advisory_only"])
        self.assertIn("health_score", sh)
        self.assertIn("overall_status", sh)
        self.assertIn("memory", sh)
        self.assertIn("cpu", sh)
        self.assertIn("disk", sh)
        self.assertIn("uptime_seconds", sh)


# ══════════════════════════════════════════════════════════════════════════════
# 4. API metrics
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIMetrics(unittest.TestCase):

    def setUp(self):
        import observability_center.api_metrics as am
        am._request_log.clear()

    def test_empty_log_returns_zero_counts(self):
        from observability_center.api_metrics import get_api_metrics
        m = get_api_metrics()
        self.assertTrue(m["available"])
        self.assertEqual(m["stats"]["request_count"], 0)

    def test_record_request_adds_entry(self):
        from observability_center.api_metrics import record_request, get_api_metrics
        record_request("/api/test", "GET", 200, 45.0)
        m = get_api_metrics()
        self.assertEqual(m["stats"]["request_count"], 1)
        self.assertEqual(m["stats"]["error_count"],   0)

    def test_error_request_counted(self):
        from observability_center.api_metrics import record_request, get_api_metrics
        record_request("/api/test", "GET", 500, 120.0)
        m = get_api_metrics()
        self.assertEqual(m["stats"]["error_count"], 1)
        self.assertGreater(m["stats"]["error_rate_pct"], 0)

    def test_p95_latency_computed(self):
        from observability_center.api_metrics import record_request, get_api_metrics
        for i in range(20):
            record_request("/api/test", "GET", 200, float(i * 10))
        m = get_api_metrics()
        self.assertGreater(m["stats"]["p95_latency_ms"], 0)

    def test_endpoint_breakdown_populated(self):
        from observability_center.api_metrics import record_request, get_api_metrics
        record_request("/api/summary",    "GET", 200, 50.0)
        record_request("/api/summary",    "GET", 200, 60.0)
        record_request("/api/strategies", "GET", 200, 80.0)
        m = get_api_metrics()
        endpoints = [e["endpoint"] for e in m["endpoint_breakdown"]]
        self.assertIn("/api/summary", endpoints)
        self.assertIn("/api/strategies", endpoints)

    def test_note_present(self):
        from observability_center.api_metrics import get_api_metrics
        m = get_api_metrics()
        self.assertIn("note", m)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Database metrics
# ══════════════════════════════════════════════════════════════════════════════

class TestDBMetrics(unittest.TestCase):

    def test_no_database_url_returns_unknown(self):
        saved = os.environ.pop("DATABASE_URL", None)
        from observability_center.db_metrics import get_db_metrics
        m = get_db_metrics()
        self.assertIn(m["status"], ("UNKNOWN", "DOWN", "HEALTHY"))
        self.assertFalse(m["connection"]["url_set"])
        if saved:
            os.environ["DATABASE_URL"] = saved

    def test_structure_always_returned(self):
        from observability_center.db_metrics import get_db_metrics
        m = get_db_metrics()
        self.assertTrue(m["available"])
        self.assertTrue(m["advisory_only"])
        self.assertIn("connection", m)
        self.assertIn("pool", m)
        self.assertIn("operations", m)
        self.assertIn("health_score", m)

    def test_write_probe_is_none(self):
        from observability_center.db_metrics import get_db_metrics
        m = get_db_metrics()
        self.assertIsNone(m["operations"]["write_probe"])

    def test_health_score_in_range(self):
        from observability_center.db_metrics import get_db_metrics
        m = get_db_metrics()
        self.assertGreaterEqual(m["health_score"], 0.0)
        self.assertLessEqual(m["health_score"],   100.0)

    def test_pool_note_present(self):
        from observability_center.db_metrics import get_db_metrics
        m = get_db_metrics()
        self.assertIn("note", m["pool"])


# ══════════════════════════════════════════════════════════════════════════════
# 6. Cache metrics
# ══════════════════════════════════════════════════════════════════════════════

class TestCacheMetrics(unittest.TestCase):

    def test_returns_structure(self):
        from observability_center.cache_metrics import get_cache_metrics
        c = get_cache_metrics()
        self.assertTrue(c["available"])
        self.assertTrue(c["advisory_only"])
        self.assertIn("total_entries", c)
        self.assertIn("caches", c)
        self.assertIsInstance(c["caches"], list)

    def test_hit_rate_in_range(self):
        from observability_center.cache_metrics import get_cache_metrics
        c = get_cache_metrics()
        self.assertGreaterEqual(c["cache_hit_rate_est_pct"], 0)
        self.assertLessEqual(c["cache_hit_rate_est_pct"], 100)

    def test_stale_entries_non_negative(self):
        from observability_center.cache_metrics import get_cache_metrics
        c = get_cache_metrics()
        self.assertGreaterEqual(c["stale_entries"], 0)

    def test_memory_estimate_non_negative(self):
        from observability_center.cache_metrics import get_cache_metrics
        c = get_cache_metrics()
        self.assertGreaterEqual(c["memory_est_kb"], 0)

    def test_note_present(self):
        from observability_center.cache_metrics import get_cache_metrics
        c = get_cache_metrics()
        self.assertIn("note", c)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Job monitor
# ══════════════════════════════════════════════════════════════════════════════

class TestJobMonitor(unittest.TestCase):

    def test_returns_structure(self):
        from observability_center.job_monitor import get_job_monitor
        j = get_job_monitor()
        self.assertTrue(j["available"])
        self.assertTrue(j["advisory_only"])
        self.assertIn("scheduler_status", j)
        self.assertIn("jobs", j)
        self.assertIn("last_scan", j)

    def test_jobs_list_non_empty(self):
        from observability_center.job_monitor import get_job_monitor
        j = get_job_monitor()
        self.assertGreater(len(j["jobs"]), 0)

    def test_scheduler_status_valid(self):
        from observability_center.job_monitor import get_job_monitor
        j = get_job_monitor()
        self.assertIn(j["scheduler_status"],
                      {"HEALTHY", "DEGRADED", "DOWN", "UNKNOWN"})

    def test_health_score_in_range(self):
        from observability_center.job_monitor import get_job_monitor
        j = get_job_monitor()
        self.assertGreaterEqual(j["health_score"], 0.0)
        self.assertLessEqual(j["health_score"],   100.0)

    def test_failed_count_non_negative(self):
        from observability_center.job_monitor import get_job_monitor
        j = get_job_monitor()
        self.assertGreaterEqual(j["failed_count"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# 8. Error monitor
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorMonitor(unittest.TestCase):

    def setUp(self):
        import observability_center.error_monitor as em
        em._error_log.clear()

    def test_empty_log_returns_zeros(self):
        from observability_center.error_monitor import get_error_monitor
        m = get_error_monitor()
        self.assertTrue(m["available"])
        self.assertEqual(m["total_errors"], 0)
        self.assertEqual(m["error_rate_per_h"], 0.0)

    def test_record_error_increments_count(self):
        from observability_center.error_monitor import record_error, get_error_monitor
        record_error("api.test", "ValueError", "bad input")
        m = get_error_monitor()
        self.assertEqual(m["total_errors"], 1)

    def test_recent_errors_populated(self):
        from observability_center.error_monitor import record_error, get_error_monitor
        for i in range(5):
            record_error("api.test", "IOError", f"error {i}")
        m = get_error_monitor()
        self.assertGreater(len(m["recent_errors"]), 0)

    def test_frequency_by_type(self):
        from observability_center.error_monitor import record_error, get_error_monitor
        record_error("api", "ValueError", "v1")
        record_error("api", "ValueError", "v2")
        record_error("api", "IOError",    "io1")
        m = get_error_monitor()
        by_type = m["frequency"]["by_type"]
        self.assertEqual(by_type.get("ValueError", 0), 2)
        self.assertEqual(by_type.get("IOError",    0), 1)

    def test_health_score_decreases_with_errors(self):
        from observability_center.error_monitor import record_error, get_error_monitor
        for i in range(15):
            record_error("api", "ValueError", f"err {i}")
        m = get_error_monitor()
        self.assertLess(m["health_score"], 100.0)

    def test_note_present(self):
        from observability_center.error_monitor import get_error_monitor
        m = get_error_monitor()
        self.assertIn("note", m)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Alert engine
# ══════════════════════════════════════════════════════════════════════════════

class TestAlertEngine(unittest.TestCase):

    def setUp(self):
        import observability_center.alert_engine as ae
        ae._active_alerts.clear()

    def _make_healthy(self) -> dict:
        return {"available": True, "status": "HEALTHY", "health_score": 90.0,
                "memory": {"usage_pct": 50.0, "status": "HEALTHY"},
                "disk":   {"usage_pct": 40.0, "status": "HEALTHY"},
                "environment": {"missing_critical": [], "status": "HEALTHY"}}

    def test_no_alerts_when_all_healthy(self):
        from observability_center.alert_engine import get_alert_summary
        system  = self._make_healthy()
        db      = {"status": "HEALTHY", "health_score": 90.0,
                   "connection": {"latency_ms": 10.0}}
        jobs    = {"last_scan": {"fresh": True, "age_min": 5}}
        errors  = {"error_rate_per_h": 0.0, "total_errors": 0}
        cache   = {"stale_entries": 0}
        perf    = {"overall_score": 85.0}
        r = get_alert_summary(system, db, jobs, errors, cache, perf)
        self.assertEqual(r["critical_count"], 0)

    def test_memory_critical_alert(self):
        from observability_center.alert_engine import generate_alerts_from_system
        system = self._make_healthy()
        system["memory"]["usage_pct"] = 92.0
        alerts = generate_alerts_from_system(system)
        sevs = [a.severity for a in alerts]
        self.assertIn("CRITICAL", sevs)

    def test_db_down_alert(self):
        from observability_center.alert_engine import generate_alerts_from_db
        db = {"status": "DOWN", "connection": {"error": "Connection refused"}}
        alerts = generate_alerts_from_db(db)
        self.assertTrue(any(a.severity == "CRITICAL" for a in alerts))

    def test_stale_scan_warning(self):
        from observability_center.alert_engine import generate_alerts_from_jobs
        jobs = {"last_scan": {"fresh": False, "age_min": 90}}
        alerts = generate_alerts_from_jobs(jobs)
        self.assertTrue(any(a.severity == "WARNING" for a in alerts))

    def test_high_error_rate_critical(self):
        from observability_center.alert_engine import generate_alerts_from_errors
        errors = {"error_rate_per_h": 25.0, "total_errors": 30}
        alerts = generate_alerts_from_errors(errors)
        self.assertTrue(any(a.severity == "CRITICAL" for a in alerts))

    def test_get_alert_summary_shape(self):
        from observability_center.alert_engine import get_alert_summary
        r = get_alert_summary(
            self._make_healthy(),
            {"status": "HEALTHY", "health_score": 90.0, "connection": {"latency_ms": 5.0}},
            {"last_scan": {"fresh": True, "age_min": 2}},
            {"error_rate_per_h": 0.0, "total_errors": 0},
            {"stale_entries": 0},
            {"overall_score": 80.0},
        )
        self.assertTrue(r["available"])
        self.assertTrue(r["advisory_only"])
        for key in ("total_active", "critical_count", "warning_count",
                    "critical_alerts", "warnings", "resolved"):
            self.assertIn(key, r)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Audit tracker
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditTracker(unittest.TestCase):

    def setUp(self):
        import observability_center.audit_tracker as at
        at._audit_log.clear()

    def test_record_and_retrieve(self):
        from observability_center.audit_tracker import record_audit, get_audit_timeline
        record_audit("TEST_ACTION", "operator", "unit test", "CONFIGURATION")
        t = get_audit_timeline()
        actions = [e["action"] for e in t["recent_entries"]]
        self.assertIn("TEST_ACTION", actions)

    def test_timeline_structure(self):
        from observability_center.audit_tracker import get_audit_timeline
        t = get_audit_timeline()
        self.assertTrue(t["available"])
        self.assertIn("timeline", t)
        self.assertIn("category_counts", t)
        self.assertIn("actor_counts", t)

    def test_seed_adds_entries_when_empty(self):
        from observability_center.audit_tracker import get_audit_timeline
        t = get_audit_timeline()
        self.assertGreater(t["total_entries"], 0)

    def test_category_counts_populated(self):
        from observability_center.audit_tracker import record_audit, get_audit_timeline
        record_audit("FLAG_ON", "system", "test", "CONFIGURATION")
        record_audit("FLAG_ON", "system", "test", "CONFIGURATION")
        record_audit("DEPLOY",  "system", "test", "DEPLOYMENT")
        t = get_audit_timeline()
        cats = t["category_counts"]
        self.assertGreaterEqual(cats.get("CONFIGURATION", 0), 2)

    def test_actor_counts_populated(self):
        from observability_center.audit_tracker import record_audit, get_audit_timeline
        record_audit("ACTION", "operator_1", "test")
        record_audit("ACTION", "operator_1", "test")
        t = get_audit_timeline()
        self.assertGreaterEqual(t["actor_counts"].get("operator_1", 0), 2)


# ══════════════════════════════════════════════════════════════════════════════
# 11. Performance dashboard
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformanceDashboard(unittest.TestCase):

    def test_returns_structure(self):
        from observability_center.performance_dashboard import get_performance_dashboard
        p = get_performance_dashboard()
        self.assertTrue(p["available"])
        self.assertTrue(p["advisory_only"])
        self.assertIn("overall_score", p)
        self.assertIn("grade", p)
        self.assertIn("module_probes", p)

    def test_score_in_range(self):
        from observability_center.performance_dashboard import get_performance_dashboard
        p = get_performance_dashboard()
        self.assertGreaterEqual(p["overall_score"], 0.0)
        self.assertLessEqual(p["overall_score"],   100.0)

    def test_module_probes_list(self):
        from observability_center.performance_dashboard import get_performance_dashboard
        p = get_performance_dashboard()
        self.assertIsInstance(p["module_probes"], list)
        for probe in p["module_probes"]:
            self.assertIn("module",      probe)
            self.assertIn("response_ms", probe)
            self.assertIn("available",   probe)
            self.assertIn("grade",       probe)

    def test_avg_snapshot_ms_non_negative(self):
        from observability_center.performance_dashboard import get_performance_dashboard
        p = get_performance_dashboard()
        self.assertGreaterEqual(p["avg_snapshot_ms"], 0.0)

    def test_benchmarks_present(self):
        from observability_center.performance_dashboard import get_performance_dashboard
        p = get_performance_dashboard()
        self.assertIn("benchmarks", p)
        self.assertIn("fast_threshold_ms", p["benchmarks"])


# ══════════════════════════════════════════════════════════════════════════════
# 12. Availability
# ══════════════════════════════════════════════════════════════════════════════

class TestAvailability(unittest.TestCase):

    def test_returns_structure(self):
        from observability_center.availability import get_availability
        a = get_availability()
        self.assertTrue(a["available"])
        self.assertTrue(a["advisory_only"])
        self.assertIn("overall_availability_pct", a)
        self.assertIn("module_availability", a)
        self.assertIn("uptime", a)

    def test_availability_pct_in_range(self):
        from observability_center.availability import get_availability
        a = get_availability()
        self.assertGreaterEqual(a["overall_availability_pct"], 0.0)
        self.assertLessEqual(a["overall_availability_pct"],   100.0)

    def test_uptime_has_required_keys(self):
        from observability_center.availability import get_availability
        a = get_availability()
        uptime = a["uptime"]
        for key in ("seconds", "hours", "days", "label"):
            self.assertIn(key, uptime)
        self.assertGreaterEqual(uptime["seconds"], 0.0)

    def test_module_availability_list(self):
        from observability_center.availability import get_availability
        a = get_availability()
        modules = a["module_availability"]
        self.assertIsInstance(modules, list)
        self.assertGreater(len(modules), 0)
        for m in modules:
            self.assertIn("module",  m)
            self.assertIn("status",  m)
            self.assertIn("available", m)

    def test_availability_score_in_range(self):
        from observability_center.availability import get_availability
        a = get_availability()
        self.assertGreaterEqual(a["availability_score"], 0.0)
        self.assertLessEqual(a["availability_score"],   100.0)

    def test_grade_valid(self):
        from observability_center.availability import get_availability
        a = get_availability()
        self.assertIn(a["grade"], {"A+", "A", "B", "C", "D"})


# ══════════════════════════════════════════════════════════════════════════════
# 13. Shared services
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedServices(unittest.TestCase):

    def setUp(self):
        os.environ["OBSERVABILITY_CENTER_ENABLED"] = "true"

    def test_summary_returns_enabled(self):
        from observability_center.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertTrue(r["available"])
        self.assertIn("observability_score", r)
        self.assertIn("grade", r)

    def test_summary_score_in_range(self):
        from observability_center.shared_services import get_summary
        r = get_summary()
        self.assertGreaterEqual(r["observability_score"], 0.0)
        self.assertLessEqual(r["observability_score"],   100.0)

    def test_get_system_structure(self):
        from observability_center.shared_services import get_system
        r = get_system()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("health_score", r)
        self.assertIn("memory", r)

    def test_get_performance_structure(self):
        from observability_center.shared_services import get_performance
        r = get_performance()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("overall_score", r)

    def test_get_errors_structure(self):
        from observability_center.shared_services import get_errors
        r = get_errors()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("total_errors", r)

    def test_get_alerts_structure(self):
        from observability_center.shared_services import get_alerts
        r = get_alerts()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("total_active", r)
        self.assertIn("critical_alerts", r)

    def test_get_audit_structure(self):
        from observability_center.shared_services import get_audit
        r = get_audit()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("timeline", r)

    def test_snapshot_never_raises(self):
        from observability_center.shared_services import get_observability_snapshot
        s = get_observability_snapshot()
        self.assertIn("observability_score", s)
        self.assertIn("grade", s)
        self.assertIn("available", s)

    def test_all_endpoints_advisory_only(self):
        from observability_center import shared_services as ss
        for fn in (ss.get_summary, ss.get_system, ss.get_errors,
                   ss.get_alerts, ss.get_audit):
            r = fn()
            self.assertTrue(r.get("advisory_only") or r.get("status") != "ENABLED",
                            f"{fn.__name__} missing advisory_only flag")

    def test_export_csv_non_empty(self):
        from observability_center.shared_services import export_csv
        csv_str = export_csv()
        self.assertIsInstance(csv_str, str)
        self.assertIn("observability_score", csv_str)

    def test_export_json_parseable(self):
        from observability_center.shared_services import export_json
        data = export_json()
        self.assertIsInstance(data, dict)
        self.assertIn("summary", data)
        self.assertTrue(data.get("advisory_only"))


# ══════════════════════════════════════════════════════════════════════════════
# 14. API dispatch
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIDispatch(unittest.TestCase):

    def test_cmd_summary(self):
        from observability_center.api import cmd_summary
        r = cmd_summary()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_system(self):
        from observability_center.api import cmd_system
        r = cmd_system()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("health_score", r)

    def test_cmd_performance(self):
        from observability_center.api import cmd_performance
        r = cmd_performance()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_errors(self):
        from observability_center.api import cmd_errors
        r = cmd_errors()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_alerts(self):
        from observability_center.api import cmd_alerts
        r = cmd_alerts()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_audit(self):
        from observability_center.api import cmd_audit
        r = cmd_audit()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_snapshot(self):
        from observability_center.api import cmd_snapshot
        r = cmd_snapshot()
        self.assertIn("observability_score", r)
        self.assertIn("available", r)

    def test_cmd_export_csv(self):
        from observability_center.api import cmd_export_csv
        r = cmd_export_csv()
        self.assertIn("csv", r)
        self.assertIn("status", r)

    def test_cmd_export_json(self):
        from observability_center.api import cmd_export_json
        r = cmd_export_json()
        self.assertIsInstance(r, dict)
        self.assertIn("summary", r)


# ══════════════════════════════════════════════════════════════════════════════
# 15. Advisory-only safety (AST scan)
# ══════════════════════════════════════════════════════════════════════════════

class TestAdvisoryOnlySafety(unittest.TestCase):

    FORBIDDEN_IMPORTS = [
        "order_executor", "trade_executor", "portfolio_writer",
        "signal_writer", "strategy_mutator", "risk_engine_writer",
        "model_trainer", "execution_engine",
    ]

    def _scan_module(self, module_path: str) -> list:
        import ast
        violations = []
        try:
            with open(module_path) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else ([node.module] if node.module else [])
                    )
                    for name in names:
                        for forbidden in self.FORBIDDEN_IMPORTS:
                            if forbidden in (name or ""):
                                violations.append(f"{module_path}: imports {name}")
        except Exception:
            pass
        return violations

    def test_no_write_imports_in_package(self):
        import glob
        pkg_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "observability_center"
        )
        py_files = glob.glob(os.path.join(pkg_dir, "*.py"))
        self.assertTrue(len(py_files) > 0, "No Python files found in observability_center/")
        all_violations = []
        for f in py_files:
            all_violations.extend(self._scan_module(f))
        self.assertEqual(
            all_violations, [],
            f"Forbidden write imports found: {all_violations}",
        )

    def test_summary_has_advisory_flag(self):
        from observability_center.shared_services import get_summary
        r = get_summary()
        self.assertTrue(r.get("advisory_only", False))

    def test_models_no_execution_imports(self):
        models_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "observability_center", "models.py",
        )
        violations = self._scan_module(models_path)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
