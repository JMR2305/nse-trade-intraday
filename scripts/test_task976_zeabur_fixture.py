#!/usr/bin/env python3
"""Offline tests for the Task976 Zeabur disposable fixture wrapper."""

from __future__ import annotations

import contextlib
import io
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
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


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


if __name__ == "__main__":
    unittest.main()
