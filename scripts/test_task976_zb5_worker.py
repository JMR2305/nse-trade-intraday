#!/usr/bin/env python3
"""Offline tests for the deterministic, isolated ZB5 compute worker."""
from __future__ import annotations

import ast
import os
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zb5_worker as worker


class ZB5WorkerTests(unittest.TestCase):
    def test_resource_snapshot_missing_and_malformed(self):
        from types import SimpleNamespace
        with patch.object(worker.resource, "getrusage", return_value=SimpleNamespace(ru_utime=1.5, ru_stime=float("nan"), ru_maxrss=-1)):
            result = worker.worker_resources("workload", 2.0, 1.0)
        self.assertEqual(result["cpu_user_seconds"], 1.5)
        self.assertIsNone(result["cpu_system_seconds"])
        self.assertIsNone(result["max_rss"])
        self.assertIsNone(result["voluntary_ctx_switches"])

    def test_success_and_deadline_emit_resources_without_alarm_reset(self):
        import contextlib, io, json
        for fail in (False, True):
            with self.subTest(fail=fail):
                out, err = io.StringIO(), io.StringIO()
                def workload(tier):
                    if fail: raise worker.WorkerSafetyError("worker deadline exceeded")
                    return {"tier": tier}
                with patch.object(worker, "run_deterministic_workload", side_effect=workload), patch.object(worker.signal, "signal"), patch.object(worker.signal, "alarm") as alarm, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(worker.main(["--tier", "3"]), int(fail))
                payload = json.loads(err.getvalue() if fail else out.getvalue())
                self.assertGreaterEqual(payload["resources"]["cpu_user_seconds"], 0)
                self.assertEqual(payload["resources"]["stage"], "workload" if fail else "finalization")
                self.assertEqual([call.args[0] for call in alarm.call_args_list], [75, 0])

    def test_exact_universe_and_hash(self):
        worker.require_exact_symbols(worker.CANONICAL_SYMBOLS)
        self.assertEqual(len(worker.CANONICAL_SYMBOLS), 23)
        self.assertEqual(worker.CANONICAL_HASH,
                         "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016")

    def test_wrong_symbol_set_fails(self):
        with self.assertRaises(worker.WorkerSafetyError):
            worker.require_exact_symbols(worker.CANONICAL_SYMBOLS[:-1])

    def test_deterministic_ohlcv_for_all_symbols(self):
        first = {s: worker.deterministic_ohlcv(s, 252) for s in worker.CANONICAL_SYMBOLS}
        second = {s: worker.deterministic_ohlcv(s, 252) for s in worker.CANONICAL_SYMBOLS}
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(worker.CANONICAL_SYMBOLS))
        self.assertTrue(all(len(rows) == 252 for rows in first.values()))

    def test_invalid_bar_bounds_fail(self):
        for bars in (0, 59, 2001):
            with self.subTest(bars=bars), self.assertRaises(worker.WorkerSafetyError):
                worker.deterministic_ohlcv("WIPRO", bars)

    def test_provider_is_blocking_stub(self):
        worker.install_provider_stubs()
        module = sys.modules["yfinance"]
        self.assertTrue(module.__task976_stub__)
        with self.assertRaises(worker.ExternalAccessBlocked):
            module.download("WIPRO.NS")

    def test_network_allowlist(self):
        worker.require_allowed_destination(("127.0.0.1", 19776))
        worker.require_allowed_destination((worker.AUTHORIZED_DB_HOST, 5432))
        for address in (("api.kite.trade", 443), ("query1.finance.yahoo.com", 443),
                        ("nseindia.com", 443), (worker.AUTHORIZED_DB_HOST, 5433)):
            with self.subTest(address=address), self.assertRaises(worker.ExternalAccessBlocked):
                worker.require_allowed_destination(address)

    def test_arbitrary_unix_domain_sockets_are_blocked(self):
        for address in ("/var/run/docker.sock", "/tmp/provider.sock"):
            with self.subTest(address=address), self.assertRaises(worker.ExternalAccessBlocked):
                worker.require_allowed_destination(address)

    def test_network_guard_blocks_real_socket_attempt_before_connect(self):
        with worker.network_guard(), self.assertRaises(worker.ExternalAccessBlocked):
            socket.create_connection(("example.com", 443), timeout=0.01)

    def test_network_guard_blocks_connect_ex_and_datagrams(self):
        sock = socket.socket()
        try:
            with worker.network_guard():
                with self.assertRaises(worker.ExternalAccessBlocked):
                    sock.connect_ex(("example.com", 443))
                with self.assertRaises(worker.ExternalAccessBlocked):
                    sock.sendto(b"x", ("example.com", 443))
        finally: sock.close()

    def test_broker_modules_fail_closed(self):
        with patch.dict(sys.modules, {"kiteconnect": object()}):
            with self.assertRaises(worker.WorkerSafetyError):
                worker.require_no_forbidden_modules()

    def test_order_and_lifecycle_callables_are_forbidden(self):
        for name in ("execute_buy", "execute_sell", "place_order", "run_backtest",
                     "run_strategy_lab", "scheduled_scan_tick"):
            with self.subTest(name=name), self.assertRaises(worker.WorkerSafetyError):
                worker.require_safe_callable(name)

    def test_actual_worker_boundary_blocks_forbidden_callable_before_side_effect(self):
        effects = []
        def place_order(): effects.append("ORDER")
        def attempted_scan(_symbol, _bars):
            place_order()
            return {"stock": "unreachable", "_task976_lab_walk_calls": 1}
        with self.assertRaises(worker.WorkerSafetyError):
            worker.run_deterministic_workload(1, scan_one=attempted_scan)
        self.assertEqual(effects, [])

    def test_worker_never_requires_database_url(self):
        env = {"DATABASE_URL": "secret", "KITE_API_SECRET": "secret", "PATH": "/bin"}
        safe = worker.safe_worker_environment(env)
        self.assertNotIn("DATABASE_URL", safe)
        self.assertNotIn("KITE_API_SECRET", safe)

    def test_worker_plans_are_exact(self):
        self.assertEqual(worker.worker_plan(1), (252, 75))
        self.assertEqual(worker.worker_plan(2), (252, 75))
        self.assertEqual(worker.worker_plan(3), (504, 75))
        with self.assertRaises(worker.WorkerSafetyError):
            worker.worker_plan(4)

    def test_deterministic_scanner_aggregation(self):
        fake = lambda symbol, bars: {"stock": symbol, "score": bars + len(symbol),
                                     "_task976_lab_walk_calls": 3}
        a = worker.run_deterministic_workload(1, scan_one=fake)
        b = worker.run_deterministic_workload(1, scan_one=fake)
        self.assertEqual(a["result_hash"], b["result_hash"])
        self.assertEqual(a["symbols_processed"], 23)
        self.assertEqual(a["provider_calls"], 0)
        self.assertEqual(a["lab_walk_calls"], 69)

    def test_zero_lab_walk_calls_fail(self):
        fake = lambda symbol, bars: {"stock": symbol, "_task976_lab_walk_calls": 0}
        with self.assertRaises(worker.WorkerSafetyError):
            worker.run_deterministic_workload(1, scan_one=fake)

    def test_worker_duration_bound_enforced(self):
        with self.assertRaises(worker.WorkerSafetyError):
            worker.require_worker_duration(75.001)
        worker.require_worker_duration(75.0)

    def test_backtest_path_contract_excludes_lifecycle(self):
        source = worker.inspect_lab_walk_contract()
        calls = {node.func.id for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        for forbidden in ("run_backtest", "run_strategy_lab", "fetch_candles",
                          "connect", "open", "Popen", "spawn"):
            self.assertNotIn(forbidden, calls)


if __name__ == "__main__":
    unittest.main()
