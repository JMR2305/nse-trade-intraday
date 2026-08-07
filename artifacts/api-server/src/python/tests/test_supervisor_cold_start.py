"""
test_supervisor_cold_start.py — Regression tests for pipeline cold-start
dependency violation semantics (Task #471).

SnapshotBus design constraints respected by these tests:
  • bus.latest(topic) returns None  → topic NEVER published (never_published=True)
  • bus.latest(topic) returns an envelope → topic HAS published (never_published=False)
  • bus.latest(topic) raises an exception → BUS ERROR (never_published=False, error=True)
  • No eviction path exists; a published envelope stays for the process lifetime.

Covers:
  • Pure cold start: all topics never published → no violations, cold_start=True
  • Partial publish (health-probe scenario): market_data published only → no
    spurious violations for never-published downstream topics
  • Genuine type-1 violation: child has data but parent unavailable
  • Exception path: bus.latest() raises for a topic → cold_start=False, error
    topic does NOT count as never_published
  • Exception type-2 violation: child bus-read fails, parent healthy → violation
  • Stale data: previously-published aged topics vs never-published topics
  • All healthy: no violations, no stale, cold_start=False
"""

import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


def _make_envelope(age_s: float):
    env = MagicMock()
    env.received_at = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return env


def _make_bus(topic_spec: dict):
    """
    Build a mock SnapshotBus from a spec dict:
        topic_spec = {
            "market_data": 30,       # published 30s ago → envelope returned
            "research":    None,     # never published  → None returned
            "monitoring":  "error",  # bus.latest() raises RuntimeError
        }
    """
    def latest(topic):
        val = topic_spec.get(topic)
        if val == "error":
            raise RuntimeError(f"bus read failure for {topic}")
        if val is None:
            return None
        return _make_envelope(val)

    bus = MagicMock()
    bus.latest.side_effect = latest
    bus.stats.return_value = {
        "topics": [t for t, v in topic_spec.items() if v not in (None, "error")],
        "topic_count": sum(1 for v in topic_spec.values() if v not in (None, "error")),
        "subscriber_count": 0,
        "sequences": {},
    }
    return bus


def _make_supervisor(topic_spec: dict):
    """
    Return a SupervisorAgent with all heavy dependencies mocked.
    Only SnapshotBus is wired with test behaviour.
    """
    from supervisor_agent.supervisor import SupervisorAgent

    registry = MagicMock()
    registry.all.return_value = []
    registry.summary.return_value = {
        "total": 0, "running": 0, "busy": 0,
        "idle": 0, "paused": 0, "warning": 0,
        "error": 0, "stopped": 0,
    }

    monitor = MagicMock()
    monitor.overall_health.return_value = {"score": 100, "status": "HEALTHY"}
    monitor.advisory_alerts.return_value = []

    hb_svc = MagicMock()
    hb_svc.summary.return_value = {}

    sup = SupervisorAgent.__new__(SupervisorAgent)
    sup._registry = registry
    sup._monitor  = monitor
    sup._hb_svc   = hb_svc
    sup._bus      = _make_bus(topic_spec)
    return sup


_ALL_TOPICS = [
    "market_data", "research", "market_intelligence",
    "monitoring", "strategy", "risk", "ai_decision", "execution",
]

_SPEC_NEVER = {t: None for t in _ALL_TOPICS}  # all never published


# ── Pure cold start ───────────────────────────────────────────────────────────

class TestColdStart(unittest.TestCase):
    """All topics never published → cold_start=True, no violations."""

    def setUp(self):
        self.snap = _make_supervisor(_SPEC_NEVER).snapshot()

    def test_pipeline_cold_start_true(self):
        self.assertTrue(self.snap["pipeline_cold_start"])

    def test_no_dependency_violations(self):
        self.assertEqual(self.snap["dependency_violations"], [])

    def test_all_topics_never_published(self):
        ph = self.snap["pipeline_health"]
        for topic in _ALL_TOPICS:
            self.assertTrue(ph[topic]["never_published"], f"{topic} should be never_published")
            self.assertFalse(ph[topic]["available"])
            self.assertFalse(ph[topic].get("error", False))

    def test_no_stale_topics(self):
        # never_published topics must NOT appear in stale_topics
        self.assertEqual(self.snap["stale_topics"], [])

    def test_no_stale_data_recommendation(self):
        cats = [r["category"] for r in self.snap["recommendations"]]
        self.assertNotIn("STALE_DATA", cats)


