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
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zb5_runner as runner

GOOD_URL = ("postgresql://apexquant_benchmark:very-secret@"
            "postgres16-benchmark.zeabur.internal:5432/apexquant_disposable")


class ZB5RunnerTests(unittest.TestCase):
    def safe_env(self):
        return {"DATABASE_URL": GOOD_URL, "TASK976_DISPOSABLE_ACK": "apexquant_disposable",
                **{name: "false" for name in runner.SAFETY_FLAGS}}

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
