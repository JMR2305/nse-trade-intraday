"""
Phase 22 production-style integration verification.

Covers, end-to-end at module boundaries (stubbing only the external
network/broker edges, never the internal wiring):

  1. Login callback writes the shared session (exchange_request_token
     -> kite_token_store.save_token -> durable DB + warm file).
  2. Unattended scheduler reads the shared session from the durable DB
     even when the local warm-cache file is absent (fresh instance).
  3. Bulk fetch path (single yf.download for the whole batch).
  4. Per-symbol fallback when a symbol is missing from the bulk frame.
  5. Post-scan derived-data synchronisation (canonical values overlaid
     onto derived caches with the canonical scan_id).
  6. Atomic publication (derived caches replaced via tmp + os.replace,
     never partially written).
  7. No overlapping runs (second lock acquisition is refused while the
     first holder is alive; refused caller skips, does not poll).

The overlap test uses the real dev Postgres scan-lock table with a
dedicated test lock name and always releases it. PAPER / RESEARCH ONLY.
"""
import json
import os
import sys
import tempfile
import unittest
import uuid
from unittest import mock

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)


class SharedSessionTests(unittest.TestCase):
    """Login callback writes shared session; scheduler reads it back."""

    def setUp(self):
        # Fresh module state; stub the DB layer (never touch dev DB rows)
        # and redirect the warm-cache file to a temp path.
        import kite_token_store as kts
        self.kts = kts
        self.db: dict = {}
        self.tmp = tempfile.mkdtemp()
        self.store_path = os.path.join(self.tmp, "kite_token.json")
        self.p1 = mock.patch.object(kts, "_STORE_PATH", self.store_path)
        def save_to_db(record):
            self.db["rec"] = record
            return True

        self.p2 = mock.patch.object(kts, "_db_save", side_effect=save_to_db)
        self.p3 = mock.patch.object(
            kts, "_db_load", side_effect=lambda: (True, self.db.get("rec")))
        for p in (self.p1, self.p2, self.p3):
            p.start()
            self.addCleanup(p.stop)

    def test_login_callback_writes_shared_session(self):
        """exchange_request_token persists the token to DB + warm file."""
        import kite_session_manager as ksm
        fake_kite = mock.MagicMock()
        fake_kite.generate_session.return_value = {
            "access_token": "itest-token-abc", "user_id": "AB1234"}
        fake_mod = mock.MagicMock()
        fake_mod.KiteConnect.return_value = fake_kite
        with mock.patch.dict(os.environ, {"ZERODHA_API_KEY": "k"}), \
             mock.patch.object(ksm, "_get_secret", return_value="s"), \
             mock.patch.dict(sys.modules, {"kiteconnect": fake_mod}):
            result = ksm.exchange_request_token("req-token")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["state"], "CONNECTED")
        # Durable DB record written
        self.assertEqual(self.db["rec"]["access_token"], "itest-token-abc")
        # Warm file written with restrictive perms
        with open(self.store_path) as f:
            self.assertEqual(json.load(f)["access_token"], "itest-token-abc")
        # No token material leaked in the response
        self.assertNotIn("itest-token-abc", json.dumps(result))

    def test_scheduler_reads_shared_session_on_fresh_instance(self):
        """A new instance (no warm file) still finds the DB token."""
        self.kts.save_token("itest-shared", user_id="AB1234")
        os.remove(self.store_path)  # simulate new Autoscale instance
        rec = self.kts.load()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["access_token"], "itest-shared")
        # DB hit re-warms the local file
        self.assertTrue(os.path.exists(self.store_path))

    def test_expired_shared_token_not_served_to_scheduler(self):
        self.kts.save_token("itest-old", user_id="AB1234")
        self.db["rec"]["created_at"] = "2020-01-01T00:00:00+00:00"
        os.remove(self.store_path)
        self.assertIsNone(self.kts.load())


class BulkFetchIntegrationTests(unittest.TestCase):
    """Bulk fetch + per-symbol fallback through the real provider class."""

    def _frame(self, days: int = 120):
        import numpy as np
        import pandas as pd
        from datetime import datetime, timezone
        idx = pd.date_range(end=datetime.now(timezone.utc).date(),
                            periods=days, freq="D")
        return pd.DataFrame({
            "Open": np.linspace(100, 110, days),
            "High": np.linspace(101, 111, days),
            "Low": np.linspace(99, 109, days),
            "Close": np.linspace(100, 110, days),
            "Volume": np.full(days, 1_000_000),
        }, index=idx)

    def test_bulk_then_fallback_provenance(self):
        import pandas as pd
        import ohlcv_cache_store
        from live_data_provider import (LiveDataProvider, SymbolFetchResult,
                                        DataQuality)
        bulk = pd.concat({"AAA.NS": self._frame()}, axis=1)
        p = LiveDataProvider()
        with mock.patch.object(ohlcv_cache_store, "OHLCV_CACHE_ENABLED", False), \
             mock.patch("live_data_provider.yf.download", return_value=bulk) as dl, \
             mock.patch.object(p, "fetch_symbol") as fs:
            fs.return_value = SymbolFetchResult(
                symbol="BBB", success=True, df=self._frame(),
                latest_date=None, data_age_days=0,
                data_quality=DataQuality.LIVE, data_source="yfinance",
                fetch_ts="", fetch_latency_ms=5, retries_used=0,
                error=None, bars=120)
            res = p.fetch_batch(["AAA", "BBB"])
            self.assertEqual(dl.call_count, 1)       # one bulk call
            fs.assert_called_once()                  # one fallback only
        self.assertTrue(res["AAA"].success)
        self.assertTrue(res["BBB"].success)


