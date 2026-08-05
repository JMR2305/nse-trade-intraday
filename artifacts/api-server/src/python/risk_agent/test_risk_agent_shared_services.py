"""
test_risk_agent_shared_services.py — Task 313

Unit tests for risk_agent/shared_services.py (get_risk_snapshot) and the
_collect_risk collector in ops_centre.py.

Three-level fallback coverage:
  Path A: SnapshotBus cache hit              → available=True  (bus path)
  Path B: Bus empty, agent computes fresh    → available=True  (agent path)
  Path C: Bus + agent both fail/empty,       → available=True  (phase20 path)
           but phase20 KV has data
  Path D: All three levels return nothing    → available=False (never raises)

All I/O is mocked — zero real database, broker, or network calls.
READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# ── Helpers: bus & agent reset ────────────────────────────────────────────────

def _reset_bus():
    """Reset the SnapshotBus singleton so each test gets an empty bus."""
    from agent_framework.snapshot_bus import SnapshotBus
    SnapshotBus.reset()


def _reset_agent_singleton():
    """Force the module-level _agent singleton back to None between tests."""
    import risk_agent.shared_services as _ss
    _ss._agent = None


def _publish_to_bus(payload: dict, topic: str = "risk"):
    """Put a payload into the SnapshotBus under *topic*."""
    from agent_framework.snapshot_bus import SnapshotBus
    SnapshotBus.instance().publish(topic, "test-publisher", payload)


# ── Fixture builders ──────────────────────────────────────────────────────────

def _make_bus_payload(**overrides):
    base = {
        "available": True,
        "advisory_only": True,
        "risk_level": "LOW",
        "risk_score": 88.0,
        "generated_at": "2026-08-05T09:00:00Z",
        "candidates_evaluated": 10,
        "approved": 8,
        "rejected": 2,
        "rejection_reasons": ["Max Loss Gate"],
    }
    base.update(overrides)
    return base


def _make_phase20_kv(**overrides):
    base = {
        "candidates": [
            {"eligible": True, "sizing": {"rr_ratio": 2.5}},
            {"eligible": False, "failed_gates": ["max_loss_gate"], "sizing": {}},
        ],
        "eligible_count": 1,
        "blocked_count": 1,
        "evaluated_at": "2026-08-05T09:00:00Z",
        "scan_id": "scan_abc",
        "snapshot_ts": "2026-08-05T09:00:00Z",
        "global_pass": True,
        "global_gates": ["daily_loss", "volatility"],
        "market_state": "OPEN",
    }
    base.update(overrides)
    return base


def _make_mock_agent(payload=None):
    agent = MagicMock()
    agent.execute_task.return_value = payload or {
        "available": True,
        "risk_level": "MODERATE",
        "risk_score": 72.0,
        "generated_at": "2026-08-05T09:05:00Z",
        "candidates_evaluated": 5,
        "approved": 4,
        "rejected": 1,
    }
    return agent


# ═══════════════════════════════════════════════════════════════════════════════
# Path A: SnapshotBus cache hit
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRiskSnapshotPathA_BusHit(unittest.TestCase):
    """Path A: SnapshotBus has a cached snapshot — returned immediately."""

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()

    def tearDown(self):
        _reset_bus()
        _reset_agent_singleton()

    def test_bus_hit_returns_available_true(self):
        import risk_agent.shared_services as ss
        _publish_to_bus(_make_bus_payload())
        result = ss.get_risk_snapshot()
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("available"), "Bus hit must set available=True")

    def test_bus_hit_sets_from_cache_flag(self):
        import risk_agent.shared_services as ss
        _publish_to_bus(_make_bus_payload())
        result = ss.get_risk_snapshot()
        self.assertTrue(result.get("from_cache"), "Bus hit must mark from_cache=True")

    def test_bus_hit_preserves_risk_level(self):
        import risk_agent.shared_services as ss
        _publish_to_bus(_make_bus_payload(risk_level="MODERATE"))
        result = ss.get_risk_snapshot()
        self.assertEqual(result.get("risk_level"), "MODERATE")

    def test_bus_hit_supplements_missing_candidate_counts_from_phase20(self):
        """If bus payload lacks candidates_evaluated, phase20 data fills it in."""
        import risk_agent.shared_services as ss
        payload = {
            "available": True,
            "risk_level": "LOW",
            "risk_score": 90.0,
            "generated_at": "2026-08-05T09:00:00Z",
            # deliberately NO candidates_evaluated
        }
        _publish_to_bus(payload)

        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio", return_value={
                "positions": [], "cash": 100000.0,
                "invested_value": 0.0, "total_value": 100000.0,
            }):
                result = ss.get_risk_snapshot()

        self.assertTrue(result.get("available"))
        self.assertIn("candidates_evaluated", result)
        self.assertGreaterEqual(result["candidates_evaluated"], 0)

    def test_bus_hit_does_not_call_agent(self):
        """When bus has data the agent's execute_task must NOT be called."""
        import risk_agent.shared_services as ss
        _publish_to_bus(_make_bus_payload())
        with patch("risk_agent.shared_services._get_agent") as mock_get:
            ss.get_risk_snapshot()
        mock_get.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Path B: Bus empty, agent computes fresh
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRiskSnapshotPathB_AgentCompute(unittest.TestCase):
    """Path B: Bus is empty; agent's execute_task() provides the snapshot."""

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()
        # Ensure phase20 KV is empty so we don't slip into path C
        self._p20_patcher = patch("phase20_store.kv_get", return_value=None)
        self._p20_patcher.start()

    def tearDown(self):
        self._p20_patcher.stop()
        _reset_bus()
        _reset_agent_singleton()

    def test_agent_compute_returns_available_true(self):
        import risk_agent.shared_services as ss
        mock_agent = _make_mock_agent()
        with patch("risk_agent.shared_services._get_agent", return_value=mock_agent):
            result = ss.get_risk_snapshot()
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("available"))

    def test_agent_compute_sets_available_when_missing_from_payload(self):
        """execute_task() payload that lacks `available` gets it injected."""
        import risk_agent.shared_services as ss
        payload = {
            "risk_level": "HIGH",
            "risk_score": 45.0,
            "generated_at": "2026-08-05T09:05:00Z",
            "candidates_evaluated": 3,
            # no `available` key
        }
        mock_agent = _make_mock_agent(payload)
        with patch("risk_agent.shared_services._get_agent", return_value=mock_agent):
            result = ss.get_risk_snapshot()
        self.assertTrue(result.get("available"))

    def test_agent_compute_calls_beat_and_execute(self):
        import risk_agent.shared_services as ss
        mock_agent = _make_mock_agent()
        with patch("risk_agent.shared_services._get_agent", return_value=mock_agent):
            ss.get_risk_snapshot()
        mock_agent.beat.assert_called()
        mock_agent.execute_task.assert_called_once()

    def test_agent_returning_none_falls_through_gracefully(self):
        """If agent returns None the function must still return a dict."""
        import risk_agent.shared_services as ss
        mock_agent = MagicMock()
        mock_agent.execute_task.return_value = None
        with patch("risk_agent.shared_services._get_agent", return_value=mock_agent):
            result = ss.get_risk_snapshot()
        self.assertIsInstance(result, dict)
        self.assertIn("available", result)

    def test_agent_exception_is_swallowed(self):
        """Agent raising an exception must not propagate — falls through."""
        import risk_agent.shared_services as ss
        mock_agent = MagicMock()
        mock_agent.execute_task.side_effect = RuntimeError("simulated agent crash")
        with patch("risk_agent.shared_services._get_agent", return_value=mock_agent):
            try:
                result = ss.get_risk_snapshot()
            except Exception as exc:
                self.fail(f"Agent exception must not propagate: {exc}")
        self.assertIn("available", result)


