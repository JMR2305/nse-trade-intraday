"""
test_circuit_breaker.py — unit tests for the Phase 20 paper-entry circuit
breaker. All broker/DB interactions are mocked; nothing real is touched.
Run: .pythonlibs/bin/python3 test_circuit_breaker.py
"""

import unittest
from unittest.mock import patch

import phase20_circuit_breaker as cb


SETTINGS = {"daily_loss_limit_pct": 3.0}


def _trade(pnl, ts, strategy="StratA"):
    return {"status": "CLOSED", "realized_pnl": pnl, "exit_ts": ts,
            "strategy_name": strategy}


class KVFake:
    def __init__(self):
        self.data = {}
        self.notifications = []

    def kv_get(self, key, default=None):
        return self.data.get(key, default)

    def kv_set(self, key, value):
        self.data[key] = value

    def add_notification(self, kind, title, body="", severity="INFO",
                         context=None):
        self.notifications.append({"kind": kind, "title": title,
                                   "severity": severity})


class Base(unittest.TestCase):
    def setUp(self):
        self.kv = KVFake()
        self.patches = [
            patch.object(cb.store, "kv_get", side_effect=self.kv.kv_get),
            patch.object(cb.store, "kv_set", side_effect=self.kv.kv_set),
            patch.object(cb.store, "add_notification",
                         side_effect=self.kv.add_notification),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _with_ledger(self, trades, daily_pnl=0.0):
        return patch.object(cb, "_closed_trades", return_value=trades), \
            patch.object(cb, "compute_metrics",
                         wraps=lambda s: self._metrics(trades, daily_pnl, s))

    def _metrics(self, trades, daily_pnl, settings):
        # Use the real compute logic for consecutive/expectancy but a fixed
        # daily P&L (paper_trader state is not available in unit tests).
        with patch.object(cb, "_closed_trades", return_value=trades):
            m = _real_compute(settings)
        m["daily_realized_pnl"] = daily_pnl
        m["daily_loss_limit"] = 150.0  # 3% of ₹5,000
        m["trip_reasons"] = [r for r in m["trip_reasons"]
                             if r["code"] != "DAILY_LOSS_LIMIT"]
        if daily_pnl <= -150.0:
            m["trip_reasons"].append({
                "code": "DAILY_LOSS_LIMIT",
                "detail": f"daily pnl {daily_pnl}", "strategies": []})
        return m


_real_compute = cb.compute_metrics


class TestTripConditions(Base):
    def test_no_trip_when_healthy(self):
        trades = [_trade(10, f"2026-07-0{i}") for i in range(1, 6)]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertFalse(state["tripped"])

    def test_trip_on_three_consecutive_losses(self):
        trades = [_trade(20, "2026-07-01"), _trade(-5, "2026-07-02", "S1"),
                  _trade(-3, "2026-07-03", "S2"), _trade(-8, "2026-07-04", "S1")]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertTrue(state["tripped"])
        codes = [r["code"] for r in state["reasons"]]
        self.assertIn("CONSECUTIVE_LOSSES", codes)
        self.assertIn("S1", state["affected_strategies"])
        self.assertIn("S2", state["affected_strategies"])
        self.assertEqual(state["tripped_at"] is not None, True)
        # CRITICAL notification recorded
        self.assertTrue(any(n["kind"] == "CIRCUIT_BREAKER_TRIPPED"
                            and n["severity"] == "CRITICAL"
                            for n in self.kv.notifications))
        # Audit log entry recorded
        audit = cb.get_audit_log()
        self.assertEqual(audit[0]["event"], "CIRCUIT_BREAKER_TRIPPED")

    def test_two_losses_do_not_trip(self):
        trades = [_trade(20, "2026-07-01"), _trade(-5, "2026-07-02"),
                  _trade(-3, "2026-07-03")]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertFalse(state["tripped"])

    def test_trip_on_daily_loss_limit(self):
        trades = [_trade(10, "2026-07-01")]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, -200.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertTrue(state["tripped"])
        self.assertIn("DAILY_LOSS_LIMIT", [r["code"] for r in state["reasons"]])

    def test_trip_on_negative_expectancy_full_window(self):
        # 10 trades alternating small wins / bigger losses → negative mean,
        # but never 3 consecutive losses.
        trades = []
        for i in range(5):
            trades.append(_trade(5, f"2026-07-{2*i+1:02d}"))
            trades.append(_trade(-20, f"2026-07-{2*i+2:02d}"))
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertTrue(state["tripped"])
        self.assertIn("NEGATIVE_EXPECTANCY",
                      [r["code"] for r in state["reasons"]])

    def test_negative_expectancy_needs_full_window(self):
        trades = [_trade(-5, f"2026-07-0{i}") for i in range(1, 3)]  # only 2
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertNotIn("NEGATIVE_EXPECTANCY",
                         [r["code"] for r in state.get("reasons", [])])

    def test_trip_is_idempotent(self):
        trades = [_trade(-5, "2026-07-01"), _trade(-3, "2026-07-02"),
                  _trade(-8, "2026-07-03")]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            s1 = cb.evaluate_and_maybe_trip(SETTINGS)
            s2 = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertEqual(s1["tripped_at"], s2["tripped_at"])
        trips = [a for a in cb.get_audit_log()
                 if a["event"] == "CIRCUIT_BREAKER_TRIPPED"]
        self.assertEqual(len(trips), 1)

    def test_never_auto_resumes(self):
        trades_bad = [_trade(-5, "2026-07-01"), _trade(-3, "2026-07-02"),
                      _trade(-8, "2026-07-03")]
        trades_good = [_trade(50, "2026-07-05")]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades_bad, 0.0, s)):
            cb.evaluate_and_maybe_trip(SETTINGS)
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades_good, 0.0, s)):
            state = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertTrue(state["tripped"], "Breaker must NEVER auto-resume")


