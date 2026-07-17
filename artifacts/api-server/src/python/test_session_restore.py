"""
test_session_restore.py — Priority 2 (#21) tests: archived session review
and guarded restore.

Unit-level, no live network. Uses the local-file fallback storage path
(DATABASE_URL removed inside the tests) so real Postgres state is never
touched — a scratch temp directory is used for all state files.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

PASSED = 0
FAILED = 0


class SessionRestoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="smtest_session_")
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("DATABASE_URL", None)

        import importlib
        import portfolio_store
        import session_archive
        importlib.reload(portfolio_store)
        importlib.reload(session_archive)
        self.ps = portfolio_store
        self.sa = session_archive
        # Redirect all file storage to scratch dir
        self.ps.WARM_CACHE_FILE = os.path.join(self.tmp, "state.json")
        self.ps.ARCHIVE_FALLBACK_FILE = os.path.join(self.tmp, "trades_archive.json")
        self.sa.FALLBACK_FILE = os.path.join(self.tmp, "session_archives.json")

        self.state = {
            "cash": 3200.0,
            "positions": {"TCS": {"quantity": 1, "avg_price": 1800.0}},
            "pnl_history": [{"timestamp": "2026-07-16T10:00:00Z", "value": 5000.0}],
            "trades": [],
        }
        self.ps.save_state(dict(self.state))

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestArchiveCreation(SessionRestoreBase):
    def test_archive_captures_metrics(self):
        rec = self.sa.archive_current_session("test reset")
        self.assertTrue(rec["id"].startswith("arch_"))
        m = rec["metrics"]
        self.assertEqual(m["cash"], 3200.0)
        self.assertEqual(m["open_positions"], 1)
        self.assertEqual(m["portfolio_value"], 5000.0)
        self.assertEqual(rec["reset_reason"], "test reset")
        for key in ("realized_pnl", "unrealized_pnl", "pending_orders",
                    "config_hash", "latest_scan_id"):
            self.assertIn(key, m)

    def test_archive_snapshot_is_complete(self):
        rec = self.sa.archive_current_session("r")
        snap = rec["snapshot"]
        self.assertEqual(snap["cash"], 3200.0)
        self.assertIn("TCS", snap["positions"])
        self.assertEqual(len(snap["pnl_history"]), 1)

    def test_list_and_get(self):
        a = self.sa.archive_current_session("first")
        b = self.sa.archive_current_session("second")
        lst = self.sa.list_archives()
        self.assertEqual([x["id"] for x in lst[:2]], [b["id"], a["id"]])
        self.assertNotIn("snapshot", lst[0])  # list view is metadata-only
        full = self.sa.get_archive(a["id"])
        self.assertIn("snapshot", full)  # inspection includes snapshot

    def test_unreadable_state_blocks_archive(self):
        with mock.patch.object(self.ps, "load_state", return_value=None):
            with self.assertRaises(RuntimeError):
                self.sa.archive_current_session("r")


class TestRestoreGuards(SessionRestoreBase):
    def setUp(self):
        super().setUp()
        self.arch = self.sa.archive_current_session("guard tests")

    def test_wrong_phrase_blocked_step1(self):
        r = self.sa.request_restore(self.arch["id"], "restore paper session")
        self.assertFalse(r["success"])
        self.assertIn("RESTORE PAPER SESSION", r["error"])

    def test_missing_archive_blocked(self):
        r = self.sa.request_restore("arch_nope", "RESTORE PAPER SESSION")
        self.assertFalse(r["success"])

    def test_step1_issues_token_not_restore(self):
        before = self.ps.load_state()
        r = self.sa.request_restore(self.arch["id"], "RESTORE PAPER SESSION")
        self.assertTrue(r["success"])
        self.assertIn("restore_token", r)
        self.assertEqual(self.ps.load_state()["cash"], before["cash"])

    def test_step2_requires_phrase_again(self):
        r1 = self.sa.request_restore(self.arch["id"], "RESTORE PAPER SESSION")
        r2 = self.sa.confirm_restore(self.arch["id"], "yes", r1["restore_token"])
        self.assertFalse(r2["success"])

    def test_step2_requires_valid_token(self):
        self.sa.request_restore(self.arch["id"], "RESTORE PAPER SESSION")
        r = self.sa.confirm_restore(self.arch["id"], "RESTORE PAPER SESSION", "bad-token")
        self.assertFalse(r["success"])
        self.assertIn("token", r["error"].lower())

    def test_token_is_single_use(self):
        r1 = self.sa.request_restore(self.arch["id"], "RESTORE PAPER SESSION")
        tok = r1["restore_token"]
        ok = self.sa.confirm_restore(self.arch["id"], "RESTORE PAPER SESSION", tok)
        self.assertTrue(ok["success"])
        again = self.sa.confirm_restore(self.arch["id"], "RESTORE PAPER SESSION", tok)
        self.assertFalse(again["success"])

    def test_malformed_snapshot_blocked(self):
        items = json.load(open(self.sa.FALLBACK_FILE))
        items[0]["snapshot"]["cash"] = -50
        json.dump(items, open(self.sa.FALLBACK_FILE, "w"))
        r = self.sa.request_restore(self.arch["id"], "RESTORE PAPER SESSION")
        self.assertFalse(r["success"])
        self.assertIn("validation", r["error"])

    def test_failed_backup_blocks_restore(self):
        r1 = self.sa.request_restore(self.arch["id"], "RESTORE PAPER SESSION")
        with mock.patch.object(self.sa, "archive_current_session",
                               side_effect=RuntimeError("backup exploded")):
            r2 = self.sa.confirm_restore(self.arch["id"], "RESTORE PAPER SESSION",
                                         r1["restore_token"])
        self.assertFalse(r2["success"])
        self.assertIn("backup", r2["error"].lower())


class TestRestoreExecution(SessionRestoreBase):
    def test_full_restore_roundtrip(self):
        arch = self.sa.archive_current_session("before change")
        # Simulate the session moving on
        self.ps.save_state({"cash": 100.0, "positions": {}, "pnl_history": [], "trades": []})
        r1 = self.sa.request_restore(arch["id"], "RESTORE PAPER SESSION")
        r2 = self.sa.confirm_restore(arch["id"], "RESTORE PAPER SESSION", r1["restore_token"])
        self.assertTrue(r2["success"])
        restored = self.ps.load_state()
        self.assertEqual(restored["cash"], 3200.0)
        self.assertIn("TCS", restored["positions"])
        # Current session was archived first
        self.assertTrue(r2["backup_archive_id"].startswith("arch_"))
        backup = self.sa.get_archive(r2["backup_archive_id"])
        self.assertEqual(backup["snapshot"]["cash"], 100.0)
        # restored_at stamped
        self.assertIsNotNone(self.sa.get_archive(arch["id"])["restored_at"])

    def test_rollback_on_apply_failure(self):
        arch = self.sa.archive_current_session("rollback test")
        self.ps.save_state({"cash": 777.0, "positions": {}, "pnl_history": [], "trades": []})
        r1 = self.sa.request_restore(arch["id"], "RESTORE PAPER SESSION")

        real_save = self.ps.save_state
        calls = {"n": 0}

        def flaky_save(state):
            calls["n"] += 1
            # First call applying the restore fails; rollback call succeeds
            if calls["n"] == 1:
                raise RuntimeError("disk full")
            real_save(state)

        with mock.patch.object(self.ps, "save_state", side_effect=flaky_save):
            r2 = self.sa.confirm_restore(arch["id"], "RESTORE PAPER SESSION",
                                         r1["restore_token"])
        self.assertFalse(r2["success"])
        self.assertTrue(r2.get("rolled_back"))
        self.assertEqual(self.ps.load_state()["cash"], 777.0)

    def test_restore_never_touches_protected_domains(self):
        """Restore writes only via portfolio_store.save_state — assert no other
        mutating surface is invoked (credentials, evidence, live controls)."""
        arch = self.sa.archive_current_session("scope test")
        r1 = self.sa.request_restore(arch["id"], "RESTORE PAPER SESSION")
        with mock.patch.object(self.ps, "save_state", wraps=self.ps.save_state) as sv:
            r2 = self.sa.confirm_restore(arch["id"], "RESTORE PAPER SESSION",
                                         r1["restore_token"])
        self.assertTrue(r2["success"])
        # save_state is the ONLY mutation path used to apply the snapshot
        self.assertGreaterEqual(sv.call_count, 1)
        for call in sv.call_args_list:
            state = call.args[0]
            self.assertEqual(set(state.keys()),
                             {"cash", "positions", "pnl_history", "trades"})

    def test_audit_events_recorded(self):
        events = []
        with mock.patch.object(self.sa, "_audit",
                               side_effect=lambda *a, **k: events.append(a[0])):
            arch = self.sa.archive_current_session("audit test")
            r1 = self.sa.request_restore(arch["id"], "RESTORE PAPER SESSION")
            self.sa.confirm_restore(arch["id"], "RESTORE PAPER SESSION",
                                    r1["restore_token"])
            self.sa.request_restore(arch["id"], "wrong")
        self.assertIn("session_restored", events)
        self.assertIn("session_restore_blocked", events)


class TestResetIntegration(SessionRestoreBase):
    def test_reset_archives_first(self):
        import importlib
        import paper_trader
        importlib.reload(paper_trader)
        with mock.patch.object(paper_trader, "_store", self.ps):
            import main as main_mod
            importlib.reload(main_mod)
            with mock.patch.object(main_mod, "reset_portfolio") as rp:
                with mock.patch.dict(sys.modules, {"session_archive": self.sa}):
                    out = main_mod.cmd_reset("integration reset")
        self.assertTrue(out["success"])
        self.assertTrue(out["archive_id"].startswith("arch_"))
        rp.assert_called_once()
        recs = self.sa.list_archives()
        self.assertEqual(recs[0]["reset_reason"], "integration reset")


if __name__ == "__main__":
    runner = unittest.main(exit=False, verbosity=1)
    result = runner.result
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"\n{total - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