# ═══════════════════════════════════════════════════════════════════════════════
# Path C: Phase-20 KV fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRiskSnapshotPathC_Phase20Fallback(unittest.TestCase):
    """Path C: Bus empty, agent fails — phase20 KV provides the snapshot."""

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()
        # Patch paper_trader so capital fields are stable
        self._pt_patcher = patch("paper_trader.get_portfolio", return_value={
            "positions": [], "cash": 100000.0,
            "invested_value": 0.0, "total_value": 100000.0,
        })
        self._pt_patcher.start()

    def tearDown(self):
        self._pt_patcher.stop()
        _reset_bus()
        _reset_agent_singleton()

    @staticmethod
    def _agent_none_patch():
        mock_agent = MagicMock()
        mock_agent.execute_task.return_value = None
        return patch("risk_agent.shared_services._get_agent", return_value=mock_agent)

    def test_phase20_fallback_returns_available_true(self):
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("available"))

    def test_phase20_fallback_source_label(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=_make_phase20_kv()):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertEqual(result.get("source"), "phase20_evaluation")

    def test_phase20_fallback_computes_risk_score(self):
        """risk_score = approval_rate: 1 eligible / 2 total → 50.0."""
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=_make_phase20_kv()):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertEqual(result.get("risk_score"), 50.0)

    def test_phase20_fallback_includes_candidate_counts(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=_make_phase20_kv()):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertEqual(result.get("candidates_evaluated"), 2)
        self.assertEqual(result.get("approved"), 1)
        self.assertEqual(result.get("rejected"), 1)

    def test_phase20_fallback_collects_rejection_reasons(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=_make_phase20_kv()):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        reasons = result.get("rejection_reasons", [])
        self.assertIsInstance(reasons, list)
        self.assertTrue(any("Max Loss Gate" in r for r in reasons),
                        f"Expected 'Max Loss Gate' in rejection_reasons, got: {reasons}")

    def test_phase20_all_approved_gives_100_score(self):
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        kv["candidates"] = [
            {"eligible": True, "sizing": {"rr_ratio": 3.0}},
            {"eligible": True, "sizing": {"rr_ratio": 2.0}},
        ]
        kv["eligible_count"] = 2
        kv["blocked_count"] = 0
        with patch("phase20_store.kv_get", return_value=kv):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertEqual(result.get("risk_score"), 100.0)
        self.assertEqual(result.get("risk_level"), "LOW")

    def test_phase20_empty_candidates_defaults_to_100_pct(self):
        """No candidates → approval_rate defaults to 100.0 (nothing to reject)."""
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        kv["candidates"] = []
        kv["eligible_count"] = 0
        kv["blocked_count"] = 0
        with patch("phase20_store.kv_get", return_value=kv):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertTrue(result.get("available"))
        self.assertEqual(result.get("risk_score"), 100.0)

    def test_phase20_avg_rr_computed_from_sizing(self):
        """reward_risk is the average rr_ratio across all candidates."""
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        kv["candidates"] = [
            {"eligible": True,  "sizing": {"rr_ratio": 3.0}},
            {"eligible": False, "sizing": {"rr_ratio": 1.0}, "failed_gates": []},
        ]
        with patch("phase20_store.kv_get", return_value=kv):
            with self._agent_none_patch():
                result = ss.get_risk_snapshot()
        self.assertAlmostEqual(result.get("reward_risk"), 2.0)

    def test_phase20_portfolio_capital_folded_in(self):
        """capital_available should reflect the paper_trader cash balance."""
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio", return_value={
                "positions": [], "cash": 55000.0,
                "invested_value": 10000.0, "total_value": 65000.0,
            }):
                with self._agent_none_patch():
                    result = ss.get_risk_snapshot()
        self.assertEqual(result.get("capital_available"), 55000.0)

    def test_phase20_paper_trader_crash_still_returns_available_true(self):
        """Even if paper_trader raises, phase20 data gives available=True."""
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio",
                       side_effect=RuntimeError("portfolio DB offline")):
                with self._agent_none_patch():
                    result = ss.get_risk_snapshot()
        self.assertTrue(result.get("available"))


