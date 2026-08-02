"""
test_learning_layer.py — Phase 10D
Comprehensive test suite for the Learning Layer:
Learning Agent, Knowledge Agent, and Learning Layer aggregation.

READ-ONLY · ADVISORY-ONLY
Auto_model_updates = false, auto_strategy_tuning = false.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── ensure python path ────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))


# =============================================================================
# 1. Learning Engine — compute_learning_metrics
# =============================================================================
class TestLearningMetrics(unittest.TestCase):

    def _make_trades(self):
        return [
            {"status": "CLOSED", "pnl_pct": 2.5, "sector": "BANKING", "strategy": "MOMENTUM",
             "entry_time": "2024-01-01T09:20:00Z", "exit_time": "2024-01-01T10:00:00Z",
             "risk_pct": 1.0},
            {"status": "CLOSED", "pnl_pct": -1.0, "sector": "IT", "strategy": "MEAN_REVERT",
             "entry_time": "2024-01-01T09:25:00Z", "exit_time": "2024-01-01T10:15:00Z",
             "risk_pct": 1.0},
            {"status": "OPEN", "pnl_pct": 0.5, "sector": "PHARMA", "strategy": "MOMENTUM"},
        ]

    def _make_recs(self):
        return [
            {"confidence": 0.8, "outcome": "TARGET_HIT", "decision_type": "BUY_CANDIDATE"},
            {"confidence": 0.6, "outcome": "LOSS",       "decision_type": "WATCH"},
        ]

    def test_basic_metrics_shape(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), self._make_recs(), {}, {})
        required = [
            "recommendation_accuracy", "strategy_win_rate", "confidence_calibration",
            "avg_holding_minutes", "avg_reward_risk", "sector_performance",
            "regime_performance", "risk_prediction_accuracy",
            "execution_validation_accuracy", "trades_analysed",
        ]
        for key in required:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_trades_analysed_excludes_open(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), [], {}, {})
        self.assertEqual(result["trades_analysed"], 2)  # only CLOSED

    def test_win_rate_calculation(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), [], {}, {})
        self.assertEqual(result["strategy_win_rate"], 50.0)  # 1 win out of 2

    def test_recommendation_accuracy(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics([], self._make_recs(), {}, {})
        self.assertEqual(result["recommendation_accuracy"], 50.0)

    def test_sector_performance_structure(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), [], {}, {})
        sp = result["sector_performance"]
        self.assertIn("BANKING", sp)
        self.assertIn("IT", sp)
        self.assertIn("count", sp["BANKING"])
        self.assertIn("win_rate", sp["BANKING"])
        self.assertIn("avg_pnl_pct", sp["BANKING"])

    def test_confidence_calibration_range(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics([], self._make_recs(), {}, {})
        cal = result["confidence_calibration"]
        self.assertGreaterEqual(cal, 0.0)
        self.assertLessEqual(cal, 1.0)

    def test_empty_trades_does_not_crash(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics([], [], {}, {})
        self.assertEqual(result["trades_analysed"], 0)
        self.assertEqual(result["strategy_win_rate"], 0.0)

    def test_avg_reward_risk_computed(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), [], {}, {})
        self.assertIn("avg_reward_risk", result)

    def test_regime_performance_uses_risk_snapshot(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), [], {"regime": "TRENDING"}, {})
        self.assertIn("TRENDING", result["regime_performance"])

    def test_winners_and_losers_counts(self):
        from learning_agent.learning_engine import compute_learning_metrics
        result = compute_learning_metrics(self._make_trades(), [], {}, {})
        self.assertEqual(result["winners"], 1)
        self.assertEqual(result["losers"], 1)


# =============================================================================
# 2. Learning Engine — compute_learning_insights
# =============================================================================
class TestLearningInsights(unittest.TestCase):

    def _make_trades(self):
        return [
            {"status": "CLOSED", "pnl_pct": 3.0, "strategy": "MOMENTUM", "sector": "BANKING"},
            {"status": "CLOSED", "pnl_pct": -1.5, "strategy": "MEAN_REVERT", "sector": "IT"},
        ]

    def _make_metrics(self):
        return {
            "strategy_win_rate": 50.0,
            "recommendation_accuracy": 60.0,
            "confidence_calibration": 0.7,
            "avg_reward_risk": 2.0,
            "sector_performance": {
                "BANKING": {"count": 1, "win_rate": 100.0, "avg_pnl_pct": 3.0},
                "IT":      {"count": 1, "win_rate": 0.0,   "avg_pnl_pct": -1.5},
            },
        }

    def test_insights_shape(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights(self._make_metrics(), self._make_trades(), [], {})
        required = [
            "best_strategy_today", "worst_strategy_today",
            "most_profitable_sector", "weakest_sector",
            "most_reliable_rec_type", "common_rejection_reasons",
            "most_frequent_risk_warnings", "recurring_patterns",
        ]
        for key in required:
            self.assertIn(key, result, f"Missing: {key}")

    def test_best_strategy_identified(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights(self._make_metrics(), self._make_trades(), [], {})
        self.assertEqual(result["best_strategy_today"], "MOMENTUM")

    def test_worst_strategy_identified(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights(self._make_metrics(), self._make_trades(), [], {})
        self.assertEqual(result["worst_strategy_today"], "MEAN_REVERT")

    def test_most_profitable_sector(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights(self._make_metrics(), self._make_trades(), [], {})
        self.assertEqual(result["most_profitable_sector"], "BANKING")

    def test_weakest_sector(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights(self._make_metrics(), self._make_trades(), [], {})
        self.assertEqual(result["weakest_sector"], "IT")

    def test_recurring_patterns_is_list(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights(self._make_metrics(), self._make_trades(), [], {})
        self.assertIsInstance(result["recurring_patterns"], list)
        self.assertGreater(len(result["recurring_patterns"]), 0)

    def test_common_rejection_reasons_structure(self):
        from learning_agent.learning_engine import compute_learning_insights
        recs = [{"rejection_reasons": ["LOW_CONFIDENCE"], "outcome": "REJECTED"}]
        result = compute_learning_insights(self._make_metrics(), [], recs, {})
        reasons = result["common_rejection_reasons"]
        self.assertIsInstance(reasons, list)
        if reasons:
            self.assertIn("reason", reasons[0])
            self.assertIn("count", reasons[0])

    def test_empty_input_does_not_crash(self):
        from learning_agent.learning_engine import compute_learning_insights
        result = compute_learning_insights({}, [], [], {})
        self.assertIn("best_strategy_today", result)

    def test_most_reliable_rec_type(self):
        from learning_agent.learning_engine import compute_learning_insights
        recs = [
            {"decision_type": "BUY_CANDIDATE", "outcome": "TARGET_HIT"},
            {"decision_type": "BUY_CANDIDATE", "outcome": "TARGET_HIT"},
            {"decision_type": "WATCH",          "outcome": "LOSS"},
        ]
        result = compute_learning_insights(self._make_metrics(), [], recs, {})
        self.assertEqual(result["most_reliable_rec_type"], "BUY_CANDIDATE")

    def test_risk_warnings_from_snapshot(self):
        from learning_agent.learning_engine import compute_learning_insights
        risk = {"recent_warnings": [{"message": "DRAWDOWN"}, {"message": "DRAWDOWN"}]}
        result = compute_learning_insights(self._make_metrics(), [], [], risk)
        warnings = result["most_frequent_risk_warnings"]
        self.assertIsInstance(warnings, list)


# =============================================================================
# 3. Learning Engine — discover_patterns
# =============================================================================
class TestPatternDiscovery(unittest.TestCase):

    def test_returns_list(self):
        from learning_agent.learning_engine import discover_patterns
        result = discover_patterns([])
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_baseline_when_no_trades(self):
        from learning_agent.learning_engine import discover_patterns
        result = discover_patterns([])
        ids = [p["pattern_id"] for p in result]
        self.assertIn("BASELINE_OBSERVATION", ids)

    def test_gap_breakout_detected(self):
        from learning_agent.learning_engine import discover_patterns
        trades = [
            {"gap_pct": 2.0, "pnl_pct": 3.0, "status": "CLOSED"},
            {"gap_pct": 1.8, "pnl_pct": 2.5, "status": "CLOSED"},
        ]
        result = discover_patterns(trades)
        ids = [p["pattern_id"] for p in result]
        self.assertIn("GAP_BREAKOUT", ids)

    def test_high_vix_pattern_detected(self):
        from learning_agent.learning_engine import discover_patterns
        trades = [
            {"vix_at_entry": 20.0, "pnl_pct": -2.0, "status": "CLOSED"},
            {"vix_at_entry": 22.0, "pnl_pct": -1.5, "status": "CLOSED"},
        ]
        result = discover_patterns(trades)
        ids = [p["pattern_id"] for p in result]
        self.assertIn("HIGH_VIX_FALSE_BREAKOUT", ids)

    def test_morning_fade_detected(self):
        from learning_agent.learning_engine import discover_patterns
        trades = [
            {"holding_minutes": 30, "pnl_pct": -1.0, "status": "CLOSED"},
            {"holding_minutes": 45, "pnl_pct": -0.5, "status": "CLOSED"},
        ]
        result = discover_patterns(trades)
        ids = [p["pattern_id"] for p in result]
        self.assertIn("MORNING_MOMENTUM_FADE", ids)

    def test_pattern_has_required_fields(self):
        from learning_agent.learning_engine import discover_patterns
        result = discover_patterns([])
        for p in result:
            self.assertIn("pattern_id", p)
            self.assertIn("name", p)
            self.assertIn("description", p)
            self.assertIn("occurrences", p)
            self.assertIn("advisory", p)
            self.assertIn("confidence", p)
            self.assertIn("category", p)

    def test_confidence_in_range(self):
        from learning_agent.learning_engine import discover_patterns
        trades = [{"gap_pct": 2.0, "pnl_pct": 3.0, "status": "CLOSED"}] * 5
        result = discover_patterns(trades)
        for p in result:
            self.assertGreaterEqual(p["confidence"], 0.0)
            self.assertLessEqual(p["confidence"], 1.0)


# =============================================================================
# 4. Learning Agent (agent.py)
# =============================================================================
class TestLearningAgent(unittest.TestCase):

    def _make_agent(self):
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        # Stub all upstream loaders to avoid network/db calls
        agent._load_trades          = lambda: []
        agent._load_recommendations = lambda: []
        agent._load_risk_snapshot   = lambda: {}
        agent._load_strategy_snapshot = lambda: {}
        agent._load_decision_snapshot = lambda: {}
        agent._load_timeline_events   = lambda: []
        return agent

    def test_execute_returns_dict(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertIsInstance(result, dict)

    def test_execute_has_safety_flags(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertFalse(result["auto_model_updates"])
        self.assertFalse(result["auto_strategy_tuning"])

    def test_execute_advisory_only(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertTrue(result["advisory_only"])
        self.assertTrue(result["read_only"])

    def test_execute_has_required_fields(self):
        agent = self._make_agent()
        result = agent.execute()
        required = ["agent_id", "agent_name", "version", "status", "metrics",
                    "insights", "patterns", "learning_health", "generated_at"]
        for key in required:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_agent_id_correct(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertEqual(result["agent_id"], "learning_agent")

    def test_health_healthy_on_good_metrics(self):
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        metrics = {"strategy_win_rate": 55, "recommendation_accuracy": 60, "confidence_calibration": 0.7}
        health = agent._compute_health(metrics)
        self.assertEqual(health, "HEALTHY")

    def test_health_degraded_on_low_metrics(self):
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        metrics = {"strategy_win_rate": 38, "recommendation_accuracy": 20, "confidence_calibration": 0.4}
        health = agent._compute_health(metrics)
        self.assertEqual(health, "DEGRADED")

    def test_health_needs_review_on_very_low(self):
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        metrics = {"strategy_win_rate": 20, "recommendation_accuracy": 20, "confidence_calibration": 0.2}
        health = agent._compute_health(metrics)
        self.assertEqual(health, "NEEDS_REVIEW")

    def test_get_status_returns_correct_agent_id(self):
        agent = self._make_agent()
        status = agent.get_status()
        self.assertEqual(status["agent_id"], "learning_agent")
        self.assertFalse(status["auto_model_updates"])
        self.assertFalse(status["auto_strategy_tuning"])

    def test_latency_field_present(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertIn("learning_latency_ms", result)
        self.assertGreaterEqual(result["learning_latency_ms"], 0)


# =============================================================================
# 5. Knowledge Engine — build_knowledge_index
# =============================================================================
class TestKnowledgeIndex(unittest.TestCase):

    def _closed_trade(self):
        return {"status": "CLOSED", "pnl_pct": 2.0, "symbol": "RELIANCE",
                "sector": "ENERGY", "strategy": "MOMENTUM", "id": "T1"}

    def test_indexes_closed_trades(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        entries = build_knowledge_index(
            [self._closed_trade()], [], {}, [], {}, []
        )
        trade_entries = [e for e in entries if e["type"] == "TRADE"]
        self.assertEqual(len(trade_entries), 1)

    def test_skips_open_trades(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        open_trade = {**self._closed_trade(), "status": "OPEN"}
        entries = build_knowledge_index([open_trade], [], {}, [], {}, [])
        trade_entries = [e for e in entries if e["type"] == "TRADE"]
        self.assertEqual(len(trade_entries), 0)

    def test_indexes_recommendations(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        recs = [{"symbol": "TCS", "decision_type": "BUY_CANDIDATE",
                 "confidence": 0.8, "outcome": "TARGET_HIT", "recommendation_id": "R1"}]
        entries = build_knowledge_index([], recs, {}, [], {}, [])
        rec_entries = [e for e in entries if e["type"] == "RECOMMENDATION"]
        self.assertEqual(len(rec_entries), 1)

    def test_entry_has_required_fields(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        entries = build_knowledge_index([self._closed_trade()], [], {}, [], {}, [])
        e = entries[0]
        for field in ["entry_id", "type", "label", "title", "content", "tags", "timestamp"]:
            self.assertIn(field, e)

    def test_timeline_events_indexed(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        events = [{"event_type": "TRADE_EXECUTED", "title": "Buy INFY", "event_id": "E1"}]
        entries = build_knowledge_index([], [], {}, events, {}, [])
        ev_entries = [e for e in entries if e["type"] == "TIMELINE_EVENT"]
        self.assertEqual(len(ev_entries), 1)

    def test_annotations_indexed(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        anns = [{"note": "Interesting breakout", "symbol": "HDFC", "id": "A1"}]
        entries = build_knowledge_index([], [], {}, [], {}, anns)
        ann_entries = [e for e in entries if e["type"] == "ANNOTATION"]
        self.assertEqual(len(ann_entries), 1)

    def test_empty_input_returns_empty_list(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        entries = build_knowledge_index([], [], {}, [], {}, [])
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 0)

    def test_entry_ids_are_unique(self):
        from knowledge_agent.knowledge_engine import build_knowledge_index
        trades = [
            {"status": "CLOSED", "pnl_pct": 1.0, "symbol": "A", "id": "T1"},
            {"status": "CLOSED", "pnl_pct": 2.0, "symbol": "B", "id": "T2"},
        ]
        entries = build_knowledge_index(trades, [], {}, [], {}, [])
        ids = [e["entry_id"] for e in entries]
        self.assertEqual(len(ids), len(set(ids)))


# =============================================================================
# 6. Knowledge Engine — search_knowledge
# =============================================================================
class TestKnowledgeSearch(unittest.TestCase):

    def _make_entries(self):
        return [
            {"entry_id": "1", "type": "TRADE", "label": "WIN",
             "title": "Win HDFC Banking", "content": "win trade banking breakout",
             "tags": ["BANKING", "MOMENTUM", "WIN"], "timestamp": "2024-01-01T10:00:00Z",
             "symbol": "HDFC", "confidence": 0.9},
            {"entry_id": "2", "type": "TRADE", "label": "LOSS",
             "title": "Loss IT sector", "content": "loss trade it sector",
             "tags": ["IT", "MEAN_REVERT", "LOSS"], "timestamp": "2024-01-01T10:05:00Z",
             "symbol": "INFY", "confidence": 0.6},
            {"entry_id": "3", "type": "RECOMMENDATION", "label": "BUY_CANDIDATE",
             "title": "Rec RELIANCE high confidence", "content": "recommendation buy candidate reliance confidence",
             "tags": ["BUY_CANDIDATE", "RECOMMENDATION"], "timestamp": "2024-01-01T10:10:00Z",
             "symbol": "RELIANCE", "confidence": 0.85},
        ]

    def test_search_returns_list(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("banking", self._make_entries())
        self.assertIsInstance(results, list)

    def test_search_banking_returns_hdfc(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("banking breakout", self._make_entries())
        ids = [r["entry_id"] for r in results]
        self.assertIn("1", ids)

    def test_search_confidence_filter(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        # Query filters above 80%
        results = search_knowledge("recommendation above 80%", self._make_entries())
        for r in results:
            self.assertGreaterEqual(r.get("confidence", 0), 0.80)

    def test_search_relevance_score_present(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("banking", self._make_entries())
        for r in results:
            self.assertIn("relevance_score", r)

    def test_search_results_sorted_by_relevance(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("banking", self._make_entries())
        scores = [r["relevance_score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_search_empty_query_returns_empty(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("", self._make_entries())
        self.assertEqual(results, [])

    def test_search_limit_respected(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        many = self._make_entries() * 20
        results = search_knowledge("trade", many, limit=5)
        self.assertLessEqual(len(results), 5)

    def test_search_symbol_boost(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("hdfc", self._make_entries())
        if results:
            self.assertEqual(results[0]["symbol"], "HDFC")

    def test_search_no_match_returns_empty(self):
        from knowledge_agent.knowledge_engine import search_knowledge
        results = search_knowledge("zzznomatch", self._make_entries())
        self.assertEqual(results, [])


# =============================================================================
# 7. Knowledge Engine — build_trade_memory
# =============================================================================
class TestTradeMemory(unittest.TestCase):

    def _make_closed_trade(self):
        return {
            "status": "CLOSED", "symbol": "SBIN", "sector": "BANKING",
            "strategy": "MOMENTUM", "pnl_pct": 2.5,
            "entry_price": 650.0, "exit_price": 666.25,
            "entry_time": "2024-01-01T09:20:00Z",
            "exit_time":  "2024-01-01T11:00:00Z",
            "risk_pct": 1.0, "stop_loss": 643.5,
        }

    def test_returns_list(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        result = build_trade_memory([self._make_closed_trade()], [], {})
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_skips_open_trades(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        open_t = {**self._make_closed_trade(), "status": "OPEN"}
        result = build_trade_memory([open_t], [], {})
        self.assertEqual(len(result), 0)

    def test_memory_has_required_fields(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        result = build_trade_memory([self._make_closed_trade()], [], {})
        mem = result[0]
        for field in ["memory_id", "symbol", "outcome", "pnl_pct",
                      "lessons_learned", "timestamp", "strategy", "sector"]:
            self.assertIn(field, mem, f"Missing: {field}")

    def test_win_outcome_for_positive_pnl(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        result = build_trade_memory([self._make_closed_trade()], [], {})
        self.assertEqual(result[0]["outcome"], "WIN")

    def test_loss_outcome_for_negative_pnl(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        trade = {**self._make_closed_trade(), "pnl_pct": -1.5}
        result = build_trade_memory([trade], [], {})
        self.assertEqual(result[0]["outcome"], "LOSS")

    def test_lessons_learned_is_list(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        result = build_trade_memory([self._make_closed_trade()], [], {})
        self.assertIsInstance(result[0]["lessons_learned"], list)
        self.assertGreater(len(result[0]["lessons_learned"]), 0)

    def test_recommendation_matched_by_symbol(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        rec = {"symbol": "SBIN", "decision_type": "BUY_CANDIDATE", "confidence": 0.82}
        result = build_trade_memory([self._make_closed_trade()], [rec], {})
        self.assertEqual(result[0]["decision_type"], "BUY_CANDIDATE")
        self.assertAlmostEqual(result[0]["decision_confidence"], 0.82)

    def test_empty_input_returns_empty(self):
        from knowledge_agent.knowledge_engine import build_trade_memory
        result = build_trade_memory([], [], {})
        self.assertEqual(result, [])


# =============================================================================
# 8. Knowledge Engine — generate_lessons_library
# =============================================================================
class TestLessonsLibrary(unittest.TestCase):

    def _make_memory(self, outcome="WIN"):
        return {
            "memory_id": "m1", "symbol": "TCS", "outcome": outcome,
            "strategy": "MOMENTUM", "sector": "IT", "pnl_pct": 2.0 if outcome == "WIN" else -1.0,
            "lessons_learned": ["Test lesson."], "timestamp": "2024-01-01T10:00:00Z",
            "decision_confidence": 0.75,
        }

    def _make_metrics(self):
        return {"strategy_win_rate": 55, "confidence_calibration": 0.7,
                "avg_reward_risk": 1.8, "avg_holding_minutes": 80}

    def _make_insights(self):
        return {"most_profitable_sector": "IT", "weakest_sector": "PHARMA",
                "common_rejection_reasons": [], "most_frequent_risk_warnings": [],
                "recurring_patterns": ["Gap-up detected in 3 sessions."]}

    def test_returns_required_categories(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        result = generate_lessons_library([self._make_memory()], self._make_metrics(), self._make_insights())
        for key in ["what_worked", "what_failed", "what_to_review", "what_to_monitor", "open_questions"]:
            self.assertIn(key, result, f"Missing: {key}")

    def test_what_worked_non_empty(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        result = generate_lessons_library([self._make_memory("WIN")], self._make_metrics(), self._make_insights())
        self.assertGreater(len(result["what_worked"]), 0)

    def test_what_failed_non_empty(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        result = generate_lessons_library([self._make_memory("LOSS")], self._make_metrics(), self._make_insights())
        self.assertGreater(len(result["what_failed"]), 0)

    def test_open_questions_always_present(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        result = generate_lessons_library([], {}, {})
        self.assertGreater(len(result["open_questions"]), 0)

    def test_low_win_rate_triggers_review(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        metrics = {**self._make_metrics(), "strategy_win_rate": 30}
        result = generate_lessons_library([], metrics, self._make_insights())
        reviews = " ".join(result["what_to_review"])
        self.assertIn("Win rate", reviews)

    def test_patterns_appear_in_monitor(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        result = generate_lessons_library([], self._make_metrics(), self._make_insights())
        monitors = " ".join(result["what_to_monitor"])
        self.assertIn("Gap-up", monitors)

    def test_generated_at_present(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        result = generate_lessons_library([], {}, {})
        self.assertIn("generated_at", result)

    def test_trades_analysed_field(self):
        from knowledge_agent.knowledge_engine import generate_lessons_library
        memories = [self._make_memory("WIN"), self._make_memory("LOSS")]
        result = generate_lessons_library(memories, self._make_metrics(), self._make_insights())
        self.assertEqual(result["trades_analysed"], 2)


# =============================================================================
# 9. Knowledge Agent (agent.py)
# =============================================================================
class TestKnowledgeAgent(unittest.TestCase):

    def _make_agent(self):
        from knowledge_agent.agent import KnowledgeAgent
        agent = KnowledgeAgent()
        agent._load_trades             = lambda: []
        agent._load_recommendations    = lambda: []
        agent._load_research_snapshot  = lambda: {}
        agent._load_timeline_events    = lambda: []
        agent._load_decision_snapshot  = lambda: {}
        agent._load_learning_snapshot  = lambda: {}
        agent._load_annotations        = lambda: []
        return agent

    def test_execute_returns_dict(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertIsInstance(result, dict)

    def test_execute_has_required_fields(self):
        agent = self._make_agent()
        result = agent.execute()
        for field in ["agent_id", "knowledge_base_size", "trades_learned",
                      "trade_memory", "lessons_library", "patterns",
                      "indexing_latency_ms", "generated_at"]:
            self.assertIn(field, result, f"Missing: {field}")

    def test_advisory_only_flag(self):
        agent = self._make_agent()
        result = agent.execute()
        self.assertTrue(result["advisory_only"])
        self.assertTrue(result["read_only"])

    def test_agent_id_correct(self):
        agent = self._make_agent()
        self.assertEqual(agent.execute()["agent_id"], "knowledge_agent")

    def test_search_returns_results(self):
        from knowledge_agent.agent import KnowledgeAgent
        agent = KnowledgeAgent()
        agent._load_trades = lambda: [
            {"status": "CLOSED", "pnl_pct": 2.0, "symbol": "HDFC",
             "sector": "BANKING", "strategy": "MOMENTUM", "id": "T1"}
        ]
        agent._load_recommendations   = lambda: []
        agent._load_research_snapshot = lambda: {}
        agent._load_timeline_events   = lambda: []
        agent._load_decision_snapshot = lambda: {}
        agent._load_annotations       = lambda: []
        result = agent.search("banking")
        self.assertIn("results", result)
        self.assertIn("result_count", result)
        self.assertIn("advisory_only", result)

    def test_search_latency_present(self):
        agent = self._make_agent()
        result = agent.search("banking")
        self.assertIn("search_latency_ms", result)

    def test_get_status_returns_correct_agent_id(self):
        agent = self._make_agent()
        status = agent.get_status()
        self.assertEqual(status["agent_id"], "knowledge_agent")
        self.assertTrue(status["advisory_only"])

    def test_knowledge_base_size_with_trades(self):
        from knowledge_agent.agent import KnowledgeAgent
        agent = KnowledgeAgent()
        agent._load_trades = lambda: [
            {"status": "CLOSED", "pnl_pct": 1.0, "symbol": "SBIN", "id": "T1"},
            {"status": "CLOSED", "pnl_pct": 2.0, "symbol": "HDFC", "id": "T2"},
        ]
        agent._load_recommendations   = lambda: []
        agent._load_research_snapshot = lambda: {}
        agent._load_timeline_events   = lambda: []
        agent._load_decision_snapshot = lambda: {}
        agent._load_learning_snapshot = lambda: {}
        agent._load_annotations       = lambda: []
        result = agent.execute()
        self.assertEqual(result["knowledge_base_size"], 2)


# =============================================================================
# 10. Learning Agent shared_services
# =============================================================================
class TestLearningSharedServices(unittest.TestCase):

    def test_get_learning_status_disabled(self):
        import os
        os.environ["LEARNING_AGENT_ENABLED"] = "false"
        from learning_agent import shared_services as svc
        result = svc.get_learning_status()
        self.assertEqual(result["status"], "DISABLED")
        self.assertFalse(result["available"])
        os.environ["LEARNING_AGENT_ENABLED"] = "true"

    def test_get_learning_metrics_shape_enabled(self):
        import os
        os.environ["LEARNING_AGENT_ENABLED"] = "true"
        from learning_agent import shared_services as svc
        # Patch the agent class where it's imported (inside the function)
        with patch("learning_agent.agent.LearningAgent") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = {
                "available": True, "metrics": {"strategy_win_rate": 55},
                "learning_health": "HEALTHY", "generated_at": "2024-01-01T10:00:00Z",
                "auto_model_updates": False, "auto_strategy_tuning": False,
            }
            result = svc.get_learning_snapshot()
        self.assertIn("metrics", result)

    def test_safety_flags_in_disabled_response(self):
        import os
        os.environ["LEARNING_AGENT_ENABLED"] = "false"
        from learning_agent import shared_services as svc
        result = svc.get_learning_snapshot()
        self.assertFalse(result["auto_model_updates"])
        self.assertFalse(result["auto_strategy_tuning"])
        os.environ["LEARNING_AGENT_ENABLED"] = "true"


# =============================================================================
# 11. Knowledge Agent shared_services
# =============================================================================
class TestKnowledgeSharedServices(unittest.TestCase):

    def test_get_knowledge_status_disabled(self):
        import os
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "false"
        from knowledge_agent import shared_services as svc
        result = svc.get_knowledge_status()
        self.assertEqual(result["status"], "DISABLED")
        self.assertFalse(result["available"])
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "true"

    def test_search_empty_query(self):
        import os
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "true"
        from knowledge_agent import shared_services as svc
        result = svc.get_knowledge_search("")
        self.assertEqual(result["result_count"], 0)
        self.assertIn("message", result)

    def test_search_disabled_returns_disabled(self):
        import os
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "false"
        from knowledge_agent import shared_services as svc
        result = svc.get_knowledge_search("banking")
        self.assertEqual(result["status"], "DISABLED")
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "true"

    def test_advisory_only_in_disabled_response(self):
        import os
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "false"
        from knowledge_agent import shared_services as svc
        result = svc.get_knowledge_snapshot()
        self.assertTrue(result["advisory_only"])
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "true"


# =============================================================================
# 12. Learning Layer — aggregation (shared_services)
# =============================================================================
class TestLearningLayerAggregation(unittest.TestCase):

    def _stub_learning(self):
        return {
            "available": True, "learning_health": "HEALTHY",
            "learning_latency_ms": 120.0, "trades_analysed": 5,
            "recommendations_analysed": 10, "patterns_identified": 2,
            "top_insight": "MOMENTUM",
            "metrics": {
                "recommendation_accuracy": 65.0, "strategy_win_rate": 55.0,
                "confidence_calibration": 0.72,
                "trades_analysed": 5,
            },
            "insights": {
                "best_strategy_today": "MOMENTUM", "worst_strategy_today": "MEAN_REVERT",
                "most_profitable_sector": "BANKING", "weakest_sector": "IT",
            },
            "patterns": [
                {"pattern_id": "GAP_BREAKOUT", "name": "Gap-Up Breakout"},
            ],
            "generated_at": "2024-01-01T10:00:00Z",
            "status": "ACTIVE",
        }

    def _stub_knowledge(self):
        return {
            "available": True, "knowledge_base_size": 25,
            "trades_learned": 5, "patterns_identified": 2,
            "indexing_latency_ms": 30.0,
            "lessons_library": {
                "what_worked": ["MOMENTUM delivered 55% win rate."],
                "what_failed": ["MEAN_REVERT struggled in current regime."],
                "what_to_review": ["Confidence calibration below target."],
                "what_to_monitor": ["Gap-up pattern active."],
                "open_questions": ["Why are short trades underperforming?"],
                "generated_at": "2024-01-01T10:00:00Z",
            },
            "patterns": [
                {"pattern_id": "GAP_BREAKOUT", "name": "Gap-Up Breakout"},
            ],
            "trade_memory": [],
            "generated_at": "2024-01-01T10:00:00Z",
            "status": "ACTIVE",
        }

    def test_get_learning_summary_shape(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_summary()
        required = [
            "trades_learned_today", "recommendation_accuracy", "strategy_win_rate",
            "learning_health", "knowledge_base_size", "top_lessons", "generated_at",
        ]
        for key in required:
            self.assertIn(key, result, f"Missing: {key}")

    def test_get_learning_summary_advisory_flags(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_summary()
        self.assertTrue(result["advisory_only"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["auto_model_updates"])
        self.assertFalse(result["auto_strategy_tuning"])

    def test_get_learning_summary_kpis(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_summary()
        self.assertEqual(result["trades_learned_today"], 5)
        self.assertEqual(result["knowledge_base_size"], 25)
        self.assertEqual(result["recommendation_accuracy"], 65.0)

    def test_get_learning_timeline_shape(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_timeline()
        self.assertIn("events", result)
        self.assertIn("event_count", result)
        self.assertIn("event_types", result)
        self.assertIsInstance(result["events"], list)

    def test_timeline_has_learning_completed_event(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_timeline()
        types = [e["event_type"] for e in result["events"]]
        self.assertIn("LEARNING_COMPLETED", types)

    def test_timeline_has_knowledge_indexed_event(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_timeline()
        types = [e["event_type"] for e in result["events"]]
        self.assertIn("KNOWLEDGE_INDEXED", types)

    def test_timeline_events_have_required_fields(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_timeline()
        for ev in result["events"]:
            for field in ["event_id", "event_type", "title", "description", "source", "timestamp"]:
                self.assertIn(field, ev, f"Missing event field: {field}")

    def test_timeline_sorted_descending(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_timeline()
        timestamps = [e["timestamp"] for e in result["events"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_get_learning_performance_shape(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_performance()
        self.assertIn("performance", result)
        self.assertIn("scalability", result)
        self.assertIn("health", result)

    def test_performance_latency_fields(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_performance()
        perf = result["performance"]
        for field in ["learning_latency_ms", "knowledge_indexing_latency_ms",
                      "search_latency_ms", "pattern_detection_ms"]:
            self.assertIn(field, perf)

    def test_scalability_fields(self):
        from learning_layer import shared_services as svc
        with patch("learning_layer.shared_services._get_learning", return_value=self._stub_learning()), \
             patch("learning_layer.shared_services._get_knowledge", return_value=self._stub_knowledge()):
            result = svc.get_learning_performance()
        sc = result["scalability"]
        for field in ["trades_indexed", "knowledge_records", "patterns_stored"]:
            self.assertIn(field, sc)


# =============================================================================
# 13. Feature Flags
# =============================================================================
class TestFeatureFlags(unittest.TestCase):

    def test_learning_agent_disabled_flag(self):
        import os
        os.environ["LEARNING_AGENT_ENABLED"] = "false"
        from learning_agent import shared_services as svc
        result = svc.get_learning_snapshot()
        self.assertEqual(result["status"], "DISABLED")
        os.environ["LEARNING_AGENT_ENABLED"] = "true"

    def test_knowledge_agent_disabled_flag(self):
        import os
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "false"
        from knowledge_agent import shared_services as svc
        result = svc.get_knowledge_snapshot()
        self.assertEqual(result["status"], "DISABLED")
        os.environ["KNOWLEDGE_AGENT_ENABLED"] = "true"

    def test_auto_model_updates_always_false(self):
        """AUTO_MODEL_UPDATES must never be true — safety constraint."""
        import os
        # Even if env var is set to true, the agent hardcodes it false
        os.environ["AUTO_MODEL_UPDATES"] = "true"
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        agent._load_trades            = lambda: []
        agent._load_recommendations   = lambda: []
        agent._load_risk_snapshot     = lambda: {}
        agent._load_strategy_snapshot = lambda: {}
        agent._load_decision_snapshot = lambda: {}
        agent._load_timeline_events   = lambda: []
        result = agent.execute()
        # Hardcoded in agent — must always be False regardless of env var
        self.assertFalse(result["auto_model_updates"])
        os.environ.pop("AUTO_MODEL_UPDATES", None)

    def test_auto_strategy_tuning_always_false(self):
        """AUTO_STRATEGY_TUNING must never be true — safety constraint."""
        import os
        os.environ["AUTO_STRATEGY_TUNING"] = "true"
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        agent._load_trades            = lambda: []
        agent._load_recommendations   = lambda: []
        agent._load_risk_snapshot     = lambda: {}
        agent._load_strategy_snapshot = lambda: {}
        agent._load_decision_snapshot = lambda: {}
        agent._load_timeline_events   = lambda: []
        result = agent.execute()
        self.assertFalse(result["auto_strategy_tuning"])
        os.environ.pop("AUTO_STRATEGY_TUNING", None)

    def test_config_flags_defined(self):
        from agent_framework.config import (
            LEARNING_AGENT_ENABLED, KNOWLEDGE_AGENT_ENABLED,
            AUTO_MODEL_UPDATES, AUTO_STRATEGY_TUNING,
        )
        self.assertEqual(LEARNING_AGENT_ENABLED,  "LEARNING_AGENT_ENABLED")
        self.assertEqual(KNOWLEDGE_AGENT_ENABLED, "KNOWLEDGE_AGENT_ENABLED")
        self.assertEqual(AUTO_MODEL_UPDATES,      "AUTO_MODEL_UPDATES")
        self.assertEqual(AUTO_STRATEGY_TUNING,    "AUTO_STRATEGY_TUNING")

    def test_learning_enabled_by_default(self):
        import os
        os.environ.pop("LEARNING_AGENT_ENABLED", None)
        from learning_agent import shared_services as svc
        # Default is enabled — should not return DISABLED
        # (may return UNAVAILABLE if upstream fails, but not DISABLED)
        with patch("learning_agent.agent.LearningAgent") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = {
                "available": True, "metrics": {}, "insights": {}, "patterns": [],
                "learning_health": "HEALTHY", "generated_at": "now",
                "auto_model_updates": False, "auto_strategy_tuning": False,
            }
            result = svc.get_learning_snapshot()
        self.assertNotEqual(result.get("status"), "DISABLED")

    def test_knowledge_enabled_by_default(self):
        import os
        os.environ.pop("KNOWLEDGE_AGENT_ENABLED", None)
        from knowledge_agent import shared_services as svc
        with patch("knowledge_agent.agent.KnowledgeAgent") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = {
                "available": True, "knowledge_base_size": 0,
                "trades_learned": 0, "patterns_identified": 0,
                "trade_memory": [], "lessons_library": {},
                "patterns": [], "indexing_latency_ms": 10,
                "generated_at": "now",
            }
            result = svc.get_knowledge_snapshot()
        self.assertNotEqual(result.get("status"), "DISABLED")


# =============================================================================
# 14. Supervisor Integration — agent IDs
# =============================================================================
class TestSupervisorIntegration(unittest.TestCase):

    def test_learning_agent_has_valid_id(self):
        from learning_agent.agent import LearningAgent
        self.assertEqual(LearningAgent.AGENT_ID, "learning_agent")

    def test_knowledge_agent_has_valid_id(self):
        from knowledge_agent.agent import KnowledgeAgent
        self.assertEqual(KnowledgeAgent.AGENT_ID, "knowledge_agent")

    def test_learning_agent_version(self):
        from learning_agent.agent import LearningAgent
        self.assertTrue(LearningAgent.VERSION.startswith("10D"))

    def test_knowledge_agent_version(self):
        from knowledge_agent.agent import KnowledgeAgent
        self.assertTrue(KnowledgeAgent.VERSION.startswith("10D"))

    def test_learning_status_has_started_at(self):
        from learning_agent.agent import LearningAgent
        agent = LearningAgent()
        status = agent.get_status()
        self.assertIn("started_at", status)
        self.assertIn("last_heartbeat", status)

    def test_knowledge_status_has_started_at(self):
        from knowledge_agent.agent import KnowledgeAgent
        agent = KnowledgeAgent()
        status = agent.get_status()
        self.assertIn("started_at", status)
        self.assertIn("last_heartbeat", status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
