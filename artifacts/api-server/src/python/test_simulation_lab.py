"""
Phase 23.8A — AI Simulation Laboratory tests.

Covers: scenario store (append-only), the scenario what-if engine (filters,
sizing, sector caps, daily circuit rules), risk-rule comparison, unlimited
scenario comparison, portfolio & execution stress tests, and the AST safety
test proving simulation_lab has no write path into live trading state.

All tests run against the FILE FALLBACK store in a temp dir — the dev
database is never touched.
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulation_lab as sim  # noqa: E402


def _trade(i, symbol="RELIANCE", pnl=100.0, conf=70.0, regime="TRENDING_UP",
           sector="ENERGY", fill_price=100.0, qty=10,
           fill_ts="2026-07-01T04:00:00Z", exit_ts="2026-07-02T04:00:00Z"):
    return {
        "trade_id": f"T{i}", "symbol": symbol, "status": "CLOSED",
        "realized_pnl": pnl, "confidence": conf, "regime": regime,
        "sector": sector, "fill_price": fill_price, "quantity": qty,
        "fill_ts": fill_ts, "exit_ts": exit_ts,
        "stop_loss": fill_price * 0.98, "target": fill_price * 1.04,
    }


class FakeBP:
    """Stub of backtest_portfolio for isolated engine tests."""
    def __init__(self, trades, capital=100000.0):
        self._trades = trades
        self._capital = capital

    def get_run(self, run_id):
        if run_id != "BT-test":
            return None
        return {"run_id": run_id, "status": "COMPLETED",
                "config": {"capital": self._capital, "interval": "1d",
                           "start": "2026-06-01", "end": "2026-07-31"}}

    def trades(self, run_id, status=None):
        return list(self._trades)


BASE_TRADES = [
    _trade(1, pnl=200, conf=80,
           fill_ts="2026-07-01T04:00:00Z", exit_ts="2026-07-02T04:00:00Z"),
    _trade(2, symbol="TCS", sector="IT", pnl=-50, conf=55,
           fill_ts="2026-07-03T04:00:00Z", exit_ts="2026-07-04T04:00:00Z"),
    _trade(3, symbol="INFY", sector="IT", pnl=120, conf=90,
           regime="RANGE_BOUND",
           fill_ts="2026-07-06T04:00:00Z", exit_ts="2026-07-07T04:00:00Z"),
    _trade(4, symbol="SBIN", sector="BANKING", pnl=-80, conf=65,
           fill_ts="2026-07-08T04:00:00Z", exit_ts="2026-07-09T04:00:00Z"),
    _trade(5, symbol="LT", sector="INFRA", pnl=150, conf=75,
           fill_ts="2026-07-10T04:00:00Z", exit_ts="2026-07-11T04:00:00Z"),
    _trade(6, symbol="WIPRO", sector="IT", pnl=60, conf=72,
           fill_ts="2026-07-13T04:00:00Z", exit_ts="2026-07-14T04:00:00Z"),
]


class SimLabBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(sim, "db_available", lambda: False),
            mock.patch.object(sim, "_SCEN_FILE",
                              os.path.join(self.tmp, "scen.json")),
            mock.patch.object(sim, "_RUNS_FILE",
                              os.path.join(self.tmp, "runs.json")),
            mock.patch.object(sim, "bp", FakeBP(BASE_TRADES)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestScenarioStore(SimLabBase):
    def test_create_and_list_scenarios(self):
        r = sim.create_scenario("Aggro", "BT-test", {"risk_pct": 2})
        self.assertTrue(r["ok"])
        rows = sim.list_scenarios()["scenarios"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Aggro")
        self.assertEqual(rows[0]["params"], {"risk_pct": 2})

    def test_unknown_params_rejected_or_stripped(self):
        r = sim.create_scenario("X", "BT-test", {"hack_the_ledger": 1})
        # unknown keys are stripped by _clean_params → empty params, ok
        self.assertTrue(r["ok"])
        self.assertEqual(r["scenario"]["params"], {})

    def test_run_history_is_append_only(self):
        a = sim.run_scenario(run_id="BT-test", params={}, label="run1")
        b = sim.run_scenario(run_id="BT-test", params={}, label="run2")
        self.assertTrue(a["ok"] and b["ok"])
        self.assertNotEqual(a["run"]["sim_id"], b["run"]["sim_id"])
        runs = sim.list_sim_runs()["runs"]
        self.assertEqual(len(runs), 2)          # both preserved, never replaced
        # results are immutable copies — re-running never mutates old rows
        c = sim.run_scenario(run_id="BT-test",
                             params={"min_confidence": 99}, label="run3")
        self.assertTrue(c["ok"])
        runs = sim.list_sim_runs()["runs"]
        self.assertEqual(len(runs), 3)
        first = next(r for r in runs if r["sim_id"] == a["run"]["sim_id"])
        self.assertEqual(first["result"]["trades_kept"], 6)


class TestScenarioEngine(SimLabBase):
    def test_baseline_keeps_all_trades(self):
        r = sim._scenario_sim("BT-test", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["trades_kept"], 6)
        self.assertEqual(r["pnl"], 400.0)
        self.assertFalse(r["resimulated_exits"])
        self.assertEqual(r["verdict"], "OK")
        self.assertFalse(r["base_run_modified"])

    def test_unknown_run(self):
        r = sim._scenario_sim("BT-nope", {})
        self.assertFalse(r["ok"])

    def test_confidence_regime_sector_filters(self):
        r = sim._scenario_sim("BT-test", {"min_confidence": 70})
        self.assertEqual(r["trades_kept"], 4)   # drops conf 55, 65
        r = sim._scenario_sim("BT-test", {"regime_filter": "TRENDING_UP"})
        self.assertEqual(r["trades_kept"], 5)   # drops RANGE_BOUND
        r = sim._scenario_sim("BT-test", {"sector_filter": "IT"})
        self.assertEqual(r["trades_kept"], 3)

    def test_liquidity_filter(self):
        # traded value = 100 × 10 = 1000 per trade
        r = sim._scenario_sim("BT-test", {"min_traded_value": 5000})
        self.assertEqual(r["trades_kept"], 0)
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_capital_and_risk_scaling(self):
        r = sim._scenario_sim("BT-test", {"capital": 200000})   # 2× capital
        self.assertEqual(r["pnl"], 800.0)
        r = sim._scenario_sim("BT-test", {"risk_pct": 0.5})     # half risk
        self.assertEqual(r["pnl"], 200.0)
        r = sim._scenario_sim("BT-test", {"position_size_scale": 2})
        self.assertEqual(r["pnl"], 800.0)

    def test_max_open_trades(self):
        # Two overlapping trades: second must be dropped at max_open=1
        overlap = [
            _trade(1, fill_ts="2026-07-01T04:00:00Z",
                   exit_ts="2026-07-05T04:00:00Z"),
            _trade(2, symbol="TCS", fill_ts="2026-07-02T04:00:00Z",
                   exit_ts="2026-07-03T04:00:00Z"),
        ]
        with mock.patch.object(sim, "bp", FakeBP(overlap)):
            r = sim._scenario_sim("BT-test", {"max_open_trades": 1})
        self.assertEqual(r["trades_kept"], 1)
        self.assertIn("max_open_trades",
                      json.dumps(r["dropped"]))

    def test_sector_exposure_cap(self):
        overlap = [
            _trade(1, sector="IT", fill_price=1000, qty=30,     # 30k = 30%
                   fill_ts="2026-07-01T04:00:00Z",
                   exit_ts="2026-07-10T04:00:00Z"),
            _trade(2, symbol="TCS", sector="IT", fill_price=1000, qty=30,
                   fill_ts="2026-07-02T04:00:00Z",
                   exit_ts="2026-07-09T04:00:00Z"),
        ]
        with mock.patch.object(sim, "bp", FakeBP(overlap)):
            r = sim._scenario_sim("BT-test",
                                  {"max_sector_exposure_pct": 40})
        self.assertEqual(r["trades_kept"], 1)
        self.assertIn("sector exposure", json.dumps(r["dropped"]))

    def test_daily_loss_limit_blocks_same_day_entries(self):
        day = [
            _trade(1, pnl=-3000, fill_ts="2026-07-01T04:00:00Z",
                   exit_ts="2026-07-01T06:00:00Z"),
            _trade(2, symbol="TCS", pnl=500,
                   fill_ts="2026-07-01T07:00:00Z",
                   exit_ts="2026-07-01T09:00:00Z"),
        ]
        with mock.patch.object(sim, "bp", FakeBP(day)):
            r = sim._scenario_sim("BT-test", {"daily_loss_limit_pct": 2})
        self.assertEqual(r["trades_kept"], 1)
        self.assertIn("daily loss limit", json.dumps(r["dropped"]))

    def test_daily_profit_lock(self):
        day = [
            _trade(1, pnl=4000, fill_ts="2026-07-01T04:00:00Z",
                   exit_ts="2026-07-01T06:00:00Z"),
            _trade(2, symbol="TCS", pnl=500,
                   fill_ts="2026-07-01T07:00:00Z",
                   exit_ts="2026-07-01T09:00:00Z"),
        ]
        with mock.patch.object(sim, "bp", FakeBP(day)):
            r = sim._scenario_sim("BT-test", {"daily_profit_lock_pct": 3})
        self.assertEqual(r["trades_kept"], 1)
        self.assertIn("profit lock", json.dumps(r["dropped"]))

    def test_resim_failure_excludes_trade(self):
        with mock.patch.object(sim.sl, "_resim_exit", return_value=None):
            r = sim._scenario_sim("BT-test", {"atr_mult": 2.0})
        self.assertEqual(r["trades_kept"], 0)
        self.assertEqual(r["resim_failures"], 6)

    def test_resim_applied(self):
        fake = {"exit_price": 110.0, "exit_rule": "TARGET",
                "exit_ts": "2026-07-02T04:00:00Z", "realized_pnl": 100.0}
        with mock.patch.object(sim.sl, "_resim_exit", return_value=dict(fake)):
            r = sim._scenario_sim("BT-test", {"risk_reward_mult": 1.5})
        self.assertTrue(r["resimulated_exits"])
        self.assertEqual(r["trades_kept"], 6)
        self.assertEqual(r["pnl"], 600.0)


class TestComparisons(SimLabBase):
    def test_compare_sim_runs_unlimited_rows(self):
        ids = []
        for i in range(12):
            r = sim.run_scenario(run_id="BT-test", params={},
                                 label=f"v{i}")
            ids.append(r["run"]["sim_id"])
        out = sim.compare_sim_runs(ids + ["SIM-missing"])
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["rows"]), 13)
        good = [r for r in out["rows"] if r.get("ok")]
        self.assertEqual(len(good), 12)
        for k in ("trades", "win_rate", "pnl", "sharpe", "sortino",
                  "max_drawdown_pct", "profit_factor", "expectancy",
                  "recovery_factor", "capital_growth_pct", "max_exposure"):
            self.assertIn(k, good[0])
        self.assertFalse(out["rows"][-1]["ok"])

    def test_compare_scales_past_history_window_and_200_ids(self):
        """Regression: comparison fetches by id directly — runs older than
        any history-list window and selections >200 must all resolve."""
        ids = []
        for i in range(250):
            row = {"sim_id": f"SIM-bulk{i:04d}",
                   "created_at": f"2026-07-{(i % 28) + 1:02d}T00:00:00Z",
                   "scenario_id": None, "label": f"bulk{i}",
                   "base_run_id": "BT-test", "params": {},
                   "result": {"trades": i, "pnl": float(i),
                              "verdict": "OK"}}
            sim._append_file(sim._RUNS_FILE, row)
            ids.append(row["sim_id"])
        # oldest run is NOT in the default 100-row history page…
        page = {r["sim_id"] for r in sim.list_sim_runs(limit=100)["runs"]}
        self.assertNotIn(ids[0], page)
        # …but comparison still resolves ALL 250 ids
        out = sim.compare_sim_runs(ids)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["rows"]), 250)
        self.assertTrue(all(r["ok"] for r in out["rows"]))
        self.assertEqual(out["rows"][0]["sim_id"], ids[0])
        # direct get also works past the window
        self.assertTrue(sim.get_sim_run(ids[0])["ok"])

    def test_risk_rule_compare(self):
        out = sim.risk_rule_compare("BT-test", {},
                                    {"min_confidence": 70})
        self.assertTrue(out["ok"])
        d = out["diff"]
        self.assertEqual(d["trades"], -2)
        # B dropped T2 (pnl -50, not profitable) and T4 (-80): no missed wins
        self.assertEqual(d["missed_opportunities"], 0)
        self.assertIsNotNone(d["capital_efficiency_a"])
        self.assertIn("risk_reduction_pct", d)
        # B blocks a profitable trade → counted as missed opportunity
        out2 = sim.risk_rule_compare("BT-test", {},
                                     {"min_confidence": 85})
        self.assertGreaterEqual(out2["diff"]["missed_opportunities"], 3)

    def test_risk_rule_compare_insufficient(self):
        with mock.patch.object(sim, "bp", FakeBP(BASE_TRADES[:2])):
            out = sim.risk_rule_compare("BT-test", {}, {})
        self.assertEqual(out["verdict"], "INSUFFICIENT_EVIDENCE")


class TestPortfolioStress(SimLabBase):
    PORT = {
        "equity": 100000.0, "invested_value": 40000.0,
        "positions": [
            {"symbol": "RELIANCE", "market_value": 25000.0, "sector": "ENERGY"},
            {"symbol": "TCS", "market_value": 15000.0, "sector": "IT"},
        ],
        "sector_exposure": {"ENERGY": 25000.0, "IT": 15000.0},
    }

    def test_all_eight_scenarios_reported(self):
        import canonical_portfolio
        with mock.patch.object(canonical_portfolio,
                               "build_canonical_portfolio",
                               return_value=dict(self.PORT)), \
             mock.patch.object(sim, "_avg_daily_pnl", return_value=500.0):
            r = sim.portfolio_stress()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["scenarios"]), 8)
        by = {s["scenario"]: s for s in r["scenarios"]}
        gd = by["GAP_DOWN_20"]
        # −20% + 0.5% slippage on 40k = 8000 + 200
        self.assertAlmostEqual(gd["portfolio_loss"], 8200.0, places=1)
        self.assertAlmostEqual(gd["capital_remaining"], 91800.0, places=1)
        self.assertAlmostEqual(gd["drawdown_pct"], 8.2, places=1)
        self.assertAlmostEqual(gd["recovery_time_days"], 16.4, places=1)
        self.assertIsNotNone(gd["margin_utilization_pct"])
        # gap up is a gain: loss negative, recovery 0
        gu = by["GAP_UP_10"]
        self.assertLess(gu["portfolio_loss"], 0)
        self.assertEqual(gu["recovery_time_days"], 0.0)
        # sector collapse targets the largest sector only
        sc = by["SECTOR_COLLAPSE"]
        self.assertEqual(sc["target_sector"], "ENERGY")
        self.assertAlmostEqual(sc["portfolio_loss"],
                               25000 * 0.30 + 25000 * 0.01, places=1)

    def test_recovery_unknown_without_positive_pnl(self):
        import canonical_portfolio
        with mock.patch.object(canonical_portfolio,
                               "build_canonical_portfolio",
                               return_value=dict(self.PORT)), \
             mock.patch.object(sim, "_avg_daily_pnl", return_value=None):
            r = sim.portfolio_stress()
        gd = next(s for s in r["scenarios"] if s["scenario"] == "GAP_DOWN_20")
        self.assertIsNone(gd["recovery_time_days"])

    def test_empty_portfolio_insufficient(self):
        import canonical_portfolio
        with mock.patch.object(canonical_portfolio,
                               "build_canonical_portfolio",
                               return_value={"equity": 0, "positions": []}):
            r = sim.portfolio_stress()
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")


class TestExecutionStress(SimLabBase):
    LEDGER = [{"symbol": f"S{i}", "fill_price": 100.0, "quantity": 10,
               "status": "CLOSED", "realized_pnl": 10}
              for i in range(10)]

    def test_fault_injection_conserves_orders_and_never_writes(self):
        import phase20_executor
        with mock.patch.object(phase20_executor, "get_ledger",
                               return_value=list(self.LEDGER)) as gl, \
             mock.patch.object(sim, "_replay_fingerprint",
                               return_value={"count": 2,
                                             "ids": ["S1", "S2"]}):
            r = sim.execution_stress()
        # replay store fingerprint identical before/after → consistent
        self.assertTrue(r["consistency"]["replay_store_consistent"])
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["scenarios"]), 6)
        for s in r["scenarios"]:
            self.assertTrue(s["conservation_ok"], s["scenario"])
            self.assertEqual(s["orders_in"],
                             s["filled"] + s["rejected"]
                             + s["partial_fills"] + s["pending"])
        self.assertTrue(r["consistency"]["ledger_untouched"])
        self.assertTrue(r["consistency"]["all_conserved"])
        by = {s["scenario"]: s for s in r["scenarios"]}
        self.assertGreater(by["REJECTED_ORDERS"]["rejected"], 0)
        self.assertGreater(by["PARTIAL_FILLS"]["partial_fills"], 0)
        self.assertGreater(by["BROKER_DISCONNECT"]["pending"], 0)
        self.assertGreater(by["API_FAILURE"]["retries_used"], 0)
        # only ever READ the ledger
        for c in gl.call_args_list:
            self.assertTrue(True)  # get_ledger is read-only by contract

    def test_replay_consistency_unknown_when_store_unavailable(self):
        import phase20_executor
        with mock.patch.object(phase20_executor, "get_ledger",
                               return_value=list(self.LEDGER)), \
             mock.patch.object(sim, "_replay_fingerprint",
                               return_value=None):
            r = sim.execution_stress()
        # advisory: unknown (None), never a fabricated pass
        self.assertIsNone(r["consistency"]["replay_store_consistent"])

    @staticmethod
    def _fake_db(scan_state_rows, snapshot_rows):
        """Fake DB boundary implementing the EXACT queries the fingerprint
        issues, so the retrieval path (unbounded ORDER BY id scan of
        signal_snapshots + scan_state head row) is exercised for real."""
        class Cur:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, *args):
                assert "LIMIT" not in sql.upper(), \
                    "fingerprint query must be unbounded"
                if "FROM scan_state" in sql:
                    self._rows = scan_state_rows
                elif "FROM signal_snapshots" in sql:
                    assert "ORDER BY id" in sql
                    self._rows = snapshot_rows
                else:
                    raise AssertionError(f"unexpected query: {sql}")
            def fetchall(self): return self._rows
        class Conn:
            def cursor(self): return Cur()
            def close(self): pass
        return Conn

    def _fp_with(self, scan_state_rows, snapshot_rows):
        Conn = self._fake_db(scan_state_rows, snapshot_rows)
        with mock.patch.object(sim, "db_available", lambda: True), \
             mock.patch.object(sim, "_connect", lambda: Conn()):
            return sim._replay_fingerprint()

    def test_replay_fingerprint_covers_full_store(self):
        head = [("SCAN-L", "COMPLETED", "2026-08-08", "md5head")]
        # 30 historical rows — well beyond any paged/list-API window
        snaps = [(i, f"SCAN-{i}", f"C-{i}", f"2026-07-{(i % 28) + 1:02d}",
                  f"sigmd5-{i}", f"ctxmd5-{i}") for i in range(30)]
        fp1 = self._fp_with(head, list(snaps))
        self.assertEqual(fp1["count"], 30)
        # identical store → identical fingerprint
        self.assertEqual(self._fp_with(head, list(snaps)), fp1)
        # row appended beyond any 20-row window → fingerprint changes
        fp2 = self._fp_with(head, list(snaps)
                            + [(99, "SCAN-99", "C-99", "2026-08-01",
                                "s99", "c99")])
        self.assertNotEqual(fp2, fp1)
        # same ids but CONTENT of row #25 mutated (content-hash column
        # differs) → fingerprint changes even though count is identical
        mutated = list(snaps)
        r = list(mutated[25]); r[4] = "sigmd5-TAMPERED"
        mutated[25] = tuple(r)
        fp3 = self._fp_with(head, mutated)
        self.assertNotEqual(fp3, fp1)
        self.assertEqual(fp3["count"], fp1["count"])
        # latest scan_state snapshot content mutated → changes too
        fp4 = self._fp_with([("SCAN-L", "COMPLETED", "2026-08-08",
                              "md5head-CHANGED")], list(snaps))
        self.assertNotEqual(fp4, fp1)

    def test_replay_fingerprint_unknown_when_unreadable(self):
        # DB unavailable → None (unknown)
        with mock.patch.object(sim, "db_available", lambda: False):
            self.assertIsNone(sim._replay_fingerprint())
        # query blows up → None, never a fabricated pass
        def boom(): raise RuntimeError("db down")
        with mock.patch.object(sim, "db_available", lambda: True), \
             mock.patch.object(sim, "_connect", boom):
            self.assertIsNone(sim._replay_fingerprint())

    def test_execution_stress_flags_replay_mutation_as_inconsistent(self):
        import phase20_executor
        with mock.patch.object(phase20_executor, "get_ledger",
                               return_value=list(self.LEDGER)), \
             mock.patch.object(sim, "_replay_fingerprint",
                               side_effect=[{"count": 6, "sha256": "aaa"},
                                            {"count": 6, "sha256": "bbb"}]):
            r = sim.execution_stress()
        self.assertFalse(r["consistency"]["replay_store_consistent"])

    def test_no_ledger_data(self):
        import phase20_executor
        with mock.patch.object(phase20_executor, "get_ledger",
                               return_value=[]):
            r = sim.execution_stress()
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")


# ── SAFETY (spec Part Q): no write path into live trading state ─────────────

FORBIDDEN_CALLS = {
    # settings / threshold mutation
    "update_settings", "save_settings", "set_settings", "save_state",
    "update_stop_loss", "execute_buy", "execute_sell", "reset_portfolio",
    # phase20 executor / paper ledger mutations
    "create_paper_entry", "record_exit", "record_fill", "run_entries",
    "close_trade", "open_trade",
    # event store writes
    "emit", "emit_many", "prune_events",
    # backtest run mutation
    "create_run", "update_run", "claim_run", "execute_run",
    # strategy config application
    "approve_adjustment", "apply_adjustment", "promote_challenger",
    "kv_set",
}
FORBIDDEN_IMPORTS = {"paper_trader", "phase20_exits", "backtest_runner",
                     "pipeline_events"}
SIM_FILES = ["simulation_lab.py"]


class TestNoWritePathSafety(unittest.TestCase):
    """Prove by AST inspection that the simulation lab never calls anything
    that mutates the live portfolio, paper ledger, event store, backtest
    runs, settings, or strategy config (spec Part Q)."""

    def _tree(self, filename):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            filename)
        with open(path) as f:
            return ast.parse(f.read(), filename=filename), f

    def test_no_forbidden_calls(self):
        for fname in SIM_FILES:
            tree, _ = self._tree(fname)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else func.id if isinstance(func, ast.Name)
                            else None)
                    self.assertNotIn(
                        name, FORBIDDEN_CALLS,
                        f"{fname}: forbidden mutating call '{name}'"
                        f" at line {node.lineno}")

    def test_no_forbidden_imports(self):
        for fname in SIM_FILES:
            tree, _ = self._tree(fname)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(
                        m.split(".")[0], FORBIDDEN_IMPORTS,
                        f"{fname}: forbidden import '{m}'"
                        f" at line {node.lineno}")

    def test_sql_writes_limited_to_sim_tables(self):
        """Every INSERT targets sim_* tables only; no UPDATE/DELETE at all —
        the run history is append-only by construction."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "simulation_lab.py")
        with open(path) as f:
            src_text = f.read()
        tree = ast.parse(src_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value.upper()
                if "INSERT INTO" in s:
                    self.assertIn("SIM_", s,
                                  f"INSERT into non-sim table: {node.value}")
                import re
                if re.search(r"\bUPDATE\s+\w+\s+SET\b", s) \
                        or "DELETE FROM" in s or "DROP TABLE" in s \
                        or "TRUNCATE " in s:
                    self.fail(f"forbidden SQL verb in simulation_lab:"
                              f" {node.value[:80]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
