"""Focused lifecycle truth tests for Phase 5A/5C tick outcomes."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch


_IST = timezone(timedelta(hours=5, minutes=30))


class TestPreopenCollectCounts(unittest.TestCase):
    def test_tick_reports_engine_symbol_count_and_visible_persistence_mismatch(self):
        import preopen_intelligence_tick as tick

        engine = types.SimpleNamespace(collect_snapshot=lambda **_: {
            "success": True, "symbol_count": 12, "stale_count": 1,
            "provider_status": "LIVE",
            "provider_collected_count": 12,
            "persisted_count": 10,
            "persistence_status": "MISMATCH",
        })
        database = types.SimpleNamespace()
        with patch.dict(sys.modules, {"preopen_engine": engine, "preopen_db": database}):
            result = tick._run_collect("session-1")

        self.assertEqual(result["symbol_count"], 12)
        self.assertEqual(result["symbols_captured"], 12)  # compatibility alias
        self.assertEqual(result["persisted_symbol_count"], 10)
        self.assertEqual(result["persistence_status"], "MISMATCH")


class TestCollectionBatchPresentationTruth(unittest.TestCase):
    def test_empty_visible_coverage_is_not_certified_even_if_session_phase_is_frozen(self):
        import preopen_engine

        result = preopen_engine._collection_batch_status({
            "session_id": "prior-session",
            "trading_date": "2026-08-25",
            "status": "FROZEN",
            "valid_count": 10,
            "expected_count": 10,
            "persisted_count": 10,
            "stale_count": 0,
            "persistence_status": "MATCH",
            "verified_collection_batch_id": "batch-1",
            "frozen_collection_batch_id": "batch-1",
            "collection_coverage": {
                "outcome_complete": True,
                "live_coverage_complete": True,
            },
        }, [], "2026-08-26")

        self.assertEqual(result["session_phase"], "FROZEN")
        self.assertFalse(result["certified"])
        self.assertEqual(result["certification_status"], "NO_VALID_SYMBOLS")

    def test_certification_requires_matching_pointers_and_complete_current_coverage(self):
        import preopen_engine

        result = preopen_engine._collection_batch_status({
            "session_id": "current-session",
            "trading_date": "2026-08-26",
            "status": "FROZEN",
            "valid_count": 2,
            "expected_count": 2,
            "persisted_count": 2,
            "stale_count": 0,
            "persistence_status": "MATCH",
            "verified_collection_batch_id": "batch-2",
            "frozen_collection_batch_id": "batch-2",
            "collection_coverage": {
                "outcome_complete": True,
                "live_coverage_complete": True,
            },
        }, [
            {
                "is_stale": False,
                "session_id": "current-session",
                "collection_batch_id": "batch-2",
            },
            {
                "is_stale": False,
                "session_id": "current-session",
                "collection_batch_id": "batch-2",
            },
        ], "2026-08-26")

        self.assertTrue(result["certified"])
        self.assertEqual(result["certification_status"], "CERTIFIED_FROZEN")

    def test_later_equal_size_batch_is_not_certified_as_the_frozen_batch(self):
        import preopen_engine

        result = preopen_engine._collection_batch_status({
            "session_id": "current-session",
            "trading_date": "2026-08-26",
            "status": "FROZEN",
            "valid_count": 2,
            "expected_count": 2,
            "persisted_count": 2,
            "stale_count": 0,
            "persistence_status": "MATCH",
            "verified_collection_batch_id": "frozen-batch",
            "frozen_collection_batch_id": "frozen-batch",
            "collection_coverage": {
                "outcome_complete": True,
                "live_coverage_complete": True,
            },
        }, [
            {
                "is_stale": False,
                "session_id": "current-session",
                "collection_batch_id": "later-unfrozen-batch",
            },
            {
                "is_stale": False,
                "session_id": "current-session",
                "collection_batch_id": "later-unfrozen-batch",
            },
        ], "2026-08-26")

        self.assertFalse(result["certified"])
        self.assertEqual(result["certification_status"], "DISPLAYED_BATCH_MISMATCH")

    def test_snapshot_reads_only_the_current_trading_date_session(self):
        import preopen_engine
        current_session = {"session_id": "current", "trading_date": "2026-08-26"}
        database = types.SimpleNamespace(
            get_latest_snapshots=Mock(return_value=[]),
            get_session_for_trading_date=Mock(return_value=current_session),
            get_latest_session=Mock(),
        )
        provider = types.SimpleNamespace(PROVIDER_LABEL="Fixture")
        with (
            patch.object(preopen_engine, "_is_enabled", return_value=True),
            patch.object(preopen_engine, "_today_ist", return_value="2026-08-26"),
            patch.object(preopen_engine, "_get_provider", return_value=provider),
            patch.object(preopen_engine, "_resolve_collection_symbols", return_value=["ONE"]),
            patch.object(preopen_engine, "db", database),
        ):
            result = preopen_engine.get_snapshot()

        database.get_session_for_trading_date.assert_called_once_with("2026-08-26")
        database.get_latest_session.assert_not_called()
        self.assertEqual(result["session"], current_session)
        self.assertFalse(result["collection_batch"]["certified"])


class TestForwardOnlySessionWrites(unittest.TestCase):
    def test_5a_collection_cannot_regress_frozen_or_reconciled_statuses(self):
        from preopen_db import _forward_session_status

        self.assertEqual(_forward_session_status("FROZEN", "COLLECTING"), "FROZEN")
        self.assertEqual(_forward_session_status("RECONCILED", "COLLECTING"), "RECONCILED")
        self.assertEqual(_forward_session_status("RECONCILED_0930", "INITIALISING"),
                         "RECONCILED_0930")
        self.assertEqual(_forward_session_status("FROZEN", "RECONCILED"), "RECONCILED")
        self.assertEqual(_forward_session_status("RECONCILED", "RECONCILED_0930"),
                         "RECONCILED_0930")

    def test_5b_partial_writes_cannot_reopen_terminal_sessions(self):
        from preopen_validation_db import _forward_session_status

        self.assertEqual(_forward_session_status("COMPLETE", "COLLECTING"), "COMPLETE")
        self.assertEqual(_forward_session_status("NO_CANDIDATES", "PENDING"),
                         "NO_CANDIDATES")
        self.assertEqual(_forward_session_status("COLLECTING", None), "COLLECTING")
        self.assertEqual(_forward_session_status("COLLECTING", "COMPLETE"), "COMPLETE")


class TestPreopenPersistenceFailures(unittest.TestCase):
    def test_health_observation_does_not_persist_provider_telemetry(self):
        import preopen_engine
        provider = types.SimpleNamespace(
            health_check=lambda: {"status": "LIVE", "provider": "Mock"},
        )
        with (
            patch.object(preopen_engine, "_is_enabled", return_value=True),
            patch.object(preopen_engine, "_resolve_collection_symbols", return_value=["SBIN"]),
            patch.object(preopen_engine, "_get_provider", return_value=provider),
            patch.object(preopen_engine.db, "save_provider_health") as save_health,
        ):
            result = preopen_engine.get_health()
        self.assertTrue(result["success"])
        save_health.assert_not_called()

    def test_unavailable_persistence_is_an_explicit_failed_collection(self):
        import preopen_db as db
        with patch.object(db, "db_available", return_value=False):
            result = db.persist_collection(
                "session-1", "2026-08-24", [{"snapshot_id": "one"}],
                "LIVE", valid_count=1, stale_count=0,
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["persistence_status"], "PERSISTENCE_UNAVAILABLE")
        self.assertEqual(result["provider_collected_count"], 1)
        self.assertEqual(result["persisted_count"], None)

    def test_failed_freeze_is_not_marked_complete_or_allowed_downstream(self):
        import preopen_intelligence_tick as tick
        state = {
            "trading_date": "2026-07-28",
            "session_id": "preopen-test-001",
            "phases_done": {"init": {}, "readiness": {}},
            "collect_count": 0,
        }
        database = types.SimpleNamespace(update_phase_state=Mock())
        with (
            patch("preopen_intelligence_tick._is_enabled", return_value=True),
            patch("preopen_intelligence_tick._is_trading_day", return_value=True),
            patch("preopen_intelligence_tick._now_ist",
                  return_value=tick.datetime(2026, 7, 28, 9, 16, tzinfo=tick._IST)),
            patch("preopen_intelligence_tick._load_state", return_value=state),
            patch("preopen_intelligence_tick._save_state"),
            patch("preopen_intelligence_tick._run_freeze",
                  return_value={"success": False, "phase": "ERROR", "error": "persistence mismatch"}),
            patch.dict(sys.modules, {"preopen_db": database}),
        ):
            result = tick.run_tick()
        self.assertFalse(result["ran"])
        self.assertNotIn("freeze", state["phases_done"])
        database.update_phase_state.assert_called_once()
        self.assertFalse(database.update_phase_state.call_args.kwargs["completed"])

    def test_freeze_blocks_when_collection_parity_is_not_proven(self):
        import preopen_scheduler
        scheduler = preopen_scheduler.PreOpenScheduler(
            session_id="session-1", test_mode=True,
        )
        database = types.SimpleNamespace(
            get_session=lambda _: {
                "provider_collected_count": 23,
                "persisted_count": 22,
                "persistence_status": "MISMATCH",
            },
            record_collection_failure=Mock(return_value=True),
        )
        with patch.dict(sys.modules, {"preopen_db": database}):
            result = scheduler._phase_09_15_freeze()
        self.assertFalse(result)
        self.assertEqual(scheduler.phase, "ERROR")
        database.record_collection_failure.assert_called_once()

    def test_freeze_uses_only_the_latest_verified_batch_not_prior_retry_rows(self):
        """A retry that omits TCS must not let the earlier TCS row enter freeze."""
        import preopen_scheduler

        class Snapshot:
            def __init__(self, **values):
                self._values = values
                self.opportunity_score = float(values.get("opportunity_score") or 0)
                self.is_stale = bool(values.get("is_stale", False))

            def to_dict(self):
                return self._values

        scheduler = preopen_scheduler.PreOpenScheduler(
            session_id="session-1", test_mode=True,
        )
        latest_batch = "batch-2"
        database = types.SimpleNamespace(
            get_session=lambda _: {
                "provider_collected_count": 1,
                "persisted_count": 1,
                "expected_count": 1,
                "failed_count": 0,
                "persistence_status": "MATCH",
                "verified_collection_batch_id": latest_batch,
                "collection_source": "SCHEDULED",
                "collection_completed_at": "2026-07-28T03:41:30Z",
                "trading_date": "2026-07-28",
                "collection_coverage": {"expected_symbols": ["SBIN"]},
            },
            get_session_snapshots=Mock(return_value=[{
                "snapshot_id": "batch-2-SBIN",
                "collection_batch_id": latest_batch,
                "symbol": "SBIN",
                "is_stale": False,
                "source_status": "LIVE",
            }]),
            get_collection_outcomes=Mock(return_value=[{
                "symbol": "SBIN",
                "outcome_status": "LIVE_PREOPEN_DATA",
            }]),
            save_watchlist=Mock(),
            save_rankings=Mock(),
            upsert_session=Mock(return_value=True),
            record_collection_failure=Mock(return_value=True),
        )
        watchlist = types.SimpleNamespace(generate_watchlists=lambda _: {"watch": []})
        data_model = types.SimpleNamespace(PreOpenSnapshot=Snapshot)
        with patch.dict(sys.modules, {
            "preopen_db": database,
            "preopen_engine": types.SimpleNamespace(),
            "preopen_watchlist": watchlist,
            "preopen_data_model": data_model,
        }), patch(
            "preopen_scheduler._now_ist",
            return_value=datetime(2026, 7, 28, 9, 15, tzinfo=_IST),
        ):
            result = scheduler._phase_09_15_freeze()

        self.assertTrue(result, scheduler._log)
        database.get_session_snapshots.assert_called_once_with("session-1", latest_batch)
        self.assertEqual(database.save_rankings.call_args[0][2][0]["symbol"], "SBIN")
        self.assertEqual(
            database.upsert_session.call_args[0][0]["frozen_collection_batch_id"],
            latest_batch,
        )

    def test_freeze_authority_rejects_manual_invalid_future_and_arbitrary_old_batches(self):
        import preopen_scheduler

        now = datetime(2026, 7, 28, 9, 15, tzinfo=_IST)
        base = {
            "collection_source": "SCHEDULED",
            "collection_completed_at": "2026-07-28T03:41:00Z",
            "trading_date": "2026-07-28",
        }
        self.assertTrue(preopen_scheduler._approved_final_collection(base, now)[0])

        cases = [
            ({"collection_source": "MANUAL"}, "naturally scheduled"),
            ({"collection_completed_at": "not-a-timestamp"}, "invalid completion"),
            ({"collection_completed_at": "2026-07-28T04:00:00Z"}, "in the future"),
            ({"collection_completed_at": "2026-07-28T03:37:59Z"}, "09:08–09:12"),
            ({"collection_completed_at": "2026-07-28T03:42:00Z"}, "09:08–09:12"),
            ({"trading_date": "2026-07-27"}, "this trading date"),
        ]
        for overrides, expected_text in cases:
            candidate = {**base, **overrides}
            approved, reason = preopen_scheduler._approved_final_collection(candidate, now)
            self.assertFalse(approved, candidate)
            self.assertIn(expected_text, reason)

    def test_freeze_accepts_exact_fresh_23_symbol_scheduled_batch(self):
        import preopen_scheduler

        class Snapshot:
            def __init__(self, **values):
                self._values = values
                self.opportunity_score = 0.0
                self.is_stale = False

            def to_dict(self):
                return self._values

        symbols = [f"SYM{i:02d}" for i in range(23)]
        batch_id = "approved-final-batch"
        snapshots = [{
            "snapshot_id": f"{batch_id}-{symbol}",
            "collection_batch_id": batch_id,
            "symbol": symbol,
            "is_stale": False,
            "source_status": "LIVE",
        } for symbol in symbols]
        database = types.SimpleNamespace(
            get_session=lambda _: {
                "provider_collected_count": 23,
                "persisted_count": 23,
                "expected_count": 23,
                "failed_count": 0,
                "persistence_status": "MATCH",
                "verified_collection_batch_id": batch_id,
                "collection_source": "SCHEDULED",
                "collection_completed_at": "2026-07-28T03:41:30Z",
                "trading_date": "2026-07-28",
                "collection_coverage": {"expected_symbols": symbols},
            },
            get_session_snapshots=Mock(return_value=snapshots),
            get_collection_outcomes=Mock(return_value=[{
                "symbol": symbol, "outcome_status": "LIVE_PREOPEN_DATA",
            } for symbol in symbols]),
            save_watchlist=Mock(),
            save_rankings=Mock(),
            upsert_session=Mock(return_value=True),
            record_collection_failure=Mock(return_value=True),
        )
        with patch.dict(sys.modules, {
            "preopen_db": database,
            "preopen_engine": types.SimpleNamespace(),
            "preopen_watchlist": types.SimpleNamespace(
                generate_watchlists=lambda _: {"watch": []},
            ),
            "preopen_data_model": types.SimpleNamespace(PreOpenSnapshot=Snapshot),
        }), patch(
            "preopen_scheduler._now_ist",
            return_value=datetime(2026, 7, 28, 9, 15, tzinfo=_IST),
        ):
            result = preopen_scheduler.PreOpenScheduler(
                session_id="session-23", test_mode=True,
            )._phase_09_15_freeze()

        self.assertTrue(result)
        database.record_collection_failure.assert_not_called()

    def test_freeze_rejects_rows_returned_from_a_different_batch(self):
        import preopen_scheduler

        batch_id = "approved-final-batch"
        database = types.SimpleNamespace(
            get_session=lambda _: {
                "provider_collected_count": 1,
                "persisted_count": 1,
                "expected_count": 1,
                "failed_count": 0,
                "persistence_status": "MATCH",
                "verified_collection_batch_id": batch_id,
                "collection_source": "SCHEDULED",
                "collection_completed_at": "2026-07-28T03:41:30Z",
                "trading_date": "2026-07-28",
                "collection_coverage": {"expected_symbols": ["SBIN"]},
            },
            get_session_snapshots=Mock(return_value=[{
                "snapshot_id": "wrong-batch-SBIN",
                "collection_batch_id": "wrong-batch",
                "symbol": "SBIN",
                "is_stale": False,
                "source_status": "LIVE",
            }]),
            record_collection_failure=Mock(return_value=True),
        )
        with patch.dict(sys.modules, {"preopen_db": database}), patch(
            "preopen_scheduler._now_ist",
            return_value=datetime(2026, 7, 28, 9, 15, tzinfo=_IST),
        ):
            result = preopen_scheduler.PreOpenScheduler(
                session_id="session-wrong-batch", test_mode=True,
            )._phase_09_15_freeze()

        self.assertFalse(result)
        database.record_collection_failure.assert_called_once()

    def test_batch_snapshot_reader_filters_by_session_and_batch(self):
        import preopen_db as db

        class Cursor:
            description = [("snapshot_id",), ("collection_batch_id",), ("symbol",)]

            def __init__(self):
                self.sql = ""
                self.params = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [("batch-2-SBIN", "batch-2", "SBIN")]

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

        connection = Connection()
        with patch.object(db, "_with_db", side_effect=lambda callback: callback(connection)):
            rows = db.get_session_snapshots("session-1", "batch-2")

        self.assertEqual(rows, [{
            "snapshot_id": "batch-2-SBIN",
            "collection_batch_id": "batch-2",
            "symbol": "SBIN",
        }])
        self.assertIn("collection_batch_id = %s", connection.cursor_instance.sql)
        self.assertEqual(connection.cursor_instance.params, ["session-1", "batch-2"])

    def test_collection_persists_verified_batch_pointer_with_its_count_proof(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.calls = []
                self.rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params):
                self.calls.append((sql, params))

            def fetchone(self):
                return (1,)

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                self.committed = True

        connection = Connection()
        with patch.object(db, "_with_db", side_effect=lambda callback, fallback=None: callback(connection)):
            result = db.persist_collection(
                "session-1", "2026-08-24",
                [{
                    "snapshot_id": "batch-2-SBIN",
                    "symbol": "SBIN",
                    "is_stale": False,
                    "source_status": "LIVE",
                }],
                "LIVE", valid_count=1, stale_count=0,
                collection_batch_id="batch-2",
                coverage={
                    "expected_count": 1,
                    "expected_symbols": ["SBIN"],
                    "normalized_count": 1,
                    "provider_returned_count": 1,
                },
                outcomes=[{
                    "symbol": "SBIN",
                    "outcome_status": "LIVE_PREOPEN_DATA",
                    "reason_code": "PERSISTENCE_CANDIDATE_READY",
                    "provider_response_present": True,
                    "normalization_result": "NORMALIZED",
                }],
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["collection_batch_id"], "batch-2")
        insert_sql, insert_params = connection.cursor_instance.calls[0]
        self.assertIn("collection_batch_id", insert_sql)
        self.assertEqual(insert_params[2], "batch-2")
        outcome_sql, _outcome_params = connection.cursor_instance.calls[1]
        self.assertIn("INSERT INTO preopen_collection_outcomes", outcome_sql)
        proof_sql, proof_params = connection.cursor_instance.calls[2]
        self.assertIn("collection_batch_id = %s", proof_sql)
        self.assertEqual(proof_params[:2], ["session-1", "batch-2"])
        session_sql, session_params = connection.cursor_instance.calls[4]
        self.assertIn("verified_collection_batch_id", session_sql)
        self.assertIn("batch-2", session_params)
        self.assertTrue(connection.committed)

    def test_collection_persists_one_outcome_for_every_expected_symbol(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.calls = []
                self.rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params=None):
                self.calls.append((sql, params))

            def fetchone(self):
                return (2,)

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                self.committed = True

        connection = Connection()
        outcomes = [{
            "symbol": symbol,
            "outcome_status": "LIVE_PREOPEN_DATA",
            "reason_code": "PERSISTENCE_CANDIDATE_READY",
            "provider_response_present": True,
            "normalization_result": "NORMALIZED",
        } for symbol in ("ALPHA", "BETA")]
        coverage = {
            "expected_count": 2,
            "expected_symbols": ["ALPHA", "BETA"],
            "provider_returned_count": 2,
            "normalized_count": 2,
            "missing_count": 0,
            "duplicate_count": 0,
            "malformed_count": 0,
            "unusable_count": 0,
            "provider_raw_count": 50,
        }
        with patch.object(
            db, "_with_db", side_effect=lambda callback, fallback=None: callback(connection)
        ):
            result = db.persist_collection(
                "session-outcomes", "2026-08-26",
                [
                    {
                        "snapshot_id": "alpha-snapshot",
                        "symbol": "ALPHA",
                        "is_stale": False,
                        "source_status": "LIVE",
                    },
                    {
                        "snapshot_id": "beta-snapshot",
                        "symbol": "BETA",
                        "is_stale": False,
                        "source_status": "LIVE",
                    },
                ],
                "LIVE", valid_count=2, stale_count=0,
                collection_batch_id="batch-outcomes",
                coverage=coverage,
                outcomes=outcomes,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["outcome_persisted_count"], 2)
        self.assertTrue(result["outcome_complete"])
        outcome_insert_sql = connection.cursor_instance.calls[2][0]
        self.assertIn("INSERT INTO preopen_collection_outcomes", outcome_insert_sql)
        self.assertTrue(connection.committed)

    def test_collection_without_outcome_matrix_cannot_match(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.calls = []
                self.rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params=None):
                self.calls.append((sql, params))

            def fetchone(self):
                return (1,)

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                pass

        connection = Connection()
        with patch.object(
            db, "_with_db", side_effect=lambda callback, fallback=None: callback(connection)
        ):
            result = db.persist_collection(
                "session-no-outcome", "2026-08-26",
                [{"snapshot_id": "only-snapshot", "symbol": "ONLY"}],
                "LIVE", valid_count=1, stale_count=0,
                collection_batch_id="batch-no-outcome",
                coverage={
                    "expected_count": 1,
                    "expected_symbols": ["ONLY"],
                    "normalized_count": 1,
                    "provider_returned_count": 1,
                },
                outcomes=None,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["persistence_status"], "MISMATCH")
        self.assertFalse(result["outcome_complete"])

    def test_collection_without_explicit_liveness_cannot_match(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, _sql, _params=None):
                pass

            def fetchone(self):
                return (1,)

        class Connection:
            def cursor(self):
                return Cursor()

            def commit(self):
                pass

        with patch.object(
            db, "_with_db", side_effect=lambda callback, fallback=None: callback(Connection())
        ):
            result = db.persist_collection(
                "session-missing-liveness", "2026-08-26",
                [{"snapshot_id": "only-snapshot", "symbol": "ONLY"}],
                "LIVE", valid_count=1, stale_count=0,
                collection_batch_id="batch-missing-liveness",
                coverage={
                    "expected_count": 1,
                    "expected_symbols": ["ONLY"],
                    "normalized_count": 1,
                    "provider_returned_count": 1,
                },
                outcomes=[{
                    "symbol": "ONLY",
                    "outcome_status": "LIVE_PREOPEN_DATA",
                    "reason_code": "PERSISTENCE_CANDIDATE_READY",
                    "provider_response_present": True,
                    "normalization_result": "NORMALIZED",
                }],
            )

        self.assertFalse(result["success"])
        self.assertFalse(result["collection_coverage"]["live_coverage_complete"])

    def test_existing_snapshot_table_upgrades_batch_column_before_batch_index(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, _params=None):
                self.statements.append(" ".join(sql.split()))

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()
                self.committed = False

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                self.committed = True

        connection = Connection()
        old_schema_ready = db._SCHEMA_READY
        try:
            db._SCHEMA_READY = False
            db._ensure_schema(connection)
        finally:
            db._SCHEMA_READY = old_schema_ready

        statements = connection.cursor_instance.statements
        upgrade_at = next(
            index for index, sql in enumerate(statements)
            if "ALTER TABLE preopen_snapshots ADD COLUMN IF NOT EXISTS collection_batch_id TEXT" in sql
        )
        index_at = next(
            index for index, sql in enumerate(statements)
            if "idx_preopen_snaps_session_batch" in sql
        )
        self.assertLess(upgrade_at, index_at)
        self.assertTrue(connection.committed)

    def test_schema_includes_immutable_collection_outcomes(self):
        import preopen_db as db

        class Cursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, _params=None):
                self.statements.append(" ".join(sql.split()))

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                pass

        connection = Connection()
        old_schema_ready = db._SCHEMA_READY
        try:
            db._SCHEMA_READY = False
            db._ensure_schema(connection)
        finally:
            db._SCHEMA_READY = old_schema_ready

        self.assertTrue(any(
            "CREATE TABLE IF NOT EXISTS preopen_collection_outcomes" in statement
            for statement in connection.cursor_instance.statements
        ))

    def test_reconcile_cannot_advance_session_without_durable_freeze(self):
        import preopen_scheduler
        scheduler = preopen_scheduler.PreOpenScheduler(
            session_id="session-1", test_mode=True,
        )
        database = types.SimpleNamespace(
            get_session=lambda _: {"status": "COLLECTING"},
            record_collection_failure=Mock(return_value=True),
            upsert_session=Mock(return_value=True),
        )
        with patch.dict(sys.modules, {"preopen_db": database}):
            result = scheduler._phase_09_20_reconcile()
        self.assertFalse(result)
        self.assertEqual(scheduler.phase, "ERROR")
        database.upsert_session.assert_not_called()
        database.record_collection_failure.assert_called_once()

    def test_phase_is_not_locally_complete_when_durable_phase_write_fails(self):
        import preopen_intelligence_tick as tick
        state = {
            "trading_date": "2026-07-28",
            "session_id": "preopen-test-001",
            "phases_done": {},
            "collect_count": 0,
        }
        database = types.SimpleNamespace(update_phase_state=Mock(return_value=False))
        with (
            patch("preopen_intelligence_tick._is_enabled", return_value=True),
            patch("preopen_intelligence_tick._is_trading_day", return_value=True),
            patch("preopen_intelligence_tick._now_ist",
                  return_value=tick.datetime(2026, 7, 28, 8, 47, tzinfo=tick._IST)),
            patch("preopen_intelligence_tick._load_state", return_value=state),
            patch("preopen_intelligence_tick._save_state"),
            patch("preopen_intelligence_tick._run_init",
                  return_value={"success": True, "provider_status": "LIVE"}),
            patch.dict(sys.modules, {"preopen_db": database}),
        ):
            result = tick.run_tick()
        self.assertFalse(result["ran"])
        self.assertNotIn("init", state["phases_done"])
        self.assertEqual(result["status"], "PHASE_STATE_PERSISTENCE_FAILED")

    def test_sidecar_completed_freeze_cannot_unlock_reconcile_without_db_proof(self):
        import preopen_intelligence_tick as tick
        state = {
            "trading_date": "2026-07-28",
            "session_id": "preopen-test-001",
            "phases_done": {"freeze": {"completed": True}},
            "collect_count": 1,
        }
        database = types.SimpleNamespace(
            get_session_for_trading_date=lambda _: {
                "session_id": "preopen-test-001",
                "phase_state": {},
            },
            update_phase_state=Mock(return_value=True),
        )
        with (
            patch("preopen_intelligence_tick._is_enabled", return_value=True),
            patch("preopen_intelligence_tick._is_trading_day", return_value=True),
            patch("preopen_intelligence_tick._now_ist",
                  return_value=tick.datetime(2026, 7, 28, 9, 19, tzinfo=tick._IST)),
            patch("preopen_intelligence_tick._load_state", return_value=state),
            patch("preopen_intelligence_tick._save_state"),
            patch("preopen_intelligence_tick._run_reconcile") as run_reconcile,
            patch.dict(sys.modules, {"preopen_db": database}),
        ):
            result = tick.run_tick()
        self.assertFalse(result["ran"])
        self.assertEqual(result["status"], "BLOCKED_PREREQUISITE")
        run_reconcile.assert_not_called()


class TestSignalValidationEodTruth(unittest.TestCase):
    def test_missing_close_does_not_rewrite_record_or_complete_session(self):
        import signal_validation_tick as tick
        from signal_validation_model import LifecycleState

        class Db:
            sessions = []
            record_writes = 0

            @staticmethod
            def get_records(**_):
                return [{
                    "validation_id": "v1", "trading_date": "2026-01-02",
                    "session_id": "s1", "signal_id": "sig1", "symbol": "ABC",
                    "validation_status": LifecycleState.OPEN_POSITION,
                    "entry_price": "100",
                }]

            @staticmethod
            def upsert_session(data):
                Db.sessions.append(data)

            @staticmethod
            def upsert_record(_):
                Db.record_writes += 1

        # yfinance download failure is the same safe outcome as an empty
        # provider response and exercises the no-history-rewrite branch.
        yf = types.SimpleNamespace(download=lambda *_, **__: (_ for _ in ()).throw(RuntimeError("unavailable")))
        with patch.dict(sys.modules, {"signal_validation_db": Db, "yfinance": yf}):
            result = tick._run_eod_close("s1", "2026-01-02")

        self.assertTrue(result["retry_required"])
        self.assertEqual(result["session_status"], "EOD_RETRY_REQUIRED")
        self.assertEqual(result["missing_close_records"], 1)
        self.assertEqual(Db.record_writes, 0)
        self.assertEqual(Db.sessions[-1]["status"], "EOD_RETRY_REQUIRED")
