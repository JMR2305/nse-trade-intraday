#!/usr/bin/env python3
"""Offline tests for the bounded Task976 Zeabur benchmark runner."""

from __future__ import annotations

import contextlib
import inspect
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zeabur_benchmark as benchmark
import task976_zeabur_fixture as fixture


class Task976BenchmarkOfflineTests(unittest.TestCase):
    def test_wrong_database_identity_fails_closed(self):
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_preflight_identity({
                "database": "production", "db_user": fixture.AUTHORIZED_USER,
                "version_num": 160015,
            })

    def test_wrong_hash_fails_closed(self):
        evidence = benchmark.ExpectedEvidence(
            dict(fixture.EXPECTED_FIXTURE_COUNTS),
            sorted(fixture.task969.SYMBOLS), "0" * 64,
        )
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_exact_fixture(evidence, True)

    def test_incomplete_fixture_fails_closed(self):
        counts = dict(fixture.EXPECTED_FIXTURE_COUNTS)
        counts["trading_universe_members"] = 22
        evidence = benchmark.ExpectedEvidence(
            counts, sorted(fixture.task969.SYMBOLS[:-1]),
            fixture.exact_set_hash(fixture.task969.SYMBOLS[:-1]),
        )
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_exact_fixture(evidence, False)

    def test_broker_capable_mapping_token_fails_closed(self):
        tokens = list(range(900001, 900024))
        tokens[-1] = 12345
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_benchmark_only_tokens(tokens)

    def test_missing_acknowledgement_rejected(self):
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_environment({})

    def test_workload_is_bounded(self):
        config = benchmark.WorkloadConfig()
        self.assertEqual(config.iterations, 20_000)
        self.assertEqual(config.statement_timeout_ms, 5_000)
        self.assertEqual(config.max_seconds, 300)
        benchmark.validate_workload(config)
        with self.assertRaises(fixture.SafetyError):
            benchmark.validate_workload(benchmark.WorkloadConfig(iterations=100_001))

    def test_zero_and_invalid_workload_rejected(self):
        for config in (
            benchmark.WorkloadConfig(iterations=0),
            benchmark.WorkloadConfig(statement_timeout_ms=0),
            benchmark.WorkloadConfig(max_seconds=0),
        ):
            with self.subTest(config=config), self.assertRaises(fixture.SafetyError):
                benchmark.validate_workload(config)

    def test_metrics_aggregation_is_deterministic(self):
        metrics = benchmark.aggregate_metrics(
            [1.0, 2.0, 3.0, 4.0, 100.0], wall_seconds=2.0,
            total_operations=6, failed_operations=1,
            db_failures=1, timeout_count=0, memory_failures=0,
        )
        self.assertEqual(metrics.successful_operations, 5)
        self.assertEqual(metrics.throughput_ops_per_second, 2.5)
        self.assertEqual(metrics.average_ms, 22.0)
        self.assertEqual(metrics.median_ms, 3.0)
        self.assertEqual(metrics.p50_ms, 3.0)
        self.assertEqual(metrics.p95_ms, 100.0)
        self.assertEqual(metrics.p99_ms, 100.0)

    def test_zero_success_failure_metrics_are_retained(self):
        metrics = benchmark.aggregate_metrics(
            [], wall_seconds=1.0, requested_operations=20_000,
            total_operations=1, failed_operations=1, db_failures=1,
            timeout_count=1, memory_failures=0, deadline_exceeded=False,
        )
        self.assertEqual(metrics.successful_operations, 0)
        self.assertEqual(metrics.failed_operations, 1)
        self.assertEqual(metrics.timeout_count, 1)
        self.assertEqual(metrics.min_ms, 0.0)

    def test_credentials_are_redacted(self):
        url = "postgresql://apexquant_benchmark:secret@postgres16-benchmark.zeabur.internal:5432/apexquant_disposable"
        rendered = benchmark.safe_error(RuntimeError(url), url)
        self.assertNotIn("secret", rendered)
        self.assertNotIn(url, rendered)

    def test_post_run_fixture_failure_causes_fail(self):
        before = benchmark.Snapshot(
            {"pipeline_events": 375, **fixture.EXPECTED_FIXTURE_COUNTS}, True
        )
        after = benchmark.Snapshot(before.table_counts, False)
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_post_run_integrity(before, after)

    def test_unrelated_table_mutation_causes_fail(self):
        before = benchmark.Snapshot(
            {"pipeline_events": 375, **fixture.EXPECTED_FIXTURE_COUNTS}, True
        )
        after = benchmark.Snapshot(
            {"pipeline_events": 376, **fixture.EXPECTED_FIXTURE_COUNTS}, True
        )
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_post_run_integrity(before, after)

    def test_query_result_requires_exact_symbols_and_tokens(self):
        rows = [(row[0], row[2]) for row in fixture.expected_member_rows()]
        benchmark.require_operation_result(rows)
        with self.assertRaises(fixture.SafetyError):
            benchmark.require_operation_result(rows[:-1])

    def test_benchmark_sql_is_read_only_and_import_contract_excludes_brokers(self):
        self.assertTrue(benchmark.READ_QUERY.lstrip().upper().startswith("SELECT"))
        self.assertNotRegex(
            benchmark.READ_QUERY.upper(), r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b"
        )
        source = inspect.getsource(benchmark)
        for forbidden in benchmark.FORBIDDEN_BROKER_MODULES:
            self.assertNotRegex(source, rf"(?m)^\s*(?:from|import)\s+{forbidden}\b")
        benchmark.require_no_broker_modules()

    def test_main_sets_read_only_before_first_live_query_and_connect_is_bounded(self):
        events = []

        class Connection:
            configured = False
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def set_session(self, *, readonly, autocommit):
                self.configured = readonly and autocommit
                events.append("readonly")

        conn = Connection()
        env = {
            "DATABASE_URL": "postgresql://apexquant_benchmark:secret@postgres16-benchmark.zeabur.internal:5432/apexquant_disposable",
            "TASK976_DISPOSABLE_ACK": fixture.REQUIRED_ACK,
        }
        def identity(active):
            self.assertTrue(active.configured)
            events.append("identity")
            return {"database": fixture.AUTHORIZED_DATABASE,
                    "db_user": fixture.AUTHORIZED_USER, "version_num": 160015}
        with patch.object(benchmark.fixture.psycopg2, "connect", return_value=conn) as connect, \
                patch.object(benchmark.fixture, "read_live_identity", side_effect=identity), \
                patch.object(benchmark, "execute"):
            self.assertEqual(benchmark.main([], env), 0)
        self.assertEqual(events[:2], ["readonly", "identity"])
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], 10)

    def test_deadline_stops_iterations_without_counting_db_timeout(self):
        rows = [(row[0], row[2]) for row in fixture.expected_member_rows()]
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def execute(self, *_args): return None
            def fetchall(self): return rows
        class Connection:
            def cursor(self): return Cursor()
        clock = iter([0.0, 0.0, 0.0, 0.001, 301.0, 301.0])
        with patch.object(benchmark.time, "perf_counter", side_effect=lambda: next(clock)):
            metrics, complete = benchmark.run_queries(Connection(), benchmark.WorkloadConfig())
        self.assertFalse(complete)
        self.assertEqual(metrics.total_operations, 1)
        self.assertTrue(metrics.deadline_exceeded)
        self.assertEqual(metrics.timeout_count, 0)

    def test_first_operation_memory_failure_retains_metrics(self):
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def execute(self, *_args): raise MemoryError("bounded test")
        class Connection:
            def cursor(self): return Cursor()
        metrics, complete = benchmark.run_queries(Connection(), benchmark.WorkloadConfig(iterations=1))
        self.assertFalse(complete)
        self.assertEqual(metrics.memory_failures, 1)
        self.assertEqual(metrics.successful_operations, 0)

    def test_first_operation_db_timeout_retains_failure_metrics(self):
        class QueryTimeout(Exception):
            pgcode = "57014"
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def execute(self, *_args): raise QueryTimeout("statement timeout")
        class Connection:
            def cursor(self): return Cursor()
        metrics, complete = benchmark.run_queries(Connection(), benchmark.WorkloadConfig(iterations=1))
        self.assertFalse(complete)
        self.assertEqual(metrics.db_query_failures, 1)
        self.assertEqual(metrics.timeout_count, 1)
        self.assertEqual(metrics.failed_operations, 1)

    def test_main_failure_does_not_leak_url(self):
        url = "postgresql://apexquant_benchmark:secret@postgres16-benchmark.zeabur.internal:5432/apexquant_disposable"
        output = io.StringIO()
        env = {"DATABASE_URL": url, "TASK976_DISPOSABLE_ACK": fixture.REQUIRED_ACK}
        with patch.object(benchmark.fixture.psycopg2, "connect", side_effect=RuntimeError(url)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(benchmark.main([], env), 1)
        self.assertNotIn("secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
