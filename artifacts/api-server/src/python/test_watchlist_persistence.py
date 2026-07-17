"""
test_watchlist_persistence.py — Watchlist fallback semantics.

Locks the loading order: Postgres (signals_store) → watchlist.json → defaults,
and that an empty persisted watchlist is honored (not replaced by defaults).

Unit-level only — signals_store is mocked; no real DB or broker is touched.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main  # noqa: E402
from config import DEFAULT_WATCHLIST  # noqa: E402


class TestWatchlistFallback(unittest.TestCase):
    def setUp(self):
        self.tmp_file = main.WATCHLIST_FILE + ".test_tmp"
        self._orig_file = main.WATCHLIST_FILE
        main.WATCHLIST_FILE = self.tmp_file

    def tearDown(self):
        main.WATCHLIST_FILE = self._orig_file
        if os.path.exists(self.tmp_file):
            os.remove(self.tmp_file)

    def test_db_populated_list_wins(self):
        with mock.patch("signals_store.load_watchlist", return_value=["AAA", "BBB"]):
            self.assertEqual(main._load_watchlist(), ["AAA", "BBB"])

    def test_db_empty_list_is_honored(self):
        # An intentionally emptied watchlist must NOT revert to defaults.
        with open(self.tmp_file, "w") as f:
            json.dump(["FILEONLY"], f)
        with mock.patch("signals_store.load_watchlist", return_value=[]):
            self.assertEqual(main._load_watchlist(), [])

    def test_db_key_missing_falls_back_to_file(self):
        with open(self.tmp_file, "w") as f:
            json.dump(["FILEONLY"], f)
        with mock.patch("signals_store.load_watchlist", return_value=None):
            self.assertEqual(main._load_watchlist(), ["FILEONLY"])

    def test_db_unreachable_falls_back_to_file(self):
        with open(self.tmp_file, "w") as f:
            json.dump(["FILEONLY"], f)
        with mock.patch("signals_store.load_watchlist",
                        side_effect=RuntimeError("db down")):
            self.assertEqual(main._load_watchlist(), ["FILEONLY"])

    def test_no_db_no_file_uses_defaults(self):
        with mock.patch("signals_store.load_watchlist", return_value=None):
            self.assertEqual(main._load_watchlist(), list(DEFAULT_WATCHLIST))

    def test_file_dict_shape_supported(self):
        with open(self.tmp_file, "w") as f:
            json.dump({"symbols": ["DICTSYM"]}, f)
        with mock.patch("signals_store.load_watchlist", return_value=None):
            self.assertEqual(main._load_watchlist(), ["DICTSYM"])

    def test_save_writes_through_signals_store(self):
        with mock.patch("signals_store.save_watchlist") as save:
            main._save_watchlist(["XYZ"])
            save.assert_called_once_with(["XYZ"])


class TestSignalsStoreNormalization(unittest.TestCase):
    def test_load_watchlist_normalizes_dict_payload(self):
        import signals_store
        with mock.patch.object(signals_store, "_load",
                               return_value={"symbols": ["A", "B"]}):
            self.assertEqual(signals_store.load_watchlist(), ["A", "B"])

    def test_load_watchlist_none_when_never_saved(self):
        import signals_store
        with mock.patch.object(signals_store, "_load", return_value=None):
            self.assertIsNone(signals_store.load_watchlist())

    def test_load_watchlist_empty_list_passthrough(self):
        import signals_store
        with mock.patch.object(signals_store, "_load", return_value=[]):
            self.assertEqual(signals_store.load_watchlist(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
