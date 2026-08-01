"""
test_performance_center.py — Phase 8.7
76-test suite for the Performance Optimisation & Scalability Framework.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the python dir is on the path
_PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

MOD_SS = "performance_center.shared_services"
MOD_M  = "performance_center.models"


def _with_flag(fn):
    """Run fn with PERFORMANCE_CENTER_ENABLED=true."""
    with patch.dict(os.environ, {"PERFORMANCE_CENTER_ENABLED": "true"}):
        return fn()


# ── Feature flag ──────────────────────────────────────────────────────────────
class TestFeatureFlag(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            env = dict(os.environ)
            env.pop("PERFORMANCE_CENTER_ENABLED", None)
            with patch.dict(os.environ, env, clear=True):
                from performance_center.models import is_enabled
                self.assertFalse(is_enabled())

    def test_enabled_true(self):
        with patch.dict(os.environ, {"PERFORMANCE_CENTER_ENABLED": "true"}):
            from performance_center.models import is_enabled
            self.assertTrue(is_enabled())

    def test_enabled_1(self):
        with patch.dict(os.environ, {"PERFORMANCE_CENTER_ENABLED": "1"}):
            from performance_center.models import is_enabled
            self.assertTrue(is_enabled())

    def test_disabled_response_keys(self):
        from performance_center.models import disabled_response
        r = disabled_response()
        self.assertEqual(r["status"], "DISABLED")
        self.assertFalse(r["available"])
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_summary_disabled_when_flag_off(self):
        with patch.dict(os.environ, {"PERFORMANCE_CENTER_ENABLED": "false"}):
            from performance_center.shared_services import get_performance_summary
            r = get_performance_summary()
            self.assertEqual(r["status"], "DISABLED")


# ── Grade and trend helpers ───────────────────────────────────────────────────
class TestGradeHelpers(unittest.TestCase):
    def _grade(self, score):
        from performance_center.models import perf_grade
        return perf_grade(score)

    def _trend(self, cur, base):
        from performance_center.models import perf_trend
        return perf_trend(cur, base)

    def test_grade_a_plus(self):   self.assertEqual(self._grade(95), "A+")
    def test_grade_a(self):        self.assertEqual(self._grade(85), "A")
    def test_grade_b(self):        self.assertEqual(self._grade(70), "B")
    def test_grade_c(self):        self.assertEqual(self._grade(55), "C")
    def test_grade_d(self):        self.assertEqual(self._grade(40), "D")
    def test_trend_improving(self): self.assertEqual(self._trend(90, 80), "IMPROVING")
    def test_trend_degrading(self): self.assertEqual(self._trend(60, 80), "DEGRADING")
    def test_trend_stable(self):   self.assertEqual(self._trend(75, 75), "STABLE")


# ── API performance ───────────────────────────────────────────────────────────
class TestApiPerformance(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_api_performance
        return _with_flag(get_api_performance)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "request_count", "avg_latency_ms", "targets"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["performance_score"], 0)
        self.assertLessEqual(r["performance_score"], 100)

    def test_grade_valid(self):
        r = self._call()
        self.assertIn(r["grade"], ("A+", "A", "B", "C", "D"))

    def test_targets_present(self):
        r = self._call()
        targets = r["targets"]
        self.assertIn("avg_latency_ms", targets)
        self.assertIn("p95_latency_ms", targets)


# ── Database performance ───────────────────────────────────────────────────────
class TestDatabasePerformance(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_database_performance
        return _with_flag(get_database_performance)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "connection", "targets"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["performance_score"], 0)
        self.assertLessEqual(r["performance_score"], 100)

    def test_connection_has_keys(self):
        r = self._call()
        conn = r["connection"]
        self.assertIn("connected", conn)
        self.assertIn("latency_ms", conn)

    def test_targets_present(self):
        r = self._call()
        self.assertIn("latency_ms", r["targets"])


# ── Cache performance ──────────────────────────────────────────────────────────
class TestCachePerformance(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_cache_performance
        return _with_flag(get_cache_performance)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "cache_hit_rate_est_pct", "stale_entries"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["performance_score"], 0)
        self.assertLessEqual(r["performance_score"], 100)

    def test_hit_rate_range(self):
        r = self._call()
        self.assertGreaterEqual(r["cache_hit_rate_est_pct"], 0)
        self.assertLessEqual(r["cache_hit_rate_est_pct"], 100)

    def test_targets_present(self):
        r = self._call()
        self.assertIn("hit_rate_pct", r["targets"])


# ── Scheduler performance ──────────────────────────────────────────────────────
class TestSchedulerPerformance(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_scheduler_performance
        return _with_flag(get_scheduler_performance)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "scheduler_status", "jobs", "scan_timing"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["performance_score"], 0)
        self.assertLessEqual(r["performance_score"], 100)

    def test_jobs_is_list(self):
        r = self._call()
        self.assertIsInstance(r["jobs"], list)

    def test_scan_timing_keys(self):
        r = self._call()
        timing = r["scan_timing"]
        self.assertIn("run_count", timing)


# ── Resource performance ───────────────────────────────────────────────────────
class TestResourcePerformance(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_resource_performance
        return _with_flag(get_resource_performance)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "memory", "cpu", "disk", "process"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["performance_score"], 0)
        self.assertLessEqual(r["performance_score"], 100)

    def test_memory_keys(self):
        r = self._call()
        for k in ("total_mb", "used_mb", "usage_pct"):
            self.assertIn(k, r["memory"])

    def test_node_process_count(self):
        r = self._call()
        self.assertIn("node_processes", r)
        self.assertIn("count", r["node_processes"])


# ── Frontend performance ───────────────────────────────────────────────────────
class TestFrontendPerformance(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_frontend_performance
        return _with_flag(get_frontend_performance)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "bundle", "page_load"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["performance_score"], 0)
        self.assertLessEqual(r["performance_score"], 100)

    def test_bundle_keys(self):
        r = self._call()
        bundle = r["bundle"]
        self.assertIn("total_kb", bundle)
        self.assertIn("built", bundle)


# ── Scalability estimation ─────────────────────────────────────────────────────
class TestScalability(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_scalability_estimate
        return _with_flag(get_scalability_estimate)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "current_capacity",
                   "recommended_capacity", "multi_agent_readiness"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_capacity_keys(self):
        r = self._call()
        cap = r["current_capacity"]
        self.assertIn("max_symbols_per_scan", cap)
        self.assertIn("concurrent_users", cap)

    def test_agent_list(self):
        r = self._call()
        agents = r["multi_agent_readiness"]["agents"]
        self.assertIsInstance(agents, list)
        self.assertGreater(len(agents), 0)

    def test_max_symbols_positive(self):
        r = self._call()
        self.assertGreater(r["current_capacity"]["max_symbols_per_scan"], 0)


# ── Benchmark ─────────────────────────────────────────────────────────────────
class TestBenchmark(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_benchmark
        return _with_flag(get_benchmark)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "comparison",
                   "trend", "recent_runs"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_trend_valid(self):
        r = self._call()
        self.assertIn(r["trend"], ("IMPROVING", "STABLE", "DEGRADING"))

    def test_comparison_keys(self):
        r = self._call()
        comp = r["comparison"]
        self.assertIn("rolling_average", comp)
        self.assertIn("peak_performance", comp)


# ── Recommendations ───────────────────────────────────────────────────────────
class TestRecommendations(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_recommendations
        return _with_flag(get_recommendations)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "recommendations",
                   "recommendation_count", "critical_count", "warning_count"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_at_least_one_rec(self):
        r = self._call()
        self.assertGreater(len(r["recommendations"]), 0)

    def test_rec_schema(self):
        r = self._call()
        for rec in r["recommendations"]:
            self.assertIn("domain", rec)
            self.assertIn("severity", rec)
            self.assertIn("title", rec)
            self.assertIn("advisory_only", rec)
            self.assertTrue(rec["advisory_only"])

    def test_severity_values(self):
        r = self._call()
        valid = {"INFO", "WARNING", "CRITICAL"}
        for rec in r["recommendations"]:
            self.assertIn(rec["severity"], valid)


# ── Summary ───────────────────────────────────────────────────────────────────
class TestSummary(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_performance_summary
        return _with_flag(get_performance_summary)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only", "performance_score",
                   "grade", "trend", "status", "component_scores", "weights"):
            self.assertIn(k, r)

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_score_range(self):
        r = self._call()
        s = r["performance_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_component_scores_all_present(self):
        r = self._call()
        for key in ("api", "database", "cache", "scheduler", "resources", "frontend"):
            self.assertIn(key, r["component_scores"])

    def test_weights_sum_to_1(self):
        r = self._call()
        total = sum(r["weights"].values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ── Snapshot ──────────────────────────────────────────────────────────────────
class TestSnapshot(unittest.TestCase):
    def _call(self):
        from performance_center.shared_services import get_performance_snapshot
        return _with_flag(get_performance_snapshot)

    def test_keys(self):
        r = self._call()
        for k in ("available", "advisory_only", "read_only",
                   "performance_score", "grade"):
            self.assertIn(k, r)

    def test_available(self):
        r = self._call()
        self.assertTrue(r["available"])

    def test_advisory_only(self):
        r = self._call()
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])


# ── Export ────────────────────────────────────────────────────────────────────
class TestExport(unittest.TestCase):
    def test_json_keys(self):
        from performance_center.shared_services import get_export_json
        r = _with_flag(get_export_json)
        for k in ("available", "advisory_only", "read_only", "summary", "api",
                   "database", "cache", "scheduler"):
            self.assertIn(k, r)

    def test_json_advisory_only(self):
        from performance_center.shared_services import get_export_json
        r = _with_flag(get_export_json)
        self.assertTrue(r["advisory_only"])
        self.assertTrue(r["read_only"])

    def test_csv_has_csv_key(self):
        from performance_center.shared_services import get_export_csv
        r = _with_flag(get_export_csv)
        self.assertIn("csv", r)

    def test_csv_format(self):
        from performance_center.shared_services import get_export_csv
        r = _with_flag(get_export_csv)
        lines = r["csv"].strip().splitlines()
        self.assertGreater(len(lines), 1)
        header = lines[0]
        self.assertIn("domain", header)
        self.assertIn("metric", header)
        self.assertIn("value", header)


# ── API commands ──────────────────────────────────────────────────────────────
class TestApiCommands(unittest.TestCase):
    def test_all_commands_return_dicts(self):
        import performance_center.api as api_mod
        with patch.dict(os.environ, {"PERFORMANCE_CENTER_ENABLED": "true"}):
            for name in dir(api_mod):
                if name.startswith("cmd_"):
                    fn = getattr(api_mod, name)
                    result = fn()
                    self.assertIsInstance(result, dict, f"{name} did not return dict")

    def test_cmd_snapshot_available(self):
        import performance_center.api as api_mod
        with patch.dict(os.environ, {"PERFORMANCE_CENTER_ENABLED": "true"}):
            r = api_mod.cmd_snapshot()
            self.assertTrue(r.get("available"))


if __name__ == "__main__":
    unittest.main()
