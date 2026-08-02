"""
test_agent_framework.py — Phase 10A
Tests for the Multi-Agent Framework.

Covers:
  - AgentState machine and transitions
  - AgentRegistry CRUD and queries
  - HeartbeatService detection
  - LifecycleManager (start/stop/pause/resume/error)
  - Supervisor advisory alerts (NEVER auto-restart)
  - SnapshotBus publish/subscribe isolation
  - HealthMonitor scoring
  - AgentScheduler tick
  - AgentMetrics shape
  - FrameworkMetrics aggregate
  - ScalabilityEstimator
  - Feature flags (disabled returns correct response)
  - BaseAgent subclass
  - MarketDataAgent snapshot structure
  - ResearchAgent snapshot structure
  - Failure handling (error state propagation)

Target: ≥ 60 passing tests.
"""
import sys
import os
import time
import pytest

# Ensure module path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reset singletons before each test to ensure isolation
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
# 1. AgentState
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentState:
    def test_running_is_active(self):
        from agent_framework.models import AgentState
        assert AgentState.RUNNING.is_active

    def test_idle_is_active(self):
        from agent_framework.models import AgentState
        assert AgentState.IDLE.is_active

    def test_busy_is_active(self):
        from agent_framework.models import AgentState
        assert AgentState.BUSY.is_active

    def test_warning_is_active(self):
        from agent_framework.models import AgentState
        assert AgentState.WARNING.is_active

    def test_stopped_not_active(self):
        from agent_framework.models import AgentState
        assert not AgentState.STOPPED.is_active

    def test_error_not_active(self):
        from agent_framework.models import AgentState
        assert not AgentState.ERROR.is_active

    def test_running_is_healthy(self):
        from agent_framework.models import AgentState
        assert AgentState.RUNNING.is_healthy

    def test_warning_not_healthy(self):
        from agent_framework.models import AgentState
        assert not AgentState.WARNING.is_healthy

    def test_all_states_have_values(self):
        from agent_framework.models import AgentState
        states = [
            "INITIALIZING", "STARTING", "RUNNING", "BUSY",
            "IDLE", "PAUSED", "WARNING", "ERROR", "STOPPED"
        ]
        for s in states:
            assert AgentState(s).value == s


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AgentRecord
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentRecord:
    def _make(self):
        from agent_framework.models import AgentRecord
        return AgentRecord("test-1", "Test Agent", version="2.0.0")

    def test_initial_state_is_initializing(self):
        from agent_framework.models import AgentState
        r = self._make()
        assert r.state == AgentState.INITIALIZING

    def test_transition_records_timestamp(self):
        from agent_framework.models import AgentRecord, AgentState
        r = self._make()
        r.transition(AgentState.RUNNING, "test")
        assert r.state_changed_at is not None

    def test_beat_sets_last_heartbeat(self):
        r = self._make()
        assert r.last_heartbeat is None
        r.beat()
        assert r.last_heartbeat is not None

    def test_to_dict_contains_required_fields(self):
        r = self._make()
        d = r.to_dict()
        required = [
            "agent_id", "name", "version", "owner", "state", "state_reason",
            "state_changed_at", "priority", "dependencies", "capabilities",
            "current_task", "last_heartbeat", "health_score",
            "queue_depth", "processing_time_ms",
            "snapshots_published", "snapshots_consumed",
            "registered_at", "started_at",
        ]
        for f in required:
            assert f in d, f"Missing field: {f}"

    def test_version_stored(self):
        r = self._make()
        assert r.version == "2.0.0"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AgentRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentRegistry:
    def _reg(self):
        from agent_framework.agent_registry import AgentRegistry
        return AgentRegistry.instance()

    def _record(self, aid="r1"):
        from agent_framework.models import AgentRecord
        return AgentRecord(aid, f"Agent {aid}")

    def test_register_and_get(self):
        reg = self._reg()
        rec = self._record("a1")
        reg.register(rec)
        assert reg.get("a1") is rec

    def test_get_unknown_returns_none(self):
        assert self._reg().get("nonexistent") is None

    def test_deregister_returns_true_if_existed(self):
        reg = self._reg()
        reg.register(self._record("d1"))
        assert reg.deregister("d1") is True

    def test_deregister_returns_false_if_not_existed(self):
        assert self._reg().deregister("nope") is False

    def test_all_returns_list(self):
        reg = self._reg()
        reg.register(self._record("x1"))
        reg.register(self._record("x2"))
        assert len(reg.all()) == 2

    def test_count(self):
        reg = self._reg()
        reg.register(self._record("c1"))
        assert reg.count() == 1

    def test_by_state(self):
        from agent_framework.models import AgentState
        reg = self._reg()
        rec = self._record("s1")
        reg.register(rec)
        found = reg.by_state(AgentState.INITIALIZING)
        assert rec in found

    def test_summary_keys(self):
        reg = self._reg()
        s = reg.summary()
        for k in ("total", "running", "idle", "paused", "warning", "error", "stopped"):
            assert k in s

    def test_overwrite_registration(self):
        from agent_framework.models import AgentRecord
        reg = self._reg()
        r1 = AgentRecord("dup", "First")
        r2 = AgentRecord("dup", "Second")
        reg.register(r1)
        reg.register(r2)
        assert reg.get("dup").name == "Second"
        assert reg.count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LifecycleManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestLifecycleManager:
    def _lm(self):
        from agent_framework.lifecycle_manager import LifecycleManager
        return LifecycleManager()

    def _rec(self):
        from agent_framework.models import AgentRecord
        return AgentRecord("lc1", "LC Agent")

    def test_start_transitions_to_running(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        ok, _ = lm.start(r)
        assert ok
        assert r.state == AgentState.RUNNING

    def test_start_sets_started_at(self):
        lm = self._lm(); r = self._rec()
        lm.start(r)
        assert r.started_at is not None

    def test_stop_any_state(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        lm.start(r)
        ok, _ = lm.stop(r, "test stop")
        assert ok
        assert r.state == AgentState.STOPPED

    def test_pause_and_resume(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        lm.start(r)
        ok, _ = lm.pause(r)
        assert ok and r.state == AgentState.PAUSED
        ok2, _ = lm.resume(r)
        assert ok2 and r.state == AgentState.RUNNING

    def test_invalid_transition_fails(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        # STOPPED → RUNNING is invalid
        lm.stop(r)
        ok, msg = lm.transition(r, AgentState.RUNNING)
        assert not ok
        assert "Invalid transition" in msg

    def test_mark_error(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        lm.start(r)
        ok, _ = lm.mark_error(r, "disk full")
        assert ok and r.state == AgentState.ERROR

    def test_mark_busy_sets_current_task(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        lm.start(r)
        ok, _ = lm.mark_busy(r, "collecting data")
        assert ok and r.current_task == "collecting data"

    def test_mark_idle_clears_task(self):
        lm = self._lm(); r = self._rec()
        lm.start(r)
        lm.mark_busy(r, "work")
        lm.mark_idle(r)
        assert r.current_task is None

    def test_allowed_transitions_for_running(self):
        from agent_framework.models import AgentState
        lm = self._lm(); r = self._rec()
        lm.start(r)
        allowed = lm.allowed_transitions(r)
        assert "STOPPED" in allowed
        assert "PAUSED" in allowed


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SnapshotBus
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotBus:
    def _bus(self):
        from agent_framework.snapshot_bus import SnapshotBus
        return SnapshotBus.instance()

    def test_publish_and_latest(self):
        bus = self._bus()
        bus.publish("t1", "pub-1", {"value": 42})
        env = bus.latest("t1")
        assert env is not None
        assert env.payload["value"] == 42

    def test_latest_unknown_topic_returns_none(self):
        assert self._bus().latest("nonexistent") is None

    def test_topics_list(self):
        bus = self._bus()
        bus.publish("topicA", "p1", {})
        bus.publish("topicB", "p2", {})
        topics = bus.topics()
        assert "topicA" in topics
        assert "topicB" in topics

    def test_sequence_increments(self):
        bus = self._bus()
        bus.publish("seq", "p", {"x": 1})
        env1 = bus.latest("seq")
        bus.publish("seq", "p", {"x": 2})
        env2 = bus.latest("seq")
        assert env2.sequence > env1.sequence

    def test_subscribe_callback_called(self):
        bus = self._bus()
        received = []
        bus.subscribe("sub_topic", lambda e: received.append(e.payload))
        bus.publish("sub_topic", "p", {"msg": "hello"})
        assert received == [{"msg": "hello"}]

    def test_subscribe_isolation(self):
        """Subscriber on topic A must not receive topic B publishes."""
        bus = self._bus()
        received_a = []
        bus.subscribe("iso_a", lambda e: received_a.append(e))
        bus.publish("iso_b", "p", {"msg": "b"})
        assert len(received_a) == 0

    def test_no_direct_agent_refs_in_envelope(self):
        """Envelope must not contain agent object references — topic+publisher_id strings only."""
        bus = self._bus()
        env = bus.publish("check", "agent-123", {"data": 1})
        assert isinstance(env.publisher_id, str)
        assert isinstance(env.topic, str)

    def test_stats_structure(self):
        bus = self._bus()
        bus.publish("stat_topic", "p", {})
        s = bus.stats()
        assert "topics" in s
        assert "topic_count" in s

    def test_unsubscribe(self):
        bus = self._bus()
        received = []
        cb = lambda e: received.append(1)
        bus.subscribe("unsub", cb)
        bus.unsubscribe("unsub", cb)
        bus.publish("unsub", "p", {})
        assert len(received) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. HeartbeatService
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeartbeatService:
    def _svc(self):
        from agent_framework.heartbeat_service import HeartbeatService
        return HeartbeatService(grace_multiplier=3.0, stall_multiplier=6.0)

    def test_never_when_no_heartbeat(self):
        svc = self._svc()
        status, _ = svc.check("a1", None, 30.0)
        assert status == "NEVER"

    def test_ok_when_recent(self):
        from agent_framework.models import _now_iso
        svc = self._svc()
        status, elapsed = svc.check("a1", _now_iso(), 30.0)
        assert status == "OK"
        assert elapsed >= 0

    def test_stalled_when_very_old(self):
        # Fake a heartbeat 1000s ago
        svc = self._svc()
        old_ts = "2000-01-01T00:00:00Z"
        status, _ = svc.check("a1", old_ts, 30.0)
        assert status == "STALLED"

    def test_summary_keys(self):
        from agent_framework.models import AgentRecord
        svc = self._svc()
        rec = AgentRecord("h1", "H")
        s = svc.summary([rec])
        for k in ("total", "ok", "late", "missed", "never"):
            assert k in s


# ═══════════════════════════════════════════════════════════════════════════════
# 7. HealthMonitor
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthMonitor:
    def _mon(self):
        from agent_framework.health_monitor import HealthMonitor
        return HealthMonitor()

    def _running_rec(self):
        from agent_framework.models import AgentRecord, AgentState
        r = AgentRecord("hm1", "HM")
        r.beat()
        r.transition(AgentState.RUNNING, "test")
        r.snapshots_published = 1
        return r

    def test_healthy_running_agent_high_score(self):
        mon = self._mon()
        r = self._running_rec()
        s = mon.score(r)
        assert s >= 60

    def test_stopped_agent_low_score(self):
        from agent_framework.models import AgentRecord, AgentState
        mon = self._mon()
        r = AgentRecord("hm2", "HM2")
        r.transition(AgentState.STOPPED, "test")
        s = mon.score(r)
        assert s < 30

    def test_health_status_healthy(self):
        from agent_framework.health_monitor import HealthMonitor
        from agent_framework.models import HealthStatus
        mon = HealthMonitor()
        assert mon.health_status(80.0) == HealthStatus.HEALTHY

    def test_health_status_degraded(self):
        from agent_framework.health_monitor import HealthMonitor
        from agent_framework.models import HealthStatus
        mon = HealthMonitor()
        assert mon.health_status(50.0) == HealthStatus.DEGRADED

    def test_advisory_alerts_never_auto_restart(self):
        """All advisory alerts must have auto_action = None."""
        from agent_framework.models import AgentRecord, AgentState
        mon = self._mon()
        r = AgentRecord("stalled", "Stalled Agent")
        r.last_heartbeat = "2000-01-01T00:00:00Z"
        r.transition(AgentState.ERROR, "crash")
        alerts = mon.advisory_alerts([r])
        for alert in alerts:
            assert alert.get("auto_action") is None, \
                f"Alert has auto_action: {alert}"

    def test_overall_health_empty(self):
        mon = self._mon()
        h = mon.overall_health([])
        assert h["available"] is False

    def test_update_record_sets_score(self):
        mon = self._mon()
        r = self._running_rec()
        mon.update_record(r)
        assert r.health_score > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. AgentScheduler
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentScheduler:
    def _sched(self):
        from agent_framework.scheduler import AgentScheduler
        return AgentScheduler()

    def test_schedule_and_tick(self):
        sched = self._sched()
        ran = []
        sched.schedule("t1", lambda: ran.append(1), interval_s=0)
        result = sched.tick(now=time.monotonic() + 1)
        assert "t1" in result
        assert ran == [1]

    def test_periodic_not_re_run_before_interval(self):
        sched = self._sched()
        ran = []
        sched.schedule("p1", lambda: ran.append(1), interval_s=60)
        now = time.monotonic()
        sched.tick(now=now)
        sched.tick(now=now + 1)  # not due
        assert len(ran) <= 1

    def test_periodic_reruns_after_interval(self):
        sched = self._sched()
        ran = []
        sched.schedule("p2", lambda: ran.append(1), interval_s=1)
        now = time.monotonic()
        sched.tick(now=now)
        sched.tick(now=now + 2)  # due again
        assert len(ran) == 2

    def test_one_shot_runs_once(self):
        sched = self._sched()
        ran = []
        sched.run_once("once", lambda: ran.append(1))
        now = time.monotonic() + 1
        sched.tick(now=now)
        sched.tick(now=now + 1)
        assert len(ran) == 1

    def test_cancel_prevents_execution(self):
        sched = self._sched()
        ran = []
        sched.schedule("cancel_me", lambda: ran.append(1), interval_s=0)
        sched.cancel("cancel_me")
        sched.tick(now=time.monotonic() + 1)
        assert len(ran) == 0

    def test_error_in_task_does_not_propagate(self):
        sched = self._sched()
        sched.schedule("err", lambda: (_ for _ in ()).throw(RuntimeError("boom")), interval_s=0)
        ran = sched.tick(now=time.monotonic() + 1)
        assert "err" in ran  # task ran (even though it errored)

    def test_status_output(self):
        sched = self._sched()
        sched.schedule("s1", lambda: None, interval_s=5)
        status = sched.status()
        assert len(status) == 1
        assert status[0]["task_id"] == "s1"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. FrameworkMetrics + ScalabilityEstimator
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrameworkMetrics:
    def test_aggregate_empty(self):
        from agent_framework.metrics import FrameworkMetrics
        result = FrameworkMetrics.aggregate([])
        assert result["agent_count"] == 0

    def test_aggregate_with_records(self):
        from agent_framework.metrics import FrameworkMetrics
        from agent_framework.models import AgentRecord, AgentState
        r = AgentRecord("m1", "M")
        r.transition(AgentState.RUNNING, "x")
        r.snapshots_published = 5
        result = FrameworkMetrics.aggregate([r])
        assert result["agent_count"] == 1
        assert result["total_snapshots_published"] == 5

    def test_scalability_estimate_structure(self):
        from agent_framework.metrics import ScalabilityEstimator
        from agent_framework.models import AgentRecord
        rec = AgentRecord("sc1", "SC")
        est = ScalabilityEstimator.estimate([rec], current_symbols=50)
        for k in ("current_monitored_symbols", "safe_capacity_symbols", "estimated_max_capacity",
                  "current_scan_interval_s", "recommended_scan_interval_s",
                  "current_agent_count", "future_agents_supported", "advisory_only"):
            assert k in est, f"Missing: {k}"

    def test_scalability_advisory_flag(self):
        from agent_framework.metrics import ScalabilityEstimator
        from agent_framework.models import AgentRecord
        est = ScalabilityEstimator.estimate([AgentRecord("s1", "S")], 0)
        assert est["advisory_only"] is True

    def test_scalability_utilisation(self):
        from agent_framework.metrics import ScalabilityEstimator
        from agent_framework.models import AgentRecord
        rec = AgentRecord("u1", "U")
        est = ScalabilityEstimator.estimate([rec], current_symbols=50)
        assert est["utilisation_pct"] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Feature Flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlags:
    def test_disabled_response_has_required_keys(self):
        from agent_framework.config import disabled_response, SUPERVISOR_AGENT_ENABLED
        r = disabled_response(SUPERVISOR_AGENT_ENABLED)
        assert r["available"] is False
        assert r["advisory_only"] is True
        assert SUPERVISOR_AGENT_ENABLED in r["message"]

    def test_is_supervisor_enabled_default_true(self):
        from agent_framework.config import is_supervisor_enabled
        # Default should be enabled unless explicitly set to false
        # In test env, env var not set → default true
        import os
        os.environ.pop("SUPERVISOR_AGENT_ENABLED", None)
        assert is_supervisor_enabled() is True

    def test_is_supervisor_disabled_when_flag_false(self):
        from agent_framework.config import is_supervisor_enabled
        import os
        os.environ["SUPERVISOR_AGENT_ENABLED"] = "false"
        assert is_supervisor_enabled() is False
        os.environ.pop("SUPERVISOR_AGENT_ENABLED", None)

    def test_all_flags_default_true(self):
        from agent_framework.config import (
            is_supervisor_enabled, is_market_data_enabled, is_research_enabled
        )
        import os
        for k in ("SUPERVISOR_AGENT_ENABLED", "MARKET_DATA_AGENT_ENABLED", "RESEARCH_AGENT_ENABLED"):
            os.environ.pop(k, None)
        assert is_supervisor_enabled()
        assert is_market_data_enabled()
        assert is_research_enabled()


# ═══════════════════════════════════════════════════════════════════════════════
# 11. BaseAgent (concrete stub)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaseAgent:
    def _make_agent(self):
        from agent_framework.base_agent import BaseAgent
        class StubAgent(BaseAgent):
            def __init__(self):
                super().__init__("stub-agent", "Stub Agent", priority=3)
                self._counter = 0
            @property
            def default_topic(self):
                return "stub"
            def execute_task(self):
                self._counter += 1
                return {"count": self._counter}
        return StubAgent()

    def test_agent_registered_on_init(self):
        from agent_framework.agent_registry import AgentRegistry
        a = self._make_agent()
        assert AgentRegistry.instance().get("stub-agent") is not None

    def test_start_changes_state(self):
        from agent_framework.models import AgentState
        a = self._make_agent()
        a.start()
        assert a.state == AgentState.RUNNING

    def test_beat_updates_heartbeat(self):
        a = self._make_agent()
        a.beat()
        assert a.record.last_heartbeat is not None

    def test_execute_task_returns_payload(self):
        a = self._make_agent()
        result = a.execute_task()
        assert result is not None
        assert "count" in result

    def test_publish_increments_counter(self):
        a = self._make_agent()
        a.start()
        a.publish({"x": 1})
        assert a.record.snapshots_published == 1

    def test_enqueue_dequeue(self):
        a = self._make_agent()
        a.enqueue("task A")
        a.enqueue("task B")
        assert a.dequeue() == "task A"

    def test_stop_changes_state(self):
        from agent_framework.models import AgentState
        a = self._make_agent()
        a.start()
        a.stop("done")
        assert a.state == AgentState.STOPPED

    def test_to_dict_has_uptime(self):
        a = self._make_agent()
        d = a.to_dict()
        assert "uptime_s" in d


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Supervisor — advisory-only guarantee
# ═══════════════════════════════════════════════════════════════════════════════

class TestSupervisor:
    def _sup(self):
        from supervisor_agent.supervisor import SupervisorAgent
        return SupervisorAgent()

    def test_snapshot_structure(self):
        sup = self._sup()
        s = sup.snapshot()
        for k in ("available", "advisory_only", "read_only", "overall_health",
                  "agent_summary", "framework_metrics", "alerts", "generated_at"):
            assert k in s, f"Missing key: {k}"

    def test_advisory_only_flag(self):
        sup = self._sup()
        s = sup.snapshot()
        assert s["advisory_only"] is True
        assert s["read_only"] is True

    def test_alerts_have_no_auto_restart(self):
        """The supervisor MUST NEVER auto-restart agents."""
        from agent_framework.models import AgentRecord, AgentState
        from agent_framework.agent_registry import AgentRegistry
        rec = AgentRecord("fail-agent", "Failing")
        rec.last_heartbeat = "2000-01-01T00:00:00Z"
        rec.transition(AgentState.ERROR, "crash")
        AgentRegistry.instance().register(rec)
        sup = self._sup()
        alerts = sup.alerts()
        for alert in alerts.get("alerts", []):
            assert alert.get("auto_action") is None, \
                f"Supervisor issued auto_action: {alert}"

    def test_agent_list_includes_registered(self):
        from agent_framework.models import AgentRecord
        from agent_framework.agent_registry import AgentRegistry
        rec = AgentRecord("list-agent", "Listed")
        AgentRegistry.instance().register(rec)
        sup = self._sup()
        agents = sup.agent_list()
        assert any(a["agent_id"] == "list-agent" for a in agents)

    def test_agent_detail_unknown_returns_none(self):
        sup = self._sup()
        assert sup.agent_detail("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 13. MarketDataAgent snapshot shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketDataAgentSnapshot:
    def test_snapshot_required_fields(self):
        from market_data_agent.agent import MarketDataAgent
        agent = MarketDataAgent()
        agent.start()
        agent.beat()
        payload = agent.execute_task()
        # Must exist (may be None values for empty env)
        for k in ("agent_id", "agent_name", "advisory_only", "read_only",
                  "symbols_count", "watchlist_count", "india_vix_status",
                  "market_regime", "generated_at"):
            assert k in payload, f"Missing: {k}"

    def test_advisory_only(self):
        from market_data_agent.agent import MarketDataAgent
        agent = MarketDataAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        assert payload["advisory_only"] is True
        assert payload["read_only"] is True

    def test_no_analysis_fields(self):
        """Market Data Agent must not include analysis or recommendation fields."""
        from market_data_agent.agent import MarketDataAgent
        agent = MarketDataAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        forbidden = ["buy_recommendation", "sell_signal", "order", "strategy_score"]
        for f in forbidden:
            assert f not in payload, f"Forbidden field found: {f}"

    def test_publishes_to_bus(self):
        from market_data_agent.agent import MarketDataAgent
        from agent_framework.snapshot_bus import SnapshotBus
        agent = MarketDataAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        agent.publish(payload, "market_data")
        env = SnapshotBus.instance().latest("market_data")
        assert env is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 14. ResearchAgent snapshot shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearchAgentSnapshot:
    def test_snapshot_required_fields(self):
        from research_agent.agent import ResearchAgent
        agent = ResearchAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        for k in ("agent_id", "agent_name", "advisory_only", "read_only",
                  "announcement_count", "earnings_count", "economic_event_count",
                  "macro_event_count", "sector_news_count", "total_research_items",
                  "generated_at"):
            assert k in payload, f"Missing: {k}"

    def test_advisory_only(self):
        from research_agent.agent import ResearchAgent
        agent = ResearchAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        assert payload["advisory_only"] is True

    def test_no_recommendation_fields(self):
        from research_agent.agent import ResearchAgent
        agent = ResearchAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        forbidden = ["buy", "sell", "order", "strategy"]
        for f in forbidden:
            assert f not in payload, f"Forbidden field found: {f}"

    def test_publishes_to_bus(self):
        from research_agent.agent import ResearchAgent
        from agent_framework.snapshot_bus import SnapshotBus
        agent = ResearchAgent()
        agent.start(); agent.beat()
        payload = agent.execute_task()
        agent.publish(payload, "research")
        env = SnapshotBus.instance().latest("research")
        assert env is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Error / failure handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailureHandling:
    def test_error_state_propagation(self):
        from agent_framework.models import AgentRecord, AgentState
        from agent_framework.lifecycle_manager import LifecycleManager
        lm = LifecycleManager()
        r = AgentRecord("err-agent", "Error Agent")
        lm.start(r)
        ok, msg = lm.mark_error(r, "Simulated failure")
        assert ok
        assert r.state == AgentState.ERROR
        assert "Simulated failure" in r.state_reason

    def test_error_to_stopped_valid(self):
        from agent_framework.models import AgentRecord, AgentState
        from agent_framework.lifecycle_manager import LifecycleManager
        lm = LifecycleManager()
        r = AgentRecord("err2", "Error 2")
        lm.start(r)
        lm.mark_error(r, "crash")
        ok, _ = lm.stop(r, "manual shutdown after error")
        assert ok
        assert r.state == AgentState.STOPPED

    def test_scheduler_error_does_not_halt_other_tasks(self):
        from agent_framework.scheduler import AgentScheduler
        sched = AgentScheduler()
        ran = []
        sched.schedule("bad",  lambda: 1/0, interval_s=0)
        sched.schedule("good", lambda: ran.append(True), interval_s=0)
        sched.tick(now=time.monotonic() + 1)
        assert ran == [True]

    def test_snapshot_bus_subscriber_error_does_not_propagate(self):
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        def bad_cb(e): raise RuntimeError("subscriber error")
        bus.subscribe("err_topic", bad_cb)
        # Should not raise
        bus.publish("err_topic", "p", {"ok": True})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
