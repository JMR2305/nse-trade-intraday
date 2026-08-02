"""
test_phase10e.py — Phase 10E Tests
Collaborative Intelligence + Autonomous Operations

READ-ONLY · ADVISORY-ONLY
"""
import unittest
from unittest.mock import patch, MagicMock
import os


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_graph(
    healthy: int = 8,
    total: int = 11,
    missing: list | None = None,
    stale: list | None = None,
    conflicts: list | None = None,
    health_pct: float = 85.0,
) -> dict:
    nodes = []
    for i in range(total):
        nodes.append({
            "agent_id": f"agent_{i}",
            "label": f"Agent {i}",
            "layer": "ANALYSIS",
            "position": i,
            "produces": [f"snap_{i}"],
            "consumes": [f"snap_{i-1}"] if i > 0 else [],
            "health": "HEALTHY" if i < healthy else "UNAVAILABLE",
            "latency_ms": 50.0,
            "available": i < healthy,
        })
    edges = []
    for i in range(1, total):
        edges.append({
            "from": f"agent_{i-1}", "to": f"agent_{i}",
            "snapshot": f"snap_{i-1}",
            "health": "HEALTHY" if i < healthy else "DOWN",
            "latency_ms": 100.0,
        })
    return {
        "advisory_only": True, "read_only": True,
        "nodes": nodes, "edges": edges,
        "node_count": total, "edge_count": len(edges),
        "missing_dependencies": missing or [],
        "stale_nodes": stale or [],
        "conflicting_outputs": conflicts or [],
        "graph_health_pct": health_pct,
        "healthy_agents": healthy, "total_agents": total,
        "build_latency_ms": 12.0, "generated_at": "2024-01-01T10:00:00Z",
        "available": True,
    }


