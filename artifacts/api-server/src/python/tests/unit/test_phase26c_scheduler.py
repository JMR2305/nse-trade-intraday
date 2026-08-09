"""Phase 26C scheduled session validation — cadence-guard unit tests.

Verifies exactly-once milestone semantics (kv_claim_once), the post-open
grace period, close-milestone behaviour, retry-on-total-failure, and the
FAIL-verdict notification path. File-backed KV in an isolated temp dir;
no DB, no network, suites are stubbed.
"""
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.pop("DATABASE_URL", None)   # force file fallbacks everywhere

import phase20_store as store                     # noqa: E402
import phase26c_scheduler as sched                # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
IN_SESSION = datetime(2026, 8, 7, 11, 30, tzinfo=IST)      # Friday 11:30 IST
JUST_OPENED = datetime(2026, 8, 7, 9, 20, tzinfo=IST)      # within grace
AFTER_GRACE = datetime(2026, 8, 7, 9, 46, tzinfo=IST)      # grace passed


def _ok_report(**over):
    rep = {"verdict": "PASS", "fully_evaluated": True, "result_id": 1}
    rep.update(over)
    return rep


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = store._DIR
        store._DIR = self._tmp.name
        self.notifications = []
        self._notif_patch = mock.patch.object(
            store, "add_notification",
            side_effect=lambda kind, title, body="", severity="INFO",
            context=None: self.notifications.append(
                {"kind": kind, "title": title, "severity": severity,
                 "context": context}))
        self._notif_patch.start()

    def tearDown(self):
        self._notif_patch.stop()
        store._DIR = self._old_dir
        self._tmp.cleanup()

    def patch_now(self, dt):
        import market_hours
        return mock.patch.object(market_hours, "now_ist", return_value=dt)

    def patch_suites(self, results=None, side_effect=None):
        if side_effect is not None:
            return mock.patch.object(sched, "_run_suite",
                                     side_effect=side_effect)
        return mock.patch.object(
            sched, "_run_suite",
            side_effect=lambda name: results[name])

    def run_at(self, mstate, when, results=None):
        if results is None:
            results = {n: _ok_report() for n in sched.SUITES}
        with self.patch_now(when), self.patch_suites(results):
            return sched.maybe_run_session_validation(mstate)


class TestMilestoneGating(Base):
    def test_not_open_not_closed_is_idle(self):
        for state in ("WEEKEND", "HOLIDAY", "PRE_OPEN", "", None):
            self.assertIsNone(sched.maybe_run_session_validation(state))

    def test_open_within_grace_does_not_run(self):
        with self.patch_now(JUST_OPENED):
            self.assertIsNone(sched.maybe_run_session_validation("OPEN"))
        # Nothing claimed — a later tick can still run.
        self.assertTrue(store.kv_claim_once(
            sched._claim_key("2026-08-07", "open", "recovery")))

    def test_open_after_grace_runs_once(self):
        out = self.run_at("OPEN", AFTER_GRACE)
        self.assertTrue(out["ran"])
        self.assertEqual(out["milestone"], "open")
        self.assertEqual(set(out["results"]), set(sched.SUITES))

    def test_close_milestone_runs(self):
        out = self.run_at("CLOSED", IN_SESSION)
        self.assertTrue(out["ran"])
        self.assertEqual(out["milestone"], "close")

    def test_post_close_triggers_close_milestone(self):
        """POST_CLOSE (15:30–16:00 IST) runs the close milestone so results
        exist before the first CLOSED tick builds the 26D daily report —
        and the CLOSED catch-up tick is then deduped."""
        out = self.run_at("POST_CLOSE", IN_SESSION)
        self.assertTrue(out["ran"])
        self.assertEqual(out["milestone"], "close")
        self.assertFalse(self.run_at("CLOSED", IN_SESSION)["ran"])

    def test_open_and_close_are_independent_milestones(self):
        self.assertTrue(self.run_at("OPEN", AFTER_GRACE)["ran"])
        self.assertTrue(self.run_at("CLOSED", IN_SESSION)["ran"])


