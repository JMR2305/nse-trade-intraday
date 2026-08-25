"""Focused regression coverage for classified off-market scheduler jobs."""
from __future__ import annotations

import os
import json
import sys
import tempfile
import types
import unittest
import inspect
from datetime import datetime, timezone, time as dtime
from unittest.mock import patch
import subprocess


class TestJobMetadata(unittest.TestCase):
    def test_classified_job_insert_has_a_parameter_for_each_column(self):
        import phase20_store as store

        source = inspect.getsource(store.record_scan_run)
        insert_sql = source[
            source.index("INSERT INTO phase20_scan_runs"):
            source.index('"""', source.index("INSERT INTO phase20_scan_runs"))
        ]
        self.assertEqual(insert_sql.count("%s"), 24)

    def test_scheduler_market_metadata_is_execution_eligible_only_when_open(self):
        import phase20_scheduler as scheduler

        snapshot = {
            "scan_id": "s-1",
            "snapshot_ts": "2026-08-20T04:00:00Z",
            "scan_audit": {"scan_completed_ts": "2026-08-20T04:00:04Z"},
            "provider_health": {"symbols_requested": 50, "symbols_succeeded": 49},
            "safety": {},
        }
        open_job = scheduler._run_meta_from_snapshot(
            snapshot, "SCHEDULED", 4.0, "OPEN"
        )
        self.assertEqual(open_job["job_type"], "MARKET_SCAN")
        self.assertTrue(open_job["entry_eligible"])
        self.assertTrue(open_job["execution_eligible"])

        manual_job = scheduler._run_meta_from_snapshot(
            snapshot, "MANUAL", 4.0, "CLOSED", "MANUAL_SCAN"
        )
        self.assertFalse(manual_job["entry_eligible"])
        self.assertFalse(manual_job["execution_eligible"])

    def test_store_file_fallback_persists_classification_and_ist_times(self):
        import phase20_store as store

        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "runs.json")
            with patch.object(store, "_SCAN_RUNS_FILE", path), \
                 patch.object(store, "db_available", return_value=False):
                store.record_scan_run({
                    "job_type": "PREMARKET_READINESS_CHECK",
                    "scan_type": "NON_MARKET",
                    "trigger_source": "SCHEDULER",
                    "source": "SCHEDULER",
                    "market_state": "CLOSED",
                    "started_at": "2026-08-20T03:20:00Z",
                    "completed_at": "2026-08-20T03:20:02Z",
                    "duration_s": 2,
                    "status": "SUCCESS",
                })
                item = store.list_scan_runs(1)[0]
        self.assertEqual(item["job_type"], "PREMARKET_READINESS_CHECK")
        self.assertEqual(item["market_state"], "CLOSED")
        self.assertFalse(item["entry_eligible"])
        self.assertIn("+05:30", item["started_at_ist"])

    def test_manual_scan_provenance_is_sanitized_and_persisted(self):
        import phase20_scheduler as scheduler

        snapshot = {
            "scan_id": "manual-provenance-scan",
            "snapshot_ts": "2026-08-20T04:00:00Z",
            "scan_audit": {"scan_completed_ts": "2026-08-20T04:00:04Z"},
            "provider_health": {"symbols_requested": 50, "symbols_succeeded": 50},
            "safety": {},
        }
        captured = []
        fake_hours = types.SimpleNamespace(
            market_status=lambda: {"state": "OPEN"},
        )
        with patch.dict(sys.modules, {"market_hours": fake_hours}), \
             patch.object(scheduler.store, "record_scan_run", side_effect=captured.append):
            scheduler.record_manual_scan(
                snapshot,
                4.0,
                trigger_origin="API_TRIGGERED",
                provenance={
                    "actor": "authenticated_operator",
                    "actor_source": "SESSION_AUTHENTICATED",
                    "request_id": "scan-11111111-1111-4111-8111-111111111111",
                    "correlation_id": "scan-11111111-1111-4111-8111-111111111111",
                    "actor_type": "operator_api",
                    "actor_id_or_label": "unavailable",
                    "request_endpoint": "/api/live-data/scan/run",
                    "request_method": "POST",
                    "trigger_source": "API_MANUAL_SCAN",
                    "approval_required": False,
                    "approval_status": "NOT_REQUIRED",
                    "requested_at": "2026-08-20T04:00:00Z",
                    "approval_context": "RELEASE_VALIDATION",
                    "audit_reference": "RTV-3E-2026-08-25",
                    "trigger_route": "/api/live-data/scan/run",
                    "access_token": "must-not-persist",
                },
            )

        self.assertEqual(len(captured), 1)
        record = captured[0]
        self.assertEqual(record["job_type"], "MANUAL_SCAN")
        self.assertEqual(record["trigger_source"], "API_TRIGGERED")
        self.assertFalse(record["entry_eligible"])
        self.assertFalse(record["execution_eligible"])
        self.assertEqual(record["details"]["provenance"]["actor"], "authenticated_operator")
        self.assertEqual(record["details"]["provenance"]["actor_type"], "operator_api")
        self.assertEqual(record["details"]["provenance"]["request_endpoint"], "/api/live-data/scan/run")
        self.assertEqual(record["details"]["provenance"]["trigger_source"], "API_MANUAL_SCAN")
        self.assertEqual(record["details"]["provenance"]["approval_status"], "NOT_REQUIRED")
        self.assertEqual(record["details"]["provenance"]["approval_context"], "RELEASE_VALIDATION")
        self.assertEqual(record["details"]["provenance"]["audit_reference"], "RTV-3E-2026-08-25")
        self.assertNotIn("access_token", record["details"]["provenance"])

    def test_unattributed_manual_scan_has_an_explicit_safe_source(self):
        import phase20_scheduler as scheduler

        snapshot = {
            "scan_id": "unattributed-manual-scan",
            "snapshot_ts": "2026-08-20T04:00:00Z",
            "provider_health": {},
            "safety": {},
        }
        captured = []
        fake_hours = types.SimpleNamespace(market_status=lambda: {"state": "OPEN"})
        with patch.dict(sys.modules, {"market_hours": fake_hours}), \
             patch.object(scheduler.store, "record_scan_run", side_effect=captured.append):
            scheduler.record_manual_scan(snapshot)

        self.assertEqual(captured[0]["trigger_source"], "MANUAL")
        provenance = captured[0]["details"]["provenance"]
        self.assertEqual(provenance["actor"], "anonymous_operator")
        self.assertEqual(provenance["actor_type"], "operator_cli")
        self.assertEqual(provenance["actor_id_or_label"], "unavailable")
        self.assertEqual(provenance["approval_status"], "NOT_REQUIRED")
        self.assertRegex(
            provenance["request_id"],
            r"^scan-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )

    def test_internal_diagnostic_origin_is_not_classified_as_a_manual_scan(self):
        import phase20_scheduler as scheduler

        snapshot = {
            "scan_id": "recovery-diagnostic-scan",
            "snapshot_ts": "2026-08-20T04:00:00Z",
            "provider_health": {},
            "safety": {},
        }
        captured = []
        fake_hours = types.SimpleNamespace(market_status=lambda: {"state": "OPEN"})
        with patch.dict(sys.modules, {"market_hours": fake_hours}), \
             patch.object(scheduler.store, "record_scan_run", side_effect=captured.append):
            scheduler.record_manual_scan(snapshot, trigger_origin="RECOVERY")

        self.assertEqual(captured[0]["job_type"], "INTERNAL_DIAGNOSTIC")
        self.assertEqual(
            captured[0]["details"]["provenance"]["trigger_source"],
            "INTERNAL_DIAGNOSTIC",
        )

    def test_file_history_exposes_safe_manual_provenance(self):
        import phase20_store as store

        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "runs.json")
            with patch.object(store, "_SCAN_RUNS_FILE", path), \
                 patch.object(store, "db_available", return_value=False):
                store.record_scan_run({
                    "job_type": "MANUAL_SCAN",
                    "trigger_source": "MANUAL",
                    "source": "MANUAL",
                    "market_state": "OPEN",
                    "started_at": "2026-08-20T04:00:00Z",
                    "completed_at": "2026-08-20T04:00:02Z",
                    "duration_s": 2,
                    "status": "SUCCESS",
                    "details": {
                        "provenance": {
                            "actor": "authenticated_operator",
                            "actor_type": "operator_api",
                            "actor_id_or_label": "unavailable",
                            "request_endpoint": "/api/live-data/scan/run",
                            "request_method": "POST",
                            "request_id": "scan-11111111-1111-4111-8111-111111111111",
                            "correlation_id": "scan-11111111-1111-4111-8111-111111111111",
                            "trigger_source": "API_MANUAL_SCAN",
                            "approval_required": False,
                            "approval_status": "NOT_REQUIRED",
                            "requested_at": "2026-08-20T04:00:00Z",
                            "approval_context": "RELEASE_VALIDATION",
                            "audit_reference": "RTV-3E-2026-08-25",
                            "trigger_route": "/api/live-data/scan/run",
                            "api_key": "must-not-persist",
                        },
                    },
                })
                item = store.list_scan_runs(1)[0]

        self.assertEqual(item["provenance"]["actor"], "authenticated_operator")
        self.assertFalse(item["provenance"]["legacy"])
        self.assertEqual(
            item["provenance"]["request_id"],
            "scan-11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(item["provenance"]["approval_context"], "RELEASE_VALIDATION")
        self.assertNotIn("api_key", item["provenance"])

    def test_credential_shaped_provenance_is_neither_stored_nor_serialized(self):
        import phase20_store as store

        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "runs.json")
            legacy_secret = "sk-secret-should-never-appear"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([{
                    "scan_id": "legacy-unsafe-provenance",
                    "trigger_source": "MANUAL",
                    "details": {
                        "provenance": {
                            "actor": "authenticated_operator",
                            "approval_context": legacy_secret,
                            "audit_reference": "AKIAIOSFODNN7EXAMPLE",
                        },
                    },
                }], fh)
            with patch.object(store, "_SCAN_RUNS_FILE", path), \
                 patch.object(store, "db_available", return_value=False):
                item = store.list_scan_runs(1)[0]

        serialized = json.dumps(item)
        self.assertNotIn(legacy_secret, serialized)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", serialized)
        self.assertTrue(item["provenance"]["legacy"])
        self.assertEqual(item["provenance"]["trigger_source"], "UNKNOWN_LEGACY")

    def test_legacy_manual_history_is_explicitly_unavailable_not_backfilled(self):
        import phase20_store as store

        legacy = store.history_scan_provenance(
            {"provenance": {"actor": "authenticated_operator"}},
            "MANUAL_SCAN",
        )

        self.assertTrue(legacy["legacy"])
        self.assertIsNone(legacy["actor_type"])
        self.assertEqual(legacy["approval_status"], "UNKNOWN")

    def test_jwt_shaped_ids_are_neither_persisted_nor_serialized(self):
        import phase20_store as store

        jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvcGVyYXRvciJ9.signature"
        safe = store.sanitize_scan_provenance({
            "actor_type": "operator_api",
            "request_id": jwt_like,
            "correlation_id": jwt_like,
        })

        self.assertEqual(safe, {"actor_type": "operator_api"})
        self.assertNotIn(jwt_like, json.dumps(safe))