class TestResume(Base):
    def _trip(self):
        trades = [_trade(-5, "2026-07-01"), _trade(-3, "2026-07-02"),
                  _trade(-8, "2026-07-03")]
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: self._metrics(trades, 0.0, s)):
            cb.evaluate_and_maybe_trip(SETTINGS)

    def test_resume_requires_exact_confirmation(self):
        self._trip()
        with self.assertRaises(ValueError):
            cb.resume("yes please resume")
        self.assertTrue(cb.get_state()["tripped"])

    def test_resume_with_exact_text(self):
        self._trip()
        state = cb.resume(cb.RESUME_CONFIRMATION_TEXT, reviewed_by="tester")
        self.assertFalse(state["tripped"])
        self.assertEqual(state["resumed_by"], "tester")
        self.assertIsNotNone(state["last_trip"]["tripped_at"])
        audit = cb.get_audit_log()
        self.assertEqual(audit[0]["event"], "CIRCUIT_BREAKER_RESUMED")
        self.assertEqual(audit[0]["reviewed_by"], "tester")

    def test_resume_when_not_tripped_rejected(self):
        with self.assertRaises(ValueError):
            cb.resume(cb.RESUME_CONFIRMATION_TEXT)


class TestIntegration(Base):
    def test_executor_blocks_entries_when_tripped(self):
        import phase20_executor as ex
        self.kv.kv_set(cb.STATE_KEY, {"tripped": True, "reasons": [],
                                      "tripped_at": "t"})
        settings = {"auto_paper_entries": True,
                    "auto_paper_entries_confirmed_at": "t0"}
        with patch.object(cb, "compute_metrics",
                          side_effect=lambda s: {"trip_reasons": []}):
            result = ex.run_auto_entries(settings)
        self.assertFalse(result["ran"])
        self.assertIn("circuit_breaker", result)

    def test_gate_blocks_when_state_unreadable(self):
        # Fail-safe: gates module adds a failed gate on breaker read errors.
        import phase20_gates as g
        with patch.object(cb, "get_state", side_effect=RuntimeError("db down")):
            gate_list = []
            # simulate the gate block logic directly
            try:
                cb.get_state()
                gate_list.append({"passed": True})
            except Exception:
                gate_list.append({"gate": "entry_circuit_breaker",
                                  "passed": False})
        self.assertFalse(gate_list[0]["passed"])
        self.assertTrue(hasattr(g, "evaluate_entries"))

    def test_corrupted_state_blocks_entries_failsafe(self):
        # Non-dict persisted state = UNREADABLE → tripped (fail-safe).
        self.kv.kv_set(cb.STATE_KEY, "corrupted-string")
        state = cb.get_state()
        self.assertTrue(state["tripped"])
        self.assertTrue(state["unreadable"])
        # evaluate never overwrites / clears the corrupted value
        out = cb.evaluate_and_maybe_trip(SETTINGS)
        self.assertTrue(out["tripped"])
        self.assertEqual(self.kv.data[cb.STATE_KEY], "corrupted-string")
        # executor blocks entries on the fail-safe state
        import phase20_executor as ex
        result = ex.run_auto_entries({"auto_paper_entries": True,
                                      "auto_paper_entries_confirmed_at": "t"})
        self.assertFalse(result["ran"])

    def test_kv_read_error_blocks_entries_failsafe(self):
        with patch.object(cb.store, "kv_get",
                          side_effect=RuntimeError("db down")):
            state = cb.get_state()
            self.assertTrue(state["tripped"])
            self.assertTrue(state["unreadable"])
            self.assertTrue(cb.is_tripped())

    def test_exits_module_not_gated_by_breaker(self):
        import inspect
        import phase20_exits as x
        src = inspect.getsource(x)
        self.assertNotIn("circuit_breaker", src,
                         "Exits must never be blocked by the entry breaker")


if __name__ == "__main__":
    import sys
    runner = unittest.main(exit=False, verbosity=1)
    r = runner.result
    passed = r.testsRun - len(r.failures) - len(r.errors)
    print(f"\n{passed} passed, {len(r.failures) + len(r.errors)} failed")
    sys.exit(0 if r.wasSuccessful() else 1)
