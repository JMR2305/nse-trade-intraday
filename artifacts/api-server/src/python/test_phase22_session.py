"""
test_phase22_session.py — Phase 22: Zerodha session expiry + bulk fetch tests.

All tests are unit-level with mocks — no real broker or network calls.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kite_token_store  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TokenExpiryTests(unittest.TestCase):
    def test_expiry_is_next_6am_ist(self):
        # Created 2026-07-16 10:00 UTC (15:30 IST) → expires 2026-07-17 00:30 UTC
        exp = kite_token_store.token_expiry_utc("2026-07-16T10:00:00Z")
        self.assertIsNotNone(exp)
        self.assertEqual(exp, datetime(2026, 7, 17, 0, 30, tzinfo=timezone.utc))

    def test_expiry_created_before_6am_ist_same_day(self):
        # Created 2026-07-16 23:00 UTC (17-07 04:30 IST) → expires 17-07 06:00 IST
        exp = kite_token_store.token_expiry_utc("2026-07-16T23:00:00Z")
        self.assertEqual(exp, datetime(2026, 7, 17, 0, 30, tzinfo=timezone.utc))

    def test_fresh_token_not_expired(self):
        rec = {"access_token": "x", "created_at": _iso(datetime.now(timezone.utc))}
        self.assertFalse(kite_token_store.is_expired(rec))

    def test_old_token_expired(self):
        rec = {"access_token": "x",
               "created_at": _iso(datetime.now(timezone.utc) - timedelta(days=2))}
        self.assertTrue(kite_token_store.is_expired(rec))

    def test_missing_created_at_is_expired_failsafe(self):
        self.assertTrue(kite_token_store.is_expired({"access_token": "x"}))
        self.assertTrue(kite_token_store.is_expired(
            {"access_token": "x", "created_at": "garbage"}))
        self.assertTrue(kite_token_store.is_expired(None))

    def test_load_filters_expired_token(self):
        stale = {"access_token": "x",
                 "created_at": _iso(datetime.now(timezone.utc) - timedelta(days=3))}
        with mock.patch.object(kite_token_store, "_db_load",
                               return_value=(False, None)), \
             mock.patch("builtins.open", mock.mock_open(
                 read_data=__import__("json").dumps(stale))):
            self.assertIsNone(kite_token_store.load())
            self.assertIsNotNone(kite_token_store.load(include_expired=True))

    def test_metadata_reports_expired(self):
        stale = {"access_token": "x",
                 "created_at": _iso(datetime.now(timezone.utc) - timedelta(days=3))}
        with mock.patch.object(kite_token_store, "load", return_value=stale):
            meta = kite_token_store.metadata()
        self.assertFalse(meta["stored"])
        self.assertTrue(meta["expired"])
        self.assertIsNotNone(meta["expires_at"])
        self.assertNotIn("access_token", meta)

    def test_metadata_fresh_token(self):
        fresh = {"access_token": "x", "created_at": _iso(datetime.now(timezone.utc)),
                 "user_id": "AB1234"}
        with mock.patch.object(kite_token_store, "load", return_value=fresh):
            meta = kite_token_store.metadata()
        self.assertTrue(meta["stored"])
        self.assertFalse(meta["expired"])


class EnvTokenExpiryTests(unittest.TestCase):
    def test_env_token_expired_guard(self):
        import kite_quote_provider as kqp
        old = _iso(datetime.now(timezone.utc) - timedelta(days=2))
        with mock.patch.dict(os.environ, {"ZERODHA_API_KEY": "k",
                                          "ZERODHA_ACCESS_TOKEN": "t",
                                          "ZERODHA_TOKEN_TIMESTAMP": old}), \
             mock.patch.object(kite_token_store, "load", return_value=None):
            self.assertTrue(kqp._env_token_expired())
            api_key, token = kqp._resolve_creds()
            self.assertEqual(token, "")
            self.assertFalse(kqp.kite_available())

    def test_env_token_malformed_timestamp_failsafe_expired(self):
        import kite_quote_provider as kqp
        with mock.patch.dict(os.environ, {"ZERODHA_API_KEY": "k",
                                          "ZERODHA_ACCESS_TOKEN": "t",
                                          "ZERODHA_TOKEN_TIMESTAMP": "garbage"}), \
             mock.patch.object(kite_token_store, "load", return_value=None):
            self.assertTrue(kqp._env_token_expired())
            _, token = kqp._resolve_creds()
            self.assertEqual(token, "")

    def test_session_manager_malformed_timestamp_failsafe(self):
        import kite_session_manager as ksm
        with mock.patch.dict(os.environ, {"ZERODHA_API_KEY": "k",
                                          "ZERODHA_ACCESS_TOKEN": "t",
                                          "ZERODHA_TOKEN_TIMESTAMP": "not-a-date"}), \
             mock.patch.object(kite_token_store, "load", return_value=None):
            _, token = ksm._get_creds()
            self.assertIsNone(token)

    def test_consumers_do_not_reuse_hydrated_token_after_durable_logout(self):
        import importlib
        import broker_client
        import kite_quote_provider as kqp
        import kite_session_manager as ksm
        kts = importlib.import_module("kite_token_store")

        old = {"access_token": "old-token", "created_at": _iso(datetime.now(timezone.utc))}
        try:
            with mock.patch.object(kts, "_db_load", return_value=(True, old)):
                kts.apply_to_env()

            with mock.patch.object(kts, "_db_load", return_value=(True, None)):
                self.assertIsNone(ksm._get_creds()[1])
                self.assertEqual(kqp._resolve_creds()[1], "")
                self.assertIsNone(broker_client._get_creds()[1])
        finally:
            kts.clear_process_hydrated_env()

    def test_env_token_without_timestamp_trusted_without_durable_authority(self):
        import kite_quote_provider as kqp
        env = {"ZERODHA_API_KEY": "k", "ZERODHA_ACCESS_TOKEN": "t"}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kite_token_store, "_db_load",
                               return_value=(False, None)):
            os.environ.pop("ZERODHA_TOKEN_TIMESTAMP", None)
            self.assertFalse(kqp._env_token_expired())
            _, token = kqp._resolve_creds()
            self.assertEqual(token, "t")

    def test_env_token_without_timestamp_fails_closed_with_durable_authority(self):
        import kite_quote_provider as kqp
        env = {"ZERODHA_API_KEY": "k", "ZERODHA_ACCESS_TOKEN": "t"}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kite_token_store, "_db_load",
                               return_value=(True, None)):
            os.environ.pop("ZERODHA_TOKEN_TIMESTAMP", None)
            self.assertFalse(kqp._env_token_expired())
            _, token = kqp._resolve_creds()
            self.assertEqual(token, "")

    def test_env_token_with_fresh_timestamp_trusted_without_durable_authority(self):
        import kite_quote_provider as kqp
        env = {
            "ZERODHA_API_KEY": "k",
            "ZERODHA_ACCESS_TOKEN": "t",
            "ZERODHA_TOKEN_TIMESTAMP": _iso(datetime.now(timezone.utc)),
        }
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(kite_token_store, "_db_load",
                               return_value=(False, None)):
            self.assertFalse(kqp._env_token_expired())
            _, token = kqp._resolve_creds()
            self.assertEqual(token, "t")

    def test_session_manager_ignores_expired_env_token(self):
        import kite_session_manager as ksm
        old = _iso(datetime.now(timezone.utc) - timedelta(days=2))
        with mock.patch.dict(os.environ, {"ZERODHA_API_KEY": "k",
                                          "ZERODHA_ACCESS_TOKEN": "t",
                                          "ZERODHA_TOKEN_TIMESTAMP": old}), \
             mock.patch.object(kite_token_store, "load", return_value=None):
            _, token = ksm._get_creds()
            self.assertIsNone(token)
            self.assertFalse(ksm.creds_present())


class BulkFetchTests(unittest.TestCase):
    def _frame(self, days: int = 120):
        import pandas as pd
        import numpy as np
        idx = pd.date_range(end=datetime.now(timezone.utc).date(),
                            periods=days, freq="D")
        return pd.DataFrame({
            "Open": np.linspace(100, 110, days),
            "High": np.linspace(101, 111, days),
            "Low": np.linspace(99, 109, days),
            "Close": np.linspace(100, 110, days),
            "Volume": np.full(days, 1_000_000),
        }, index=idx)

    def test_bulk_fetch_all_from_single_call(self):
        import pandas as pd
        import ohlcv_cache_store
        from live_data_provider import LiveDataProvider
        syms = ["AAA", "BBB"]
        frames = {f"{s}.NS": self._frame() for s in syms}
        bulk = pd.concat(frames, axis=1)  # MultiIndex (ticker, field)
        p = LiveDataProvider()
        with mock.patch.object(ohlcv_cache_store, "OHLCV_CACHE_ENABLED", False), \
             mock.patch("live_data_provider.yf.download",
                        return_value=bulk) as dl:
            res = p.fetch_batch(syms)
            self.assertEqual(dl.call_count, 1)
        self.assertEqual(set(res), {"AAA", "BBB"})
        for r in res.values():
            self.assertTrue(r.success)
            self.assertEqual(r.data_quality, "LIVE")
            self.assertGreater(r.bars, 100)

    def test_missing_symbol_falls_back_to_per_symbol_path(self):
        import pandas as pd
        import ohlcv_cache_store
        from live_data_provider import LiveDataProvider
        bulk = pd.concat({"AAA.NS": self._frame()}, axis=1)
        p = LiveDataProvider()
        with mock.patch.object(ohlcv_cache_store, "OHLCV_CACHE_ENABLED", False), \
             mock.patch("live_data_provider.yf.download",
                        return_value=bulk), \
             mock.patch.object(p, "fetch_symbol") as fs:
            from live_data_provider import SymbolFetchResult, DataQuality
            fs.return_value = SymbolFetchResult(
                symbol="BBB", success=False, df=None, latest_date=None,
                data_age_days=None, data_quality=DataQuality.UNAVAILABLE,
                data_source="yfinance", fetch_ts="", fetch_latency_ms=0,
                retries_used=3, error="fail", bars=0)
            res = p.fetch_batch(["AAA", "BBB"])
            fs.assert_called_once()
        self.assertTrue(res["AAA"].success)
        self.assertFalse(res["BBB"].success)
        self.assertEqual(res["BBB"].data_quality, "UNAVAILABLE")

    def test_bulk_failure_falls_back_for_all(self):
        import ohlcv_cache_store
        from live_data_provider import LiveDataProvider, SymbolFetchResult, DataQuality
        p = LiveDataProvider()
        with mock.patch.object(ohlcv_cache_store, "OHLCV_CACHE_ENABLED", False), \
             mock.patch("live_data_provider.yf.download",
                        side_effect=RuntimeError("boom")), \
             mock.patch.object(p, "fetch_symbol") as fs:
            fs.return_value = SymbolFetchResult(
                symbol="AAA", success=False, df=None, latest_date=None,
                data_age_days=None, data_quality=DataQuality.UNAVAILABLE,
                data_source="yfinance", fetch_ts="", fetch_latency_ms=0,
                retries_used=3, error="fail", bars=0)
            p.fetch_batch(["AAA", "BBB"])
            self.assertEqual(fs.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
