"""
test_phase19b.py — Phase 19B: production rescan + durable scan state tests.

Runs against the file-fallback store (DATABASE_URL unset) so tests are
hermetic; the DB and file paths share identical semantics by design.
Paper trading / research only.
"""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import scan_state_store as store


def _snapshot(scan_id="abc123", snapshot_ts=None, requested=50, received=48):
    ts = snapshot_ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "scan_id": scan_id,
        "snapshot_ts": ts,
        "recommendations": [],
        "summary": {"scan_id": scan_id, "snapshot_ts": ts},
        "scan_audit": {"scan_completed_ts": ts},
        "provider_health": {
            "provider": "Yahoo Finance",
            "symbols_requested": requested,
            "symbols_succeeded": received,
            "symbols_stale": 0,
            "symbols_unavailable": requested - received,
            "unavailable_symbols": ["ETERNAL", "JIOFIN"][: requested - received],
            "stale_symbols": [],
        },
        "safety": {
            "research_only": True,
            "paper_trading_only": True,
            "no_real_orders": True,
            "data_provider": "Zerodha Kite Connect (LTP overlay)",
        },
    }


class Phase19BStoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        patches = {
            "FALLBACK_SNAPSHOT_FILE": os.path.join(d, "snap.json"),
            "FALLBACK_META_FILE": os.path.join(d, "meta.json"),
            "FALLBACK_LOCK_FILE": os.path.join(d, "lock.json"),
        }
        for k, v in patches.items():
            p = mock.patch.object(store, k, v)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("DATABASE_URL", None)