class TestPostmarketRetry(unittest.TestCase):
    def test_provider_deadline_uses_reaped_subprocess(self):
        import post_market_data_refresh as refresh

        with patch.object(
            refresh.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=1),
        ):
            with self.assertRaises(TimeoutError):
                refresh._download_batch_with_deadline(["RELIANCE.NS"])

    def test_partial_refresh_releases_lease_and_keeps_unfinished_symbols(self):
        import post_market_data_refresh as refresh

        values = {}
        released = []
        fake_store = types.SimpleNamespace(
            kv_acquire_expiring_claim=lambda *_args, **_kwargs: True,
            kv_get=lambda key: values.get(key),
            kv_set=lambda key, value: values.__setitem__(key, value),
            kv_release_if_owned=lambda key, token: released.append((key, token)),
            kv_renew_expiring_claim=lambda *_args, **_kwargs: True,
        )
        fake_hours = types.SimpleNamespace(
            MARKET_CLOSE=dtime(15, 30),
            is_trading_day=lambda _day: True,
            now_ist=lambda: datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc),
        )
        partial = {
            "success": True, "status": "PARTIAL", "duration_seconds": 1,
            "failed_symbols": ["ABC"], "missing_symbols": ["XYZ"],
        }
        with patch.dict(sys.modules, {
            "phase20_store": fake_store,
            "market_hours": fake_hours,
        }), patch.object(refresh, "_today_ist", return_value="2026-08-20"), \
             patch.object(refresh, "_perform_postmarket_refresh", return_value=partial):
            result = refresh.maybe_run_postmarket_refresh("POST_CLOSE")

        self.assertTrue(result["ran"])
        self.assertEqual(result["attempt"], 1)
        self.assertEqual(values["ohlcv_postmarket_refresh_state:2026-08-20"][
            "unfinished_symbols"], ["ABC", "XYZ"])
        self.assertEqual(released[0][0], "ohlcv_postmarket_refresh_lease:2026-08-20")

    def test_stale_lease_takeover_retries_only_prior_unfinished_symbols(self):
        import post_market_data_refresh as refresh

        values = {
            "ohlcv_postmarket_refresh_state:2026-08-20": {
                "status": "PARTIAL", "attempts": 1,
                "unfinished_symbols": ["LTIM"],
            },
        }
        acquired = []
        fake_store = types.SimpleNamespace(
            kv_acquire_expiring_claim=lambda key, lease: acquired.append((key, lease)) or True,
            kv_get=lambda key: values.get(key),
            kv_set=lambda key, value: values.__setitem__(key, value),
            kv_release_if_owned=lambda *_args: True,
            kv_renew_expiring_claim=lambda *_args, **_kwargs: True,
        )
        fake_hours = types.SimpleNamespace(
            MARKET_CLOSE=dtime(15, 30),
            is_trading_day=lambda _day: True,
            now_ist=lambda: datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc),
        )
        with patch.dict(sys.modules, {
            "phase20_store": fake_store, "market_hours": fake_hours,
        }), patch.object(refresh, "_today_ist", return_value="2026-08-20"), \
             patch.object(refresh, "_perform_postmarket_refresh", return_value={
                 "success": True, "status": "SUCCESS", "duration_seconds": 1,
                 "failed_symbols": [], "missing_symbols": [],
             }) as worker:
            result = refresh.maybe_run_postmarket_refresh("POST_CLOSE")

        worker.assert_called_once_with(retry_symbols=["LTIM"])
        self.assertEqual(result["attempt"], 2)
        self.assertIn("expires_at", acquired[0][1])

    def test_public_refresh_path_is_blocked_outside_postmarket_window(self):
        import post_market_data_refresh as refresh

        fake_hours = types.SimpleNamespace(
            market_status=lambda: {"state": "CLOSED"},
            MARKET_CLOSE=dtime(15, 30),
            is_trading_day=lambda _day: True,
            now_ist=lambda: datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc),
        )
        with patch.dict(sys.modules, {"market_hours": fake_hours}), \
             patch.object(refresh, "_perform_postmarket_refresh") as worker:
            result = refresh.run_postmarket_refresh()
        self.assertFalse(result["ran"])
        worker.assert_not_called()

    def test_lost_lease_cannot_publish_a_stale_refresh_outcome(self):
        import post_market_data_refresh as refresh

        original = {
            "status": "PARTIAL", "attempts": 1, "unfinished_symbols": ["LTIM"],
        }
        values = {"ohlcv_postmarket_refresh_state:2026-08-20": dict(original)}
        fake_store = types.SimpleNamespace(
            kv_acquire_expiring_claim=lambda *_args, **_kwargs: True,
            kv_get=lambda key: values.get(key),
            kv_set=lambda key, value: values.__setitem__(key, value),
            kv_release_if_owned=lambda *_args: True,
            # Simulates a second owner taking an expired lease while this
            # worker was running; this worker must not overwrite day state.
            kv_renew_expiring_claim=lambda *_args, **_kwargs: False,
        )
        fake_hours = types.SimpleNamespace(
            MARKET_CLOSE=dtime(15, 30),
            is_trading_day=lambda _day: True,
            now_ist=lambda: datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc),
        )
        with patch.dict(sys.modules, {
            "phase20_store": fake_store, "market_hours": fake_hours,
        }), patch.object(refresh, "_today_ist", return_value="2026-08-20"), \
             patch.object(refresh, "_perform_postmarket_refresh", return_value={
                 "success": True, "status": "SUCCESS", "duration_seconds": 1,
                 "failed_symbols": [], "missing_symbols": [],
             }):
            result = refresh.maybe_run_postmarket_refresh("POST_CLOSE")

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(values["ohlcv_postmarket_refresh_state:2026-08-20"], original)


