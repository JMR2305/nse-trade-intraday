"""Fail-safe tests for the durable Kite instrument master."""

from __future__ import annotations

import copy
import fcntl
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import kite_instrument_cache as cache


def _complete_candidate(count: int = cache.MIN_TOTAL_INSTRUMENTS):
    rows = []
    for index in range(count):
        rows.append({
            "symbol": f"SYM{index}",
            "name": f"Company {index}",
            "token": index + 1,
            "exchange": "NSE",
            "segment": "NSE",
            "instrument_type": "EQ" if index < cache.MIN_NSE_EQ_INSTRUMENTS else "BE",
            "lot_size": 1,
            "tick_size": 0.05,
        })
    return rows


@contextmanager
def _acquired_guard():
    yield True


class KiteInstrumentCacheSafetyTests(unittest.TestCase):
    def setUp(self):
        self.good = {
            "date": cache._today_iso(),
            "fetched_at": "2026-08-28T04:00:00Z",
            "provider": "ZERODHA_KITE",
            "complete": True,
            "count": cache.MIN_TOTAL_INSTRUMENTS,
            "instruments": _complete_candidate(),
        }

    def _refresh(self, candidate):
        saved = []
        with (
            patch.object(cache, "_sync_guard", _acquired_guard),
            patch.object(cache, "_load_cache", return_value=copy.deepcopy(self.good)),
            patch.object(cache, "_fetch_from_kite", return_value=candidate),
            patch.object(
                cache,
                "_promote_cache",
                side_effect=lambda value, status, previous: saved.append(value),
            ),
            patch.object(cache, "_persist_failure"),
        ):
            result = cache.refresh(force=True)
        return result, saved

    def test_complete_fetch_is_promoted(self):
        result, saved = self._refresh(_complete_candidate())
        self.assertTrue(result["success"])
        self.assertTrue(result["refreshed"])
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0]["complete"])

    def test_one_row_fetch_preserves_last_known_good(self):
        result, saved = self._refresh(_complete_candidate(1))
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "instrument_candidate_incomplete")
        self.assertEqual(result["preserved_count"], cache.MIN_TOTAL_INSTRUMENTS)
        self.assertEqual(saved, [])

    def test_empty_fetch_preserves_last_known_good(self):
        result, saved = self._refresh([])
        self.assertFalse(result["success"])
        self.assertEqual(saved, [])

    def test_provider_timeout_preserves_last_known_good(self):
        with (
            patch.object(cache, "_sync_guard", _acquired_guard),
            patch.object(cache, "_load_cache", return_value=copy.deepcopy(self.good)),
            patch.object(cache, "_fetch_from_kite", side_effect=TimeoutError("provider timeout")),
            patch.object(cache, "_promote_cache") as save,
            patch.object(cache, "_persist_failure"),
        ):
            result = cache.refresh(force=True)
        self.assertFalse(result["success"])
        save.assert_not_called()

    def test_malformed_rows_preserve_last_known_good(self):
        candidate = _complete_candidate()
        candidate[0] = {"symbol": "", "token": None}
        result, saved = self._refresh(candidate)
        self.assertFalse(result["success"])
        self.assertIn("parse_failures_present", result["validation"]["errors"])
        self.assertEqual(saved, [])

    def test_duplicate_tokens_fail_promotion(self):
        candidate = _complete_candidate()
        candidate[1]["token"] = candidate[0]["token"]
        result, saved = self._refresh(candidate)
        self.assertFalse(result["success"])
        self.assertEqual(result["validation"]["duplicate_token_count"], 1)
        self.assertEqual(saved, [])

    def test_duplicate_symbols_fail_promotion(self):
        candidate = _complete_candidate()
        candidate[1]["symbol"] = candidate[0]["symbol"]
        result, saved = self._refresh(candidate)
        self.assertFalse(result["success"])
        self.assertEqual(result["validation"]["duplicate_symbol_count"], 1)
        self.assertEqual(saved, [])

    def test_material_count_regression_preserves_last_known_good(self):
        self.good["instruments"] = _complete_candidate(6_000)
        self.good["count"] = 6_000
        result, saved = self._refresh(_complete_candidate(5_000))
        self.assertFalse(result["success"])
        self.assertIn("material_count_regression", result["validation"]["errors"])
        self.assertEqual(saved, [])

    def test_incomplete_cache_is_never_fresh(self):
        value = {
            "date": cache._today_iso(),
            "complete": False,
            "instruments": [{"symbol": "RELIANCE"}],
        }
        self.assertFalse(cache._cache_is_fresh(value))

    def test_complete_current_session_cache_is_fresh(self):
        value = {
            "date": cache._today_iso(),
            "complete": True,
            "instruments": [{"symbol": "RELIANCE"}],
        }
        self.assertTrue(cache._cache_is_fresh(value))

    def test_busy_sync_does_not_fetch_or_write(self):
        @contextmanager
        def busy_guard():
            yield False

        with (
            patch.object(cache, "_sync_guard", busy_guard),
            patch.object(cache, "_fetch_from_kite") as fetch,
            patch.object(cache, "_promote_cache") as save,
        ):
            result = cache.refresh(force=True)
        self.assertEqual(result["error"], "instrument_sync_already_running")
        fetch.assert_not_called()
        save.assert_not_called()

    def test_refreshes_are_serialized_by_guard_contract(self):
        entered = []
        lock = threading.Lock()

        @contextmanager
        def guarded():
            with lock:
                entered.append(threading.get_ident())
                yield True

        with (
            patch.object(cache, "_sync_guard", guarded),
            patch.object(cache, "_load_cache", return_value=copy.deepcopy(self.good)),
            patch.object(cache, "_fetch_from_kite", return_value=_complete_candidate()),
            patch.object(cache, "_promote_cache"),
            patch.object(cache, "_persist_failure"),
        ):
            threads = [
                threading.Thread(target=cache.refresh, kwargs={"force": True})
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(entered), 2)

    def test_lock_failure_returns_fail_closed_response(self):
        @contextmanager
        def failed_guard():
            yield False

        with (
            patch.object(cache, "_sync_guard", failed_guard),
            patch.object(cache, "_fetch_from_kite") as fetch,
        ):
            result = cache.refresh(force=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "instrument_sync_already_running")
        fetch.assert_not_called()

    def test_promotion_failure_is_reported_and_does_not_claim_success(self):
        with (
            patch.object(cache, "_sync_guard", _acquired_guard),
            patch.object(cache, "_load_cache", return_value=copy.deepcopy(self.good)),
            patch.object(cache, "_fetch_from_kite", return_value=_complete_candidate()),
            patch.object(cache, "_promote_cache", side_effect=RuntimeError("db unavailable")),
            patch.object(cache, "_persist_failure"),
        ):
            result = cache.refresh(force=True)
        self.assertFalse(result["success"])
        self.assertIn("db unavailable", result["error"])

    def test_contended_advisory_lock_releases_connection_and_file_lock(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, *_args):
                return None

            def fetchone(self):
                return (False,)

        class Connection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return Cursor()

            def close(self):
                self.closed = True

        connection = Connection()
        with tempfile.TemporaryDirectory() as directory:
            lock_path = os.path.join(directory, "instrument.lock")
            with (
                patch.object(cache, "_LOCK_PATH", lock_path),
                patch.object(cache, "_durable_store_available", return_value=True),
                patch(
                    "phase20_store._durable_kv_connection",
                    return_value=connection,
                ),
            ):
                with cache._sync_guard() as acquired:
                    self.assertFalse(acquired)

            self.assertTrue(connection.closed)
            probe_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe_fd, fcntl.LOCK_UN)
            finally:
                os.close(probe_fd)


if __name__ == "__main__":
    unittest.main()