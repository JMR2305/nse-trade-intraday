"""Regression coverage for Phase 5A active-universe collection proof."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch


class _Snapshot:
    def __init__(self, symbol: str | None):
        self.symbol = symbol
        self.is_stale = False

    def to_dict(self):
        return {
            "snapshot_id": f"snapshot-{self.symbol}",
            "symbol": self.symbol,
            "trading_date": "2026-08-25",
            "timestamp_ist": "2026-08-25T09:05:00+05:30",
        }


class _SerializedMismatchSnapshot(_Snapshot):
    def to_dict(self):
        row = super().to_dict()
        row["symbol"] = "UNEXPECTED_SERIALIZED_SYMBOL"
        return row


class TestActiveUniverseResolution(unittest.TestCase):
    def test_custom_universe_returns_all_active_symbols_not_default_watchlist(self):
        import config
        import preopen_engine

        with (
            patch.object(
                config,
                "get_active_intraday_universe_strict",
                return_value=config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR,
            ),
            patch("custom_universe_store.get_active_symbols",
                  return_value=["wipro", "pnb", "PNB", " irfc "]),
        ):
            symbols = preopen_engine._resolve_collection_symbols()

        self.assertEqual(symbols, ["WIPRO", "PNB", "IRFC"])

    def test_custom_universe_does_not_fall_back_when_durable_membership_is_empty(self):
        import config
        import preopen_engine

        with (
            patch.object(
                config,
                "get_active_intraday_universe_strict",
                return_value=config.UniverseMode.CUSTOM_LOW_PRICE_SECTOR,
            ),
            patch("custom_universe_store.get_active_symbols", return_value=[]),
        ):
            self.assertEqual(preopen_engine._resolve_collection_symbols(), [])

    def test_unreadable_durable_universe_never_falls_back_to_default_watchlist(self):
        import config
        import preopen_engine

        with (
            patch.object(
                config,
                "get_active_intraday_universe_strict",
                side_effect=RuntimeError("settings storage unavailable"),
            ),
            patch.dict("os.environ", {}, clear=True),
        ):
            self.assertEqual(preopen_engine._resolve_collection_symbols(), [])

    def test_default_watchlist_remains_available_when_durable_mode_is_non_custom(self):
        import config
        import preopen_engine

        with (
            patch.object(
                config,
                "get_active_intraday_universe_strict",
                return_value=config.UniverseMode.NIFTY_50,
            ),
            patch.object(config, "DEFAULT_WATCHLIST", ["SBIN", "TCS"]),
        ):
            self.assertEqual(preopen_engine._resolve_collection_symbols(), ["SBIN", "TCS"])

    def test_environment_default_never_overrides_durable_settings_outage(self):
        import config
        import preopen_engine

        with (
            patch.object(
                config,
                "get_active_intraday_universe_strict",
                side_effect=RuntimeError("settings storage unavailable"),
            ),
            patch.dict(
                "os.environ",
                {"ACTIVE_INTRADAY_UNIVERSE": "NIFTY_50"},
                clear=True,
            ),
        ):
            self.assertEqual(preopen_engine._resolve_collection_symbols(), [])


class TestCoverageAccounting(unittest.TestCase):
    def test_full_response_has_exact_one_to_one_coverage(self):
        import preopen_engine

        snapshots, coverage = preopen_engine._coverage_for_expected_symbols(
            [_Snapshot("alpha"), _Snapshot("BETA"), _Snapshot("gamma")],
            ["ALPHA", "BETA", "GAMMA"],
        )

        self.assertEqual([snapshot.symbol for snapshot in snapshots],
                         ["alpha", "BETA", "gamma"])
        self.assertEqual(coverage["expected_count"], 3)
        self.assertEqual(coverage["provider_returned_count"], 3)
        self.assertEqual(coverage["normalized_count"], 3)
        self.assertEqual(coverage["missing_symbols"], [])
        self.assertEqual(coverage["unusable_count"], 0)

    def test_partial_duplicate_and_malformed_rows_are_never_silently_complete(self):
        import preopen_engine

        snapshots, coverage = preopen_engine._coverage_for_expected_symbols(
            [_Snapshot("ONE"), _Snapshot("ONE"), _Snapshot("TWO"), _Snapshot(None),
             _Snapshot("UNREQUESTED")],
            ["ONE", "TWO", "THREE"],
        )

        self.assertEqual([snapshot.symbol for snapshot in snapshots], ["ONE", "TWO"])
        self.assertEqual(coverage["missing_symbols"], ["THREE"])
        self.assertEqual(coverage["duplicate_symbols"], ["ONE"])
        self.assertEqual(coverage["malformed_count"], 1)
        self.assertEqual(coverage["unexpected_symbols"], ["UNREQUESTED"])
        self.assertEqual(coverage["unusable_count"], 3)


class TestCollectionContract(unittest.TestCase):
    def _provider(self, snapshots):
        return types.SimpleNamespace(
            health_check=lambda: {"status": "LIVE", "provider": "Fixture"},
            fetch_market_snapshot=lambda: snapshots,
            PROVIDER_LABEL="Fixture",
        )

    def test_collect_passes_all_active_symbols_and_complete_coverage_to_storage(self):
        import preopen_engine

        symbols = [f"SYM{index:02d}" for index in range(23)]
        provider = self._provider([_Snapshot(symbol) for symbol in symbols])
        persisted = {
            "success": True,
            "provider_collected_count": 23,
            "persisted_count": 23,
            "failed_count": 0,
            "expected_count": 23,
            "persistence_status": "MATCH",
        }
        with (
            patch.object(preopen_engine, "_is_enabled", return_value=True),
            patch.object(preopen_engine, "_ensure_session", return_value=True),
            patch.object(preopen_engine, "_resolve_collection_symbols", return_value=symbols),
            patch.object(preopen_engine, "_get_provider", return_value=provider) as get_provider,
            patch.object(preopen_engine, "enrich_universe", side_effect=lambda rows: rows),
            patch.object(preopen_engine.db, "persist_collection", return_value=persisted) as store,
        ):
            result = preopen_engine.collect_snapshot("session-coverage-full")

        self.assertTrue(result["success"])
        self.assertEqual(result["expected_count"], 23)
        get_provider.assert_called_once_with(symbols)
        coverage = store.call_args.kwargs["coverage"]
        self.assertEqual(coverage["expected_symbols"], symbols)
        self.assertEqual(coverage["normalized_count"], 23)
        self.assertEqual(coverage["missing_count"], 0)

    def test_partial_live_response_is_reported_as_coverage_incomplete(self):
        import preopen_engine

        symbols = [f"SYM{index:02d}" for index in range(23)]
        provider = self._provider([_Snapshot(symbol) for symbol in symbols[:10]])
        persisted = {
            "success": False,
            "provider_collected_count": 10,
            "persisted_count": 10,
            "failed_count": 13,
            "expected_count": 23,
            "persistence_status": "COVERAGE_INCOMPLETE",
        }
        with (
            patch.object(preopen_engine, "_is_enabled", return_value=True),
            patch.object(preopen_engine, "_ensure_session", return_value=True),
            patch.object(preopen_engine, "_resolve_collection_symbols", return_value=symbols),
            patch.object(preopen_engine, "_get_provider", return_value=provider),
            patch.object(preopen_engine, "enrich_universe", side_effect=lambda rows: rows),
            patch.object(preopen_engine.db, "persist_collection", return_value=persisted) as store,
        ):
            result = preopen_engine.collect_snapshot("session-coverage-partial")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "COVERAGE_INCOMPLETE")
        self.assertEqual(result["missing_count"], 13)
        self.assertEqual(
            store.call_args.kwargs["coverage"]["missing_symbols"],
            symbols[10:],
        )

    def test_empty_custom_universe_fails_closed_without_selecting_a_provider(self):
        import preopen_engine

        with (
            patch.object(preopen_engine, "_is_enabled", return_value=True),
            patch.object(preopen_engine, "_ensure_session", return_value=True),
            patch.object(preopen_engine, "_resolve_collection_symbols", return_value=[]),
            patch.object(preopen_engine, "_get_provider") as get_provider,
            patch.object(preopen_engine.db, "record_collection_failure",
                         return_value=True) as record_failure,
        ):
            result = preopen_engine.collect_snapshot("session-empty-universe")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "UNIVERSE_UNAVAILABLE")
        get_provider.assert_not_called()
        self.assertEqual(record_failure.call_args.args[1], "UNIVERSE_UNAVAILABLE")

    def test_serialized_symbol_mismatch_cannot_be_persisted_as_full_coverage(self):
        import preopen_engine

        symbols = ["ONE"]
        provider = self._provider([_SerializedMismatchSnapshot("ONE")])
        persisted = {
            "success": False,
            "provider_collected_count": 0,
            "persisted_count": 0,
            "failed_count": 1,
            "expected_count": 1,
            "persistence_status": "COVERAGE_INCOMPLETE",
        }
        with (
            patch.object(preopen_engine, "_is_enabled", return_value=True),
            patch.object(preopen_engine, "_ensure_session", return_value=True),
            patch.object(preopen_engine, "_resolve_collection_symbols", return_value=symbols),
            patch.object(preopen_engine, "_get_provider", return_value=provider),
            patch.object(preopen_engine, "enrich_universe", side_effect=lambda rows: rows),
            patch.object(preopen_engine.db, "persist_collection", return_value=persisted) as store,
        ):
            result = preopen_engine.collect_snapshot("session-serialized-mismatch")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "COVERAGE_INCOMPLETE")
        self.assertEqual(store.call_args.kwargs["snapshots"], [])
        coverage = store.call_args.kwargs["coverage"]
        self.assertEqual(coverage["missing_symbols"], ["ONE"])
        self.assertEqual(coverage["unexpected_symbols"], ["UNEXPECTED_SERIALIZED_SYMBOL"])


class TestDurableCoverageGate(unittest.TestCase):
    def test_partial_10_of_23_batch_cannot_freeze(self):
        import preopen_scheduler

        scheduler = preopen_scheduler.PreOpenScheduler(
            session_id="session-partial-coverage", test_mode=True,
        )
        database = types.SimpleNamespace(
            get_session=lambda _: {
                "provider_collected_count": 10,
                "persisted_count": 10,
                "expected_count": 23,
                "failed_count": 13,
                "persistence_status": "COVERAGE_INCOMPLETE",
                "verified_collection_batch_id": None,
            },
            record_collection_failure=Mock(return_value=True),
        )
        with patch.dict(sys.modules, {"preopen_db": database}):
            result = scheduler._phase_09_15_freeze()

        self.assertFalse(result)
        self.assertEqual(scheduler.phase, "ERROR")
        database.record_collection_failure.assert_called_once()

    def test_same_count_but_wrong_persisted_symbol_set_cannot_freeze(self):
        import preopen_scheduler

        scheduler = preopen_scheduler.PreOpenScheduler(
            session_id="session-wrong-symbol-set", test_mode=True,
        )
        database = types.SimpleNamespace(
            get_session=lambda _: {
                "provider_collected_count": 2,
                "persisted_count": 2,
                "expected_count": 2,
                "failed_count": 0,
                "persistence_status": "MATCH",
                "verified_collection_batch_id": "batch-wrong-symbol-set",
                "collection_coverage": {"expected_symbols": ["ONE", "TWO"]},
            },
            get_session_snapshots=lambda *_: [
                {"snapshot_id": "snapshot-one", "symbol": "ONE"},
                {"snapshot_id": "snapshot-three", "symbol": "THREE"},
            ],
            record_collection_failure=Mock(return_value=True),
        )
        with patch.dict(sys.modules, {"preopen_db": database}):
            result = scheduler._phase_09_15_freeze()

        self.assertFalse(result)
        self.assertEqual(scheduler.phase, "ERROR")
        database.record_collection_failure.assert_called_once()

    def test_latest_session_exposes_durable_coverage_fields(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.sql = ""

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, _params=None):
                self.sql = sql

            def fetchone(self):
                return (
                    "session-coverage", "2026-08-25", "PARTIAL_COVERAGE",
                    10, 10, 0, "LIVE", 10, 10, 13, 23, 10, 10, 13, 0, 0,
                    {"missing_symbols": ["SYM10"]}, None, None, "SCHEDULED",
                    "COVERAGE_INCOMPLETE", "RETRY_REQUIRED", {}, None, None,
                    None, None, "coverage incomplete", None, None,
                )

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

        connection = Connection()
        with patch.object(
            db, "_with_db", side_effect=lambda callback, fallback=None: callback(connection)
        ):
            session = db.get_latest_session()

        self.assertIn("expected_count", connection.cursor_instance.sql)
        self.assertEqual(session["expected_count"], 23)
        self.assertEqual(session["missing_count"], 13)
        self.assertEqual(session["collection_coverage"]["missing_symbols"], ["SYM10"])