# ── Partial publish (health-probe scenario) ───────────────────────────────────

class TestPartialPublish(unittest.TestCase):
    """
    market_data published 10s ago; all downstream topics never published.
    This is what happens when the health-probe endpoint runs at server start
    before any scan has occurred.
    """

    def setUp(self):
        spec = dict(_SPEC_NEVER)
        spec["market_data"] = 10   # published and fresh
        self.snap = _make_supervisor(spec).snapshot()

    def test_pipeline_cold_start_false(self):
        # market_data published → not a pure cold start
        self.assertFalse(self.snap["pipeline_cold_start"])

    def test_no_spurious_violations(self):
        """
        market_intelligence never_published=True, market_data healthy.
        Must NOT produce a violation — downstream agents simply haven't run yet.
        """
        viols = self.snap["dependency_violations"]
        self.assertEqual(viols, [],
                         f"No violations expected for never-published downstream; got {viols}")

    def test_market_data_available_and_not_never_published(self):
        ph = self.snap["pipeline_health"]
        self.assertTrue(ph["market_data"]["available"])
        self.assertFalse(ph["market_data"]["never_published"])
        self.assertFalse(ph["market_data"].get("error", False))

    def test_downstream_never_published(self):
        ph = self.snap["pipeline_health"]
        for topic in _ALL_TOPICS:
            if topic == "market_data":
                continue
            self.assertTrue(ph[topic]["never_published"], f"{topic} must be never_published")

    def test_no_stale_topics(self):
        self.assertEqual(self.snap["stale_topics"], [])

    def test_no_stale_data_recommendation(self):
        cats = [r["category"] for r in self.snap["recommendations"]]
        self.assertNotIn("STALE_DATA", cats)


# ── Type-1 violation: child has data, parent unavailable ─────────────────────

class TestViolationType1(unittest.TestCase):
    """
    market_intelligence has published data but market_data has never published.
    This is violation type-1: always a real violation regardless of cold-start.
    """

    def setUp(self):
        spec = dict(_SPEC_NEVER)
        spec["market_intelligence"] = 20  # has data
        # market_data: None (never published) — the upstream is missing
        self.snap = _make_supervisor(spec).snapshot()

    def test_type1_violation_fires(self):
        viols = self.snap["dependency_violations"]
        self.assertTrue(
            any("market_intelligence" in v and "market_data" in v for v in viols),
            f"Expected type-1 violation for market_intelligence / market_data; got {viols}"
        )

    def test_no_spurious_violations_for_other_never_published(self):
        """monitoring, strategy etc are never_published → must not produce violations."""
        viols = self.snap["dependency_violations"]
        for topic in ("monitoring", "strategy", "risk", "ai_decision", "execution"):
            self.assertFalse(
                any(topic in v for v in viols),
                f"Unexpected violation for never-published {topic}: {viols}"
            )


# ── Exception path ────────────────────────────────────────────────────────────

class TestBusExceptionState(unittest.TestCase):
    """
    bus.latest() raises for market_data.  This is a bus-read error — distinct
    from never-published.  The error topic must not be classified as
    never_published=True, so it cannot silently contribute to cold_start suppression.
    """

    def setUp(self):
        spec = dict(_SPEC_NEVER)
        spec["market_data"] = "error"   # bus.latest() raises for this topic
        self.snap = _make_supervisor(spec).snapshot()

    def test_cold_start_false_when_error(self):
        """An error in any topic must prevent cold_start=True."""
        self.assertFalse(self.snap["pipeline_cold_start"],
                         "Bus error must not produce cold_start=True")

    def test_error_topic_not_never_published(self):
        ph = self.snap["pipeline_health"]
        self.assertFalse(ph["market_data"]["never_published"],
                         "Error state must not be classified as never_published")
        self.assertTrue(ph["market_data"].get("error", False),
                        "Error state must set error=True")
        self.assertFalse(ph["market_data"]["available"])

    def test_non_error_topics_never_published(self):
        """Non-error, non-published topics are still never_published=True."""
        ph = self.snap["pipeline_health"]
        for topic in _ALL_TOPICS:
            if topic == "market_data":
                continue
            self.assertTrue(ph[topic]["never_published"],
                            f"{topic} should be never_published (no error, no data)")


