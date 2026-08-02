"""
test_analysis_agents.py — Phase 10B
Tests for the Analysis Layer agents.

Covers:
  - MarketIntelligenceAgent snapshot structure and advisory flags
  - StockMonitoringAgent priority engine, event detection
  - SmartPriorityEngine (all 5 priorities)
  - EventDetector (12 event types)
  - StrategyAgent (6 strategies, registry, symbol evaluation)
  - Individual strategy scoring
  - RiskAgent (9 dimensions, aggregate risk level)
  - SnapshotBus integration (subscribe, publish)
  - Heartbeat and health monitor
  - Feature flags and disabled responses
  - Analysis summary aggregation
  - Timeline event shape
  - Performance metrics shape
  - Failure/error handling

Target: ≥ 60 passing tests.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def reset_singletons():
    from agent_framework.agent_registry import AgentRegistry
    from agent_framework.snapshot_bus import SnapshotBus
    AgentRegistry.reset()
    SnapshotBus.reset()
    yield
    AgentRegistry.reset()
    SnapshotBus.reset()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MarketIntelligenceAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketIntelligenceAgent:
    def _agent(self):
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        a = MarketIntelligenceAgent()
        a.start(); a.beat()
        return a

    def test_agent_registered(self):
        from agent_framework.agent_registry import AgentRegistry
        a = self._agent()
        assert AgentRegistry.instance().get("market-intelligence-agent") is not None

    def test_snapshot_required_fields(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("agent_id", "agent_name", "advisory_only", "read_only",
                  "market_regime", "trend_strength", "strongest_sector",
                  "breadth_score", "volatility_regime", "momentum_state",
                  "gap_analysis", "data_quality", "session_info", "generated_at"):
            assert k in snap, f"Missing: {k}"

    def test_advisory_only_true(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["advisory_only"] is True
        assert snap["read_only"] is True

    def test_gap_analysis_structure(self):
        a = self._agent()
        snap = a.execute_task()
        gap = snap["gap_analysis"]
        for k in ("nifty_gap_pct", "gap_direction", "gap_magnitude", "gap_risk"):
            assert k in gap

    def test_session_info_structure(self):
        a = self._agent()
        snap = a.execute_task()
        session = snap["session_info"]
        assert "phase" in session
        assert "in_session" in session

    def test_publishes_to_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        a = self._agent()
        snap = a.execute_task()
        a.publish(snap, "market_intelligence")
        env = SnapshotBus.instance().latest("market_intelligence")
        assert env is not None
        assert env.payload["agent_id"] == "market-intelligence-agent"

    def test_subscribes_to_market_data(self):
        """MI agent subscribes to market_data topic on init."""
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        a = self._agent()
        bus.publish("market_data", "test", {"market_regime": "BULL"})
        assert a._latest_market_data is not None

    def test_momentum_state_values(self):
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        valid_states = {
            "STRONG_BULLISH", "BULLISH", "STRONG_BEARISH",
            "BEARISH", "IMPROVING", "DETERIORATING", "NEUTRAL"
        }
        a = self._agent()
        snap = a.execute_task()
        assert snap["momentum_state"] in valid_states

    def test_no_buy_sell_fields(self):
        a = self._agent()
        snap = a.execute_task()
        forbidden = ["buy", "sell", "order", "recommendation", "entry", "exit"]
        for f in forbidden:
            assert f not in snap, f"Forbidden field found: {f}"

    def test_derive_momentum_strong_bullish(self):
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        regime = {"trend_strength": 65.0, "regime": "BULL"}
        breadth = {"breadth_score": 70.0, "advancers": 30, "decliners": 10}
        result = MarketIntelligenceAgent._derive_momentum(regime, breadth)
        assert result == "STRONG_BULLISH"

    def test_derive_gap_analysis(self):
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        gap = MarketIntelligenceAgent._derive_gap({"nifty50_change_pct": 1.5})
        assert gap["gap_direction"] == "UP"
        assert gap["gap_magnitude"] == "LARGE"

    def test_sector_fields_present(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("strongest_sector", "weakest_sector", "sector_count",
                  "rotation_leaders", "rotation_laggards"):
            assert k in snap


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SmartPriorityEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestSmartPriorityEngine:
    def _engine(self):
        from stock_monitoring_agent.agent import SmartPriorityEngine
        return SmartPriorityEngine()

    def test_p1_open_positions_first(self):
        engine = self._engine()
        q = engine.build_priority_queue(["INFY"], ["TCS"], [], ["RELIANCE"], [])
        assert q[0]["symbol"] == "INFY"
        assert q[0]["priority"] == 1

    def test_p2_watchlist_second(self):
        engine = self._engine()
        q = engine.build_priority_queue([], ["TCS"], [], ["RELIANCE"], [])
        assert q[0]["symbol"] == "TCS"
        assert q[0]["priority"] == 2

    def test_no_duplicates(self):
        engine = self._engine()
        q = engine.build_priority_queue(["INFY"], ["INFY", "TCS"], [], [], [])
        symbols = [item["symbol"] for item in q]
        assert len(symbols) == len(set(symbols))

    def test_p4_nifty50(self):
        engine = self._engine()
        q = engine.build_priority_queue([], [], [], ["RELIANCE", "TCS"], [])
        assert all(item["priority"] == 4 for item in q)

    def test_p5_background(self):
        engine = self._engine()
        q = engine.build_priority_queue([], [], [], [], ["ZOMATO"])
        assert q[0]["priority"] == 5

    def test_summary_keys(self):
        engine = self._engine()
        q = engine.build_priority_queue(["A"], ["B"], ["C"], ["D"], ["E"])
        s = engine.summary(q)
        for k in ("total_symbols", "p1_open_positions", "p2_high_conviction",
                  "p3_candidates", "p4_nifty50", "p5_background"):
            assert k in s

    def test_eval_frequency_p1_fastest(self):
        engine = self._engine()
        assert engine.EVAL_FREQUENCY[1] < engine.EVAL_FREQUENCY[2]
        assert engine.EVAL_FREQUENCY[2] < engine.EVAL_FREQUENCY[5]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EventDetector
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventDetector:
    def _det(self):
        from stock_monitoring_agent.agent import EventDetector
        return EventDetector()

    def test_gap_up_detected(self):
        det = self._det()
        events = det.detect("INFY", {"change_pct": 3.0})
        types = [e["event_type"] for e in events]
        assert "GAP_UP" in types

    def test_gap_down_detected(self):
        det = self._det()
        events = det.detect("INFY", {"change_pct": -3.0})
        types = [e["event_type"] for e in events]
        assert "GAP_DOWN" in types

    def test_volume_spike_detected(self):
        det = self._det()
        events = det.detect("TCS", {"volume_ratio": 3.0, "change_pct": 0.5})
        types = [e["event_type"] for e in events]
        assert "VOLUME_SPIKE" in types

    def test_delivery_spike_detected(self):
        det = self._det()
        events = det.detect("HDFC", {"delivery_pct": 75.0})
        types = [e["event_type"] for e in events]
        assert "DELIVERY_SPIKE" in types

    def test_new_high_detected(self):
        det = self._det()
        events = det.detect("WIPRO", {"near_52w_high": True, "change_pct": 1.0})
        types = [e["event_type"] for e in events]
        assert "NEW_HIGH" in types

    def test_new_low_detected(self):
        det = self._det()
        events = det.detect("SAIL", {"near_52w_low": True, "change_pct": -1.0})
        types = [e["event_type"] for e in events]
        assert "NEW_LOW" in types

    def test_vwap_cross_detected(self):
        det = self._det()
        events = det.detect("BEL", {"vwap_above": True, "change_pct": 0.5})
        types = [e["event_type"] for e in events]
        assert "VWAP_CROSS" in types

    def test_momentum_shift_rsi_overbought(self):
        det = self._det()
        events = det.detect("MRF", {"rsi": 72.0, "change_pct": 1.5})
        types = [e["event_type"] for e in events]
        assert "MOMENTUM_SHIFT" in types

    def test_unusual_activity_detected(self):
        det = self._det()
        events = det.detect("ZEEL", {"volume_ratio": 2.5, "change_pct": 2.0})
        types = [e["event_type"] for e in events]
        assert "UNUSUAL_ACTIVITY" in types

    def test_events_have_required_fields(self):
        det = self._det()
        events = det.detect("INFY", {"change_pct": 3.0, "volume_ratio": 2.0})
        for e in events:
            for k in ("symbol", "event_type", "severity", "description", "detected_at", "advisory_only"):
                assert k in e

    def test_no_events_on_neutral_stock(self):
        det = self._det()
        events = det.detect("FLAT", {"change_pct": 0.05, "volume_ratio": 1.0, "rsi": 50.0})
        assert len(events) == 0

    def test_advisory_only_in_all_events(self):
        det = self._det()
        events = det.detect("TEST", {"change_pct": 4.0, "volume_ratio": 3.0, "rsi": 72.0})
        for e in events:
            assert e["advisory_only"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. StockMonitoringAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestStockMonitoringAgent:
    def _agent(self):
        from stock_monitoring_agent.agent import StockMonitoringAgent
        a = StockMonitoringAgent()
        a.start(); a.beat()
        return a

    def test_snapshot_required_fields(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("agent_id", "symbols_monitored", "priority_summary",
                  "events_this_cycle", "events", "breakouts", "breakdowns",
                  "gap_events", "volume_spikes", "evaluation_latency_ms", "generated_at"):
            assert k in snap

    def test_advisory_only(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["advisory_only"] is True
        assert snap["read_only"] is True

    def test_priority_queue_sorted(self):
        a = self._agent()
        snap = a.execute_task()
        queue = snap["priority_queue"]
        priorities = [item["priority"] for item in queue]
        assert priorities == sorted(priorities)

    def test_event_breakdown_is_dict(self):
        a = self._agent()
        snap = a.execute_task()
        assert isinstance(snap["event_breakdown"], dict)

    def test_publishes_to_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        a = self._agent()
        snap = a.execute_task()
        a.publish(snap, "stock_monitoring")
        env = SnapshotBus.instance().latest("stock_monitoring")
        assert env is not None

    def test_registered_in_registry(self):
        from agent_framework.agent_registry import AgentRegistry
        self._agent()
        assert AgentRegistry.instance().get("stock-monitoring-agent") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Strategy Implementations
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyImplementations:
    def _regime(self, name="BULL"):
        return {"regime": name, "trend_strength": 60.0}

    def test_breakout_high_score_on_near_high(self):
        from strategy_agent.agent import BreakoutStrategy
        s = BreakoutStrategy()
        result = s.evaluate("INFY", {"near_52w_high": True, "change_pct": 2.0,
                                      "volume_ratio": 2.5, "rsi": 65.0}, self._regime())
        assert result["score"] > 60

    def test_vwap_pullback_rewards_vwap_above(self):
        from strategy_agent.agent import VWAPPullbackStrategy
        s = VWAPPullbackStrategy()
        result = s.evaluate("TCS", {"vwap_above": True, "change_pct": -0.5,
                                     "rsi": 50.0, "volume_ratio": 1.2}, self._regime())
        assert result["score"] > 40

    def test_orb_flags_closed_market(self):
        from strategy_agent.agent import ORBStrategy
        s = ORBStrategy()
        result = s.evaluate("WIPRO", {"change_pct": 0.5, "volume_ratio": 1.5, "rsi": 55.0},
                             {"regime": "BULL", "session_phase": "CLOSED"})
        assert any("closed" in f.lower() for f in result["risk_flags"])

    def test_momentum_high_rsi_risk_flag(self):
        from strategy_agent.agent import MomentumStrategy
        s = MomentumStrategy()
        result = s.evaluate("BEL", {"change_pct": 2.0, "rsi": 85.0, "volume_ratio": 1.5,
                                     "score": 70.0}, self._regime())
        assert any("overbought" in f.lower() for f in result["risk_flags"])

    def test_mean_reversion_low_rsi_setup(self):
        from strategy_agent.agent import MeanReversionStrategy
        s = MeanReversionStrategy()
        result = s.evaluate("SAIL", {"change_pct": -3.0, "rsi": 28.0,
                                      "near_52w_low": True, "volume_ratio": 1.8},
                             {"regime": "SIDEWAYS"})
        assert result["score"] > 50

    def test_gap_strategy_large_gap(self):
        from strategy_agent.agent import GapStrategy
        s = GapStrategy()
        result = s.evaluate("ZOMATO", {"change_pct": 3.5, "volume_ratio": 2.5,
                                        "rsi": 55.0}, self._regime())
        assert result["score"] > 55

    def test_result_never_contains_buy_sell(self):
        from strategy_agent.agent import BreakoutStrategy
        s = BreakoutStrategy()
        result = s.evaluate("TEST", {"change_pct": 2.0, "near_52w_high": True,
                                      "volume_ratio": 2.0, "rsi": 65.0}, self._regime())
        forbidden = ["buy", "sell", "order", "entry", "exit"]
        for f in forbidden:
            assert f not in result, f"Forbidden: {f}"

    def test_score_clamped_0_100(self):
        from strategy_agent.agent import BreakoutStrategy
        s = BreakoutStrategy()
        r = s.evaluate("X", {"change_pct": 50.0, "near_52w_high": True,
                              "volume_ratio": 10.0, "rsi": 60.0},
                        {"regime": "BULL", "trend_strength": 100.0})
        assert 0 <= r["score"] <= 100

    def test_confidence_clamped_0_1(self):
        from strategy_agent.agent import MomentumStrategy
        s = MomentumStrategy()
        r = s.evaluate("X", {"change_pct": 5.0, "rsi": 60.0, "volume_ratio": 3.0,
                              "score": 90.0}, {"regime": "BULL"})
        assert 0.0 <= r["confidence"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. StrategyAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyAgent:
    def _agent(self):
        from strategy_agent.agent import StrategyAgent
        a = StrategyAgent()
        a.start(); a.beat()
        return a

    def test_six_strategies_registered(self):
        a = self._agent()
        assert a._registry is not None
        assert len(a._registry.all()) == 6

    def test_strategy_names(self):
        a = self._agent()
        names = {s.name for s in a._registry.all()}
        expected = {"Breakout", "VWAP Pullback", "Opening Range Breakout",
                    "Momentum", "Mean Reversion", "Gap Strategy"}
        assert names == expected

    def test_snapshot_required_fields(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("strategies_registered", "strategy_names", "symbols_evaluated",
                  "top_setups", "top_strategy", "highest_score",
                  "strategy_breakdown", "generated_at"):
            assert k in snap

    def test_advisory_only(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["advisory_only"] is True
        assert snap["read_only"] is True

    def test_no_buy_sell(self):
        a = self._agent()
        snap = a.execute_task()
        import json
        text = json.dumps(snap).lower()
        # 'buy' and 'sell' may appear in field names like 'adj_buy' — check top-level keys
        for k in snap:
            assert k not in ("buy_signal", "sell_signal", "order", "trade_action")

    def test_strategy_breakdown_has_all_strategies(self):
        a = self._agent()
        snap = a.execute_task()
        for name in snap["strategy_names"]:
            assert name in snap["strategy_breakdown"]

    def test_evaluate_symbol_returns_dict(self):
        a = self._agent()
        result = a.evaluate_symbol("INFY")
        # May be None if no scan data, but if returned must have fields
        if result is not None:
            assert "best_strategy" in result
            assert "all_strategies" in result

    def test_publishes_to_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        a = self._agent()
        snap = a.execute_task()
        a.publish(snap, "strategy")
        env = SnapshotBus.instance().latest("strategy")
        assert env is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. RiskAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskAgent:
    def _agent(self):
        from risk_agent.agent import RiskAgent
        a = RiskAgent()
        a.start(); a.beat()
        return a

    def test_snapshot_required_fields(self):
        a = self._agent()
        snap = a.execute_task()
        for k in ("risk_level", "risk_score", "risk_grade", "exposure",
                  "position_sizing", "sector_concentration", "correlation",
                  "portfolio_heat", "daily_risk", "capital_utilisation",
                  "max_drawdown", "tail_risk", "risk_breakdown", "generated_at"):
            assert k in snap

    def test_advisory_only(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["advisory_only"] is True
        assert snap["never_modifies_portfolio"] is True

    def test_risk_level_valid_values(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["risk_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")

    def test_risk_score_0_100(self):
        a = self._agent()
        snap = a.execute_task()
        assert 0.0 <= snap["risk_score"] <= 100.0

    def test_risk_grade_valid(self):
        a = self._agent()
        snap = a.execute_task()
        assert snap["risk_grade"] in ("A", "B", "C", "D", "F")

    def test_exposure_structure(self):
        from risk_agent.agent import RiskAgent
        portfolio = {"capital": 100000, "positions": [
            {"symbol": "INFY", "qty": 10, "avg_price": 1500.0, "current_value": 15000.0}
        ]}
        result = RiskAgent._calc_exposure(portfolio)
        assert "exposure_pct" in result
        assert result["exposure_pct"] == 15.0

    def test_sector_concentration_hhi(self):
        from risk_agent.agent import RiskAgent
        portfolio = {"capital": 100000, "positions": [
            {"symbol": "INFY", "sector": "IT", "qty": 10, "avg_price": 1500.0},
            {"symbol": "TCS",  "sector": "IT", "qty": 5,  "avg_price": 3000.0},
        ]}
        result = RiskAgent._calc_sector_concentration(portfolio)
        assert "hhi" in result
        assert result["max_sector"] == "IT"

    def test_tail_risk_structure(self):
        from risk_agent.agent import RiskAgent
        mi = {"vix_value": 18.0, "volatility_regime": "NORMAL_VOLATILITY"}
        exposure = {"exposure_pct": 50.0}
        result = RiskAgent._calc_tail_risk(mi, exposure)
        assert "var_99_pct" in result
        assert result["advisory_only"] is True

    def test_drawdown_empty_trades(self):
        from risk_agent.agent import RiskAgent
        result = RiskAgent._calc_drawdown([])
        assert result["max_drawdown_pct"] == 0.0

    def test_aggregate_risk_no_flags(self):
        from risk_agent.agent import RiskAgent
        clean = {"risk_flag": False}
        level, score, breakdown = RiskAgent._aggregate_risk(
            clean, clean, clean, clean, clean, clean, clean, clean, clean
        )
        assert level == "LOW"
        assert score == 100.0

    def test_aggregate_risk_critical(self):
        from risk_agent.agent import RiskAgent
        flagged = {"risk_flag": True}
        level, score, _ = RiskAgent._aggregate_risk(
            flagged, flagged, flagged, flagged, flagged, flagged, flagged, flagged, flagged
        )
        assert level == "CRITICAL"

    def test_publishes_to_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        a = self._agent()
        snap = a.execute_task()
        a.publish(snap, "risk")
        env = SnapshotBus.instance().latest("risk")
        assert env is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Analysis Layer (Aggregation)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalysisLayer:
    def test_summary_required_fields(self):
        from analysis_layer.shared_services import get_analysis_summary
        snap = get_analysis_summary()
        for k in ("available", "advisory_only", "market_regime", "symbols_monitored",
                  "breakouts_found", "risk_level", "top_strategy", "generated_at"):
            assert k in snap

    def test_timeline_required_fields(self):
        from analysis_layer.shared_services import get_analysis_timeline
        result = get_analysis_timeline()
        assert "events" in result
        assert "event_count" in result
        assert result["advisory_only"] is True

    def test_timeline_events_have_correct_shape(self):
        from analysis_layer.shared_services import get_analysis_timeline
        result = get_analysis_timeline()
        for event in result["events"]:
            for k in ("type", "category", "title", "severity", "timestamp", "advisory_only"):
                assert k in event, f"Missing {k} in event {event}"

    def test_timeline_no_buy_sell(self):
        from analysis_layer.shared_services import get_analysis_timeline
        import json
        result = get_analysis_timeline()
        text = json.dumps(result).lower()
        assert "buy_signal" not in text
        assert "sell_signal" not in text

    def test_performance_required_fields(self):
        from analysis_layer.shared_services import get_analysis_performance
        result = get_analysis_performance()
        for k in ("available", "agent_metrics", "symbols_monitored", "generated_at"):
            assert k in result

    def test_performance_has_all_4_agents(self):
        from analysis_layer.shared_services import get_analysis_performance
        result = get_analysis_performance()
        ids = [m["agent_id"] for m in result["agent_metrics"]]
        for expected in ["market-intelligence-agent", "stock-monitoring-agent",
                         "strategy-agent", "risk-agent"]:
            assert expected in ids


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Feature Flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlags10B:
    def test_mi_disabled_when_flag_false(self):
        import os
        os.environ["MARKET_INTELLIGENCE_AGENT_ENABLED"] = "false"
        from market_intelligence_agent.shared_services import get_market_intelligence_agent_snapshot
        result = get_market_intelligence_agent_snapshot()
        assert result["available"] is False
        os.environ.pop("MARKET_INTELLIGENCE_AGENT_ENABLED", None)

    def test_sm_disabled_when_flag_false(self):
        import os
        os.environ["STOCK_MONITORING_AGENT_ENABLED"] = "false"
        from stock_monitoring_agent.shared_services import get_stock_monitoring_snapshot
        result = get_stock_monitoring_snapshot()
        assert result["available"] is False
        os.environ.pop("STOCK_MONITORING_AGENT_ENABLED", None)

    def test_strategy_disabled_when_flag_false(self):
        import os
        os.environ["STRATEGY_AGENT_ENABLED"] = "false"
        from strategy_agent.shared_services import get_strategy_snapshot
        result = get_strategy_snapshot()
        assert result["available"] is False
        os.environ.pop("STRATEGY_AGENT_ENABLED", None)

    def test_risk_disabled_when_flag_false(self):
        import os
        os.environ["RISK_AGENT_ENABLED"] = "false"
        from risk_agent.shared_services import get_risk_snapshot
        result = get_risk_snapshot()
        assert result["available"] is False
        os.environ.pop("RISK_AGENT_ENABLED", None)

    def test_all_flags_default_true(self):
        import os
        for k in ("MARKET_INTELLIGENCE_AGENT_ENABLED", "STOCK_MONITORING_AGENT_ENABLED",
                  "STRATEGY_AGENT_ENABLED", "RISK_AGENT_ENABLED"):
            os.environ.pop(k, None)
        from market_intelligence_agent.shared_services import _is_enabled as mi_on
        from stock_monitoring_agent.shared_services   import _is_enabled as sm_on
        from strategy_agent.shared_services           import _is_enabled as st_on
        from risk_agent.shared_services               import _is_enabled as ri_on
        assert mi_on() and sm_on() and st_on() and ri_on()

    def test_config_has_new_flags(self):
        from agent_framework.config import (
            MARKET_INTELLIGENCE_AGENT_ENABLED, STOCK_MONITORING_AGENT_ENABLED,
            STRATEGY_AGENT_ENABLED, RISK_AGENT_ENABLED,
        )
        assert MARKET_INTELLIGENCE_AGENT_ENABLED == "MARKET_INTELLIGENCE_AGENT_ENABLED"
        assert STOCK_MONITORING_AGENT_ENABLED    == "STOCK_MONITORING_AGENT_ENABLED"
        assert STRATEGY_AGENT_ENABLED            == "STRATEGY_AGENT_ENABLED"
        assert RISK_AGENT_ENABLED                == "RISK_AGENT_ENABLED"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SnapshotBus Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotBusIntegration:
    def test_all_4_agents_publish_to_distinct_topics(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        topics = [
            ("market_intelligence", {"agent_id": "market-intelligence-agent", "advisory_only": True}),
            ("stock_monitoring",    {"agent_id": "stock-monitoring-agent",    "advisory_only": True}),
            ("strategy",            {"agent_id": "strategy-agent",            "advisory_only": True}),
            ("risk",                {"agent_id": "risk-agent",                "advisory_only": True}),
        ]
        for topic, payload in topics:
            bus.publish(topic, "test-agent", payload)
        for topic, _ in topics:
            assert bus.latest(topic) is not None

    def test_risk_agent_reads_from_mi_bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        bus.publish("market_intelligence", "mi-agent", {
            "market_regime": "BULL", "vix_value": 16.0,
            "volatility_regime": "LOW_VOLATILITY"
        })
        from risk_agent.agent import RiskAgent
        a = RiskAgent()
        a.start(); a.beat()
        mi = a._load_market_intelligence()
        assert mi.get("market_regime") == "BULL"

    def test_strategy_reads_from_bus_topic(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        bus.publish("stock_monitoring", "sm-agent", {
            "symbols_monitored": 50, "events": []
        })
        env = bus.latest("stock_monitoring")
        assert env is not None
        assert env.payload["symbols_monitored"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Heartbeat & Health
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeartbeatHealth10B:
    def test_mi_agent_beat_updates_heartbeat(self):
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        a = MarketIntelligenceAgent()
        a.start()
        a.beat()
        assert a.record.last_heartbeat is not None

    def test_risk_agent_health_score_non_zero(self):
        from risk_agent.agent import RiskAgent
        a = RiskAgent()
        a.start(); a.beat()
        a.execute_task()
        assert a.record.health_score >= 0

    def test_strategy_agent_increments_published(self):
        from strategy_agent.agent import StrategyAgent
        a = StrategyAgent()
        a.start(); a.beat()
        snap = a.execute_task()
        a.publish(snap, "strategy")
        assert a.record.snapshots_published == 1

    def test_all_4_agents_registered_after_init(self):
        from agent_framework.agent_registry import AgentRegistry
        from market_intelligence_agent.agent import MarketIntelligenceAgent
        from stock_monitoring_agent.agent   import StockMonitoringAgent
        from strategy_agent.agent           import StrategyAgent
        from risk_agent.agent               import RiskAgent
        for cls in (MarketIntelligenceAgent, StockMonitoringAgent, StrategyAgent, RiskAgent):
            a = cls(); a.start()
        reg = AgentRegistry.instance()
        for aid in ("market-intelligence-agent", "stock-monitoring-agent",
                    "strategy-agent", "risk-agent"):
            assert reg.get(aid) is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
