#!/usr/bin/env python3
"""Offline tests for guarded ZB5 orchestration and evidence."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zb5_runner as runner
import task976_zb5_worker as worker
from task976_zb5_timing_and_evidence_test import ZB5TimingAndEvidenceTests, good_row

GOOD_URL = ("postgresql://apexquant_benchmark:very-secret@"
            "postgres16-benchmark.zeabur.internal:5432/apexquant_disposable")


class ZB5RunnerTests(unittest.TestCase):
    def safe_env(self):
        return {"DATABASE_URL": GOOD_URL, "TASK976_DISPOSABLE_ACK": "apexquant_disposable",
                **{name: "false" for name in runner.SAFETY_FLAGS}}

    def failure_proc(self, stderr, stdout="", returncode=1):
        class Proc:
            pid = 123
            def communicate(self, timeout):
                return stdout, stderr
            def poll(self):
                return self.returncode
        proc = Proc()
        proc.returncode = returncode
        return proc

    def controlled_failure(self, workload):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(worker, "run_deterministic_workload", side_effect=workload), \
             patch.object(worker.signal, "signal"), patch.object(worker.signal, "alarm"), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = worker.main(["--tier", "3"])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "")
        return self.failure_proc(err.getvalue(), out.getvalue(), code)

    def assert_safe_failure(self, proc, reason):
        outcome = runner.collect_worker_with_diagnostic(proc, 0, 0)
        record = runner.worker_outcome_to_dict(outcome)
        self.assertEqual(record["classification"], "NONZERO_EXIT")
        self.assertEqual(record["returncode"], 1)
        self.assertEqual(record.get("worker_failure_reason"), reason)
        self.assertEqual(record["stderr_bounded"], "<REDACTED>")
        self.assertIsNone(outcome.parsed)
        self.assertFalse(outcome.json_parse_ok)
        return record

    def test_stderr_controlled_worker_deadline_reason(self):
        def expired(tier):
            worker.signal.signal.call_args.args[1](None, None)
        proc = self.controlled_failure(expired)
        record = self.assert_safe_failure(proc, "WORKER_DEADLINE_EXCEEDED")
        self.assertNotIn("worker deadline exceeded", json.dumps(record))

    def test_stderr_controlled_forbidden_callable_reason(self):
        def forbidden(tier):
            worker.require_safe_callable("place_order")
        record = self.assert_safe_failure(self.controlled_failure(forbidden), "FORBIDDEN_CALLABLE")
        self.assertNotIn("place_order", json.dumps(record))

    def test_stderr_secrets_are_unknown_and_redacted(self):
        secret = "DATABASE_URL=postgresql://u:p@host/db PGPASSWORD=password KITE_API_KEY=key token=secret-value"
        for raw in (secret, json.dumps({"status": "FAIL", "error": secret}),
                    json.dumps({"status": "FAIL", "error": "worker deadline exceeded " + secret})):
            with self.subTest():
                record = self.assert_safe_failure(self.failure_proc(raw), "UNKNOWN_WORKER_FAILURE")
                for text in ("DATABASE_URL", "PGPASSWORD", "KITE_API_KEY", "secret-value", "postgresql", "token="):
                    self.assertNotIn(text, json.dumps(record))

    def test_stderr_malformed_or_unexpected_json_fails_closed(self):
        for raw in ('{', '[]', 'null', '{"status":"FAIL","error":[]}',
                    '{"status":"PASS","error":"worker deadline exceeded"}',
                    '{"status":"FAIL","error":"worker deadline exceeded","extra":1}',
                    '{"status":"PASS","status":"FAIL","error":"worker deadline exceeded"}',
                    '{"status":"FAIL","error":"worker deadline exceeded"} trailing',
                    '[' * 1100, ' ' * 1201):
            with self.subTest():
                self.assert_safe_failure(self.failure_proc(raw), "UNKNOWN_WORKER_FAILURE")

    def test_stderr_known_worker_messages_normalize_exactly(self):
        cases = [("worker exceeded 75-second bound", "WORKER_DEADLINE_EXCEEDED"),
                 ("external provider disabled", "EXTERNAL_ACCESS_BLOCKED"),
                 ("socket blocked", "EXTERNAL_ACCESS_BLOCKED"),
                 ("external socket destination blocked", "EXTERNAL_ACCESS_BLOCKED"),
                 ("datagram destination missing", "EXTERNAL_ACCESS_BLOCKED"),
                 ("broker/backtest-lifecycle module loaded", "FORBIDDEN_MODULE"),
                 ("real provider module loaded", "FORBIDDEN_MODULE"),
                 ("tier must be exactly 1, 2, or 3", "WORKER_SAFETY_ERROR"),
                 ("exact Task969 symbol set/hash required", "WORKER_SAFETY_ERROR"),
                 ("bars outside 60..2000", "WORKER_SAFETY_ERROR"),
                 ("_run_lab_walk execution was not proven", "WORKER_SAFETY_ERROR")]
        cases += [(prefix + name, "FORBIDDEN_CALLABLE")
                  for prefix in ("forbidden callable: ", "forbidden callable reached: ")
                  for name in worker.FORBIDDEN_CALLABLES]
        for message, reason in cases:
            with self.subTest(message=message):
                self.assert_safe_failure(self.failure_proc(json.dumps({"status": "FAIL", "error": message})), reason)
        self.assert_safe_failure(self.failure_proc(json.dumps({"status": "FAIL", "error": "forbidden callable: secret"})),
                                 "UNKNOWN_WORKER_FAILURE")

    def test_stderr_normalization_leaves_pass_evidence_unchanged(self):
        row = good_row()
        rows, diagnostic = runner.collect_worker_evidence(
            [(self.failure_proc("", json.dumps(row), 0), 0) for _ in range(3)], runner.tier_config(3))
        self.assertEqual(rows, [row] * 3)
        for record in diagnostic["worker_outcomes"]:
            self.assertEqual(record["classification"], "PASS_EVIDENCE")
            self.assertEqual(record.get("worker_failure_reason"), "")

    def test_stderr_reasons_survive_canonical_tier3_evidence_failure(self):
        messages = ["worker deadline exceeded", "forbidden callable reached: place_order", "unrecognized-secret"]
        with self.assertRaisesRegex(runner.SafetyError, "^worker evidence count mismatch$") as caught:
            runner.collect_worker_evidence([(self.failure_proc(json.dumps({"status": "FAIL", "error": message})), 0)
                                            for message in messages], runner.tier_config(3))
        diagnostic = caught.exception.worker_diagnostics
        self.assertEqual(diagnostic["worker_evidence_rows"], 0)
        self.assertEqual(diagnostic["worker_evidence_required"], 3)
        self.assertEqual(diagnostic["worker_crashes"], 3)
        self.assertEqual([r["classification"] for r in diagnostic["worker_outcomes"]], ["NONZERO_EXIT"] * 3)
        self.assertEqual([r.get("worker_failure_reason") for r in diagnostic["worker_outcomes"]],
                         ["WORKER_DEADLINE_EXCEEDED", "FORBIDDEN_CALLABLE", "UNKNOWN_WORKER_FAILURE"])
        with patch.object(runner, "execute_with_deadline", side_effect=caught.exception), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(runner.main(["--tier", "3"], env={}), 1)
        self.assertIn("worker evidence count mismatch", err.getvalue())
        self.assertIn("WORKER_DEADLINE_EXCEEDED", err.getvalue())
        self.assertNotIn("unrecognized-secret", err.getvalue())

    def test_environment_requires_ack_and_exact_identity(self):
        with self.assertRaises(runner.SafetyError): runner.require_environment({})
        env = self.safe_env(); env["DATABASE_URL"] = GOOD_URL.replace("apexquant_disposable", "prod")
        with self.assertRaises(runner.SafetyError): runner.require_environment(env)

    def test_all_execution_flags_must_be_explicitly_false(self):
        for name in runner.SAFETY_FLAGS:
            env = self.safe_env(); env[name] = "true"
            with self.subTest(name=name), self.assertRaises(runner.SafetyError):
                runner.require_environment(env)
            env = self.safe_env(); del env[name]
            with self.assertRaises(runner.SafetyError): runner.require_environment(env)

    def test_live_identity_requires_pg16(self):
        with self.assertRaises(runner.SafetyError):
            runner.require_live_identity({"database": "apexquant_disposable",
                                          "db_user": "apexquant_benchmark", "version_num": 150000})

    def test_fixture_contract_exact(self):
        runner.require_fixture(runner.expected_fixture_evidence())
        for field, value in (("universe_id", 4), ("version", 2), ("symbols", []),
                             ("exact_set_hash", "0" * 64), ("tokens", [1] * 23)):
            bad = runner.expected_fixture_evidence(); bad[field] = value
            with self.subTest(field=field), self.assertRaises(runner.SafetyError):
                runner.require_fixture(bad)

    def test_swapped_symbol_token_mapping_fails(self):
        bad = runner.expected_fixture_evidence()
        mappings = list(bad["mappings"])
        mappings[0] = (mappings[0][0], mappings[1][1])
        bad["mappings"] = mappings
        with self.assertRaises(runner.SafetyError): runner.require_fixture(bad)

    def test_tier_configs_and_whole_run_deadlines_exact(self):
        expected = {1: (120, 240, 2, 1, 180, 240),
                    2: (120, 720, 6, 2, 240, 300),
                    3: (90, 1080, 10, 3, 240, 300)}
        for tier, values in expected.items():
            c = runner.tier_config(tier)
            self.assertEqual((c.workload_duration_s, c.requests, c.concurrency,
                              c.scanner_workers, c.internal_deadline_s,
                              c.shell_timeout_s), values)
        with self.assertRaises(runner.SafetyError): runner.tier_config(0)

    def test_tier3_timing_controls_are_documented_exactly(self):
        import ast
        runner_source = Path(runner.__file__).read_text()
        worker_source = (Path(__file__).parent / "task976_zb5_worker.py").read_text()
        probe_source = (Path(__file__).parent / "task976_zb5_node_probe.mjs").read_text()

        self.assertEqual(runner.tier_config(3).scanner_workers, 3)
        self.assertEqual(worker.worker_plan(3)[0], 504)
        self.assertEqual(worker.worker_plan(3)[1], 75)

        worker_plan_nodes = [node for node in ast.parse(worker_source).body
                             if isinstance(node, ast.FunctionDef) and node.name == "worker_plan"]
        self.assertEqual(len(worker_plan_nodes), 1)
        worker_plan = worker_plan_nodes[0]
        worker_plan_dict_nodes = [node for node in ast.walk(worker_plan)
                                  if isinstance(node, ast.Dict)]
        self.assertEqual(len(worker_plan_dict_nodes), 1)
        worker_plan_dict = worker_plan_dict_nodes[0]
        self.assertEqual([key.value for key in worker_plan_dict.keys], [1, 2, 3])

        tier3_tuple = worker_plan_dict.values[2]
        self.assertTrue(isinstance(tier3_tuple, ast.Tuple) and len(tier3_tuple.elts) == 2)
        self.assertEqual(tier3_tuple.elts[0].value, 504)
        self.assertEqual(tier3_tuple.elts[1].value, 75)

        self.assertEqual(runner.tier_config(1).shell_timeout_s, 240)
        self.assertEqual(runner.tier_config(2).shell_timeout_s, 300)
        self.assertEqual(runner.tier_config(3).shell_timeout_s, 300)

        self.assertEqual(runner.tier_config(1).internal_deadline_s, 180)
        self.assertEqual(runner.tier_config(2).internal_deadline_s, 240)
        self.assertEqual(runner.tier_config(3).internal_deadline_s, 240)

        self.assertIn("19776", probe_source)
        self.assertTrue(isinstance(probe_source, str))

        self.assertNotIn("timeout --signal=TERM --kill-after=10s 600s", runner_source)

    def test_no_blanket_600_second_deadline(self):
        self.assertNotIn("600", Path(runner.__file__).read_text())

    def test_deadline_arms_before_preflight_and_disarms_after_postflight(self):
        events = []
        class Timer:
            def __init__(self, seconds): self.seconds = seconds
            def __enter__(self): events.append(("arm", self.seconds))
            def __exit__(self, *_): events.append(("disarm", self.seconds))
        def lifecycle():
            events.extend(["preflight", "workload", "drain", "postflight"])
            return "PASS"
        self.assertEqual(runner.execute_with_deadline(2, lifecycle, timer_factory=Timer), "PASS")
        self.assertEqual(events, [("arm", 240), "preflight", "workload", "drain",
                                  "postflight", ("disarm", 240)])

    def test_deadline_expiry_still_begins_cleanup(self):
        events = []
        def lifecycle():
            try: raise runner.DeadlineExceeded("expired")
            finally: events.append("cleanup")
        with self.assertRaises(runner.DeadlineExceeded):
            runner.execute_with_deadline(1, lifecycle, timer_factory=contextlib.nullcontext)
        self.assertEqual(events, ["cleanup"])

    def test_cleanup_deadline_cannot_be_swallowed(self):
        source = Path(runner.__file__).read_text()
        self.assertIn("if cleanup_deadline is not None: raise cleanup_deadline", source)
        self.assertNotIn("except DeadlineExceeded: pass", source)

    def test_shell_commands_are_exact(self):
        self.assertIn("--kill-after=10s 240s", runner.future_shell_command(1))
        self.assertIn("--kill-after=10s 300s", runner.future_shell_command(2))
        self.assertIn("--kill-after=10s 300s", runner.future_shell_command(3))

    def test_cli_has_no_database_or_password_argument(self):
        parser = runner.build_parser()
        destinations = {action.dest for action in parser._actions}
        self.assertNotIn("database_url", destinations)
        self.assertNotIn("password", destinations)

    def test_child_environments_strip_broker_credentials(self):
        env = self.safe_env(); env.update({"KITE_API_KEY": "x", "KITE_ACCESS_TOKEN": "y",
                                           "EXPO_ACCESS_TOKEN": "z", "PATH": "/bin"})
        node, worker = runner.safe_child_environments(env, Path("/tmp/shadow"))
        self.assertIn("DATABASE_URL", node)
        self.assertNotIn("DATABASE_URL", worker)
        for child in (node, worker):
            self.assertFalse(any("KITE" in key or "EXPO" in key for key in child))

    def test_database_policy_is_read_only(self):
        policy = runner.DB_SESSION_OPTIONS.lower()
        self.assertIn("default_transaction_read_only=on", policy)
        self.assertIn("statement_timeout=5000", policy)
        for token in ("insert ", "update ", "delete ", "truncate ", "create ", "alter ", "drop "):
            self.assertNotIn(token, runner.READ_ONLY_SQL.lower())

    def test_mutation_detection_catches_count_and_content_changes(self):
        before = {"pipeline_events": (10, "aaa")}
        with self.assertRaises(runner.SafetyError):
            runner.require_fingerprints_preserved(before, {"pipeline_events": (11, "bbb")})
        with self.assertRaises(runner.SafetyError):
            runner.require_fingerprints_preserved(before, {"pipeline_events": (10, "bbb")})

    def test_credentials_are_redacted(self):
        rendered = runner.redact(RuntimeError(GOOD_URL + " very-secret"), GOOD_URL)
        self.assertNotIn(GOOD_URL, rendered); self.assertNotIn("very-secret", rendered)

    def test_process_drain_failure(self):
        with self.assertRaises(runner.SafetyError): runner.require_process_drain(False, 0)
        with self.assertRaises(runner.SafetyError): runner.require_process_drain(True, 1)
        runner.require_process_drain(True, 0)

    def test_event_loop_thresholds(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics()).level, "PASS")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(event_loop_p99_ms=300)).level, "WARN")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(event_loop_p99_ms=501)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(event_loop_unresponsive_s=5)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(sustained_lag_s=10)).level, "FAIL")

    def test_memory_thresholds(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(memory_over_85_s=5)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(memory_fraction=0.80)).level, "WARN")

    def test_unbounded_memory_max_is_valid_without_fabricated_fraction(self):
        ok, fraction = runner.resolve_memory_resource_evidence(
            True,
            356601856,
            "max",
        )
        self.assertTrue(ok)
        self.assertEqual(fraction, 0)

    def test_finite_memory_max_preserves_normal_fraction(self):
        ok, fraction = runner.resolve_memory_resource_evidence(
            True,
            2147483648,
            "4294967296",
        )
        self.assertTrue(ok)
        self.assertEqual(fraction, 0.5)

    def test_missing_or_malformed_memory_capacity_fails_closed(self):
        self.assertEqual(
            runner.resolve_memory_resource_evidence(True, 100, None),
            (False, 0),
        )
        self.assertEqual(
            runner.resolve_memory_resource_evidence(True, 100, "invalid"),
            (False, 0),
        )
        self.assertEqual(
            runner.resolve_memory_resource_evidence(True, 100, "0"),
            (False, 0),
        )
        self.assertEqual(
            runner.resolve_memory_resource_evidence(False, 100, "max"),
            (False, 0),
        )

    def test_resource_sampler_accepts_unbounded_memory_max_and_keeps_peak(self):
        sampler = runner.ResourceSampler()

        values = {
            "memory.current": "183508992",
            "memory.max": "max",
            "cpu.stat": "usage_usec 1000\n",
        }

        def fake_cgroup_value(name):
            return values[name]

        with patch.object(runner, "_cgroup_value", side_effect=fake_cgroup_value), \
             patch.object(sampler.stop_event, "wait", side_effect=[False, True]), \
             patch.object(runner.time, "monotonic", side_effect=[1.0, 1.1]):
            sampler._run()

        self.assertTrue(sampler.ok)
        self.assertEqual(sampler.peak_memory, 183508992)
        self.assertEqual(sampler.memory_over_85_s, 0)

    def test_cpu_backlog_threshold(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(
            cpu_over_180_s=31, latency_increasing=True, backlog_increasing=True)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(
            cpu_over_180_s=31, latency_increasing=False, backlog_increasing=True)).level, "WARN")

    def test_http_error_thresholds_by_tier(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(tier=1, request_error_rate=.011)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(tier=2, request_error_rate=.011)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(tier=3, request_error_rate=.021)).level, "FAIL")

    def test_worker_duration_and_resource_evidence(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(max_worker_duration_s=75.1)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(resource_metrics_ok=False)).level, "FAIL")

    def test_worker_evidence_is_exact_and_required(self):
        config = runner.tier_config(2)
        good = {"tier": 2, "symbols_processed": 23, "bars_per_symbol": 252,
                "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
                "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
                "duration_seconds": 10, "lab_walk_calls": 69}
        runner.require_worker_evidence([good, dict(good)], config)
        for bad in ([], [good], [{**good, "orders_submitted": 1}, good],
                    [{**good, "lab_walk_calls": 0}, good]):
            with self.subTest(bad=bad), self.assertRaises(runner.SafetyError):
                runner.require_worker_evidence(bad, config)

    def test_db_capacity_and_lock_thresholds(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(db_connection_fraction=.71)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(db_lock_wait_s=2.1)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(db_errors=1)).level, "FAIL")

    def test_database_observation_parses_capacity_and_lock_age(self):
        class Conn:
            pass
        with patch.object(runner.fixture, "_fetchall", side_effect=[[(7, 100)], [(2.5,)]]):
            result = runner.read_db_observation(Conn())
        self.assertEqual(result, {"connections": 7, "max_connections": 100,
                                  "connection_fraction": .07, "max_lock_wait_s": 2.5})

    def test_database_observation_missing_evidence_fails(self):
        with patch.object(runner.fixture, "_fetchall", return_value=[]):
            with self.assertRaises(runner.SafetyError): runner.read_db_observation(object())

    def test_latency_trend_is_deterministic(self):
        self.assertTrue(runner.latency_increasing([1, 1, 1, 1, 4, 4, 4, 4]))
        self.assertFalse(runner.latency_increasing([4, 4, 4, 4, 1, 1, 1, 1]))

    def test_pressure_duration_must_be_continuous(self):
        self.assertAlmostEqual(runner.next_pressure_streak(4.9, True, .2), 5.1)
        self.assertEqual(runner.next_pressure_streak(4.9, False, .2), 0)

    def test_memory_event_delta_detects_oom(self):
        before = {"oom": 1, "oom_kill": 0}
        self.assertEqual(runner.memory_failure_delta(before, {"oom": 2, "oom_kill": 1}), 2)
        self.assertEqual(runner.memory_failure_delta(before, before), 0)
        self.assertFalse(runner.memory_events_valid({}))
        self.assertTrue(runner.memory_events_valid(before))

    def test_db_peak_sampler_evidence_is_required(self):
        sampler = runner.DatabasePeakEvidence()
        with self.assertRaises(runner.SafetyError): sampler.require_complete()
        sampler.observe({"connection_fraction": .72, "max_lock_wait_s": 2.1})
        result = sampler.require_complete()
        self.assertEqual(result, (.72, 2.1))

    def test_safety_violations_always_fail(self):
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(safety_violations=1)).level, "FAIL")
        self.assertEqual(runner.evaluate(runner.synthetic_metrics(unexpected_mutations=1)).level, "FAIL")

    def test_local_shadow_url_only(self):
        runner.require_local_url("http://127.0.0.1:19776/api/healthz")
        with self.assertRaises(runner.SafetyError): runner.require_local_url("https://api.kite.trade")

    def test_node_shadow_source_is_get_only_and_isolated(self):
        source = (Path(__file__).parent / "task976_zb5_node_probe.mjs").read_text().lower()
        self.assertNotIn("production router", source)
        for forbidden in ("kite", "zerodha", "yfinance", "expo", "webhook", "scheduler"):
            self.assertNotIn(forbidden, source)
        self.assertIn('request.method !== "get"', source)
        self.assertIn("route blocked", source)
        self.assertIn("sustained_lag_ms", source)
        self.assertIn("max_active_children", source)

    def test_event_loop_lag_uses_elapsed_wall_clock_and_resets(self):
        script = Path(__file__).with_name("task976_zb5_node_probe.mjs")
        def calculate(sequence):
            completed = subprocess.run(
                ["node", str(script), "--lag-sequence", json.dumps(sequence)],
                check=True, capture_output=True, text=True, timeout=3)
            return json.loads(completed.stdout)
        spike = calculate([[350, 300], [50, 0]])
        self.assertEqual(spike, {"current_ms": 0, "longest_ms": 350})
        contiguous = calculate([[400, 350]] * 25)
        self.assertEqual(contiguous, {"current_ms": 10000, "longest_ms": 10000})
        reset = calculate([[400, 350]] * 10 + [[50, 0], [400, 350]])
        self.assertEqual(reset, {"current_ms": 400, "longest_ms": 4000})

    def test_worker_diagnostics_archive_each_outcome_deterministically(self):
        from task976_zb5_runner import (
            _bounded_worker_stderr,
            _bounded_worker_stdout_diagnostics,
            WorkerOutcome,
            classify_worker_outcome,
            collect_worker_with_diagnostic,
            worker_outcome_to_dict,
        )
        pending = WorkerOutcome(
            worker_index=2,
            started_microseconds=1_000_000,
            duration_monotonic_ms=14.0,
            communicate_timeout=False,
            returncode=None,
            stderr_present=False,
            stdout_present=True,
            json_parse_ok=True,
            parsed={"tier": 3, "duration_seconds": 42.0, "symbols_processed": 23,
                   "bars_per_symbol": 504, "lab_walk_calls": 7},
            stderr_bounded="",
            pid=99,
            cleanup_ok=True,
            classification="",
            error_reason_if_any="",
        )
        record = worker_outcome_to_dict(pending)
        self.assertEqual(record["worker_index"], 2)
        self.assertEqual(record["pid"], 99)
        self.assertEqual(record["started_monotonic_ms"], 1000.0)
        self.assertAlmostEqual(record["duration_monotonic_ms"], 14.0)
        self.assertFalse(record["communicate_timeout"])
        self.assertIsNone(record["returncode"])
        self.assertFalse(record["stderr_present"])
        self.assertTrue(record["stdout_present"])
        self.assertTrue(record["json_parse_ok"])
        self.assertEqual(record["classification"], "OTHER")
        self.assertEqual(record["error_reason_if_any"], "")
        parsed = record["parsed"]
        self.assertEqual(parsed["parsed_tier"], 3)
        self.assertEqual(parsed["parsed_duration_seconds"], 42.0)
        self.assertEqual(parsed["parsed_symbols_processed"], 23)
        self.assertEqual(parsed["parsed_bars_per_symbol"], 504)
        self.assertEqual(parsed["parsed_lab_walk_calls"], 7)

    def test_worker_diagnostics_classify_each_failure_mode(self):
        from task976_zb5_runner import (
            WorkerOutcome,
            classify_worker_outcome,
            worker_outcome_to_dict,
        )
        def make_outcome(**overrides: Any) -> WorkerOutcome:
            defaults: dict[str, Any] = {
                "worker_index": 0,
                "started_microseconds": 0,
                "duration_monotonic_ms": 0.0,
                "communicate_timeout": False,
                "returncode": 0,
                "stderr_present": False,
                "stdout_present": True,
                "json_parse_ok": True,
                "parsed": good_row(),
                "stderr_bounded": "",
                "pid": None,
                "cleanup_ok": True,
                "classification": "",
                "error_reason_if_any": "",
            }
            defaults.update(overrides)
            return WorkerOutcome(**defaults)

        cases = [
            ({"communicate_timeout": True}, "COMMUNICATE_TIMEOUT"),
            ({"communicate_timeout": False, "returncode": 1}, "NONZERO_EXIT"),
            ({"communicate_timeout": False, "returncode": 0, "stderr_present": True}, "STDERR_OUTPUT"),
            ({"communicate_timeout": False, "returncode": 0, "stderr_present": False, "stdout_present": False}, "EMPTY_STDOUT"),
            ({"communicate_timeout": False, "returncode": 0, "stderr_present": False, "stdout_present": True, "json_parse_ok": False}, "INVALID_JSON"),
            ({"communicate_timeout": False, "returncode": 0, "stderr_present": False, "stdout_present": True,
              "json_parse_ok": True, "parsed": {"status": "FAIL", "error": "worker deadline exceeded"}}, "WORKER_REPORTED_FAILURE"),
            ({"communicate_timeout": False, "returncode": 0, "stderr_present": False, "stdout_present": True,
              "json_parse_ok": True, "parsed": good_row()}, "PASS_EVIDENCE"),
            ({"communicate_timeout": False, "returncode": 0, "stderr_present": False, "stdout_present": False,
              "json_parse_ok": False, "parsed": None}, "EMPTY_STDOUT"),
        ]
        for override, expected in cases:
            with self.subTest(override=override):
                outcome = make_outcome(**override)
                self.assertEqual(classify_worker_outcome(outcome), expected)
                self.assertEqual(worker_outcome_to_dict(outcome)["classification"], expected)

    def test_worker_diagnostics_preserve_worker_reported_reason(self):
        from task976_zb5_runner import (
            WorkerOutcome,
            collect_worker_with_diagnostic,
            worker_outcome_to_dict,
        )

        command_status_obj = object()
        import json as _json
        captured_stdout = _json.dumps({"status": "FAIL", "error": "worker deadline exceeded"})

        class FakeWorkerProc:
            def __init__(self, stdout: str | None, stderr: str | None, returncode: int):
                self._stdout = stdout
                self._stderr = stderr
                self._returncode = returncode
                self._called_communicate = False
                self._pid = 77
            @property
            def pid(self) -> int:
                return self._pid
            @property
            def returncode(self) -> int:
                return self._returncode
            def poll(self) -> int | None:
                return self._returncode
            def communicate(self, timeout: float = 75):
                self._called_communicate = True
                return (self._stdout, self._stderr)

        proc = FakeWorkerProc(captured_stdout, "worker deadline exceeded\n", 1)
        outcome = collect_worker_with_diagnostic(proc, worker_index=1, started_monotonic_us=0)
        self.assertTrue(proc._called_communicate)
        self.assertEqual(outcome.classification, "WORKER_REPORTED_FAILURE")
        self.assertEqual(outcome.returncode, 1)
        self.assertTrue(outcome.stderr_present)
        self.assertTrue(outcome.json_parse_ok)
        self.assertIsNotNone(outcome.parsed)
        self.assertEqual(outcome.parsed.get("status"), "FAIL")
        self.assertEqual(outcome.error_reason_if_any, "worker deadline exceeded")
        record = worker_outcome_to_dict(outcome)
        self.assertEqual(record["classification"], "WORKER_REPORTED_FAILURE")
        self.assertEqual(record["error_reason_if_any"], "worker deadline exceeded")
        self.assertIn("worker deadline exceeded", record["stderr_bounded"])
        parsed = record["parsed"]
        self.assertEqual(parsed["parsed_tier"], -1)
        self.assertEqual(parsed["parsed_duration_seconds"], -1.0)
        self.assertEqual(parsed["parsed_symbols_processed"], -1)
        self.assertEqual(parsed["parsed_bars_per_symbol"], -1)
        self.assertEqual(parsed["parsed_lab_walk_calls"], 0)

    def test_worker_diagnostics_communicate_timeout_records_exact_reason(self):
        from task976_zb5_runner import (
            WorkerOutcome,
            collect_worker_with_diagnostic,
            worker_outcome_to_dict,
        )

        class TimeoutWorkerProc:
            def __init__(self):
                self._pid = 88
                self._polled = False
            @property
            def pid(self) -> int:
                return self._pid
            def poll(self) -> int | None:
                return 99 if self._polled else None
            def terminate(self):
                self._polled = True
            def kill(self):
                self._polled = True
            def wait(self, timeout: float = 2):
                self._polled = True
                return 99
            def communicate(self, timeout: float = 75):
                raise subprocess.TimeoutExpired("worker", timeout)

        proc = TimeoutWorkerProc()
        outcome = collect_worker_with_diagnostic(proc, worker_index=0, started_monotonic_us=1234)
        self.assertEqual(outcome.classification, "COMMUNICATE_TIMEOUT")
        self.assertTrue(outcome.communicate_timeout)
        self.assertEqual(outcome.returncode, 99)
        self.assertEqual(outcome.pid, 88)
        record = worker_outcome_to_dict(outcome)
        self.assertEqual(record["classification"], "COMMUNICATE_TIMEOUT")
        self.assertEqual(record["error_reason_if_any"], "worker communicate(timeout=75) expired")
        self.assertIn("timeout=75", record["error_reason_if_any"])

    def test_worker_diagnostics_empty_stdout_and_invalid_json_oneshot(self):
        from task976_zb5_runner import (
            WorkerOutcome,
            collect_worker_with_diagnostic,
            worker_outcome_to_dict,
        )

        class QuietWorkerProc:
            def __init__(self, stdout, stderr, returncode):
                self._stdout = stdout
                self._stderr = stderr
                self._returncode = returncode
                self._pid = 90
            @property
            def pid(self) -> int:
                return self._pid
            @property
            def returncode(self) -> int:
                return self._returncode
            def poll(self) -> int | None:
                return self._returncode
            def communicate(self, timeout: float = 75):
                return (self._stdout, self._stderr)

        empty = collect_worker_with_diagnostic(QuietWorkerProc(None, "some stderr\n", 0),
                                              worker_index=2, started_monotonic_us=0)
        self.assertEqual(empty.classification, "STDERR_OUTPUT")
        self.assertTrue(empty.stderr_present)
        self.assertFalse(empty.stdout_present)

        bad_json = collect_worker_with_diagnostic(QuietWorkerProc("not-json", None, 0),
                                                  worker_index=0, started_monotonic_us=0)
        self.assertEqual(bad_json.classification, "INVALID_JSON")
        self.assertTrue(bad_json.stdout_present)
        self.assertFalse(bad_json.json_parse_ok)
        record = worker_outcome_to_dict(bad_json)
        self.assertEqual(record["classification"], "INVALID_JSON")
        parsed = record["parsed"]
        self.assertIsNone(parsed["parsed_tier"])
        self.assertIsNone(parsed["parsed_duration_seconds"])

    def test_worker_diagnostics_bound_and_redact_stderr(self):
        from task976_zb5_runner import _bounded_worker_stderr
        raw = (
            "worker diagnostic log\n"
            "DATABASE_URL=postgresql://u:p@host/db\n"
            "KITE_API_KEY=secret-key\n"
            + "x" * 5000
        )
        bounded = _bounded_worker_stderr(raw)
        self.assertNotIn("DATABASE_URL=postgresql://u:p@host/db", bounded)
        self.assertNotIn("KITE_API_KEY=secret-key", bounded)
        self.assertIn("<REDACTED>", bounded)
        self.assertIn("<...truncated mid-stream...>", bounded)

    def test_worker_diagnostics_reject_extra_or_missing_evidence(self):
        config = runner.tier_config(3)
        good = {
            "tier": 3, "symbols_processed": 23, "bars_per_symbol": 504,
            "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 10.0, "lab_walk_calls": 7,
        }
        runner.require_worker_evidence([good, good, good], config)
        for bad in ([], [good, good], [good, good, good, good],
                    [{**good, "bars_per_symbol": 252}, good, good]):
            with self.subTest(bad=bad), self.assertRaises(runner.SafetyError):
                runner.require_worker_evidence(bad, config)

    def test_tier3_worker_deadline_is_exactly_75_in_worker_side(self):
        self.assertEqual(worker.worker_plan(3)[1], 75)
        self.assertEqual(worker.worker_plan(2)[1], 75)
        self.assertEqual(worker.worker_plan(1)[1], 75)
        self.assertEqual(worker.worker_plan(3)[0], 504)
        self.assertEqual(worker.worker_plan(2)[0], 252)
        self.assertEqual(worker.worker_plan(1)[0], 252)

    def test_tier3_worker_duration_validation_uses_worker_bound(self):
        with self.assertRaises(worker.WorkerSafetyError):
            worker.require_worker_duration(75.0000001)
        worker.require_worker_duration(75.0)

    def test_tier3_worker_bound_remains_identical_across_worker_plan_and_duration_check(self):
        bound = worker.worker_plan(3)[1]
        self.assertEqual(bound, 75)
        with self.assertRaises(worker.WorkerSafetyError):
            worker.require_worker_duration(float(bound) + 1e-9)
        worker.require_worker_duration(float(bound))

    def test_runner_uses_single_hardcoded_75_second_worker_collection_timeout(self):
        source = Path(runner.__file__).read_text()
        self.assertIn("communicate(timeout=75)", source)
        import re
        timeouts = re.findall(r"\.communicate\s*\(\s*timeout\s*=\s*([0-9]+)\s*\)", source)
        self.assertEqual(timeouts, ["75"])

    def test_tier3_requires_exactly_three_worker_evidence_rows(self):
        config = runner.tier_config(3)
        self.assertEqual(config.scanner_workers, 3)
        good = {
            "tier": 3, "symbols_processed": 23, "bars_per_symbol": 504,
            "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 5.0, "lab_walk_calls": 1,
        }
        runner.require_worker_evidence([good, good, good], config)
        with self.assertRaises(runner.SafetyError):
            runner.require_worker_evidence([dict(good), dict(good)], config)

    def test_provider_broker_and_orders_still_fail_closed_in_worker_evidence(self):
        config = runner.tier_config(3)
        good = {
            "tier": 3, "symbols_processed": 23, "bars_per_symbol": 504,
            "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 5.0, "lab_walk_calls": 1,
        }
        for field in ("provider_calls", "broker_calls", "orders_submitted"):
            bad = dict(good)
            bad[field] = 1
            with self.subTest(field=field), self.assertRaises(runner.SafetyError):
                runner.require_worker_evidence([bad, good, good], config)

    def test_wrong_symbol_hash_fails_closed(self):
        config = runner.tier_config(3)
        good = {
            "tier": 3, "symbols_processed": 23, "bars_per_symbol": 504,
            "symbol_hash": "0" * 64,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 5.0, "lab_walk_calls": 1,
        }
        with self.assertRaises(runner.SafetyError):
            runner.require_worker_evidence([good, good, good], config)

    def test_wrong_bars_per_symbol_fails_closed(self):
        config = runner.tier_config(3)
        good = {
            "tier": 3, "symbols_processed": 23, "bars_per_symbol": 252,
            "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 5.0, "lab_walk_calls": 1,
        }
        with self.assertRaises(runner.SafetyError):
            runner.require_worker_evidence([good, good, good], config)

    def test_worker_duration_over_reviewed_bound_fails_closed(self):
        config = runner.tier_config(3)
        good = {
            "tier": 3, "symbols_processed": 23, "bars_per_symbol": 504,
            "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
            "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
            "duration_seconds": 75.000001, "lab_walk_calls": 1,
        }
        with self.assertRaises(runner.SafetyError):
            runner.require_worker_evidence([good, good, good], config)

    def test_tier1_and_tier2_behavior_unchanged(self):
        for tier in (1, 2):
            config = runner.tier_config(tier)
            self.assertEqual(config.scanner_workers, 1 if tier == 1 else 2)
            self.assertEqual(config.workload_duration_s, 120)
            self.assertEqual(config.requests, 240 if tier == 1 else 720)
            self.assertEqual(config.concurrency, 2 if tier == 1 else 6)
            self.assertEqual(config.internal_deadline_s, 180 if tier == 1 else 240)
            self.assertEqual(config.shell_timeout_s, 240 if tier == 1 else 300)
            good = {
                "tier": tier, "symbols_processed": 23, "bars_per_symbol": 252,
                "symbol_hash": runner.fixture.task969.APPROVED_SET_HASH,
                "provider_calls": 0, "broker_calls": 0, "orders_submitted": 0,
                "duration_seconds": 10.0, "lab_walk_calls": 1,
            }
            expected_count = 1 if tier == 1 else 2
            runner.require_worker_evidence([good] * expected_count, config)
            with self.assertRaises(runner.SafetyError):
                runner.require_worker_evidence([dict(good)] * (expected_count + 1), config)

    def test_no_blanket_600_second_deadline_elsewhere(self):
        runner_source = Path(runner.__file__).read_text()
        self.assertNotIn("timeout --signal=TERM --kill-after=10s 600s", runner_source)
        self.assertNotIn("communicate(timeout=600)", runner_source)
        self.assertNotIn("alarm(600)", runner_source)
        self.assertNotIn("worker_plan(3)[1] + 525", runner_source)

    def test_worker_outcome_and_classification_helpers_mirror_runner(self):
        from task976_zb5_runner import WorkerOutcome, classify_worker_outcome, worker_outcome_to_dict
        outcome = WorkerOutcome(
            worker_index=0,
            started_microseconds=0,
            duration_monotonic_ms=0.0,
            communicate_timeout=False,
            returncode=1,
            stderr_present=True,
            stdout_present=False,
            json_parse_ok=False,
            parsed=None,
            stderr_bounded="",
            pid=None,
            cleanup_ok=True,
            classification="",
            error_reason_if_any="",
        )
        record = worker_outcome_to_dict(outcome)
        self.assertEqual(record["classification"], classify_worker_outcome(outcome))

    def test_node_shadow_rejects_non_get_and_unknown_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); py_dir = root / "python"; py_dir.mkdir()
            (py_dir / "main.py").write_text("import json; print(json.dumps({'ok':True}))\n")
            evidence = root / "node.json"
            env = {"PATH": os.environ["PATH"], "PORT": "19776",
                   "TASK976_ZB5_NODE_EVIDENCE": str(evidence),
                   "TASK976_ZB5_PYTHON_DIR": str(py_dir),
                   "TASK976_ZB5_PYTHON_BIN": sys.executable}
            proc = subprocess.Popen(["node", str(Path(__file__).with_name(
                "task976_zb5_node_probe.mjs"))], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:19776/api/healthz",
                                                    timeout=.2) as response:
                            if response.status == 200: break
                    except Exception: time.sleep(.02)
                else: self.fail("shadow did not become ready")
                request = urllib.request.Request("http://127.0.0.1:19776/api/healthz",
                                                 method="POST")
                with self.assertRaises(urllib.error.HTTPError) as method_error:
                    urllib.request.urlopen(request, timeout=1)
                self.assertEqual(method_error.exception.code, 405)
                with self.assertRaises(urllib.error.HTTPError) as route_error:
                    urllib.request.urlopen("http://127.0.0.1:19776/not-allowed", timeout=1)
                self.assertEqual(route_error.exception.code, 404)
            finally:
                proc.terminate(); proc.communicate(timeout=3)

    def test_main_failure_redacts_credentials(self):
        output = io.StringIO()
        with patch.object(runner, "execute_with_deadline", side_effect=RuntimeError(GOOD_URL)), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(runner.main(["--tier", "1"], self.safe_env()), 1)
        self.assertNotIn("very-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