class TestBusExceptionViolationType2(unittest.TestCase):
    """
    market_data is healthy; market_intelligence bus.latest() raises (error=True).
    A type-2 violation must surface: child unavailable due to bus error despite
    parent being healthy.
    """

    def setUp(self):
        spec = dict(_SPEC_NEVER)
        spec["market_data"]         = 30     # parent: healthy
        spec["market_intelligence"] = "error"  # child: bus error
        self.snap = _make_supervisor(spec).snapshot()

    def test_type2_violation_fires_for_error_child(self):
        viols = self.snap["dependency_violations"]
        self.assertTrue(
            any("market_intelligence" in v and "bus read error" in v for v in viols),
            f"Expected type-2 error-path violation for market_intelligence; got {viols}"
        )

    def test_cold_start_false(self):
        self.assertFalse(self.snap["pipeline_cold_start"])

    def test_no_spurious_violations_for_never_published_downstream(self):
        """monitoring etc are never_published → no type-2 violations for them."""
        viols = self.snap["dependency_violations"]
        for topic in ("monitoring", "strategy", "risk", "ai_decision", "execution"):
            self.assertFalse(
                any(topic in v for v in viols),
                f"Unexpected violation for never-published {topic}: {viols}"
            )


# ── Stale flag semantics ──────────────────────────────────────────────────────

class TestStaleFlagSemantics(unittest.TestCase):
    """
    Previously-published topics with age > 600s are flagged stale.
    Never-published topics are NOT stale and must NOT appear in stale_topics.
    """

    def setUp(self):
        spec = dict(_SPEC_NEVER)
        spec["market_data"] = 700   # published but stale
        spec["research"]    = 50    # published and fresh
        self.snap = _make_supervisor(spec).snapshot()

    def test_stale_topic_flagged(self):
        ph = self.snap["pipeline_health"]
        self.assertTrue(ph["market_data"]["stale"])
        self.assertFalse(ph["market_data"]["never_published"])

    def test_fresh_topic_not_stale(self):
        ph = self.snap["pipeline_health"]
        self.assertFalse(ph["research"]["stale"])
        self.assertFalse(ph["research"]["never_published"])

    def test_never_published_not_stale(self):
        ph = self.snap["pipeline_health"]
        for topic in _ALL_TOPICS:
            if topic in ("market_data", "research"):
                continue
            self.assertFalse(ph[topic]["stale"],
                             f"{topic} is never_published; stale must be False")
            self.assertTrue(ph[topic]["never_published"])

    def test_stale_topics_list_correct(self):
        st = self.snap["stale_topics"]
        self.assertIn("market_data", st)
        for topic in _ALL_TOPICS:
            if topic != "market_data":
                self.assertNotIn(topic, st,
                                 f"Never-published / fresh {topic} must not appear in stale_topics")

    def test_stale_data_recommendation_present_and_accurate(self):
        recs = self.snap["recommendations"]
        stale_rec = next((r for r in recs if r["category"] == "STALE_DATA"), None)
        self.assertIsNotNone(stale_rec, "STALE_DATA recommendation expected")
        self.assertIn("market_data", stale_rec["message"])


# ── All healthy ───────────────────────────────────────────────────────────────

class TestFullyHealthyPipeline(unittest.TestCase):
    """All topics published and fresh → no violations, cold_start=False."""

    def setUp(self):
        spec = {t: 30 for t in _ALL_TOPICS}
        self.snap = _make_supervisor(spec).snapshot()

    def test_cold_start_false(self):
        self.assertFalse(self.snap["pipeline_cold_start"])

    def test_no_violations(self):
        self.assertEqual(self.snap["dependency_violations"], [])

    def test_no_stale_topics(self):
        self.assertEqual(self.snap["stale_topics"], [])

    def test_all_available_not_never_published_not_error(self):
        ph = self.snap["pipeline_health"]
        for topic in _ALL_TOPICS:
            self.assertTrue(ph[topic]["available"], f"{topic} should be available")
            self.assertFalse(ph[topic]["never_published"])
            self.assertFalse(ph[topic].get("error", False))
            self.assertFalse(ph[topic]["stale"])


if __name__ == "__main__":
    unittest.main()