# ═══════════════════════════════════════════════════════════════════════════════
# Path D: Clean-slate — nothing available
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRiskSnapshotPathD_CleanSlate(unittest.TestCase):
    """Path D: Bus empty, agent returns nothing, phase20 KV empty.
    Function must return available=False and must NEVER raise.
    """

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()
        self._p20_patcher = patch("phase20_store.kv_get", return_value=None)
        self._p20_patcher.start()
        self._agent_patcher = patch(
            "risk_agent.shared_services._get_agent",
            return_value=MagicMock(execute_task=MagicMock(return_value=None)),
        )
        self._agent_patcher.start()

    def tearDown(self):
        self._p20_patcher.stop()
        self._agent_patcher.stop()
        _reset_bus()
        _reset_agent_singleton()

    def _call(self):
        import risk_agent.shared_services as ss
        return ss.get_risk_snapshot()

    def test_clean_slate_returns_dict_not_raises(self):
        try:
            result = self._call()
        except Exception as exc:
            self.fail(f"get_risk_snapshot() raised unexpectedly: {exc}")
        self.assertIsInstance(result, dict)

    def test_clean_slate_available_is_false(self):
        result = self._call()
        self.assertFalse(result.get("available"),
                         "Clean slate must set available=False")

    def test_clean_slate_includes_error_message(self):
        result = self._call()
        self.assertIn("error", result)
        self.assertIsInstance(result["error"], str)
        self.assertTrue(result["error"])  # non-empty

    def test_clean_slate_advisory_only_flag_present(self):
        result = self._call()
        self.assertTrue(result.get("advisory_only"))