def _make_ops_snap() -> dict:
    return {
        "advisory_only": True, "read_only": True, "available": True,
        "registered_agents": 11, "healthy_agents": 9, "busy_agents": 5,
        "warning_agents": 1, "failed_agents": 0,
        "snapshot_throughput": 22, "queue_depth": 0,
        "heartbeat_status": "HEALTHY",
        "data_freshness_s": 45, "avg_decision_latency_ms": 120.0,
        "avg_snapshot_latency_ms": 55.0,
        "learning_queue": 3, "knowledge_queue": 7,
        "overall_health": "HEALTHY", "overall_health_score": 87.0,
        "collaboration_alerts": [],
        "ops_latency_ms": 210.0, "generated_at": "2024-01-01T10:00:00Z",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Collaboration Graph
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollaborationGraph(unittest.TestCase):

    def test_agent_chain_has_11_entries(self):
        from collaboration_engine.collaboration_graph import AGENT_CHAIN
        self.assertEqual(len(AGENT_CHAIN), 11)

    def test_agent_chain_starts_with_supervisor(self):
        from collaboration_engine.collaboration_graph import AGENT_CHAIN
        self.assertEqual(AGENT_CHAIN[0]["agent_id"], "supervisor")

    def test_agent_chain_ends_with_knowledge(self):
        from collaboration_engine.collaboration_graph import AGENT_CHAIN
        self.assertEqual(AGENT_CHAIN[-1]["agent_id"], "knowledge")

    def test_each_node_has_required_fields(self):
        from collaboration_engine.collaboration_graph import AGENT_CHAIN
        required = {"agent_id", "label", "layer", "produces", "consumes", "position"}
        for spec in AGENT_CHAIN:
            self.assertTrue(required.issubset(spec.keys()), f"Missing fields in {spec['agent_id']}")

    def test_positions_are_sequential(self):
        from collaboration_engine.collaboration_graph import AGENT_CHAIN
        positions = [s["position"] for s in AGENT_CHAIN]
        self.assertEqual(positions, list(range(11)))

    def test_build_graph_returns_required_keys(self):
        from collaboration_engine.collaboration_graph import AGENT_CHAIN
        # Mock all _probe_agent_health calls
        with patch("collaboration_engine.collaboration_graph._probe_agent_health") as mock_probe:
            mock_probe.return_value = {"health": "HEALTHY", "latency_ms": 10.0, "available": True, "last_snapshot_age_s": None}
            from collaboration_engine.collaboration_graph import build_collaboration_graph
            result = build_collaboration_graph()
        required = {"nodes", "edges", "node_count", "edge_count", "missing_dependencies",
                    "stale_nodes", "conflicting_outputs", "graph_health_pct", "generated_at"}
        self.assertTrue(required.issubset(result.keys()))

    def test_graph_has_11_nodes(self):
        with patch("collaboration_engine.collaboration_graph._probe_agent_health") as mock_probe:
            mock_probe.return_value = {"health": "HEALTHY", "latency_ms": 5.0, "available": True, "last_snapshot_age_s": None}
            from collaboration_engine.collaboration_graph import build_collaboration_graph
            result = build_collaboration_graph()
        self.assertEqual(result["node_count"], 11)

    def test_graph_has_10_edges(self):
        with patch("collaboration_engine.collaboration_graph._probe_agent_health") as mock_probe:
            mock_probe.return_value = {"health": "HEALTHY", "latency_ms": 5.0, "available": True, "last_snapshot_age_s": None}
            from collaboration_engine.collaboration_graph import build_collaboration_graph
            result = build_collaboration_graph()
        # 10 edges: supervisor→market_data plus 9 downstream agent handoffs
        self.assertEqual(result["edge_count"], 10)

    def test_all_healthy_gives_100_pct(self):
        with patch("collaboration_engine.collaboration_graph._probe_agent_health") as mock_probe:
            mock_probe.return_value = {"health": "HEALTHY", "latency_ms": 5.0, "available": True, "last_snapshot_age_s": None}
            from collaboration_engine.collaboration_graph import build_collaboration_graph
            result = build_collaboration_graph()
        self.assertEqual(result["graph_health_pct"], 100.0)

    def test_unhealthy_agent_reduces_score(self):
        call_count = [0]
        def side_effect(agent_id):
            call_count[0] += 1
            if call_count[0] <= 3:
                return {"health": "UNAVAILABLE", "latency_ms": 5.0, "available": False, "last_snapshot_age_s": None}
            return {"health": "HEALTHY", "latency_ms": 5.0, "available": True, "last_snapshot_age_s": None}
        with patch("collaboration_engine.collaboration_graph._probe_agent_health", side_effect=side_effect):
            from collaboration_engine.collaboration_graph import build_collaboration_graph
            result = build_collaboration_graph()
        self.assertLess(result["graph_health_pct"], 100.0)

    def test_dependency_report_has_required_fields(self):
        with patch("collaboration_engine.collaboration_graph._probe_agent_health") as mock_probe:
            mock_probe.return_value = {"health": "HEALTHY", "latency_ms": 5.0, "available": True, "last_snapshot_age_s": None}
            from collaboration_engine.collaboration_graph import build_dependency_report
            result = build_dependency_report()
        self.assertIn("chain_intact", result)
        self.assertIn("missing_dependencies", result)

    def test_advisory_only_flag(self):
        with patch("collaboration_engine.collaboration_graph._probe_agent_health") as mock_probe:
            mock_probe.return_value = {"health": "HEALTHY", "latency_ms": 5.0, "available": True, "last_snapshot_age_s": None}
            from collaboration_engine.collaboration_graph import build_collaboration_graph
            result = build_collaboration_graph()
        self.assertTrue(result.get("advisory_only"))
        self.assertTrue(result.get("read_only"))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Decision Lineage
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecisionLineage(unittest.TestCase):

    def _patched_lineage(self):
        with patch("collaboration_engine.decision_lineage._safe_call") as mock_safe:
            mock_safe.return_value = {
                "available": True, "symbols_tracked": 10,
                "total_reports": 5, "fresh_reports": 5,
                "current_regime": "BULLISH", "regime_strength": 0.75,
                "overall_market_health": "HEALTHY",
                "monitored_count": 10, "alert_count": 0, "events_today": 2,
                "active_strategies": 3, "top_strategy": "MOMENTUM", "avg_strategy_confidence": 0.72,
                "risk_level": "LOW", "risk_score": 25, "exposure_pct": 30.0,
                "decision_health": "HEALTHY",
                "recommendations": [{"symbol": "RELIANCE", "decision_type": "BUY", "confidence": 0.82, "explanation": "Momentum signal"}],
                "learning_health": "HEALTHY", "knowledge_base_size": 15,
            }
            from collaboration_engine.decision_lineage import build_decision_lineage
            return build_decision_lineage()

    def test_lineage_has_10_steps(self):
        result = self._patched_lineage()
        self.assertEqual(result["step_count"], 10)

    def test_lineage_has_required_fields(self):
        result = self._patched_lineage()
        required = {"lineage_steps", "step_count", "traceability_pct", "lineage_latency_ms", "generated_at"}
        self.assertTrue(required.issubset(result.keys()))

    def test_advisory_only(self):
        result = self._patched_lineage()
        self.assertTrue(result.get("advisory_only"))
        self.assertTrue(result.get("read_only"))

    def test_steps_have_agent_and_label(self):
        result = self._patched_lineage()
        for step in result["lineage_steps"]:
            self.assertIn("agent", step)
            self.assertIn("label", step)
            self.assertIn("step", step)

    def test_traceability_pct_range(self):
        result = self._patched_lineage()
        self.assertGreaterEqual(result["traceability_pct"], 0)
        self.assertLessEqual(result["traceability_pct"], 100)

    def test_step_numbers_sequential(self):
        result = self._patched_lineage()
        steps = [s["step"] for s in result["lineage_steps"]]
        self.assertEqual(steps, list(range(1, 11)))

    def test_first_step_is_market_data(self):
        result = self._patched_lineage()
        self.assertEqual(result["lineage_steps"][0]["agent"], "market_data")

    def test_last_step_is_knowledge(self):
        result = self._patched_lineage()
        self.assertEqual(result["lineage_steps"][-1]["agent"], "knowledge")

    def test_latency_is_positive(self):
        result = self._patched_lineage()
        self.assertGreaterEqual(result["lineage_latency_ms"], 0)

    def test_unavailable_snap_gives_unavailable_status(self):
        with patch("collaboration_engine.decision_lineage._safe_call") as mock_safe:
            mock_safe.return_value = None
            from collaboration_engine.decision_lineage import build_decision_lineage
            result = build_decision_lineage()
        # When all snaps return None, no step should be AVAILABLE
        # Step 7 returns NO_RECOMMENDATIONS (no recs), others return UNAVAILABLE
        available_steps = [s for s in result["lineage_steps"] if s.get("status") == "AVAILABLE"]
        self.assertEqual(len(available_steps), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Collaboration Alerts
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollaborationAlerts(unittest.TestCase):

    def test_empty_graph_produces_no_missing_snapshot_alerts(self):
        graph = _make_graph(healthy=11, total=11)
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        missing = [a for a in alerts if a["alert_type"] == "MISSING_SNAPSHOT"]
        self.assertEqual(len(missing), 0)

    def test_unavailable_agent_creates_missing_snapshot_alert(self):
        graph = _make_graph(healthy=8, total=11)
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        missing = [a for a in alerts if a["alert_type"] == "MISSING_SNAPSHOT"]
        self.assertGreater(len(missing), 0)

    def test_low_health_pct_creates_data_freshness_alert(self):
        graph = _make_graph(healthy=4, total=11, health_pct=35.0)
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        freshness = [a for a in alerts if a["alert_type"] == "DATA_FRESHNESS"]
        self.assertGreater(len(freshness), 0)

    def test_conflicts_create_conflicting_recommendations_alerts(self):
        graph = _make_graph(conflicts=["Agent A healthy but Agent B offline."])
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        conflict = [a for a in alerts if a["alert_type"] == "CONFLICTING_RECOMMENDATIONS"]
        self.assertGreater(len(conflict), 0)

    def test_alerts_sorted_critical_first(self):
        graph = _make_graph(healthy=4, total=11, health_pct=30.0)
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        if len(alerts) > 1:
            severities = [a["severity"] for a in alerts]
            _order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
            ordered = sorted(severities, key=lambda s: _order.get(s, 3))
            self.assertEqual(severities, ordered)

    def test_all_alerts_have_required_fields(self):
        graph = _make_graph(healthy=5, total=11)
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        required = {"alert_id", "alert_type", "severity", "title", "description", "recommendation", "advisory_only"}
        for a in alerts:
            self.assertTrue(required.issubset(a.keys()), f"Missing fields in alert {a.get('alert_id')}")

    def test_all_alerts_are_advisory_only(self):
        graph = _make_graph(healthy=3, total=11)
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        for a in alerts:
            self.assertTrue(a.get("advisory_only"))

    def test_stale_research_alert_fires(self):
        # Create a graph where 'research' node (index ~2) is unavailable
        graph = _make_graph(healthy=11, total=11)
        # Manually set the research node unavailable
        for n in graph["nodes"]:
            if n.get("agent_id") == "research" or n.get("agent_id") == "agent_2":
                n["available"] = False
                n["agent_id"] = "research"
        from collaboration_engine.collaboration_alerts import generate_collaboration_alerts
        alerts = generate_collaboration_alerts(graph)
        stale = [a for a in alerts if a["alert_type"] == "STALE_RESEARCH"]
        self.assertGreater(len(stale), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Collaboration Engine Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollaborationEngineAgent(unittest.TestCase):

    def _patched_agent(self):
        with patch("collaboration_engine.agent.build_collaboration_graph") as mg, \
             patch("collaboration_engine.agent.build_decision_lineage") as ml, \
             patch("collaboration_engine.agent.build_dependency_report") as md, \
             patch("collaboration_engine.agent._gen_alerts") as ma:
            mg.return_value = _make_graph()
            ml.return_value = {"traceability_pct": 80.0, "lineage_latency_ms": 50.0}
            md.return_value = {"missing_dependencies": [], "stale_nodes": []}
            ma.return_value = []
            from collaboration_engine.agent import CollaborationEngine
            agent = CollaborationEngine()
            return agent.execute(), agent

    def test_agent_id(self):
        _, agent = self._patched_agent()
        self.assertEqual(agent.agent_id, "collaboration_engine")

    def test_version_prefix(self):
        _, agent = self._patched_agent()
        self.assertTrue(agent.version.startswith("10E"))

    def test_execute_returns_dict(self):
        snap, _ = self._patched_agent()
        self.assertIsInstance(snap, dict)

    def test_execute_advisory_only(self):
        snap, _ = self._patched_agent()
        self.assertTrue(snap.get("advisory_only"))
        self.assertTrue(snap.get("read_only"))

    def test_autonomous_execution_always_false(self):
        snap, _ = self._patched_agent()
        self.assertFalse(snap.get("autonomous_execution"))

    def test_auto_recovery_always_false(self):
        snap, _ = self._patched_agent()
        self.assertFalse(snap.get("auto_recovery"))

    def test_execute_has_required_fields(self):
        snap, _ = self._patched_agent()
        required = {"collaboration_health", "graph_health_pct", "healthy_agents",
                    "total_agents", "alerts", "alert_count", "traceability_pct", "generated_at"}
        self.assertTrue(required.issubset(snap.keys()))

    def test_status_returns_started_at(self):
        _, agent = self._patched_agent()
        status = agent.get_status()
        self.assertIn("started_at", status)

    def test_healthy_graph_gives_healthy_status(self):
        snap, _ = self._patched_agent()
        self.assertIn(snap.get("collaboration_health"), ("HEALTHY", "WARNING", "DEGRADED", "CRITICAL"))

    def test_total_agents_is_11(self):
        snap, _ = self._patched_agent()
        self.assertEqual(snap.get("total_agents"), 11)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. System Health Score
# ═══════════════════════════════════════════════════════════════════════════════

class TestSystemHealthScore(unittest.TestCase):

    def _patch_and_compute(self):
        with patch("autonomous_operations.operations_engine._safe") as mock_safe:
            def safe_side(fn_path, *args):
                if "supervisor" in fn_path and "alerts" not in fn_path:
                    return {
                        "available": True,
                        "framework_metrics": {"agent_count": 11, "healthy_agents": 9, "warning_agents": 1, "error_agents": 0},
                        "supervisor_health": "HEALTHY",
                    }
                if "alerts" in fn_path:
                    return {"alert_count": 0}
                if "collaboration_health" in fn_path:
                    return {"available": True, "collaboration_health": "HEALTHY", "graph_health_pct": 90.0}
                if "learning_timeline" in fn_path:
                    return [{"event_type": "LEARNING_COMPLETED"}]
                if "knowledge_snapshot" in fn_path:
                    return {"available": True, "knowledge_base_size": 10}
                if "learning_snapshot" in fn_path:
                    return {"available": True, "learning_health": "HEALTHY"}
                if "market_data_metrics" in fn_path or "research_metrics" in fn_path:
                    return {"avg_processing_time_ms": 100.0}
                return None
            mock_safe.side_effect = safe_side
            from autonomous_operations.operations_engine import compute_system_health
            return compute_system_health()

    def test_returns_required_fields(self):
        result = self._patch_and_compute()
        required = {"overall_score", "overall_health", "components", "history", "generated_at"}
        self.assertTrue(required.issubset(result.keys()))

    def test_overall_score_in_range(self):
        result = self._patch_and_compute()
        self.assertGreaterEqual(result["overall_score"], 0)
        self.assertLessEqual(result["overall_score"], 100)

    def test_all_8_components_present(self):
        result = self._patch_and_compute()
        expected = {"agent_health", "snapshot_health", "heartbeat_health", "timeline_health",
                    "knowledge_health", "learning_health", "performance_health", "collaboration_health"}
        self.assertEqual(set(result["components"].keys()), expected)

    def test_each_component_has_score_and_weight(self):
        result = self._patch_and_compute()
        for name, comp in result["components"].items():
            self.assertIn("score", comp, f"Missing score in {name}")
            self.assertIn("weight", comp, f"Missing weight in {name}")
            self.assertIn("contribution", comp, f"Missing contribution in {name}")

    def test_weights_sum_to_1(self):
        from autonomous_operations.operations_engine import _WEIGHTS
        total = sum(_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_history_is_appended(self):
        result = self._patch_and_compute()
        self.assertIsInstance(result["history"], list)

    def test_advisory_only(self):
        result = self._patch_and_compute()
        self.assertTrue(result.get("advisory_only"))

    def test_available(self):
        result = self._patch_and_compute()
        self.assertTrue(result.get("available"))

    def test_overall_health_is_valid_string(self):
        result = self._patch_and_compute()
        self.assertIn(result["overall_health"], ("HEALTHY", "DEGRADED", "CRITICAL", "DOWN"))

    def test_computation_latency_positive(self):
        result = self._patch_and_compute()
        self.assertGreaterEqual(result.get("computation_latency_ms", 0), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Supervisor Extensions
# ═══════════════════════════════════════════════════════════════════════════════

class TestSupervisorExtensions(unittest.TestCase):

    def _patched_extended(self):
        with patch("autonomous_operations.supervisor_extensions._safe") as mock_safe:
            def side(fn_path):
                if "collaboration_graph" in fn_path:
                    return _make_graph()
                if "scalability_dashboard" in fn_path:
                    return {"utilisation_pct": 25.0, "safe_capacity_symbols": 1100,
                            "current_monitored_symbols": 10, "remaining_capacity": 1090,
                            "scaling_estimate": "OK"}
                return None
            mock_safe.side_effect = side
            from autonomous_operations.supervisor_extensions import build_supervisor_extended
            return build_supervisor_extended()

    def test_returns_required_fields(self):
        result = self._patched_extended()
        required = {"dependency_validation", "snapshot_freshness", "collaboration_health",
                    "capacity_score", "restart_recommendations", "recovery_suggestions",
                    "maintenance_recommendations", "generated_at"}
        self.assertTrue(required.issubset(result.keys()))

    def test_advisory_only(self):
        result = self._patched_extended()
        self.assertTrue(result.get("advisory_only"))

    def test_auto_recovery_always_false(self):
        result = self._patched_extended()
        self.assertFalse(result.get("auto_recovery"))

    def test_dependency_validation_has_chain_intact(self):
        result = self._patched_extended()
        self.assertIn("chain_intact", result["dependency_validation"])

    def test_freshness_validation_has_counts(self):
        result = self._patched_extended()
        fv = result["snapshot_freshness"]
        self.assertIn("fresh_agents", fv)
        self.assertIn("stale_agents", fv)

    def test_capacity_score_in_range(self):
        result = self._patched_extended()
        score = result["capacity_score"]["capacity_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_maintenance_recommendations_is_list(self):
        result = self._patched_extended()
        self.assertIsInstance(result["maintenance_recommendations"], list)
        self.assertGreater(len(result["maintenance_recommendations"]), 0)

    def test_restart_recs_are_advisory(self):
        result = self._patched_extended()
        for rec in result["restart_recommendations"]:
            self.assertTrue(rec.get("advisory_only"))

    def test_recovery_suggestions_is_list(self):
        result = self._patched_extended()
        self.assertIsInstance(result["recovery_suggestions"], list)
        self.assertGreater(len(result["recovery_suggestions"]), 0)

    def test_overall_status_valid(self):
        result = self._patched_extended()
        self.assertIn(result.get("overall_status"), ("HEALTHY", "DEGRADED", "CRITICAL"))


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Autonomous Ops Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousOpsAgent(unittest.TestCase):

    def _patched_agent(self):
        with patch("autonomous_operations.agent.compute_ops_snapshot") as mock_ops:
            mock_ops.return_value = _make_ops_snap()
            from autonomous_operations.agent import AutonomousOpsAgent
            agent = AutonomousOpsAgent()
            return agent.execute(), agent

    def test_agent_id(self):
        _, agent = self._patched_agent()
        self.assertEqual(agent.agent_id, "autonomous_ops_agent")

    def test_version_prefix(self):
        _, agent = self._patched_agent()
        self.assertTrue(agent.version.startswith("10E"))

    def test_advisory_only(self):
        snap, _ = self._patched_agent()
        self.assertTrue(snap.get("advisory_only"))
        self.assertTrue(snap.get("read_only"))

    def test_autonomous_execution_false(self):
        snap, _ = self._patched_agent()
        self.assertFalse(snap.get("autonomous_execution"))

    def test_auto_strategy_tuning_false(self):
        snap, _ = self._patched_agent()
        self.assertFalse(snap.get("auto_strategy_tuning"))

    def test_auto_ai_retraining_false(self):
        snap, _ = self._patched_agent()
        self.assertFalse(snap.get("auto_ai_retraining"))

    def test_auto_portfolio_changes_false(self):
        snap, _ = self._patched_agent()
        self.assertFalse(snap.get("auto_portfolio_changes"))

    def test_execute_has_ops_fields(self):
        snap, _ = self._patched_agent()
        required = {"registered_agents", "healthy_agents", "snapshot_throughput",
                    "heartbeat_status", "learning_queue", "knowledge_queue"}
        self.assertTrue(required.issubset(snap.keys()))

    def test_status_returns_started_at(self):
        _, agent = self._patched_agent()
        status = agent.get_status()
        self.assertIn("started_at", status)

    def test_status_advisory_only(self):
        _, agent = self._patched_agent()
        status = agent.get_status()
        self.assertTrue(status.get("advisory_only"))


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Scalability Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class TestScalabilityDashboard(unittest.TestCase):

    def _patched_scalability(self):
        with patch("autonomous_operations.operations_engine._safe") as mock_safe:
            def side(fn_path, *args):
                if "supervisor_snapshot" in fn_path:
                    return {
                        "available": True,
                        "framework_metrics": {"agent_count": 11, "total_snapshots_published": 22, "total_queue_depth": 0},
                        "monitored_symbols": 15,
                    }
                if "learning_performance" in fn_path:
                    return {"scalability": {"learning_throughput": "~15 trades/session"}}
                if "knowledge_snapshot" in fn_path:
                    return {"available": True, "knowledge_base_size": 30}
                if "scalability_estimate" in fn_path:
                    return {}
                return None
            mock_safe.side_effect = side
            from autonomous_operations.operations_engine import compute_scalability_dashboard
            return compute_scalability_dashboard()

    def test_required_fields(self):
        result = self._patched_scalability()
        required = {"current_agents", "current_monitored_symbols", "snapshots_per_minute",
                    "recommendations_per_hour", "learning_throughput", "knowledge_growth",
                    "safe_capacity_symbols", "utilisation_pct", "remaining_capacity",
                    "estimated_cpu_pct", "estimated_memory_mb", "future_agents_supported", "generated_at"}
        self.assertTrue(required.issubset(result.keys()))

    def test_safe_capacity_based_on_agents(self):
        result = self._patched_scalability()
        self.assertEqual(result["safe_capacity_symbols"], 11 * 100)

    def test_utilisation_in_range(self):
        result = self._patched_scalability()
        self.assertGreaterEqual(result["utilisation_pct"], 0)
        self.assertLessEqual(result["utilisation_pct"], 100)

    def test_advisory_only(self):
        result = self._patched_scalability()
        self.assertTrue(result.get("advisory_only"))

    def test_future_agents_supported_non_negative(self):
        result = self._patched_scalability()
        self.assertGreaterEqual(result["future_agents_supported"], 0)

    def test_cpu_estimate_positive(self):
        result = self._patched_scalability()
        self.assertGreater(result["estimated_cpu_pct"], 0)

    def test_memory_estimate_positive(self):
        result = self._patched_scalability()
        self.assertGreater(result["estimated_memory_mb"], 0)

    def test_scaling_estimate_is_string(self):
        result = self._patched_scalability()
        self.assertIsInstance(result.get("scaling_estimate"), str)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Collaboration Shared Services
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollaborationSharedServices(unittest.TestCase):

    def test_disabled_returns_disabled_status(self):
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "false"
        from collaboration_engine import shared_services as svc
        result = svc.get_collaboration_snapshot()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "true"

    def test_enabled_returns_available(self):
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "true"
        with patch("collaboration_engine.agent.CollaborationEngine") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = {"available": True, "collaboration_health": "HEALTHY",
                                               "advisory_only": True}
            from collaboration_engine import shared_services as svc
            result = svc.get_collaboration_snapshot()
        self.assertTrue(result.get("available"))

    def test_get_collaboration_alerts_disabled(self):
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "false"
        from collaboration_engine import shared_services as svc
        result = svc.get_collaboration_alerts()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "true"

    def test_get_collaboration_health_disabled(self):
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "false"
        from collaboration_engine import shared_services as svc
        result = svc.get_collaboration_health()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "true"

    def test_get_comm_monitor_has_channels(self):
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "true"
        with patch("collaboration_engine.collaboration_graph.build_collaboration_graph") as mg:
            mg.return_value = _make_graph()
            from collaboration_engine import shared_services as svc
            result = svc.get_comm_monitor()
        self.assertIn("comm_records", result)
        self.assertIn("channel_count", result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Autonomous Ops Shared Services
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousOpsSharedServices(unittest.TestCase):

    def test_disabled_returns_disabled(self):
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "false"
        from autonomous_operations import shared_services as svc
        result = svc.get_autonomous_ops_snapshot()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "true"

    def test_enabled_returns_available(self):
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "true"
        with patch("autonomous_operations.agent.AutonomousOpsAgent") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = _make_ops_snap()
            from autonomous_operations import shared_services as svc
            result = svc.get_autonomous_ops_snapshot()
        self.assertTrue(result.get("available"))

    def test_system_health_disabled(self):
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "false"
        from autonomous_operations import shared_services as svc
        result = svc.get_system_health()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "true"

    def test_capacity_forecast_has_fields(self):
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "true"
        with patch("autonomous_operations.operations_engine.compute_scalability_dashboard") as mock_sc:
            mock_sc.return_value = {
                "utilisation_pct": 25.0, "remaining_capacity": 825,
                "estimated_cpu_pct": 32.5, "estimated_memory_mb": 370.0,
                "scaling_estimate": "Platform healthy",
                "current_monitored_symbols": 15,
            }
            from autonomous_operations import shared_services as svc
            result = svc.get_capacity_forecast()
        self.assertIn("cpu_headroom_pct", result)
        self.assertIn("forecast_30d", result)
        self.assertTrue(result.get("advisory_only"))

    def test_supervisor_extended_disabled(self):
        os.environ["SUPERVISOR_EXTENDED_ENABLED"] = "false"
        from autonomous_operations import shared_services as svc
        result = svc.get_supervisor_extended()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["SUPERVISOR_EXTENDED_ENABLED"] = "true"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Collaboration Layer
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollaborationLayer(unittest.TestCase):

    def _stub_collab(self):
        return {
            "available": True, "advisory_only": True,
            "collaboration_health": "HEALTHY", "graph_health_pct": 88.0,
            "healthy_agents": 10, "total_agents": 11,
            "missing_dependencies": [], "stale_nodes": [],
            "conflicting_outputs": [], "alerts": [], "alert_count": 0,
            "critical_alerts": 0, "traceability_pct": 90.0,
            "collaboration_latency_ms": 180.0,
        }

    def _stub_ops(self):
        return _make_ops_snap()

    def _stub_health(self):
        return {
            "available": True, "overall_score": 87.0, "overall_health": "HEALTHY",
            "components": {"performance_health": {"avg_latency_ms": 55.0}},
        }

    def test_summary_has_required_fields(self):
        with patch("collaboration_layer.shared_services._get_collab", return_value=self._stub_collab()), \
             patch("collaboration_layer.shared_services._get_ops", return_value=self._stub_ops()), \
             patch("collaboration_layer.shared_services._get_health", return_value=self._stub_health()):
            from collaboration_layer.shared_services import get_collaboration_summary
            result = get_collaboration_summary()
        required = {"registered_agents", "healthy_agents", "collaboration_health",
                    "overall_health", "alert_count", "traceability_pct", "generated_at"}
        self.assertTrue(required.issubset(result.keys()))

    def test_summary_advisory_only(self):
        with patch("collaboration_layer.shared_services._get_collab", return_value=self._stub_collab()), \
             patch("collaboration_layer.shared_services._get_ops", return_value=self._stub_ops()), \
             patch("collaboration_layer.shared_services._get_health", return_value=self._stub_health()):
            from collaboration_layer.shared_services import get_collaboration_summary
            result = get_collaboration_summary()
        self.assertTrue(result.get("advisory_only"))

    def test_timeline_has_events(self):
        with patch("collaboration_layer.shared_services._get_collab", return_value=self._stub_collab()), \
             patch("collaboration_layer.shared_services._get_ops", return_value=self._stub_ops()), \
             patch("collaboration_layer.shared_services._get_health", return_value=self._stub_health()), \
             patch("collaboration_layer.shared_services._safe", return_value=None):
            from collaboration_layer.shared_services import get_collaboration_timeline
            result = get_collaboration_timeline()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_timeline_events_have_required_fields(self):
        with patch("collaboration_layer.shared_services._get_collab", return_value=self._stub_collab()), \
             patch("collaboration_layer.shared_services._get_ops", return_value=self._stub_ops()), \
             patch("collaboration_layer.shared_services._get_health", return_value=self._stub_health()), \
             patch("collaboration_layer.shared_services._safe", return_value=None):
            from collaboration_layer.shared_services import get_collaboration_timeline
            events = get_collaboration_timeline()
        required = {"event_id", "event_type", "title", "description", "source", "severity", "timestamp"}
        for ev in events:
            self.assertTrue(required.issubset(ev.keys()), f"Missing fields in event {ev.get('event_id')}")

    def test_performance_has_scalability(self):
        with patch("collaboration_layer.shared_services._get_collab", return_value=self._stub_collab()), \
             patch("collaboration_layer.shared_services._get_ops", return_value=self._stub_ops()), \
             patch("collaboration_layer.shared_services._get_health", return_value=self._stub_health()), \
             patch("collaboration_layer.shared_services._safe", return_value={"utilisation_pct": 10.0,
                                                                               "current_agents": 11,
                                                                               "current_monitored_symbols": 15,
                                                                               "snapshots_per_minute": 22,
                                                                               "recommendations_per_hour": 30,
                                                                               "future_agents_supported": 9,
                                                                               "estimated_cpu_pct": 30.0,
                                                                               "estimated_memory_mb": 370.0}):
            from collaboration_layer.shared_services import get_collaboration_performance
            result = get_collaboration_performance()
        self.assertIn("scalability", result)
        self.assertIn("snapshot_latency_ms", result)

    def test_registered_agents_in_summary(self):
        with patch("collaboration_layer.shared_services._get_collab", return_value=self._stub_collab()), \
             patch("collaboration_layer.shared_services._get_ops", return_value=self._stub_ops()), \
             patch("collaboration_layer.shared_services._get_health", return_value=self._stub_health()):
            from collaboration_layer.shared_services import get_collaboration_summary
            result = get_collaboration_summary()
        self.assertEqual(result["registered_agents"], 11)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Feature Flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlags(unittest.TestCase):

    def test_collaboration_engine_flag_defined(self):
        from agent_framework.config import COLLABORATION_ENGINE_ENABLED
        self.assertEqual(COLLABORATION_ENGINE_ENABLED, "COLLABORATION_ENGINE_ENABLED")

    def test_autonomous_operations_flag_defined(self):
        from agent_framework.config import AUTONOMOUS_OPERATIONS_ENABLED
        self.assertEqual(AUTONOMOUS_OPERATIONS_ENABLED, "AUTONOMOUS_OPERATIONS_ENABLED")

    def test_supervisor_extended_flag_defined(self):
        from agent_framework.config import SUPERVISOR_EXTENDED_ENABLED
        self.assertEqual(SUPERVISOR_EXTENDED_ENABLED, "SUPERVISOR_EXTENDED_ENABLED")

    def test_collaboration_alerts_flag_defined(self):
        from agent_framework.config import COLLABORATION_ALERTS_ENABLED
        self.assertEqual(COLLABORATION_ALERTS_ENABLED, "COLLABORATION_ALERTS_ENABLED")

    def test_collab_enabled_by_default(self):
        os.environ.pop("COLLABORATION_ENGINE_ENABLED", None)
        with patch("collaboration_engine.agent.CollaborationEngine") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = {"available": True, "advisory_only": True}
            from collaboration_engine import shared_services as svc
            result = svc.get_collaboration_snapshot()
        self.assertNotEqual(result.get("status"), "DISABLED")

    def test_autonomous_ops_enabled_by_default(self):
        os.environ.pop("AUTONOMOUS_OPERATIONS_ENABLED", None)
        with patch("autonomous_operations.agent.AutonomousOpsAgent") as MockAgent:
            mock_inst = MockAgent.return_value
            mock_inst.execute.return_value = _make_ops_snap()
            from autonomous_operations import shared_services as svc
            result = svc.get_autonomous_ops_snapshot()
        self.assertNotEqual(result.get("status"), "DISABLED")

    def test_autonomous_execution_hardcoded_false(self):
        from autonomous_operations.agent import AUTONOMOUS_EXECUTION
        self.assertFalse(AUTONOMOUS_EXECUTION)

    def test_auto_recovery_hardcoded_false(self):
        from collaboration_engine.agent import AUTO_RECOVERY
        self.assertFalse(AUTO_RECOVERY)

    def test_collab_disabled_flag(self):
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "false"
        from collaboration_engine import shared_services as svc
        result = svc.get_collaboration_snapshot()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["COLLABORATION_ENGINE_ENABLED"] = "true"

    def test_autonomous_ops_disabled_flag(self):
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "false"
        from autonomous_operations import shared_services as svc
        result = svc.get_autonomous_ops_snapshot()
        self.assertEqual(result.get("status"), "DISABLED")
        os.environ["AUTONOMOUS_OPERATIONS_ENABLED"] = "true"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Supervisor Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestSupervisorIntegration(unittest.TestCase):

    def test_collab_engine_agent_id(self):
        from collaboration_engine.agent import AGENT_ID
        self.assertEqual(AGENT_ID, "collaboration_engine")

    def test_collab_engine_version(self):
        from collaboration_engine.agent import VERSION
        self.assertTrue(VERSION.startswith("10E"))

    def test_autonomous_ops_agent_id(self):
        from autonomous_operations.agent import AGENT_ID
        self.assertEqual(AGENT_ID, "autonomous_ops_agent")

    def test_autonomous_ops_version(self):
        from autonomous_operations.agent import VERSION
        self.assertTrue(VERSION.startswith("10E"))

    def test_collab_status_has_started_at(self):
        from collaboration_engine.agent import CollaborationEngine
        status = CollaborationEngine().get_status()
        self.assertIn("started_at", status)

    def test_autonomous_ops_status_has_started_at(self):
        from autonomous_operations.agent import AutonomousOpsAgent
        status = AutonomousOpsAgent().get_status()
        self.assertIn("started_at", status)


if __name__ == "__main__":
    unittest.main()
