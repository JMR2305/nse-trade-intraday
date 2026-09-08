#!/usr/bin/env python3
"""Offline tests for the Task976 Zeabur disposable fixture wrapper."""

from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zeabur_fixture as fixture


PASSWORD = "very-secret-password"
GOOD_URL = (
    "postgresql://apexquant_benchmark:" + PASSWORD
    + "@postgres16-benchmark.zeabur.internal:5432/apexquant_disposable"
)


class FakeConnection:
    def __init__(self):
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        self.commits += 1


class RecordingCursor:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))


class RecordingConnection(FakeConnection):
    def __init__(self):
        super().__init__()
        self.statements = []

    def cursor(self):
        return RecordingCursor(self.statements)


class ZeaburFixtureOfflineTests(unittest.TestCase):
    def assert_url_rejected(self, url: str) -> None:
        with self.assertRaises(fixture.SafetyError):
            fixture.validate_database_url(url)

    def test_rejects_wrong_host(self):
        self.assert_url_rejected(GOOD_URL.replace(fixture.AUTHORIZED_HOST, "prod.internal"))

    def test_rejects_wrong_database(self):
        self.assert_url_rejected(GOOD_URL.replace("/apexquant_disposable", "/apexquant"))

    def test_rejects_wrong_port(self):
        self.assert_url_rejected(GOOD_URL.replace(":5432/", ":5433/"))

    def test_rejects_wrong_user(self):
        self.assert_url_rejected(GOOD_URL.replace("apexquant_benchmark:", "postgres:"))

    def test_rejects_non_pg16(self):
        with self.assertRaises(fixture.SafetyError):
            fixture.require_live_identity({
                "database": fixture.AUTHORIZED_DATABASE,
                "db_user": fixture.AUTHORIZED_USER,
                "version_num": 150015,
            })

    def test_rejects_missing_acknowledgement(self):
        with self.assertRaises(fixture.SafetyError):
            fixture.require_ack({})

    def test_redacts_url_and_credentials(self):
        message = f"connection failed: {GOOD_URL}; password={PASSWORD}"
        redacted = fixture.redact(message, GOOD_URL)
        self.assertNotIn(GOOD_URL, redacted)
        self.assertNotIn(PASSWORD, redacted)
        self.assertIn("[REDACTED", redacted)

    def test_accepts_only_exact_authorized_identity(self):
        parsed = fixture.validate_database_url(GOOD_URL)
        self.assertEqual(parsed.host, fixture.AUTHORIZED_HOST)
        self.assertEqual(parsed.port, fixture.AUTHORIZED_PORT)
        self.assertEqual(parsed.database, fixture.AUTHORIZED_DATABASE)
        self.assertEqual(parsed.user, fixture.AUTHORIZED_USER)
        fixture.require_live_identity({
            "database": fixture.AUTHORIZED_DATABASE,
            "db_user": fixture.AUTHORIZED_USER,
            "version_num": 160015,
        })

    def test_computes_exact_expected_23_symbol_hash(self):
        self.assertEqual(len(fixture.task969.SYMBOLS), 23)
        self.assertEqual(
            fixture.exact_set_hash(fixture.task969.SYMBOLS),
            "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016",
        )

    def test_main_failure_never_prints_credentials(self):
        env = {
            "DATABASE_URL": GOOD_URL,
            "TASK976_DISPOSABLE_ACK": fixture.REQUIRED_ACK,
        }
        output = io.StringIO()
        with patch.object(fixture.psycopg2, "connect", side_effect=RuntimeError(GOOD_URL)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(fixture.main([], env), 1)
        rendered = output.getvalue()
        self.assertNotIn(GOOD_URL, rendered)
        self.assertNotIn(PASSWORD, rendered)

    def test_bootstrapped_unrelated_tables_are_allowed_and_preserved(self):
        before = {"pipeline_events": 375, **dict.fromkeys(fixture.AUTHORITY_TABLES, 0)}
        after = {"pipeline_events": 375, **fixture.EXPECTED_FIXTURE_COUNTS}
        fixture.require_unrelated_tables_preserved(before, after)

    def test_unrelated_table_change_fails_closed(self):
        with self.assertRaises(fixture.SafetyError):
            fixture.require_unrelated_tables_preserved(
                {"pipeline_events": 375}, {"pipeline_events": 376}
            )

    def test_empty_existing_authority_tables_are_accepted(self):
        counts = dict.fromkeys(fixture.AUTHORITY_TABLES, 0)
        self.assertEqual(fixture.classify_authority_state(counts, False), "EMPTY")

    def test_missing_reviewed_authority_tables_are_created_additively(self):
        conn = FakeConnection()
        missing = {"trading_universe_validations", "trading_universe_baseline_migrations"}
        statements = fixture.reviewed_additive_statements(missing)
        rendered = "\n".join(statements)
        self.assertIn("CREATE TABLE trading_universe_validations", rendered)
        self.assertIn("CREATE TABLE trading_universe_baseline_migrations", rendered)
        self.assertNotRegex(rendered.upper(), r"\b(DROP|TRUNCATE|DELETE)\b")

    def test_nonempty_conflicting_authority_tables_fail_closed(self):
        counts = dict.fromkeys(fixture.AUTHORITY_TABLES, 0)
        counts["trading_universes"] = 1
        with self.assertRaises(fixture.SafetyError):
            fixture.classify_authority_state(counts, False)

    def test_exact_existing_fixture_is_idempotently_accepted_without_seed(self):
        conn = FakeConnection()
        before = {"pipeline_events": 375, **fixture.EXPECTED_FIXTURE_COUNTS}
        evidence = (fixture.EXPECTED_FIXTURE_COUNTS, sorted(fixture.task969.SYMBOLS), fixture.task969.APPROVED_SET_HASH)
        with patch.object(fixture, "public_table_counts", side_effect=[before, before]), \
                patch.object(fixture, "fixture_state_is_exact", return_value=True), \
                patch.object(fixture, "fixture_evidence", return_value=evidence), \
                patch.object(fixture, "create_missing_authority_tables") as create, \
                patch.object(fixture.task969, "seed_authority_state") as seed:
            fixture.prepare(conn)
        create.assert_not_called()
        seed.assert_not_called()

    def test_first_prepare_seeds_once_without_touching_unrelated_tables(self):
        conn = FakeConnection()
        before = {"pipeline_events": 375, **dict.fromkeys(fixture.AUTHORITY_TABLES, 0)}
        after = {"pipeline_events": 375, **fixture.EXPECTED_FIXTURE_COUNTS}
        evidence = (fixture.EXPECTED_FIXTURE_COUNTS, sorted(fixture.task969.SYMBOLS), fixture.task969.APPROVED_SET_HASH)
        with patch.object(fixture, "public_table_counts", side_effect=[before, after]), \
                patch.object(fixture, "fixture_state_is_exact", side_effect=[False, True]), \
                patch.object(fixture, "create_missing_authority_tables") as create, \
                patch.object(
                    fixture.task969, "seed_authority_state",
                    side_effect=lambda wrapped: wrapped.commit(),
                ) as seed, \
                patch.object(fixture, "fixture_evidence", return_value=evidence):
            fixture.prepare(conn)
        create.assert_called_once_with(conn, set())
        seed.assert_called_once()
        self.assertIsNot(seed.call_args.args[0], conn)
        self.assertEqual(conn.commits, 1)

    def test_wrong_23_symbol_set_fails(self):
        symbols = sorted(fixture.task969.SYMBOLS[:-1] + ["RELIANCE"])
        with self.assertRaises(fixture.SafetyError):
            fixture.require_fixture_evidence(
                fixture.EXPECTED_FIXTURE_COUNTS, symbols, fixture.exact_set_hash(symbols)
            )

    def test_wrong_hash_fails(self):
        with self.assertRaises(fixture.SafetyError):
            fixture.require_fixture_evidence(
                fixture.EXPECTED_FIXTURE_COUNTS,
                sorted(fixture.task969.SYMBOLS),
                "0" * 64,
            )

    def test_canonical_fixture_sector_distribution_is_exact(self):
        rows = fixture.expected_member_rows()
        sectors = [row[1] for row in rows]
        self.assertEqual(sectors.count("BANK"), 9)
        self.assertEqual(sectors.count("INFRA"), 13)
        self.assertEqual(sectors.count("IT"), 1)

    def test_cleanup_sql_targets_only_authority_tables(self):
        conn = RecordingConnection()
        fixture.delete_fixture_rows(conn)
        rendered = "\n".join(sql for sql, _params in conn.statements)
        self.assertNotRegex(rendered.upper(), r"\b(DROP|TRUNCATE|ALTER)\b")
        targets = set(re.findall(r"DELETE FROM ([a-z0-9_]+)", rendered, re.I))
        self.assertEqual(targets, fixture.AUTHORITY_TABLE_SET)

    def test_cleanup_predicates_prove_full_fixture_ownership(self):
        conn = RecordingConnection()
        fixture.delete_fixture_rows(conn)
        rendered = "\n".join(sql for sql, _params in conn.statements)
        for required in (
            "universe_symbols", "universe_set_hash", "metadata", "evidence",
            "instrument_token", "exchange", "source_reference", "reason",
        ):
            self.assertIn(required, rendered)

    def test_cleanup_deletes_only_fixture_rows_and_preserves_runtime_tables(self):
        conn = RecordingConnection()
        before = {"pipeline_events": 375, **fixture.EXPECTED_FIXTURE_COUNTS}
        after = {"pipeline_events": 375, **dict.fromkeys(fixture.AUTHORITY_TABLES, 0)}
        with patch.object(fixture, "public_table_counts", side_effect=[before, after]), \
                patch.object(fixture, "fixture_state_is_exact", return_value=True), \
                patch.object(fixture, "delete_fixture_rows") as delete:
            fixture.cleanup(conn)
        delete.assert_called_once_with(conn)

    def test_cleanup_refuses_unproven_fixture_ownership(self):
        conn = FakeConnection()
        with patch.object(
            fixture, "public_table_counts", return_value={"pipeline_events": 375}
        ), patch.object(fixture, "fixture_state_is_exact", return_value=False), \
                patch.object(fixture, "delete_fixture_rows") as delete:
            with self.assertRaises(fixture.SafetyError):
                fixture.cleanup(conn)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