# ═══════════════════════════════════════════════════════════════════════════════
# Guarantee: get_risk_snapshot() never raises regardless of failure mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRiskSnapshotNeverRaises(unittest.TestCase):

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()

    def tearDown(self):
        _reset_bus()
        _reset_agent_singleton()

    def _call_safely(self, extra_patches=()):
        import risk_agent.shared_services as ss
        try:
            result = ss.get_risk_snapshot()
        except Exception as exc:
            self.fail(
                f"get_risk_snapshot() must never raise. "
                f"Got: {type(exc).__name__}: {exc}"
            )
        return result

    def test_no_exception_when_bus_latest_raises(self):
        from agent_framework.snapshot_bus import SnapshotBus
        with patch.object(SnapshotBus, "latest", side_effect=OSError("bus crash")):
            with patch("risk_agent.shared_services._get_agent",
                       return_value=MagicMock(execute_task=MagicMock(return_value=None))):
                with patch("phase20_store.kv_get", return_value=None):
                    result = self._call_safely()
        self.assertIn("available", result)

    def test_no_exception_when_phase20_store_raises(self):
        with patch("risk_agent.shared_services._get_agent",
                   return_value=MagicMock(execute_task=MagicMock(return_value=None))):
            with patch("phase20_store.kv_get", side_effect=Exception("DB offline")):
                result = self._call_safely()
        self.assertIn("available", result)

    def test_no_exception_when_paper_trader_raises_in_phase20_path(self):
        """Phase20 path calls paper_trader; a crash there must not propagate."""
        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio",
                       side_effect=RuntimeError("portfolio DB offline")):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=MagicMock(execute_task=MagicMock(return_value=None))):
                    result = self._call_safely()
        # Phase20 should still succeed (paper_trader failure zeroes capital fields)
        self.assertTrue(result.get("available"))

    def test_always_returns_dict_with_available_key(self):
        with patch("risk_agent.shared_services._get_agent",
                   return_value=MagicMock(execute_task=MagicMock(return_value=None))):
            with patch("phase20_store.kv_get", return_value=None):
                result = self._call_safely()
        self.assertIn("available", result)
        self.assertIsInstance(result["available"], bool)


