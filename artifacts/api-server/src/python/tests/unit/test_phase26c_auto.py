"""Task: run 26C recovery/performance/quality checks automatically per session.

Covers: post-close gating, exactly-once per IST day (existing-run skip + KV
claim), claim release on persist failure, and one-area-fails isolation.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import phase26c_store as store                    # noqa: E402
import phase26c_auto as auto                      # noqa: E402


def _report(area, verdict="PASS"):
    return {"area": area, "verdict": verdict,
            "generated_at": datetime.now(timezone.utc).isoformat()}


class TestPhase26cAuto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_results = store.RESULTS_FILE
        self._old_db = os.environ.pop("DATABASE_URL", None)
        store.RESULTS_FILE = os.path.join(self.tmp.name, "results.json")
        self.claims = set()

        def claim_once(key):
            if key in self.claims:
                return False
            self.claims.add(key)
            return True

        self.kv = mock.MagicMock()
        self.kv.kv_claim_once.side_effect = claim_once
        self.kv.kv_release.side_effect = lambda k: self.claims.discard(k)
        self.kv_patch = mock.patch.dict(
            sys.modules, {"phase20_store": self.kv})
        self.kv_patch.start()

    def tearDown(self):
        self.kv_patch.stop()
        store.RESULTS_FILE = self._old_results
        if self._old_db is not None:
            os.environ["DATABASE_URL"] = self._old_db
        self.tmp.cleanup()

    def _patch_runners(self, **overrides):
        runners = {a: (lambda a=a: _report(a)) for a in store.AREAS}
        runners.update(overrides)
        return mock.patch.object(auto, "_runners", lambda: runners)

    def test_not_closed_returns_none(self):
        for state in ("OPEN", "PRE_OPEN", "", "unknown"):
            self.assertIsNone(auto.maybe_run_session_validations(state))

    def test_runs_all_areas_once_post_close(self):
        with self._patch_runners():
            out = auto.maybe_run_session_validations("CLOSED")
        self.assertEqual(len(out["ran"]), 3)
        for area in store.AREAS:
            self.assertEqual(len(store.list_results(area, limit=10)), 1)

    def test_second_tick_skips_all(self):
        with self._patch_runners():
            auto.maybe_run_session_validations("CLOSED")
            out = auto.maybe_run_session_validations("CLOSED")
        self.assertEqual(out["ran"], [])
        self.assertEqual(sorted(out["skipped"]), sorted(store.AREAS))
        for area in store.AREAS:
            self.assertEqual(len(store.list_results(area, limit=10)), 1)

    def test_lost_kv_claim_means_skip(self):
        # Another process already claimed every area today.
        today = datetime.now(auto.IST).date().isoformat()
        for area in store.AREAS:
            self.claims.add(f"p26c_auto:{area}:{today}")
        with self._patch_runners():
            out = auto.maybe_run_session_validations("CLOSED")
        self.assertEqual(out["ran"], [])
        for area in store.AREAS:
            self.assertEqual(store.list_results(area, limit=10), [])

    def test_one_area_failure_never_blocks_others(self):
        def boom():
            raise RuntimeError("collector exploded")
        with self._patch_runners(RECOVERY=boom):
            out = auto.maybe_run_session_validations("CLOSED")
        self.assertEqual(len(out["ran"]), 2)
        self.assertIn("RECOVERY", out["errors"])
        self.assertEqual(store.list_results("RECOVERY", limit=10), [])
        self.assertEqual(len(store.list_results("QUALITY", limit=10)), 1)

    def test_persist_failure_releases_claim_for_retry(self):
        with self._patch_runners(), \
             mock.patch.object(store, "append_result",
                               side_effect=RuntimeError("db down")):
            out = auto.maybe_run_session_validations("CLOSED")
        self.assertEqual(out["ran"], [])
        self.assertEqual(len(out["errors"]), 3)
        self.assertEqual(self.claims, set())   # all claims released
        # Next tick (store healthy again) succeeds.
        with self._patch_runners():
            out2 = auto.maybe_run_session_validations("CLOSED")
        self.assertEqual(len(out2["ran"]), 3)

    def test_never_raises(self):
        with mock.patch.object(auto, "_runners",
                               side_effect=RuntimeError("import broke")):
            out = auto.maybe_run_session_validations("CLOSED")
        self.assertIsInstance(out, dict)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()


class TestPostCloseAndDurableIdempotency(TestPhase26cAuto):
    def test_post_close_triggers_runs(self):
        with self._patch_runners():
            out = auto.maybe_run_session_validations("POST_CLOSE")
        self.assertEqual(len(out["ran"]), 3)

    def test_day_scoped_result_id_is_deterministic(self):
        today = datetime.now(auto.IST).date().isoformat()
        with self._patch_runners():
            out = auto.maybe_run_session_validations("POST_CLOSE")
        ids = sorted(r["result_id"] for r in out["ran"])
        self.assertEqual(ids, sorted(
            f"auto-{a.lower()}-{today}" for a in store.AREAS))

    def test_duplicate_persist_is_idempotent_even_past_claim(self):
        # Simulate two processes racing past the KV guard: same day-scoped
        # result_id → the store keeps a single row.
        with self._patch_runners():
            auto.maybe_run_session_validations("POST_CLOSE")
        self.claims.clear()                      # second process, fresh claims
        # Erase the _ran_today short-circuit by pretending list check fails
        with self._patch_runners(), \
             mock.patch.object(auto, "_ran_today", return_value=False):
            auto.maybe_run_session_validations("CLOSED")
        for area in store.AREAS:
            self.assertEqual(len(store.list_results(area, limit=10)), 1)
