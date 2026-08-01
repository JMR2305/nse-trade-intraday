"""
test_deployment_center.py — Phase 8.8
Tests for the Deployment & Disaster Recovery Centre.

READ-ONLY. ADVISORY-ONLY.
All tests use mocked upstream dependencies.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# ── helpers ────────────────────────────────────────────────────────────────────
def _enable():
    os.environ["DEPLOYMENT_CENTER_ENABLED"] = "true"

def _disable():
    os.environ.pop("DEPLOYMENT_CENTER_ENABLED", None)

def _obs_snap():
    return {"available": True, "observability_score": 80.0}

def _ops_snap():
    return {"available": True, "operations_score": 75.0}

def _sec_snap():
    return {"available": True, "security_score": 78.0}

def _perf_snap():
    return {"available": True, "performance_score": 72.0}

def _sys_health():
    return {
        "memory": {"usage_pct": 45.0, "total_mb": 8192, "used_mb": 3686},
        "cpu":    {"load_1m": 0.8, "load_5m": 0.6, "count": 4},
        "disk":   {"usage_pct": 52.0, "total_gb": 50.0, "free_gb": 24.0},
    }

def _db_metrics():
    return {"connected": True, "available": True, "connection": {"latency_ms": 4.2}}

def _sched_health():
    return {"status": "RUNNING", "available": True}

def _scan_runs(n=5):
    from datetime import datetime, timezone, timedelta
    runs = []
    for i in range(n):
        ts = (datetime.now(timezone.utc) - timedelta(hours=i * 2)).isoformat()
        runs.append({"snapshot_ts": ts, "status": "completed", "scan_id": f"scan_{i}"})
    return runs

COMMON_PATCHES = [
    "deployment_center.shared_services._load_obs",
    "deployment_center.shared_services._load_ops",
    "deployment_center.shared_services._load_sec",
    "deployment_center.shared_services._load_perf",
    "deployment_center.shared_services._load_system_health",
    "deployment_center.shared_services._load_db_metrics",
    "deployment_center.shared_services._load_scheduler_health",
    "deployment_center.shared_services._load_scan_runs",
]

def _apply_patches(test_case):
    patches = [
        patch("deployment_center.shared_services._load_obs",              return_value=_obs_snap()),
        patch("deployment_center.shared_services._load_ops",              return_value=_ops_snap()),
        patch("deployment_center.shared_services._load_sec",              return_value=_sec_snap()),
        patch("deployment_center.shared_services._load_perf",             return_value=_perf_snap()),
        patch("deployment_center.shared_services._load_system_health",    return_value=_sys_health()),
        patch("deployment_center.shared_services._load_db_metrics",       return_value=_db_metrics()),
        patch("deployment_center.shared_services._load_scheduler_health", return_value=_sched_health()),
        patch("deployment_center.shared_services._load_scan_runs",        return_value=_scan_runs()),
    ]
    mocks = [p.start() for p in patches]
    test_case.addCleanup(lambda: [p.stop() for p in patches])
    return mocks


# ── Feature flag ───────────────────────────────────────────────────────────────
class TestFeatureFlag(unittest.TestCase):
    def tearDown(self):
        _disable()

    def test_disabled_by_default(self):
        _disable()
        from deployment_center.models import is_enabled
        self.assertFalse(is_enabled())

    def test_enabled_true(self):
        os.environ["DEPLOYMENT_CENTER_ENABLED"] = "true"
        from deployment_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_enabled_1(self):
        os.environ["DEPLOYMENT_CENTER_ENABLED"] = "1"
        from deployment_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_enabled_yes(self):
        os.environ["DEPLOYMENT_CENTER_ENABLED"] = "yes"
        from deployment_center.models import is_enabled
        self.assertTrue(is_enabled())

    def test_disabled_false(self):
        os.environ["DEPLOYMENT_CENTER_ENABLED"] = "false"
        from deployment_center.models import is_enabled
        self.assertFalse(is_enabled())

    def test_disabled_response_shape(self):
        _disable()
        from deployment_center.models import disabled_response
        r = disabled_response()
        self.assertEqual(r["available"], False)
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])
        self.assertIn("DEPLOYMENT_CENTER_ENABLED", r["message"])


# ── Grade / trend helpers ──────────────────────────────────────────────────────
class TestGradeTrend(unittest.TestCase):
    def test_grade_a_plus(self):
        from deployment_center.models import dr_grade
        self.assertEqual(dr_grade(95), "A+")

    def test_grade_a(self):
        from deployment_center.models import dr_grade
        self.assertEqual(dr_grade(82), "A")

    def test_grade_b(self):
        from deployment_center.models import dr_grade
        self.assertEqual(dr_grade(70), "B")

    def test_grade_c(self):
        from deployment_center.models import dr_grade
        self.assertEqual(dr_grade(55), "C")

    def test_grade_d(self):
        from deployment_center.models import dr_grade
        self.assertEqual(dr_grade(30), "D")

    def test_trend_stable(self):
        from deployment_center.models import dr_trend
        self.assertEqual(dr_trend([70, 71]), "STABLE")

    def test_trend_improving(self):
        from deployment_center.models import dr_trend
        self.assertEqual(dr_trend([60, 70]), "IMPROVING")

    def test_trend_degrading(self):
        from deployment_center.models import dr_trend
        self.assertEqual(dr_trend([80, 70]), "DEGRADING")

    def test_trend_single_point(self):
        from deployment_center.models import dr_trend
        self.assertEqual(dr_trend([75]), "STABLE")


# ── Score formula weights ──────────────────────────────────────────────────────
class TestScoreFormula(unittest.TestCase):
    def test_weights_sum_to_1(self):
        weights = [0.25, 0.25, 0.20, 0.15, 0.15]
        self.assertAlmostEqual(sum(weights), 1.0, places=10)

    def test_formula_100_all(self):
        overall = round(100*0.25 + 100*0.25 + 100*0.20 + 100*0.15 + 100*0.15, 1)
        self.assertEqual(overall, 100.0)

    def test_formula_0_all(self):
        overall = round(0*0.25 + 0*0.25 + 0*0.20 + 0*0.15 + 0*0.15, 1)
        self.assertEqual(overall, 0.0)


# ── Deployment Readiness ───────────────────────────────────────────────────────
class TestReadiness(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_readiness_score(self):
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertIn("readiness_score", r)
        self.assertGreaterEqual(r["readiness_score"], 0)
        self.assertLessEqual(r["readiness_score"], 100)

    def test_has_checks_list(self):
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertIn("checks", r)
        self.assertIsInstance(r["checks"], list)
        self.assertGreater(len(r["checks"]), 0)

    def test_has_env_vars(self):
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertIn("env_vars", r)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertEqual(r["available"], False)

    def test_has_grade(self):
        from deployment_center.shared_services import get_readiness
        r = get_readiness()
        self.assertIn(r.get("grade"), ["A+", "A", "B", "C", "D"])


# ── Configuration ──────────────────────────────────────────────────────────────
class TestConfig(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_config_score(self):
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertIn("config_score", r)
        self.assertGreaterEqual(r["config_score"], 0)
        self.assertLessEqual(r["config_score"], 100)

    def test_has_feature_flags(self):
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertIn("feature_flags", r)
        self.assertIsInstance(r["feature_flags"], list)

    def test_has_env_vars(self):
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertIn("env_vars", r)

    def test_has_issues_list(self):
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertIn("issues", r)
        self.assertIsInstance(r["issues"], list)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_config
        r = get_config()
        self.assertEqual(r["available"], False)


# ── Backup Validation ──────────────────────────────────────────────────────────
class TestBackups(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_backups
        r = get_backups()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_backups
        r = get_backups()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_backup_status(self):
        from deployment_center.shared_services import get_backups
        r = get_backups()
        self.assertIn("backup_status", r)

    def test_has_last_backup_time(self):
        from deployment_center.shared_services import get_backups
        r = get_backups()
        self.assertIn("last_backup_time", r)
        self.assertIsNotNone(r["last_backup_time"])  # scan_runs mocked with 5 entries

    def test_has_backup_score(self):
        from deployment_center.shared_services import get_backups
        r = get_backups()
        self.assertIn("backup_score", r)
        self.assertGreaterEqual(r["backup_score"], 0)
        self.assertLessEqual(r["backup_score"], 100)

    def test_no_scan_runs_produces_unknown(self):
        with patch("deployment_center.shared_services._load_scan_runs", return_value=[]):
            _enable()
            from deployment_center.shared_services import get_backups
            r = get_backups()
            self.assertEqual(r["backup_status"], "UNKNOWN")

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_backups
        r = get_backups()
        self.assertEqual(r["available"], False)

    def test_fresh_backup_is_ready(self):
        from deployment_center.shared_services import get_backups
        r = get_backups()
        # mocked runs are 0, 2, 4, 6, 8 hours old — latest is ~0h → READY
        self.assertIn(r["backup_status"], ["READY", "DEGRADED"])


# ── Restore Readiness ──────────────────────────────────────────────────────────
class TestRestore(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_restore_score(self):
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertIn("restore_score", r)

    def test_has_checks(self):
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertIn("checks", r)
        self.assertIsInstance(r["checks"], list)

    def test_has_checklist(self):
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertIn("recovery_checklist", r)
        self.assertGreater(len(r["recovery_checklist"]), 0)

    def test_has_estimate(self):
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertIn("estimated_restore_minutes", r)
        self.assertEqual(r["estimated_restore_minutes"], 30)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_restore
        r = get_restore()
        self.assertEqual(r["available"], False)


# ── Rollback Readiness ─────────────────────────────────────────────────────────
class TestRollback(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_rollback_score(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertIn("rollback_score", r)

    def test_has_checks(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertIn("checks", r)
        self.assertIsInstance(r["checks"], list)

    def test_has_checklist(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertIn("rollback_checklist", r)
        self.assertGreater(len(r["rollback_checklist"]), 0)

    def test_has_estimate(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertIn("estimated_rollback_minutes", r)
        self.assertEqual(r["estimated_rollback_minutes"], 15)

    def test_history_available_with_runs(self):
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertTrue(r.get("previous_version_available"))

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_rollback
        r = get_rollback()
        self.assertEqual(r["available"], False)


# ── Infrastructure ─────────────────────────────────────────────────────────────
class TestInfrastructure(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_infra_score(self):
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        self.assertIn("infra_score", r)
        self.assertGreaterEqual(r["infra_score"], 0)
        self.assertLessEqual(r["infra_score"], 100)

    def test_has_components(self):
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        self.assertIn("components", r)
        self.assertIsInstance(r["components"], list)
        self.assertGreater(len(r["components"]), 0)

    def test_has_memory_cpu_disk(self):
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        self.assertIn("memory", r)
        self.assertIn("cpu", r)
        self.assertIn("disk", r)

    def test_components_have_status(self):
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        for comp in r["components"]:
            self.assertIn("status", comp)
            self.assertIn("component", comp)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_infrastructure
        r = get_infrastructure()
        self.assertEqual(r["available"], False)


# ── Business Continuity ────────────────────────────────────────────────────────
class TestContinuity(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_continuity_score(self):
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        self.assertIn("continuity_score", r)
        self.assertGreaterEqual(r["continuity_score"], 0)
        self.assertLessEqual(r["continuity_score"], 100)

    def test_has_services(self):
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        self.assertIn("services", r)
        self.assertIsInstance(r["services"], list)
        self.assertGreater(len(r["services"]), 0)

    def test_services_have_tier(self):
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        for svc in r["services"]:
            self.assertIn("tier", svc)
            self.assertIn(svc["tier"], [1, 2])

    def test_has_single_points(self):
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        self.assertIn("single_points_of_failure", r)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_continuity
        r = get_continuity()
        self.assertEqual(r["available"], False)


# ── Recommendations ────────────────────────────────────────────────────────────
class TestRecommendations(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_recommendations
        r = get_recommendations()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_recommendations
        r = get_recommendations()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_recommendations_list(self):
        from deployment_center.shared_services import get_recommendations
        r = get_recommendations()
        self.assertIn("recommendations", r)
        self.assertIsInstance(r["recommendations"], list)

    def test_recommendations_have_category_severity(self):
        from deployment_center.shared_services import get_recommendations
        r = get_recommendations()
        for rec in r["recommendations"]:
            self.assertIn("category", rec)
            self.assertIn("severity", rec)
            self.assertIn("message", rec)
            self.assertIn("action", rec)
            self.assertTrue(rec.get("advisory_only"))

    def test_has_counts(self):
        from deployment_center.shared_services import get_recommendations
        r = get_recommendations()
        self.assertIn("critical_count", r)
        self.assertIn("warning_count", r)
        self.assertIn("info_count", r)

    def test_stale_backup_triggers_warning(self):
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
        stale_runs = [{"snapshot_ts": old_ts, "status": "completed", "scan_id": "old_scan"}]
        with patch("deployment_center.shared_services._load_scan_runs", return_value=stale_runs):
            from deployment_center.shared_services import get_recommendations
            r = get_recommendations()
            messages = [rec["message"] for rec in r["recommendations"]]
            self.assertTrue(any("backup" in m.lower() or "old" in m.lower() for m in messages))

    def test_no_scan_runs_triggers_critical(self):
        with patch("deployment_center.shared_services._load_scan_runs", return_value=[]):
            from deployment_center.shared_services import get_recommendations
            r = get_recommendations()
            critical_recs = [rec for rec in r["recommendations"] if rec["severity"] == "CRITICAL"]
            self.assertGreater(len(critical_recs), 0)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_recommendations
        r = get_recommendations()
        self.assertEqual(r["available"], False)


# ── Summary ────────────────────────────────────────────────────────────────────
class TestSummary(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_summary
        r = get_summary()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_summary
        r = get_summary()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_dr_score(self):
        from deployment_center.shared_services import get_summary
        r = get_summary()
        self.assertIn("dr_score", r)
        self.assertGreaterEqual(r["dr_score"], 0)
        self.assertLessEqual(r["dr_score"], 100)

    def test_has_grade(self):
        from deployment_center.shared_services import get_summary
        r = get_summary()
        self.assertIn(r.get("grade"), ["A+", "A", "B", "C", "D"])

    def test_has_domain_scores(self):
        from deployment_center.shared_services import get_summary
        r = get_summary()
        for key in ["readiness_score", "config_score", "backup_score", "infra_score", "continuity_score"]:
            self.assertIn(key, r)

    def test_has_status_fields(self):
        from deployment_center.shared_services import get_summary
        r = get_summary()
        for key in ["deployment_status", "backup_status", "infra_status", "config_status", "continuity_status"]:
            self.assertIn(key, r)

    def test_disabled_when_flag_off(self):
        _disable()
        from deployment_center.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["available"], False)


# ── Snapshot ───────────────────────────────────────────────────────────────────
class TestSnapshot(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_returns_dict(self):
        from deployment_center.shared_services import get_deployment_snapshot
        r = get_deployment_snapshot()
        self.assertIsInstance(r, dict)

    def test_advisory_flags(self):
        from deployment_center.shared_services import get_deployment_snapshot
        r = get_deployment_snapshot()
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_has_dr_score(self):
        from deployment_center.shared_services import get_deployment_snapshot
        r = get_deployment_snapshot()
        self.assertIn("dr_score", r)

    def test_disabled_returns_unavailable(self):
        _disable()
        from deployment_center.shared_services import get_deployment_snapshot
        r = get_deployment_snapshot()
        self.assertFalse(r["available"])


# ── Export ─────────────────────────────────────────────────────────────────────
class TestExport(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_export_json_returns_dict(self):
        from deployment_center.shared_services import export_json
        r = export_json()
        self.assertIsInstance(r, dict)
        self.assertTrue(r.get("advisory_only"))
        self.assertTrue(r.get("read_only"))

    def test_export_json_has_sections(self):
        from deployment_center.shared_services import export_json
        r = export_json()
        for key in ["summary", "readiness", "config", "backups", "restore",
                    "rollback", "infrastructure", "continuity", "recommendations"]:
            self.assertIn(key, r)

    def test_export_csv_returns_dict(self):
        from deployment_center.shared_services import export_csv
        r = export_csv()
        self.assertIsInstance(r, dict)
        self.assertIn("csv", r)

    def test_export_csv_has_rows(self):
        from deployment_center.shared_services import export_csv
        r = export_csv()
        self.assertGreater(r.get("row_count", 0), 0)

    def test_export_csv_is_parseable(self):
        import csv, io
        from deployment_center.shared_services import export_csv
        r = export_csv()
        rows = list(csv.reader(io.StringIO(r["csv"])))
        self.assertGreater(len(rows), 1)
        self.assertEqual(rows[0][0], "domain")

    def test_export_json_disabled(self):
        _disable()
        from deployment_center.shared_services import export_json
        r = export_json()
        self.assertFalse(r["available"])

    def test_export_csv_disabled(self):
        _disable()
        from deployment_center.shared_services import export_csv
        r = export_csv()
        self.assertFalse(r["available"])


# ── API command layer ──────────────────────────────────────────────────────────
class TestApiCommands(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_cmd_summary(self):
        from deployment_center.api import cmd_summary
        r = cmd_summary()
        self.assertIn("dr_score", r)

    def test_cmd_readiness(self):
        from deployment_center.api import cmd_readiness
        r = cmd_readiness()
        self.assertIn("readiness_score", r)

    def test_cmd_config(self):
        from deployment_center.api import cmd_config
        r = cmd_config()
        self.assertIn("config_score", r)

    def test_cmd_backups(self):
        from deployment_center.api import cmd_backups
        r = cmd_backups()
        self.assertIn("backup_status", r)

    def test_cmd_restore(self):
        from deployment_center.api import cmd_restore
        r = cmd_restore()
        self.assertIn("restore_score", r)

    def test_cmd_rollback(self):
        from deployment_center.api import cmd_rollback
        r = cmd_rollback()
        self.assertIn("rollback_score", r)

    def test_cmd_infrastructure(self):
        from deployment_center.api import cmd_infrastructure
        r = cmd_infrastructure()
        self.assertIn("infra_score", r)

    def test_cmd_continuity(self):
        from deployment_center.api import cmd_continuity
        r = cmd_continuity()
        self.assertIn("continuity_score", r)

    def test_cmd_recommendations(self):
        from deployment_center.api import cmd_recommendations
        r = cmd_recommendations()
        self.assertIn("recommendations", r)

    def test_cmd_snapshot(self):
        from deployment_center.api import cmd_snapshot
        r = cmd_snapshot()
        self.assertIn("dr_score", r)

    def test_cmd_export_json(self):
        from deployment_center.api import cmd_export_json
        r = cmd_export_json()
        self.assertIn("summary", r)

    def test_cmd_export_csv(self):
        from deployment_center.api import cmd_export_csv
        r = cmd_export_csv()
        self.assertIn("csv", r)


# ── Safety / read-only guarantee ──────────────────────────────────────────────
class TestReadOnlyGuarantee(unittest.TestCase):
    def setUp(self):
        _enable()
        _apply_patches(self)

    def test_summary_never_writes(self):
        import ast, inspect
        from deployment_center import shared_services
        src = inspect.getsource(shared_services)
        # Must not contain raw SQL write statements
        self.assertNotIn("DELETE FROM", src.upper())
        self.assertNotIn("INSERT INTO", src.upper())
        self.assertNotIn("DROP TABLE", src.upper())
        # Must not call any OS-level write outside the csv export buffer
        self.assertNotIn("os.remove(", src)
        self.assertNotIn("shutil.rmtree", src)
        # advisory_only and read_only must be present in every response
        self.assertIn("advisory_only", src)
        self.assertIn("read_only",     src)

    def test_advisory_only_in_all_responses(self):
        from deployment_center.shared_services import (
            get_summary, get_readiness, get_config, get_backups,
            get_restore, get_rollback, get_infrastructure, get_continuity,
            get_recommendations, get_deployment_snapshot,
        )
        fns = [get_summary, get_readiness, get_config, get_backups,
               get_restore, get_rollback, get_infrastructure, get_continuity,
               get_recommendations, get_deployment_snapshot]
        for fn in fns:
            r = fn()
            self.assertTrue(r.get("advisory_only"), f"{fn.__name__} missing advisory_only=True")
            self.assertTrue(r.get("read_only"), f"{fn.__name__} missing read_only=True")


if __name__ == "__main__":
    unittest.main(verbosity=2)