class TestGetRiskSnapshotDisabled(unittest.TestCase):
    """When RISK_AGENT_ENABLED=false the disabled_response is returned."""

    def setUp(self):
        _reset_bus()
        _reset_agent_singleton()
        os.environ["RISK_AGENT_ENABLED"] = "false"

    def tearDown(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()

    def test_disabled_returns_dict(self):
        import risk_agent.shared_services as ss
        result = ss.get_risk_snapshot()
        self.assertIsInstance(result, dict)

    def test_disabled_available_is_false(self):
        import risk_agent.shared_services as ss
        result = ss.get_risk_snapshot()
        self.assertFalse(result.get("available"))


# ═══════════════════════════════════════════════════════════════════════════════
# _snapshot_from_phase20() — direct unit tests for the Level-3 helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshotFromPhase20(unittest.TestCase):

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        self._pt_patcher = patch("paper_trader.get_portfolio", return_value={
            "positions": [], "cash": 100000.0,
            "invested_value": 0.0, "total_value": 100000.0,
        })
        self._pt_patcher.start()

    def tearDown(self):
        self._pt_patcher.stop()

    def test_returns_none_when_kv_empty(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=None):
            result = ss._snapshot_from_phase20()
        self.assertIsNone(result)

    def test_returns_none_when_kv_dict_empty(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value={}):
            result = ss._snapshot_from_phase20()
        self.assertIsNone(result)

    def test_returns_dict_when_kv_populated(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=_make_phase20_kv()):
            result = ss._snapshot_from_phase20()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_available_always_true_when_kv_populated(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", return_value=_make_phase20_kv()):
            result = ss._snapshot_from_phase20()
        self.assertTrue(result["available"])

    def test_risk_level_critical_when_zero_approval(self):
        import risk_agent.shared_services as ss
        kv = _make_phase20_kv()
        kv["candidates"] = [
            {"eligible": False, "failed_gates": ["gate_a"], "sizing": {}},
            {"eligible": False, "failed_gates": ["gate_b"], "sizing": {}},
            {"eligible": False, "failed_gates": ["gate_c"], "sizing": {}},
            {"eligible": False, "failed_gates": ["gate_d"], "sizing": {}},
        ]
        kv["eligible_count"] = 0
        kv["blocked_count"] = 4
        with patch("phase20_store.kv_get", return_value=kv):
            result = ss._snapshot_from_phase20()
        self.assertEqual(result["risk_level"], "CRITICAL")
        self.assertEqual(result["risk_score"], 0.0)

    def test_returns_none_when_store_raises(self):
        import risk_agent.shared_services as ss
        with patch("phase20_store.kv_get", side_effect=Exception("DB error")):
            result = ss._snapshot_from_phase20()
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# ops_centre._collect_risk() — card status driven by available flag
# ═══════════════════════════════════════════════════════════════════════════════

def _snap_available(**overrides):
    base = {
        "available": True,
        "advisory_only": True,
        "risk_level": "LOW",
        "risk_score": 88.0,
        "generated_at": "2026-08-05T09:00:00Z",
        "candidates_evaluated": 10,
        "approved": 8,
        "rejected": 2,
        "rejection_reasons": ["Capital Breach"],
        "capital_used": 20000.0,
        "capital_used_pct": 20.0,
        "capital_available": 80000.0,
        "open_positions": 2,
        "reward_risk": 2.5,
        "global_pass": True,
        "source": "phase20_evaluation",
    }
    base.update(overrides)
    return base


def _snap_unavailable(**overrides):
    base = {
        "available": False,
        "advisory_only": True,
        "error": "Risk snapshot unavailable — no scan has run yet",
    }
    base.update(overrides)
    return base


def _call_collect_risk_with(snapshot):
    """Patch ops_centre._get_fn to return get_risk_snapshot → snapshot."""
    def fake_get_fn(mod, fn):
        if mod == "risk_agent.shared_services" and fn == "get_risk_snapshot":
            return lambda: snapshot
        return None

    with patch("ops_centre._get_fn", side_effect=fake_get_fn):
        return ops_centre._collect_risk()


import ops_centre  # noqa: E402 — imported after env is set up


class TestCollectRiskCardStatus(unittest.TestCase):
    """_collect_risk() must map available→ACTIVE and not-available→ERROR."""

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"

    # ── available=True paths ─────────────────────────────────────────────────

    def test_active_when_available_true(self):
        card = _call_collect_risk_with(_snap_available())
        self.assertEqual(card["status"], "ACTIVE")

    def test_active_after_phase20_fallback_source(self):
        snap = _snap_available(source="phase20_evaluation")
        card = _call_collect_risk_with(snap)
        self.assertEqual(card["status"], "ACTIVE")

    def test_active_with_zero_candidates_stale_valid_snapshot(self):
        """
        A stale-but-valid snapshot (0 candidates) must show ACTIVE, not WAITING.
        WAITING is reserved for the available=False case only.
        """
        snap = _snap_available(candidates_evaluated=0, approved=0, rejected=0)
        card = _call_collect_risk_with(snap)
        self.assertEqual(card["status"], "ACTIVE",
                         "Stale-but-valid snapshot must be ACTIVE, not WAITING")

    def test_active_card_enabled_true(self):
        card = _call_collect_risk_with(_snap_available())
        self.assertTrue(card["enabled"])

    def test_active_card_health_pct_positive(self):
        card = _call_collect_risk_with(_snap_available())
        self.assertGreater(card["health_pct"], 0)

    def test_active_card_details_populated(self):
        card = _call_collect_risk_with(_snap_available())
        details = card.get("details", {})
        self.assertIn("risk_score", details)
        self.assertIn("risk_level", details)
        self.assertIn("candidates_evaluated", details)

    def test_active_card_stocks_in_matches_candidates_evaluated(self):
        snap = _snap_available(candidates_evaluated=12, approved=10)
        card = _call_collect_risk_with(snap)
        self.assertEqual(card["stocks_in"], 12)
        self.assertEqual(card["stocks_out"], 10)

    def test_active_card_rejection_reason_filled(self):
        snap = _snap_available(
            rejection_reasons=["Capital Breach", "Max Loss Gate"],
            rejected=3,
        )
        card = _call_collect_risk_with(snap)
        self.assertIn("Capital Breach", card["rejection_reason"])

    def test_active_card_data_source_in_details(self):
        snap = _snap_available(source="phase20_evaluation")
        card = _call_collect_risk_with(snap)
        self.assertEqual(card["details"]["data_source"], "phase20_evaluation")

    def test_active_card_global_gates_pass_shown(self):
        snap = _snap_available(global_pass=True)
        card = _call_collect_risk_with(snap)
        self.assertIn("✓ Pass", card["details"]["global_gates_pass"])

    def test_active_card_global_gates_fail_shown(self):
        snap = _snap_available(global_pass=False)
        card = _call_collect_risk_with(snap)
        self.assertIn("✗ Fail", card["details"]["global_gates_pass"])

    # ── available=False path ─────────────────────────────────────────────────

    def test_error_when_available_false(self):
        """No scan data → card status must be ERROR."""
        card = _call_collect_risk_with(_snap_unavailable())
        self.assertEqual(card["status"], "ERROR")

    def test_waiting_activity_when_no_scan(self):
        card = _call_collect_risk_with(_snap_unavailable())
        self.assertIn("Waiting", card["current_activity"])

    def test_error_card_health_is_zero(self):
        card = _call_collect_risk_with(_snap_unavailable())
        self.assertEqual(card["health_pct"], 0)

    def test_error_card_errors_list_non_empty(self):
        card = _call_collect_risk_with(_snap_unavailable())
        self.assertTrue(card["errors"])

    def test_snapshot_none_treated_as_error(self):
        """If the snapshot callable returns None the card must be ERROR."""
        def fake_get_fn(mod, fn):
            if mod == "risk_agent.shared_services" and fn == "get_risk_snapshot":
                return lambda: None
            return None

        with patch("ops_centre._get_fn", side_effect=fake_get_fn):
            card = ops_centre._collect_risk()
        self.assertEqual(card["status"], "ERROR")

    # ── Disabled ─────────────────────────────────────────────────────────────

    def test_disabled_status_when_env_off(self):
        os.environ["RISK_AGENT_ENABLED"] = "false"
        try:
            with patch("ops_centre._get_fn", return_value=None):
                card = ops_centre._collect_risk()
            self.assertEqual(card["status"], "DISABLED")
        finally:
            os.environ["RISK_AGENT_ENABLED"] = "true"


# ═══════════════════════════════════════════════════════════════════════════════
# Restart simulation: clean-slate and post-first-scan behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollectRiskAfterRestartNoScanData(unittest.TestCase):
    """Simulate a full restart with no prior scan data, then after first scan."""

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"

    def test_card_error_on_clean_restart(self):
        """
        Phase-20 KV empty + no bus cache → get_risk_snapshot returns available=False.
        _collect_risk must surface ERROR, never crash.
        """
        no_scan = _snap_unavailable()
        try:
            card = _call_collect_risk_with(no_scan)
        except Exception as exc:
            self.fail(f"_collect_risk() must not raise on clean restart: {exc}")

        self.assertIsInstance(card, dict)
        self.assertEqual(card["status"], "ERROR",
                         "Before any scan: card must be ERROR, not ACTIVE")
        self.assertIn("Waiting", card["current_activity"])

    def test_card_active_after_first_scan(self):
        """
        Once phase20 returns data get_risk_snapshot gives available=True,
        and _collect_risk must switch to ACTIVE on every subsequent call.
        """
        snap = _snap_available(source="phase20_evaluation")
        # Simulate two calls (across restarts / repeated polls)
        for call_number in range(1, 3):
            card = _call_collect_risk_with(snap)
            self.assertEqual(
                card["status"], "ACTIVE",
                f"Call #{call_number}: card must stay ACTIVE once scan data exists",
            )

    def test_collect_risk_never_raises_on_module_not_loaded(self):
        """_collect_risk must not propagate any exception."""
        def fake_get_fn(mod, fn):
            raise RuntimeError("module not loaded yet")

        with patch("ops_centre._get_fn", side_effect=fake_get_fn):
            try:
                card = ops_centre._collect_risk()
            except Exception as exc:
                self.fail(f"_collect_risk must never raise. Got: {exc}")
        self.assertIsInstance(card, dict)
        self.assertIn("status", card)

    def test_collect_risk_never_raises_when_snapshot_raises(self):
        """Even if get_risk_snapshot() itself raises, the card must be returned."""
        def fake_get_fn(mod, fn):
            if mod == "risk_agent.shared_services" and fn == "get_risk_snapshot":
                def _raise():
                    raise RuntimeError("snapshot computation crashed")
                return _raise
            return None

        with patch("ops_centre._get_fn", side_effect=fake_get_fn):
            try:
                card = ops_centre._collect_risk()
            except Exception as exc:
                self.fail(f"_collect_risk must never raise. Got: {exc}")
        self.assertIsInstance(card, dict)
        self.assertIn("status", card)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration-style restart transition tests
#
# These tests do NOT patch ops_centre._get_fn.  _collect_risk() calls the real
# get_risk_snapshot() via the real sys.modules lookup — only the deep external
# I/O (phase20_store.kv_get, paper_trader.get_portfolio, _get_agent) is mocked.
# This validates the full chain:
#   state-reset → get_risk_snapshot() → _collect_risk() → card status
# ═══════════════════════════════════════════════════════════════════════════════

class TestRestartTransitionIntegration(unittest.TestCase):
    """
    Integration tests for the restart-transition behaviour.

    Each test resets SnapshotBus and the _agent singleton (simulating a cold
    start), then drives the *real* get_risk_snapshot() through ops_centre
    ._collect_risk() without patching _get_fn.

    The only mocked surface is external I/O:
      - phase20_store.kv_get  (Postgres KV)
      - paper_trader.get_portfolio
      - risk_agent.shared_services._get_agent  (avoids spinning up real agent)
    """

    def setUp(self):
        os.environ["RISK_AGENT_ENABLED"] = "true"
        _reset_bus()
        _reset_agent_singleton()

    def tearDown(self):
        _reset_bus()
        _reset_agent_singleton()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _agent_none():
        """Return a mock agent whose execute_task() gives None (init not done)."""
        a = MagicMock()
        a.execute_task.return_value = None
        return a

    @staticmethod
    def _portfolio_empty():
        return {"positions": [], "cash": 100000.0,
                "invested_value": 0.0, "total_value": 100000.0}

    def _call_real_chain(self):
        """
        Call _collect_risk() without patching _get_fn so the real
        get_risk_snapshot() is invoked via the sys.modules lookup.
        """
        return ops_centre._collect_risk()

    # ── cold-start (no scan data) ─────────────────────────────────────────────

    def test_cold_start_real_chain_card_is_error(self):
        """
        Full restart, no phase20 KV, no bus, agent not ready.
        Real get_risk_snapshot() returns available=False.
        Real _collect_risk() must produce status=ERROR.
        """
        with patch("phase20_store.kv_get", return_value=None):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    card = self._call_real_chain()

        self.assertIsInstance(card, dict)
        self.assertEqual(card["status"], "ERROR",
                         "Cold start: no scan data → card must be ERROR")
        self.assertIn("Waiting", card["current_activity"])

    def test_cold_start_real_chain_never_raises(self):
        """Real chain on cold start must not propagate any exception."""
        with patch("phase20_store.kv_get", return_value=None):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    try:
                        card = self._call_real_chain()
                    except Exception as exc:
                        self.fail(
                            f"Real _collect_risk() must never raise on cold start: {exc}"
                        )
        self.assertIn("status", card)

    # ── phase20-fallback path (post-scan) ─────────────────────────────────────

    def test_phase20_kv_path_real_chain_card_is_active(self):
        """
        Phase-20 KV has data (first scan ran), bus empty, agent returns None.
        Real get_risk_snapshot() reaches level-3 (phase20) → available=True.
        Real _collect_risk() must produce status=ACTIVE.
        """
        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    card = self._call_real_chain()

        self.assertEqual(card["status"], "ACTIVE",
                         "Phase-20 KV data → real get_risk_snapshot → ACTIVE card")

    def test_phase20_kv_path_details_populated(self):
        """Card details must be fully populated when coming from phase20 path."""
        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    card = self._call_real_chain()

        details = card.get("details", {})
        self.assertIn("risk_score", details)
        self.assertIn("risk_level", details)
        self.assertIn("data_source", details)
        self.assertEqual(details["data_source"], "phase20_evaluation")

    # ── agent-compute path (post-restart, agent ready) ─────────────────────────

    def test_agent_compute_path_real_chain_card_is_active(self):
        """
        Bus empty, phase20 KV empty, but agent execute_task() returns data.
        Real get_risk_snapshot() reaches level-2 (agent compute) → available=True.
        Real _collect_risk() must produce status=ACTIVE.
        """
        agent_payload = {
            "risk_level": "LOW",
            "risk_score": 82.0,
            "generated_at": "2026-08-05T09:10:00Z",
            "candidates_evaluated": 7,
            "approved": 6,
            "rejected": 1,
        }
        mock_agent = MagicMock()
        mock_agent.execute_task.return_value = agent_payload

        with patch("phase20_store.kv_get", return_value=None):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=mock_agent):
                    card = self._call_real_chain()

        self.assertEqual(card["status"], "ACTIVE",
                         "Agent compute path → real get_risk_snapshot → ACTIVE card")

    # ── bus-hit path (warm restart, bus repopulated) ───────────────────────────

    def test_bus_hit_path_real_chain_card_is_active(self):
        """
        Bus has a cached snapshot (e.g. published before restart replica).
        Real get_risk_snapshot() returns from level-1 (bus) → available=True.
        Real _collect_risk() must produce status=ACTIVE.
        """
        _publish_to_bus(_make_bus_payload(risk_level="MODERATE"))

        with patch("phase20_store.kv_get", return_value=None):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                card = self._call_real_chain()

        self.assertEqual(card["status"], "ACTIVE",
                         "Bus hit → real get_risk_snapshot → ACTIVE card")
        self.assertTrue(card["details"].get("data_source") in (None, "agent", ""),
                        "Bus hit source is not phase20 (expected plain agent or unset)")

    # ── transition: ERROR → ACTIVE across two sequential calls ──────────────────

    def test_transition_error_to_active_across_two_calls(self):
        """
        State transition test:
          Call 1: cold start (no scan data)  → status=ERROR
          Call 2: phase20 KV populated       → status=ACTIVE

        This is the core behavior of Task 313: the card must move from ERROR to
        ACTIVE when data becomes available, with no server restart required.
        """
        import risk_agent.shared_services as ss  # ensure module is in sys.modules

        # ── Phase 1: cold start ───────────────────────────────────────────────
        _reset_bus()
        _reset_agent_singleton()

        with patch("phase20_store.kv_get", return_value=None):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    # Verify get_risk_snapshot reports unavailable
                    snap_before = ss.get_risk_snapshot()
                    card_before = self._call_real_chain()

        self.assertFalse(snap_before.get("available"),
                         "Before any scan: get_risk_snapshot must return available=False")
        self.assertEqual(card_before["status"], "ERROR",
                         "Before any scan: card must be ERROR")

        # ── Phase 2: first scan completes (phase20 KV populated) ─────────────
        _reset_bus()
        _reset_agent_singleton()

        kv = _make_phase20_kv()
        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    # Verify get_risk_snapshot now reports available
                    snap_after = ss.get_risk_snapshot()
                    card_after = self._call_real_chain()

        self.assertTrue(snap_after.get("available"),
                        "After first scan: get_risk_snapshot must return available=True")
        self.assertEqual(card_after["status"], "ACTIVE",
                         "After first scan: card must be ACTIVE (not WAITING/ERROR)")

    def test_card_stays_active_across_repeated_polls_after_scan(self):
        """
        After the first scan the card must remain ACTIVE on every subsequent
        poll, simulating what happens when the operator refreshes the dashboard
        after a restart.
        """
        kv = _make_phase20_kv()

        for poll_number in range(1, 4):
            _reset_bus()
            _reset_agent_singleton()
            with patch("phase20_store.kv_get", return_value=kv):
                with patch("paper_trader.get_portfolio",
                           return_value=self._portfolio_empty()):
                    with patch("risk_agent.shared_services._get_agent",
                               return_value=self._agent_none()):
                        card = self._call_real_chain()
            self.assertEqual(
                card["status"], "ACTIVE",
                f"Poll #{poll_number} post-scan: card must stay ACTIVE",
            )

    def test_stale_valid_snapshot_card_is_active_not_waiting(self):
        """
        A phase20 snapshot with 0 candidates (stale-but-valid) must produce
        ACTIVE, not WAITING.  WAITING must only appear on the no-data path.
        """
        kv = _make_phase20_kv()
        kv["candidates"] = []
        kv["eligible_count"] = 0
        kv["blocked_count"] = 0

        _reset_bus()
        _reset_agent_singleton()

        with patch("phase20_store.kv_get", return_value=kv):
            with patch("paper_trader.get_portfolio",
                       return_value=self._portfolio_empty()):
                with patch("risk_agent.shared_services._get_agent",
                           return_value=self._agent_none()):
                    card = self._call_real_chain()

        # Card STATUS must be ACTIVE — "Waiting for pipeline candidates" in
        # current_activity is expected when total==0; that is a pipeline-level
        # description, not the card health/status indicator.
        self.assertEqual(card["status"], "ACTIVE",
                         "Stale-but-valid snapshot (0 candidates) must be ACTIVE, not ERROR/DISABLED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