class TestCommitTimeMarketGuard(unittest.TestCase):
    def test_paper_ledger_admission_fails_closed_when_market_is_not_open(self):
        import phase20_executor as executor

        with patch.object(executor, "_market_entry_allowed", return_value=False):
            with self.assertRaises(executor.MarketClosedForEntry):
                executor._insert_row({"status": "OPEN", "symbol": "RELIANCE"})


class TestStatusAndHistoryContract(unittest.TestCase):
    def test_history_prefers_labeled_job_rows_over_generic_pipeline_events(self):
        import scan_state_store as state

        jobs = [{
            "job_type": "POSTMARKET_CACHE_REFRESH",
            "scan_type": "NON_MARKET",
            "started_at": "2026-08-20T10:05:00Z",
            "completed_at": "2026-08-20T10:05:02Z",
            "started_at_ist": "2026-08-20T15:35:00+05:30",
            "completed_at_ist": "2026-08-20T15:35:02+05:30",
            "duration_s": 2, "symbols_scanned": 50, "gap_from_prev_s": None,
            "status": "SUCCESS", "market_state": "POST_CLOSE",
            "entry_eligible": False, "execution_eligible": False,
            "source": "SCHEDULER",
        }]
        with patch.object(state, "_classified_jobs_today_ist", return_value=jobs):
            response = state.build_scan_history_response()
        self.assertEqual(response["all_system_jobs_today"], 1)
        self.assertEqual(response["market_scans_today"], 0)
        self.assertEqual(response["history"][0]["job_type"], "POSTMARKET_CACHE_REFRESH")
        self.assertFalse(response["history"][0]["execution_eligible"])


if __name__ == "__main__":
    unittest.main()