#!/usr/bin/env python3
"""Offline timing/evidence regressions using real runner and worker modules."""
import contextlib
import io
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zb5_runner as runner
import task976_zb5_worker as worker


def good_row():
    return {"status": "PASS", "tier": 3, "symbols_processed": 23,
            "bars_per_symbol": 504, "symbol_hash": worker.CANONICAL_HASH,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 10.0, "lab_walk_calls": 7}


class Proc:
    pid = 123
    returncode = 0

    def __init__(self, row):
        self.row = row

    def communicate(self, timeout):
        assert timeout == 75
        return json.dumps(self.row), ""

    def poll(self):
        return self.returncode


class ZB5TimingAndEvidenceTests(unittest.TestCase):
    def test_elapsed_includes_delay_after_actual_spawn(self):
        proc, launched = runner.spawn_worker(
            [sys.executable, "-c", "print('{}')"], env={})
        try:
            time.sleep(.08)
            collection_started = time.monotonic()
            outcome = runner.collect_worker_with_diagnostic(proc, 0, launched)
            self.assertGreaterEqual(outcome.duration_monotonic_ms, 80)
            self.assertLess(launched / 1_000_000, collection_started)
        finally:
            runner.cleanup_process(proc)

    def test_original_timestamp_controls_elapsed(self):
        with patch.object(runner.time, "monotonic", return_value=12):
            outcome = runner.collect_worker_with_diagnostic(Proc(good_row()), 0, 2_000_000)
        self.assertEqual(outcome.duration_monotonic_ms, 10000)

    def test_explicit_failure_is_rejected_even_with_valid_fields(self):
        row = {**good_row(), "status": "FAIL", "error": "worker deadline exceeded"}
        outcome = runner.collect_worker_with_diagnostic(Proc(row), 0, 0)
        self.assertEqual(outcome.classification, "WORKER_REPORTED_FAILURE")
        with self.assertRaisesRegex(runner.SafetyError, "worker evidence count mismatch"):
            runner.collect_worker_evidence([(Proc(row), 0)] * 3, runner.tier_config(3))

    def test_three_pass_rows_accepted(self):
        rows, diagnostics = runner.collect_worker_evidence(
            [(Proc(good_row()), 0) for _ in range(3)], runner.tier_config(3))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["classification"] for r in diagnostics["worker_outcomes"]],
                         ["PASS_EVIDENCE"] * 3)

    def test_two_pass_one_failure_emits_all_diagnostics(self):
        failed = {"status": "FAIL", "error": "secret-value", "tier": "secret-value"}
        with self.assertRaises(runner.SafetyError) as caught:
            runner.collect_worker_evidence(
                [(Proc(row), 0) for row in [good_row(), good_row(), failed]], runner.tier_config(3))
        self.assertEqual(str(caught.exception), "worker evidence count mismatch")
        diagnostics = caught.exception.worker_diagnostics
        self.assertEqual(diagnostics["worker_evidence_rows"], 2)
        self.assertEqual([r["classification"] for r in diagnostics["worker_outcomes"]],
                         ["PASS_EVIDENCE", "PASS_EVIDENCE", "WORKER_REPORTED_FAILURE"])
        self.assertTrue(diagnostics["worker_outcomes"][2]["error_reason_if_any"])
        with patch.object(runner, "execute_with_deadline", side_effect=caught.exception), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(runner.main(["--tier", "3"], env={}), 1)
        self.assertIn("worker evidence count mismatch", err.getvalue())
        self.assertIn('"worker_index": 2', err.getvalue())
        self.assertNotIn("secret-value", err.getvalue())

    def test_existing_statusless_worker_contract(self):
        row = worker.run_deterministic_workload(3, scan_one=lambda symbol, bars: {"_task976_lab_walk_calls": 1})
        self.assertNotIn("status", row)
        outcome = runner.collect_worker_with_diagnostic(Proc(row), 0, 0)
        self.assertEqual(outcome.classification, "PASS_EVIDENCE")
        bad = runner.collect_worker_with_diagnostic(Proc({}), 0, 0)
        self.assertNotEqual(bad.classification, "PASS_EVIDENCE")

    def test_cleanup_failure_is_rejected(self):
        with patch.object(runner, "cleanup_process", return_value=False):
            outcome = runner.collect_worker_with_diagnostic(Proc(good_row()), 0, 0)
        self.assertEqual(outcome.classification, "CLEANUP_FAILURE")

    def test_each_failure_mode_excludes_row_and_retains_diagnostics(self):
        cases = [
            ("NONZERO_EXIT", 1, "", json.dumps(good_row()), True),
            ("STDERR_OUTPUT", 0, "arbitrary-secret", json.dumps(good_row()), True),
            ("EMPTY_STDOUT", 0, "", "", True),
            ("INVALID_JSON", 0, "", "broken", True),
            ("INVALID_JSON", 0, "", "[]", True),
            ("INVALID_EVIDENCE", 0, "", "{}", True),
            ("CLEANUP_FAILURE", 0, "", json.dumps(good_row()), False),
            ("COMMUNICATE_TIMEOUT", None, "", None, True),
        ]
        for classification, code, stderr, stdout, cleanup_ok in cases:
            with self.subTest(classification=classification):
                proc = Proc(good_row())
                proc.returncode = code
                def communicate(timeout):
                    if stdout is None:
                        raise subprocess.TimeoutExpired("worker", timeout)
                    return stdout, stderr
                proc.communicate = communicate
                with patch.object(runner, "cleanup_process", return_value=cleanup_ok), self.assertRaises(runner.SafetyError) as caught:
                    runner.collect_worker_evidence(
                        [(Proc(good_row()), 0), (Proc(good_row()), 0), (proc, 0)], runner.tier_config(3))
                self.assertEqual(str(caught.exception), "worker evidence count mismatch")
                evidence = caught.exception.worker_diagnostics
                self.assertEqual(len(evidence["worker_outcomes"]), 3)
                self.assertEqual(evidence["worker_outcomes"][2]["classification"], classification)
                self.assertLess(evidence["worker_evidence_rows"], 3)
                self.assertNotIn("arbitrary-secret", json.dumps(evidence))

    def test_timeout_elapsed_includes_precollection_lifetime(self):
        proc = Proc(good_row())
        with patch.object(proc, "communicate", side_effect=subprocess.TimeoutExpired("worker", 75)), patch.object(runner.time, "monotonic", return_value=85):
            outcome = runner.collect_worker_with_diagnostic(proc, 0, 2_000_000)
        self.assertEqual(outcome.duration_monotonic_ms, 83000)
        self.assertEqual(outcome.classification, "COMMUNICATE_TIMEOUT")

    def test_timing_contract_unchanged(self):
        for tier, bars, deadline, shell in [(1, 252, 180, 240), (2, 252, 240, 300), (3, 504, 240, 300)]:
            with self.subTest(tier=tier):
                self.assertEqual(worker.worker_plan(tier), (bars, 75))
                config = runner.tier_config(tier)
                self.assertEqual(config.internal_deadline_s, deadline)
                self.assertEqual(config.shell_timeout_s, shell)
                self.assertEqual(config.scanner_workers, tier)


if __name__ == "__main__":
    unittest.main()