class TestScanStateStore(Phase19BStoreBase):
    def test_save_and_load_snapshot(self):
        snap = _snapshot()
        store.save_successful_scan(snap)
        loaded = store.load_latest_snapshot()
        self.assertEqual(loaded["scan_id"], "abc123")

    def test_manual_scan_updates_scan_id_and_completed_at(self):
        store.save_successful_scan(_snapshot(scan_id="first"))
        m1 = store.load_latest_meta()
        ts2 = (datetime.now(timezone.utc) + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        store.save_successful_scan(_snapshot(scan_id="second", snapshot_ts=ts2))
        m2 = store.load_latest_meta()
        self.assertNotEqual(m1["scan_id"], m2["scan_id"])
        self.assertEqual(m2["scan_id"], "second")
        self.assertNotEqual(m1["completed_at"], m2["completed_at"])

    def test_failed_scan_preserves_previous_snapshot(self):
        store.save_successful_scan(_snapshot(scan_id="good"))
        before = store.load_latest_snapshot()
        store.record_failed_scan("provider exploded")
        after = store.load_latest_snapshot()
        self.assertEqual(after["scan_id"], "good")
        self.assertEqual(before["snapshot_ts"], after["snapshot_ts"])

    def test_missing_symbols_reported_explicitly(self):
        store.save_successful_scan(_snapshot(requested=50, received=48))
        meta = store.load_latest_meta()
        self.assertEqual(meta["symbols_requested"], 50)
        self.assertEqual(meta["symbols_received"], 48)
        self.assertEqual(meta["symbols_missing"], 2)
        self.assertEqual(sorted(meta["missing_symbols"]), ["ETERNAL", "JIOFIN"])

    def test_meta_includes_required_fields(self):
        store.save_successful_scan(_snapshot())
        meta = store.load_latest_meta()
        for field in ("scan_id", "status", "started_at", "completed_at",
                      "snapshot_ts", "provider"):
            self.assertIn(field, meta)
            self.assertTrue(meta[field])
        self.assertEqual(meta["status"], "SUCCESS")


class TestScanLock(Phase19BStoreBase):
    def test_concurrent_acquire_only_one_wins(self):
        ok1, h1 = store.acquire_scan_lock()
        ok2, _h2 = store.acquire_scan_lock()
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        store.release_scan_lock(h1)

    def test_release_allows_reacquire(self):
        ok1, h1 = store.acquire_scan_lock()
        self.assertTrue(ok1)
        store.release_scan_lock(h1)
        ok2, h2 = store.acquire_scan_lock()
        self.assertTrue(ok2)
        store.release_scan_lock(h2)

    def test_expired_stuck_lock_recovers(self):
        ok1, _h1 = store.acquire_scan_lock(timeout_s=0.5)
        self.assertTrue(ok1)
        time.sleep(0.6)  # lease expires — simulates a crashed scanner
        ok2, h2 = store.acquire_scan_lock()
        self.assertTrue(ok2)
        store.release_scan_lock(h2)


class TestStaleness(Phase19BStoreBase):
    def test_stale_banner_clears_only_after_fresh_scan(self):
        import phase15_scan_context as ctx
        with mock.patch.object(ctx, "SCAN_CACHE", store.FALLBACK_SNAPSHOT_FILE):
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
            store.save_successful_scan(_snapshot(scan_id="old", snapshot_ts=old_ts))
            self.assertGreater(ctx.scan_age_seconds(), ctx.STALE_AFTER_S)
            store.save_successful_scan(_snapshot(scan_id="fresh"))
            self.assertLess(ctx.scan_age_seconds(), ctx.STALE_AFTER_S)

    def test_failed_scan_keeps_stale_state(self):
        import phase15_scan_context as ctx
        with mock.patch.object(ctx, "SCAN_CACHE", store.FALLBACK_SNAPSHOT_FILE):
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
            store.save_successful_scan(_snapshot(scan_id="old", snapshot_ts=old_ts))
            store.record_failed_scan("network down")
            self.assertGreater(ctx.scan_age_seconds(), ctx.STALE_AFTER_S)

    def test_stale_scan_disables_buy_recommendations(self):
        import phase15_scan_context as ctx
        with mock.patch.object(ctx, "SCAN_CACHE", store.FALLBACK_SNAPSHOT_FILE):
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
            snap = _snapshot(scan_id="old", snapshot_ts=old_ts)
            snap["recommendations"] = [{
                "symbol": "RELIANCE", "final_action": "BUY", "error": None,
                "opportunity_score": 80, "entry_price": 100, "stop_loss": 95,
                "target_price": 110,
            }]
            store.save_successful_scan(snap)
            built = ctx.build_scan_context()
            self.assertTrue(built["stale"])
            self.assertTrue(built["buy_recommendations_disabled"])
            sym = built["symbols"]["RELIANCE"]
            self.assertEqual(sym["effective_action"], "WATCH")


class TestTimestamps(unittest.TestCase):
    def test_market_scanner_scanned_at_is_utc_zulu(self):
        # scanned_at must be tz-aware UTC "Z" so the browser converts to IST.
        with open(os.path.join(os.path.dirname(__file__), "market_scanner.py")) as f:
            src = f.read()
        self.assertIn('datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")', src)
        self.assertNotIn("datetime.now().isoformat()", src)

    def test_zulu_ts_converts_to_ist_correctly(self):
        from zoneinfo import ZoneInfo
        dt = datetime(2026, 7, 16, 9, 42, 0, tzinfo=timezone.utc)
        ist = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        self.assertEqual((ist.hour, ist.minute), (15, 12))


class TestSafetyInvariants(Phase19BStoreBase):
    def test_paper_trading_remains_enabled(self):
        store.save_successful_scan(_snapshot())
        snap = store.load_latest_snapshot()
        self.assertTrue(snap["safety"]["paper_trading_only"])
        self.assertTrue(snap["safety"]["no_real_orders"])

    def test_no_live_order_commands_exposed(self):
        with open(os.path.join(os.path.dirname(__file__), "main.py")) as f:
            src = f.read()
        for cmd in ("place_live_order", "live_order", "real_order"):
            self.assertNotIn(f'command == "{cmd}"', src)

    def test_stale_after_limit_not_weakened(self):
        import phase15_scan_context as ctx
        self.assertEqual(ctx.STALE_AFTER_S, 90 * 60)


class TestSharedStateAcrossInstances(Phase19BStoreBase):
    def test_second_reader_sees_latest_snapshot(self):
        # Simulates two Autoscale instances sharing the durable store: any
        # reader that goes through the store loader sees the newest write.
        store.save_successful_scan(_snapshot(scan_id="written-by-instance-A"))
        loaded = store.load_latest_snapshot()
        self.assertEqual(loaded["scan_id"], "written-by-instance-A")
        meta = store.load_latest_meta()
        self.assertEqual(meta["scan_id"], "written-by-instance-A")


if __name__ == "__main__":
    unittest.main()
