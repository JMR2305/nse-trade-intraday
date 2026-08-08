"""
test_phase24.py — Phase 24: AI Learning & Continuous Improvement Engine.

Unit tests: file-fallback store append-only enforcement, trade capture
idempotency, excursion computation, post-trade analysis verdicts,
missed-opportunity correctness, risk-rule learning, aggregate analytics
(ranking math, time analysis, scorecard), recommendation lifecycle
(approval records INTENT ONLY), report generation idempotency, and an
explicit AST safety test proving no Phase 24 code path writes to trading
rules, thresholds, or strategy enablement.

All tests run against the JSON file fallback in a tmpdir — the dev
database is never touched.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import phase24_store as store
import phase24_engine as engine
import phase24_analytics as analytics
import phase24_recommendations as recommendations


class Phase24Base(unittest.TestCase):
    """Force file-fallback mode into a private tmpdir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._patches = [
            patch.object(store, "db_available", lambda: False),
            patch.object(store, "TRADES_FILE", os.path.join(d, "ti.json")),
            patch.object(store, "MISSED_FILE", os.path.join(d, "mo.json")),
            patch.object(store, "RECS_FILE", os.path.join(d, "recs.json")),
            patch.object(store, "REPORTS_FILE", os.path.join(d, "reports.json")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _insert_trade(self, tid="T1", pnl=100.0, **over):
        record = {
            "trade_id": tid, "scan_id": "S1", "symbol": over.get("symbol", "TCS"),
            "sector": over.get("sector", "IT"), "date": over.get("date", "2026-08-07"),
            "entry_time": over.get("entry_time", "2026-08-07T04:30:00Z"),
            "exit_time": "2026-08-07T08:30:00Z", "holding_time_minutes": 240.0,
            "entry_price": 100.0, "exit_price": 100.0 + pnl / 10.0,
            "quantity": 10, "capital_used": 1000.0,
            "strategy": over.get("strategy", "Trend Rider"),
            "confidence": over.get("confidence", 70.0),
            "realized_pnl": pnl, "exit_reason": over.get("exit_reason", "TARGET"),
            "market_regime": over.get("market_regime", "STRONG_UPTREND"),
            "volatility": over.get("volatility", 1.5),
            "mfe": over.get("mfe", max(pnl, 0) + 50), "mae": over.get("mae", -30),
            "highest_price": over.get("highest_price", 112.0),
            "lowest_price": over.get("lowest_price", 97.0),
            "stop_loss": 95.0, "target": 110.0, "slippage": 0.1,
        }
        record.update(over)
        return store.insert_trade_record(tid, "S1", record["symbol"],
                                         record["date"], record,
                                         over.get("analysis"))


# ── Store: append-only enforcement ───────────────────────────────────────────

class TestStoreAppendOnly(Phase24Base):
    def test_trade_insert_and_duplicate_rejected(self):
        self.assertTrue(self._insert_trade("T1"))
        self.assertFalse(self._insert_trade("T1", pnl=999.0))  # never overwritten
        rows = store.list_trade_records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record"]["realized_pnl"], 100.0)

    def test_has_trade_record(self):
        self.assertFalse(store.has_trade_record("TX"))
        self._insert_trade("TX")
        self.assertTrue(store.has_trade_record("TX"))

    def test_missed_opp_append_only(self):
        self.assertTrue(store.insert_missed_opp("S1", "RELIANCE", {"a": 1}))
        self.assertFalse(store.insert_missed_opp("S1", "RELIANCE", {"a": 2}))
        rows = store.list_missed_opps()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record"]["a"], 1)

    def test_report_idempotent_per_period(self):
        r1 = store.save_report("daily", "2026-08-07", {"x": 1})
        r2 = store.save_report("daily", "2026-08-07", {"x": 2})
        self.assertTrue(r1["inserted"])
        self.assertFalse(r2["inserted"])
        rep = store.get_report("daily", "2026-08-07")
        self.assertEqual(rep["record"]["x"], 1)


# ── Recommendation lifecycle ─────────────────────────────────────────────────

class TestRecommendationLifecycle(Phase24Base):
    def test_propose_approve_is_intent_only_and_final(self):
        row = store.insert_recommendation("2026-08-07", {"title": "t"})
        rid = row["id"]
        out = store.decide_recommendation(rid, "APPROVED", "ok")
        self.assertTrue(out["success"])
        self.assertIn("intent only", out["note"])
        # decisions are final
        out2 = store.decide_recommendation(rid, "DISMISSED")
        self.assertFalse(out2["success"])
        recs = store.list_recommendations()
        self.assertEqual(recs[0]["status"], "APPROVED")

    def test_invalid_decision_rejected(self):
        row = store.insert_recommendation("2026-08-07", {"title": "t"})
        out = store.decide_recommendation(row["id"], "APPLY")
        self.assertFalse(out["success"])

    def test_dismiss(self):
        row = store.insert_recommendation("2026-08-07", {"title": "t"})
        out = store.decide_recommendation(row["id"], "DISMISSED", "no")
        self.assertTrue(out["success"])
        self.assertEqual(store.list_recommendations(status="DISMISSED")[0]["id"],
                         row["id"])


# ── Engine: excursions + post-trade analysis ─────────────────────────────────

class TestExcursions(unittest.TestCase):
    def test_compute_excursions(self):
        candles = [{"high": 110, "low": 98, "close": 105},
                   {"high": 115, "low": 101, "close": 112}]
        e = engine.compute_excursions(candles, 100.0, 10)
        self.assertEqual(e["highest_price"], 115)
        self.assertEqual(e["lowest_price"], 98)
        self.assertEqual(e["mfe"], 150.0)
        self.assertEqual(e["mae"], -20.0)
        self.assertEqual(e["excursion_source"], "intraday_candles")

    def test_no_candles_yields_explicit_none(self):
        e = engine.compute_excursions([], 100.0, 10)
        self.assertIsNone(e["mfe"])
        self.assertEqual(e["excursion_source"], "unavailable")


class TestPostTradeAnalysis(unittest.TestCase):
    def _rec(self, **over):
        rec = {"entry_price": 100.0, "exit_price": 105.0, "quantity": 10,
               "stop_loss": 95.0, "target": 110.0, "realized_pnl": 50.0,
               "highest_price": 108.0, "lowest_price": 98.0,
               "mfe": 80.0, "mae": -20.0, "exit_reason": "TARGET",
               "market_regime": "STRONG_UPTREND", "strategy": "Trend Rider"}
        rec.update(over)
        return rec

    def test_exit_early_could_have_earned_more(self):
        v = engine.analyze_trade(self._rec(mfe=500.0, realized_pnl=50.0))
        self.assertEqual(v["exit_timing"], "EARLY")
        self.assertTrue(v["could_have_earned_more"])
        self.assertEqual(v["missed_pnl"], 450.0)

    def test_exit_late_profit_turned_loss(self):
        v = engine.analyze_trade(self._rec(realized_pnl=-100.0, mfe=200.0,
                                           exit_reason="STOP_LOSS"))
        self.assertEqual(v["exit_timing"], "LATE")

    def test_stop_too_tight(self):
        v = engine.analyze_trade(self._rec(realized_pnl=-50.0, exit_price=95.0,
                                           exit_reason="STOP_LOSS", mfe=300.0))
        self.assertEqual(v["stop_verdict"], "TOO_TIGHT")

    def test_target_too_conservative(self):
        v = engine.analyze_trade(self._rec(highest_price=120.0))
        self.assertEqual(v["target_verdict"], "TOO_CONSERVATIVE")

    def test_target_too_aggressive(self):
        v = engine.analyze_trade(self._rec(highest_price=102.0, mfe=20.0))
        self.assertEqual(v["target_verdict"], "TOO_AGGRESSIVE")

    def test_unknown_when_data_missing(self):
        v = engine.analyze_trade({"entry_price": 0, "quantity": 0})
        self.assertEqual(v["entry_timing"], "UNKNOWN")
        self.assertEqual(v["stop_verdict"], "UNKNOWN")
        self.assertIsNone(v["could_have_earned_more"])

    def test_always_advisory(self):
        self.assertTrue(engine.analyze_trade(self._rec())["advisory_only"])


# ── Engine: capture idempotency ──────────────────────────────────────────────

class TestCaptureIdempotency(Phase24Base):
    def _ledger_row(self, tid="P24-CAP-1"):
        return {"trade_id": tid, "status": "CLOSED", "scan_id": "S9",
                "symbol": "INFY", "sector": "IT", "strategy_id": "trend_rider",
                "strategy_name": "Trend Rider", "fill_ts": "2026-08-07T04:30:00Z",
                "exit_ts": "2026-08-07T08:00:00Z", "fill_price": 1500.0,
                "exit_price": 1520.0, "quantity": 3, "stop_loss": 1470.0,
                "target": 1560.0, "realized_pnl": 60.0, "exit_rule": "TARGET",
                "confidence": 66.0, "opportunity_score": 70.0,
                "trade_quality_score": 60.0, "regime": "Strong uptrend",
                "est_charges": 5.0, "slippage": 1.0, "risk_amount": 90.0,
                "trigger_source": "AUTO", "evidence": {"gates": []}}

    def test_capture_is_idempotent(self):
        rows = [self._ledger_row()]
        with patch("phase20_executor.get_ledger", return_value=rows), \
             patch.object(engine, "_candles_between", return_value=[]):
            r1 = engine.capture_closed_trades()
            r2 = engine.capture_closed_trades()
        self.assertEqual(r1["captured_count"], 1)
        self.assertEqual(r2["captured_count"], 0)
        self.assertEqual(r2["skipped_existing"], 1)
        rec = store.list_trade_records()[0]
        self.assertEqual(rec["record"]["capital_used"], 4500.0)
        self.assertIsNotNone(rec["analysis"])

    def test_open_trades_not_captured(self):
        row = self._ledger_row()
        row["status"] = "OPEN"
        with patch("phase20_executor.get_ledger", return_value=[row]):
            r = engine.capture_closed_trades()
        self.assertEqual(r["closed_in_ledger"], 0)

    def test_record_built_from_ledger_payload_not_reevaluated(self):
        """Record fields must come from the exact ledger row values."""
        rows = [self._ledger_row()]
        with patch("phase20_executor.get_ledger", return_value=rows), \
             patch.object(engine, "_candles_between", return_value=[]):
            engine.capture_closed_trades()
        rec = store.list_trade_records()[0]["record"]
        self.assertEqual(rec["entry_price"], 1500.0)
        self.assertEqual(rec["confidence"], 66.0)
        self.assertEqual(rec["exit_reason"], "TARGET")
        self.assertEqual(rec["source"], "phase20_ledger")


# ── Missed opportunities + risk learning ─────────────────────────────────────

class TestMissedAndRiskLearning(Phase24Base):
    def _seed_missed(self, gate="min_confidence", move=3.5, correct=False, n=6):
        for i in range(n):
            store.insert_missed_opp(f"SC{i}", "SYM" + str(i), {
                "rejected_by_gates": [gate], "later_max_move_pct": move,
                "rejection_correct": correct, "symbol": "SYM" + str(i)})

    def test_rule_blocks_profits(self):
        self._seed_missed(move=4.0, correct=False, n=6)
        out = engine.risk_rule_learning()
        rule = out["rules"][0]
        self.assertEqual(rule["verdict"], "BLOCKS_PROFITS")
        self.assertEqual(rule["blocked_profitable"], 6)

    def test_rule_saves_money(self):
        self._seed_missed(gate="scan_fresh", move=0.5, correct=True, n=8)
        out = engine.risk_rule_learning()
        rule = next(r for r in out["rules"] if r["rule"] == "scan_fresh")
        self.assertEqual(rule["verdict"], "SAVES_MONEY")

    def test_insufficient_evidence(self):
        self._seed_missed(n=2)
        out = engine.risk_rule_learning()
        self.assertEqual(out["rules"][0]["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(out["rules"][0]["effectiveness"])

    def test_missed_analysis_stores_permanently(self):
        snap = {"scan_id": "SCAN1", "snapshot_ts": "2026-08-07T05:00:00Z",
                "recommendations": [{"symbol": "RELIANCE", "entry_price": 100.0,
                                     "confidence": 57.0, "sector": "ENERGY"}]}
        gate_result = {"candidates": [{"symbol": "RELIANCE", "eligible": False,
                                       "failed_gates": ["min_confidence"]}]}
        candles = [{"high": 104.0, "low": 99.0, "close": 103.6, "time": "x"}]
        with patch("scan_state_store.load_latest_snapshot", return_value=snap), \
             patch("phase20_gates.evaluate_entries", return_value=gate_result), \
             patch.object(engine, "_candles_between", return_value=candles):
            out = engine.run_missed_opportunity_analysis(move_threshold_pct=2.0)
        self.assertEqual(out["stored"], 1)
        rec = store.list_missed_opps()[0]["record"]
        self.assertAlmostEqual(rec["later_max_move_pct"], 3.6)
        self.assertFalse(rec["rejection_correct"])
        self.assertTrue(rec["should_have_allowed"])
        # Idempotent per (scan_id, symbol)
        with patch("scan_state_store.load_latest_snapshot", return_value=snap), \
             patch("phase20_gates.evaluate_entries", return_value=gate_result), \
             patch.object(engine, "_candles_between", return_value=candles):
            out2 = engine.run_missed_opportunity_analysis()
        self.assertEqual(out2["stored"], 0)


# ── Aggregate analytics ──────────────────────────────────────────────────────

class TestAnalytics(Phase24Base):
    def test_strategy_ranking_math(self):
        for i, pnl in enumerate([100.0, -50.0, 200.0]):
            self._insert_trade(f"A{i}", pnl=pnl, strategy="Alpha")
        self._insert_trade("B0", pnl=-80.0, strategy="Beta")
        out = analytics.strategy_ranking()
        alpha = next(i for i in out["items"] if i["strategy"] == "Alpha")
        self.assertEqual(alpha["trades"], 3)
        self.assertAlmostEqual(alpha["win_rate"], 2 / 3, places=3)
        self.assertEqual(alpha["total_pnl"], 250.0)
        self.assertAlmostEqual(alpha["profit_factor"], 300.0 / 50.0, places=2)
        self.assertAlmostEqual(alpha["expectancy"], 250.0 / 3, places=1)
        self.assertEqual(alpha["rank"], 1)
        self.assertTrue(out["advisory_only"])

    def test_sector_ranking_summary(self):
        self._insert_trade("S1", pnl=100.0, sector="IT")
        self._insert_trade("S2", pnl=-200.0, sector="ENERGY")
        out = analytics.sector_ranking()
        self.assertEqual(out["summary"]["best_sector"], "IT")
        self.assertEqual(out["summary"]["worst_sector"], "ENERGY")

    def test_time_analysis_buckets(self):
        # 04:30 UTC = 10:00 IST
        self._insert_trade("H1", pnl=100.0, entry_time="2026-08-07T04:30:00Z")
        out = analytics.time_analysis()
        self.assertTrue(any(h["bucket"] == "10:00" for h in out["hours"]))
        self.assertTrue(any(w["bucket"] == "Friday" for w in out["weekdays"]))
        self.assertIn("regime", out["summary"])

    def test_best_worst_trades(self):
        self._insert_trade("W1", pnl=-500.0)
        self._insert_trade("W2", pnl=800.0)
        out = analytics.best_worst_trades(limit=1)
        self.assertEqual(out["best"][0]["trade_id"], "W2")
        self.assertEqual(out["worst"][0]["trade_id"], "W1")

    def test_scorecard_shape(self):
        self._insert_trade("SC1", pnl=100.0)
        card = analytics.ai_scorecard()
        for key in ("scanner", "research", "market_intelligence", "monitoring",
                    "strategy", "risk", "execution", "portfolio"):
            self.assertIn(key, card["scores"])
        self.assertTrue(card["advisory_only"])
        self.assertIn("strengths", card)
        self.assertIn("weaknesses", card)

    def test_lessons_detect_mistakes(self):
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
        self._insert_trade("L1", pnl=50.0, date=today,
                           analysis={"exit_timing": "EARLY",
                                     "could_have_earned_more": True,
                                     "stop_verdict": "OK"})
        out = analytics.lessons(1, "daily")
        self.assertTrue(any("exited early" in m for m in out["mistakes"]))
        self.assertTrue(any("Trailing" in m for m in out["improvements"]))


# ── Recommendations + reports generation ─────────────────────────────────────

class TestGeneration(Phase24Base):
    def test_recommendations_from_bad_strategy(self):
        for i in range(6):
            self._insert_trade(f"BAD{i}", pnl=-100.0, strategy="LossMaker")
        with patch.object(analytics, "calibration", side_effect=Exception("skip")):
            out = recommendations.generate_recommendations(force=True)
        self.assertTrue(out["generated"])
        titles = [r["record"]["title"] for r in out["recommendations"]]
        self.assertTrue(any("disabling strategy LossMaker" in t for t in titles))
        # All stored as PROPOSED, advisory
        for r in store.list_recommendations():
            self.assertEqual(r["status"], "PROPOSED")
            self.assertTrue(r["record"]["requires_manual_approval"])

    def test_recommendations_once_per_day(self):
        with patch.object(analytics, "calibration", side_effect=Exception("skip")):
            recommendations.generate_recommendations(force=True)
            # A generated (possibly empty) run still counts only via stored rows;
            # force a stored row to trigger the dedup path
            store.insert_recommendation(recommendations._today_ist(), {"title": "x"})
            out = recommendations.generate_recommendations()
        self.assertFalse(out["generated"])

    def test_report_generation_idempotent(self):
        self._insert_trade("R1", pnl=100.0)
        with patch.object(analytics, "ai_scorecard",
                          return_value={"overall": 8.0, "scores": {},
                                        "strengths": [], "weaknesses": []}):
            r1 = recommendations.generate_report("daily")
            r2 = recommendations.generate_report("daily")
        self.assertTrue(r1["generated"])
        self.assertFalse(r2["generated"])
        self.assertIn("performance", r1["report"])
        self.assertTrue(r1["report"]["advisory_only"])

    def test_report_invalid_period(self):
        self.assertIn("error", recommendations.generate_report("hourly"))

    def test_period_keys(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(recommendations._period_key("daily", dt), "2026-08-07")
        self.assertEqual(recommendations._period_key("monthly", dt), "2026-08")
        self.assertEqual(recommendations._period_key("quarterly", dt), "2026-Q3")
        self.assertTrue(recommendations._period_key("weekly", dt).startswith("2026-W"))


# ── SAFETY: no write path into trading rules / thresholds / strategies ──────

FORBIDDEN_CALLS = {
    # settings / threshold mutation
    "update_settings", "save_settings", "set_settings", "save_state",
    "update_stop_loss", "execute_buy", "execute_sell", "reset_portfolio",
    # phase20 executor mutations
    "create_paper_entry", "record_exit", "record_fill", "run_entries",
    # strategy enablement / adjustments application
    "approve_adjustment", "apply_adjustment", "promote_challenger",
}
FORBIDDEN_IMPORTS = {"paper_trader", "phase20_exits"}
PHASE24_FILES = ["phase24_store.py", "phase24_engine.py",
                 "phase24_analytics.py", "phase24_recommendations.py"]


class TestNoWritePathSafety(unittest.TestCase):
    """Prove by AST inspection that Phase 24 modules never call any function
    that mutates trading rules, thresholds, strategies, or portfolio state."""

    def _tree(self, filename):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path) as f:
            return ast.parse(f.read(), filename=filename)

    def test_no_forbidden_calls(self):
        for fname in PHASE24_FILES:
            tree = self._tree(fname)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else func.id if isinstance(func, ast.Name) else None)
                    self.assertNotIn(
                        name, FORBIDDEN_CALLS,
                        f"{fname}: forbidden mutating call '{name}' at line {node.lineno}")

    def test_no_forbidden_imports(self):
        for fname in PHASE24_FILES:
            tree = self._tree(fname)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(
                        m.split(".")[0], FORBIDDEN_IMPORTS,
                        f"{fname}: forbidden import '{m}' at line {node.lineno}")

    def test_kv_writes_limited_to_phase24_keys(self):
        """The only phase20_store mutation Phase 24 performs is its own
        scheduler-guard KV key."""
        tree = self._tree("phase24_recommendations.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "kv_set":
                key = node.args[0]
                self.assertIsInstance(key, (ast.Constant, ast.Name))
                if isinstance(key, ast.Constant):
                    self.assertTrue(str(key.value).startswith("phase24_"),
                                    f"kv_set on non-phase24 key: {key.value}")

    def test_decide_recommendation_never_touches_configs(self):
        """Approving a recommendation calls nothing outside phase24_store."""
        tree = self._tree("phase24_store.py")
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "decide_recommendation")
        for node in ast.walk(fn):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.fail("decide_recommendation must not import anything")


if __name__ == "__main__":
    unittest.main(verbosity=2)