class TestExactlyOnce(Base):
    def test_second_tick_same_day_is_deduped(self):
        first = self.run_at("OPEN", IN_SESSION)
        second = self.run_at("OPEN", IN_SESSION)
        self.assertTrue(first["ran"])
        self.assertFalse(second["ran"])
        self.assertIn("already ran", second["reason"])

    def test_new_day_runs_again(self):
        self.assertTrue(self.run_at("OPEN", IN_SESSION)["ran"])
        next_day = datetime(2026, 8, 10, 11, 30, tzinfo=IST)  # Monday
        self.assertTrue(self.run_at("OPEN", next_day)["ran"])

    def test_concurrent_ticks_each_suite_runs_once(self):
        """Simulates concurrent scheduler processes hitting the same
        milestone — the flock-serialised file KV must admit each suite
        exactly once in total."""
        calls = []
        lock = threading.Lock()

        def suite(name):
            with lock:
                calls.append(name)
            return _ok_report()

        outs = []
        with self.patch_now(IN_SESSION), \
                mock.patch.object(sched, "_run_suite", side_effect=suite):
            threads = [threading.Thread(
                target=lambda: outs.append(
                    sched.maybe_run_session_validation("OPEN")))
                for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(sorted(calls), sorted(sched.SUITES))

    def test_all_suites_errored_all_retry(self):
        errored = {n: {"verdict": "ERROR", "error": "x"}
                   for n in sched.SUITES}
        out = self.run_at("OPEN", IN_SESSION, results=errored)
        self.assertTrue(out["ran"])
        # All claims released — every suite retries next tick.
        retry = self.run_at("OPEN", IN_SESSION)
        self.assertEqual(set(retry["results"]), set(sched.SUITES))
        self.assertEqual(retry["skipped"], [])

    def test_persist_failure_surfaces_as_error_and_retries(self):
        """A suite that computed a verdict but failed to persist must be
        treated as ERROR (claim released, retried) — an unpersisted
        scheduled run never counts as done."""
        import phase26_recovery
        with mock.patch.object(
                phase26_recovery, "run_recovery_validation",
                return_value={"verdict": "PASS", "fully_evaluated": True,
                              "persist_error": "db down"}):
            result = sched._run_suite("recovery")
        self.assertEqual(result["verdict"], "ERROR")
        self.assertIn("persist failed", result["error"])
        self.assertIn("db down", result["error"])

    def test_partial_error_retries_only_the_failed_suite(self):
        partial = {"recovery": _ok_report(),
                   "performance": {"verdict": "ERROR", "error": "x"},
                   "quality": _ok_report()}
        first = self.run_at("OPEN", IN_SESSION, results=partial)
        self.assertTrue(first["ran"])
        # Next tick: only the errored suite re-runs; completed ones stay
        # claimed (no double-run).
        retry = self.run_at("OPEN", IN_SESSION,
                            results={"performance": _ok_report()})
        self.assertEqual(list(retry["results"]), ["performance"])
        self.assertEqual(sorted(retry["skipped"]), ["quality", "recovery"])
        # Now everything completed — a third tick is fully deduped.
        third = self.run_at("OPEN", IN_SESSION)
        self.assertFalse(third["ran"])
        self.assertIn("already ran", third["reason"])


class TestNotifications(Base):
    def test_all_pass_no_notification(self):
        out = self.run_at("OPEN", IN_SESSION)
        self.assertFalse(out["notified"])
        self.assertEqual(self.notifications, [])

    def test_fail_verdict_raises_critical_notification(self):
        results = {"recovery": _ok_report(verdict="FAIL"),
                   "performance": _ok_report(),
                   "quality": _ok_report(verdict="WARN")}
        out = self.run_at("CLOSED", IN_SESSION, results=results)
        self.assertTrue(out["notified"])
        self.assertEqual(len(self.notifications), 1)
        n = self.notifications[0]
        self.assertEqual(n["kind"], "VALIDATION_FAILED")
        self.assertEqual(n["severity"], "CRITICAL")
        self.assertIn("recovery", n["title"])
        self.assertNotIn("quality", n["title"])   # WARN never alerts
        self.assertEqual(n["context"]["milestone"], "close")

    def test_suite_error_notifies_once_across_retries(self):
        results = {"recovery": _ok_report(),
                   "performance": {"verdict": "ERROR", "error": "kaput"},
                   "quality": _ok_report()}
        out = self.run_at("OPEN", IN_SESSION, results=results)
        self.assertTrue(out["notified"])
        self.assertEqual(self.notifications[0]["kind"], "VALIDATION_FAILED")
        # The errored suite retries next tick and errors again — but the
        # operator alert is NOT repeated (dedup per milestone per suite).
        retry = self.run_at(
            "OPEN", IN_SESSION,
            results={"performance": {"verdict": "ERROR", "error": "kaput"}})
        self.assertFalse(retry["notified"])
        self.assertEqual(len(self.notifications), 1)

    def test_validation_failed_kind_is_emailed(self):
        import email_alerts
        self.assertIn("VALIDATION_FAILED", email_alerts.EMAIL_KINDS)


class TestSchedulerWiring(Base):
    def test_tick_helper_never_raises(self):
        import phase20_scheduler as p20
        with mock.patch.object(sched, "maybe_run_session_validation",
                               side_effect=RuntimeError("boom")):
            out = p20._maybe_run_phase26c_validation("OPEN")
        self.assertFalse(out["ran"])
        self.assertIn("boom", out["error"])

    def test_only_one_phase26c_implementation_exists(self):
        """Guard against a second, conflicting automation path being wired
        in (a duplicated phase26c_auto once caused double daily runs)."""
        import ast
        import phase20_scheduler as p20
        src = open(p20.__file__).read()
        self.assertNotIn("phase26c_auto", src)
        tree = ast.parse(open(sched.__file__).read())  # module still parses
        self.assertTrue(tree)


class TestRunTickIntegration(Base):
    """Integration-style run_tick tests: the real tick path invokes the 26C
    milestone scheduler with exactly-once per suite and notification
    delivery — heavy unrelated tick work is stubbed."""

    def setUp(self):
        super().setUp()
        import phase20_scheduler as p20
        self.p20 = p20
        self.calls = []
        self._patches = [
            mock.patch.object(store, "get_settings", return_value={
                "auto_scan_enabled": True, "scan_interval_minutes": 5}),
            mock.patch.object(store, "update_scheduler_state"),
            mock.patch.object(p20, "_maybe_generate_session_report",
                              return_value=None),
            mock.patch.object(p20, "_maybe_run_eod_reconciliation",
                              return_value=None),
            mock.patch.object(p20, "_maybe_alert_low_coverage",
                              return_value=None),
            mock.patch.object(p20, "_maybe_run_live_validation",
                              return_value=None),
            mock.patch.object(p20, "_manage_paper",
                              return_value={"stubbed": True}),
            mock.patch.object(
                sched, "_run_suite",
                side_effect=lambda name: (self.calls.append(name),
                                          _ok_report())[1]),
        ]
        for p in self._patches:
            p.start()
        # Modules imported inside run_tick — stub via sys.modules.
        self._mods = {}
        for name, attrs in {
            "daily_session_manager":
                {"check_and_maybe_initialize": lambda mstate: None},
            "phase26_reports":
                {"maybe_generate_daily_report": lambda mstate: None},
            "phase24_recommendations":
                {"maybe_run_daily_learning": lambda: None},
            "phase15_scan_context": {"scan_age_seconds": lambda: 30},
        }.items():
            m = mock.MagicMock()
            for a, fn in attrs.items():
                setattr(m, a, mock.MagicMock(side_effect=fn))
            self._mods[name] = sys.modules.get(name)
            sys.modules[name] = m

    def tearDown(self):
        for name, orig in self._mods.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        for p in self._patches:
            p.stop()
        super().tearDown()

    def tick(self, state, when):
        import market_hours
        with mock.patch.object(market_hours, "market_status",
                               return_value={"state": state}), \
                mock.patch.object(market_hours, "now_ist",
                                  return_value=when):
            return self.p20.run_tick()

    def test_open_tick_runs_each_suite_once(self):
        first = self.tick("OPEN", IN_SESSION)
        second = self.tick("OPEN", IN_SESSION)
        self.assertTrue(first["phase26c_validation"]["ran"])
        self.assertEqual(first["phase26c_validation"]["milestone"], "open")
        self.assertFalse(second["phase26c_validation"]["ran"])
        self.assertEqual(sorted(self.calls), sorted(sched.SUITES))

    def test_post_close_then_closed_tick_runs_close_once(self):
        first = self.tick("POST_CLOSE", IN_SESSION)
        second = self.tick("CLOSED", IN_SESSION)
        self.assertTrue(first["phase26c_validation"]["ran"])
        self.assertEqual(first["phase26c_validation"]["milestone"], "close")
        self.assertFalse(second["phase26c_validation"]["ran"])
        self.assertEqual(sorted(self.calls), sorted(sched.SUITES))

    def test_closed_tick_delivers_fail_notification(self):
        with mock.patch.object(
                sched, "_run_suite",
                side_effect=lambda name: _ok_report(
                    verdict="FAIL" if name == "quality" else "PASS")):
            out = self.tick("CLOSED", IN_SESSION)
        self.assertTrue(out["phase26c_validation"]["notified"])
        self.assertEqual(len(self.notifications), 1)
        self.assertEqual(self.notifications[0]["kind"], "VALIDATION_FAILED")
        self.assertEqual(self.notifications[0]["severity"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