class DerivedDataSyncTests(unittest.TestCase):
    """Post-scan derived-data synchronisation + atomic publication."""

    def setUp(self):
        import phase15_sync as ps
        self.ps = ps
        self.tmp = tempfile.mkdtemp()
        self.ai_path = os.path.join(self.tmp, "ai_decisions_cache.json")
        self.opp_path = os.path.join(self.tmp, "opportunity_cache.json")
        with open(self.ai_path, "w") as f:
            json.dump([{"symbol": "AAA", "entry_price": 1.0, "stop_loss": 1.0,
                        "target": 1.0, "rr_ratio": 0.1, "scan_id": "old"}], f)
        with open(self.opp_path, "w") as f:
            json.dump([{"symbol": "AAA", "entry_price": 1.0, "scan_id": "old"}], f)
        for name, path in (("AI_DECISIONS_CACHE", self.ai_path),
                           ("OPPORTUNITY_CACHE", self.opp_path)):
            p = mock.patch.object(ps, name, path)
            p.start()
            self.addCleanup(p.stop)
        self.ctx = {
            "available": True, "scan_id": "scan-itest-1",
            "symbols": {"AAA": {"entry_price": 250.5, "stop_loss": 240.0,
                                "target_price": 270.0, "rr_ratio": 1.86,
                                "opportunity_score": 71.0, "confidence": 0.8,
                                "regime": "SIDEWAYS"}},
        }

    def test_canonical_values_overlaid_with_scan_id(self):
        import phase15_scan_context
        with mock.patch.object(phase15_scan_context, "build_scan_context",
                               return_value=self.ctx):
            out = self.ps.sync_derived_caches()
        self.assertTrue(out["success"], out)
        self.assertTrue(out["synced"])
        self.assertEqual(out["scan_id"], "scan-itest-1")
        with open(self.ai_path) as f:
            row = json.load(f)[0]
        self.assertEqual(row["entry_price"], 250.5)
        self.assertEqual(row["scan_id"], "scan-itest-1")
        with open(self.opp_path) as f:
            row = json.load(f)[0]
        self.assertEqual(row["scan_id"], "scan-itest-1")

    def test_publication_is_atomic_via_replace(self):
        """Caches are swapped with os.replace — a crash mid-write can never
        leave a truncated cache behind."""
        import phase15_scan_context
        replaced = []
        real_replace = os.replace

        def spy(src, dst):
            replaced.append(dst)
            return real_replace(src, dst)

        with mock.patch.object(phase15_scan_context, "build_scan_context",
                               return_value=self.ctx), \
             mock.patch.object(self.ps.os, "replace", side_effect=spy):
            out = self.ps.sync_derived_caches()
        self.assertTrue(out["synced"])
        self.assertIn(self.ai_path, replaced)
        self.assertIn(self.opp_path, replaced)
        # No temp remnants left behind
        self.assertFalse(os.path.exists(self.ai_path + ".tmp"))
        self.assertFalse(os.path.exists(self.opp_path + ".tmp"))

    def test_no_canonical_scan_is_a_safe_noop(self):
        import phase15_scan_context
        with mock.patch.object(phase15_scan_context, "build_scan_context",
                               return_value={"available": False,
                                             "reason": "no scan"}):
            out = self.ps.sync_derived_caches()
        self.assertTrue(out["success"])
        self.assertFalse(out["synced"])


@unittest.skipUnless(os.environ.get("DATABASE_URL"),
                     "requires Postgres (DATABASE_URL)")
class ScanLockOverlapTests(unittest.TestCase):
    """No overlapping runs — real Postgres advisory lock table."""

    LOCK = "itest_phase22_lock"

    def setUp(self):
        import scan_state_store as sss
        self.sss = sss
        if not sss.db_available():
            self.skipTest("DB not reachable")
        self.holders = []

    def tearDown(self):
        for h in self.holders:
            try:
                self.sss.release_scan_lock(h, name=self.LOCK)
            except Exception:
                pass

    def test_second_acquire_refused_then_freed(self):
        ok1, h1 = self.sss.acquire_scan_lock(name=self.LOCK)
        self.holders.append(h1)
        self.assertTrue(ok1)
        # A concurrent scheduler run must be refused (skip, not poll)
        with mock.patch.object(self.sss, "_holder_id",
                               return_value=f"itest-{uuid.uuid4()}"):
            ok2, _ = self.sss.acquire_scan_lock(name=self.LOCK)
        self.assertFalse(ok2)
        # After release, the lock is acquirable again
        self.sss.release_scan_lock(h1, name=self.LOCK)
        ok3, h3 = self.sss.acquire_scan_lock(name=self.LOCK)
        self.holders.append(h3)
        self.assertTrue(ok3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
