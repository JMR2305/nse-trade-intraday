"""
test_history.py — Task #257
Unit tests for data_quality.history_store and shared_services.get_history().

All tests use the JSON file fallback (no DATABASE_URL required).
Tests that exercise persist_run() write to a temp file and clean up.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Ensure feature flag is ON for all tests
os.environ["DATA_QUALITY_ENABLED"] = "true"
# Ensure no DATABASE_URL so all tests use the file fallback
os.environ.pop("DATABASE_URL", None)


def _enable():  os.environ["DATA_QUALITY_ENABLED"] = "true"
def _disable(): os.environ["DATA_QUALITY_ENABLED"] = "false"


def _fake_summary(score=80.0, grade="A", critical=0, warning=2) -> dict:
    return {
        "status": "ENABLED", "available": True, "advisory_only": True,
        "quality_score": score, "grade": grade,
        "critical_count": critical, "warning_count": warning,
        "domains": [
            {"domain": "market",    "score": 90.0},
            {"domain": "preopen",   "score": 85.0},
            {"domain": "paper",     "score": 80.0},
            {"domain": "portfolio", "score": 75.0},
            {"domain": "ai",        "score": 70.0},
            {"domain": "signals",   "score": 92.0},
            {"domain": "config",    "score": 65.0},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# history_store — file-fallback tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistoryStoreFallback(unittest.TestCase):
    """All tests use the JSON file fallback (DATABASE_URL absent)."""

    def setUp(self):
        # Patch _FALLBACK_FILE to a per-test temp file
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        os.unlink(self._tmp.name)          # start with no file (missing = empty)
        import data_quality.history_store as hs
        self._orig = hs._FALLBACK_FILE
        hs._FALLBACK_FILE = self._tmp.name
        self._hs = hs
        os.environ.pop("DATABASE_URL", None)

    def tearDown(self):
        self._hs._FALLBACK_FILE = self._orig
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    # ── db_available ──────────────────────────────────────────────────────────
    def test_db_available_false_without_url(self):
        self.assertFalse(self._hs.db_available())

    def test_db_available_true_with_url(self):
        os.environ["DATABASE_URL"] = "postgres://fake"
        self.assertTrue(self._hs.db_available())
        del os.environ["DATABASE_URL"]

    # ── persist_run / get_history ─────────────────────────────────────────────
    def test_empty_history_returns_empty_list(self):
        runs = self._hs.get_history()
        self.assertEqual(runs, [])

    def test_persist_then_retrieve(self):
        summary = _fake_summary(score=82.0, grade="A")
        self._hs.persist_run(summary)
        runs = self._hs.get_history()
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0]["quality_score"], 82.0)
        self.assertEqual(runs[0]["grade"], "A")

    def test_persist_multiple_most_recent_first(self):
        for score in [70.0, 75.0, 80.0, 85.0]:
            self._hs.persist_run(_fake_summary(score=score))
        runs = self._hs.get_history()
        # Most-recent first: last persisted (85) should be first
        self.assertAlmostEqual(runs[0]["quality_score"], 85.0)
        self.assertAlmostEqual(runs[-1]["quality_score"], 70.0)

    def test_get_history_respects_limit(self):
        for score in range(10):
            self._hs.persist_run(_fake_summary(score=float(score * 10)))
        runs = self._hs.get_history(limit=3)
        self.assertEqual(len(runs), 3)

    def test_persist_run_stores_critical_count(self):
        self._hs.persist_run(_fake_summary(score=60.0, critical=3))
        runs = self._hs.get_history()
        self.assertEqual(runs[0]["critical_count"], 3)

    def test_persist_run_stores_warning_count(self):
        self._hs.persist_run(_fake_summary(score=70.0, warning=5))
        runs = self._hs.get_history()
        self.assertEqual(runs[0]["warning_count"], 5)

    def test_persist_run_stores_domain_scores(self):
        self._hs.persist_run(_fake_summary(score=80.0))
        runs = self._hs.get_history()
        ds = runs[0]["domain_scores"]
        self.assertIn("market", ds)
        self.assertAlmostEqual(ds["market"], 90.0)

    def test_fallback_cap_at_max(self):
        # Persist more than _MAX_FALLBACK (30)
        for i in range(35):
            self._hs.persist_run(_fake_summary(score=float(i)))
        runs = self._hs.get_history()
        self.assertLessEqual(len(runs), 30)

    def test_get_history_returns_list_of_dicts(self):
        self._hs.persist_run(_fake_summary())
        runs = self._hs.get_history()
        self.assertIsInstance(runs, list)
        self.assertIsInstance(runs[0], dict)

    def test_run_has_required_fields(self):
        self._hs.persist_run(_fake_summary())
        run = self._hs.get_history()[0]
        for fld in ("run_ts", "quality_score", "grade",
                    "critical_count", "warning_count", "domain_scores"):
            self.assertIn(fld, run)

    def test_run_ts_is_iso_string(self):
        self._hs.persist_run(_fake_summary())
        run = self._hs.get_history()[0]
        self.assertIsInstance(run["run_ts"], str)
        self.assertTrue(run["run_ts"].startswith("20"))

    # ── prune_old_runs ────────────────────────────────────────────────────────
    def test_prune_removes_old_runs(self):
        # Inject an ancient run manually into the fallback file
        ancient = {
            "run_ts": "2020-01-01T00:00:00Z",
            "quality_score": 55.0, "grade": "C",
            "critical_count": 1, "warning_count": 3, "domain_scores": {},
        }
        recent = {
            "run_ts": "2026-07-30T09:00:00Z",
            "quality_score": 82.0, "grade": "A",
            "critical_count": 0, "warning_count": 1, "domain_scores": {},
        }
        with open(self._tmp.name, "w") as f:
            json.dump([ancient, recent], f)

        deleted = self._hs.prune_old_runs(days=90)
        self.assertEqual(deleted, 1)
        runs = self._hs.get_history()
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0]["quality_score"], 82.0)

    def test_prune_no_op_when_all_recent(self):
        self._hs.persist_run(_fake_summary(score=80.0))
        deleted = self._hs.prune_old_runs(days=90)
        self.assertEqual(deleted, 0)

    def test_prune_empty_file_no_error(self):
        # No file → should not raise
        deleted = self._hs.prune_old_runs()
        self.assertEqual(deleted, 0)

    # ── corrupt fallback file ─────────────────────────────────────────────────
    def test_corrupt_fallback_file_returns_empty(self):
        with open(self._tmp.name, "w") as f:
            f.write("NOT_JSON{{{{")
        runs = self._hs.get_history()
        self.assertEqual(runs, [])

    def test_non_list_fallback_file_returns_empty(self):
        with open(self._tmp.name, "w") as f:
            json.dump({"bad": "structure"}, f)
        runs = self._hs.get_history()
        self.assertEqual(runs, [])


# ═══════════════════════════════════════════════════════════════════════════════
# shared_services.get_history() — feature flag + response shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharedServicesGetHistory(unittest.TestCase):
    """Tests for the shared_services.get_history() public API."""

    def setUp(self):
        _enable()
        # Patch the history_store to avoid touching any file/DB
        import data_quality.history_store as hs
        self._hs = hs
        self._orig = hs._FALLBACK_FILE
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        os.unlink(self._tmp.name)
        hs._FALLBACK_FILE = self._tmp.name

    def tearDown(self):
        self._hs._FALLBACK_FILE = self._orig
        _enable()
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def _get_history(self):
        from data_quality.shared_services import get_history
        return get_history()

    def test_disabled_returns_disabled_response(self):
        _disable()
        from data_quality.shared_services import get_history
        r = get_history()
        self.assertEqual(r["status"], "DISABLED")
        _enable()

    def test_history_has_required_fields(self):
        r = self._get_history()
        for fld in ("status", "available", "advisory_only",
                    "total_runs", "runs", "generated_at"):
            self.assertIn(fld, r)

    def test_history_advisory_only_always_true(self):
        self.assertTrue(self._get_history()["advisory_only"])

    def test_history_runs_is_list(self):
        self.assertIsInstance(self._get_history()["runs"], list)

    def test_history_returns_persisted_runs(self):
        self._hs.persist_run(_fake_summary(score=77.0, grade="B"))
        self._hs.persist_run(_fake_summary(score=83.0, grade="A"))
        r = self._get_history()
        self.assertEqual(r["total_runs"], 2)
        # Most-recent first
        self.assertAlmostEqual(r["runs"][0]["quality_score"], 83.0)

    def test_history_status_enabled(self):
        r = self._get_history()
        self.assertEqual(r["status"], "ENABLED")

    def test_history_total_runs_matches_runs_length(self):
        r = self._get_history()
        self.assertEqual(r["total_runs"], len(r["runs"]))


# ═══════════════════════════════════════════════════════════════════════════════
# shared_services.get_summary() — persist_run is called non-blockingly
# ═══════════════════════════════════════════════════════════════════════════════

class TestSummaryPersistsRun(unittest.TestCase):
    """Confirm get_summary() appends a run record and never raises on failure."""

    def setUp(self):
        _enable()
        import data_quality.history_store as hs
        self._hs = hs
        self._orig = hs._FALLBACK_FILE
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        os.unlink(self._tmp.name)
        hs._FALLBACK_FILE = self._tmp.name

    def tearDown(self):
        self._hs._FALLBACK_FILE = self._orig
        _enable()
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def _call_summary(self):
        from data_quality.shared_services import get_summary
        # Patch domain loaders to avoid real data dependencies
        domain = {
            "status": "ENABLED", "available": True, "advisory_only": True,
            "score": 80.0, "grade": "A", "checks_run": 10, "checks_passed": 8,
            "checks_failed": 2, "pass_rate": 80.0, "critical_count": 0,
            "warning_count": 1, "issues": [], "generated_at": "2026-07-30",
        }
        with patch("data_quality.shared_services._load_market",   return_value=domain), \
             patch("data_quality.shared_services._load_preopen",  return_value=domain), \
             patch("data_quality.shared_services._load_paper",    return_value=domain), \
             patch("data_quality.shared_services._load_portfolio",return_value=domain), \
             patch("data_quality.shared_services._load_ai",       return_value=domain), \
             patch("data_quality.shared_services._load_signals",  return_value=domain), \
             patch("data_quality.shared_services._load_config",   return_value=domain):
            return get_summary()

    def test_get_summary_appends_history_run(self):
        self._call_summary()
        runs = self._hs.get_history()
        self.assertEqual(len(runs), 1)

    def test_get_summary_twice_appends_two_runs(self):
        self._call_summary()
        self._call_summary()
        runs = self._hs.get_history()
        self.assertEqual(len(runs), 2)

    def test_get_summary_does_not_raise_when_persist_fails(self):
        """If history_store raises, get_summary() must still return normally."""
        with patch("data_quality.history_store.persist_run",
                   side_effect=RuntimeError("DB down")):
            result = self._call_summary()
        # Summary returned successfully despite persist failure
        self.assertEqual(result["status"], "ENABLED")
        self.assertIn("quality_score", result)

    def test_persisted_run_score_matches_summary_score(self):
        result = self._call_summary()
        runs = self._hs.get_history()
        self.assertAlmostEqual(
            runs[0]["quality_score"], result["quality_score"], places=1
        )


if __name__ == "__main__":
    unittest.main()
