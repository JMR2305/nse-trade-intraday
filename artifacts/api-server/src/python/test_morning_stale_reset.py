"""
test_morning_stale_reset.py — Morning stale data reset fix verification.

Scenario: The latest scan has a snapshot_ts from the *previous* IST trading
day (≥14 h old).  Asserts that:

  1. phase15_scan_context.build_scan_context() returns is_today_session=False.
  2. pipeline_stats.get_pipeline_stats() returns empty top_buy_candidates
     and session_mismatch=True.
  3. phase11_autonomous.get_recommendation_queue() returns empty items and
     session_mismatch=True.
  4. replay_engine._build_symbol_journey() labels paper_eligible=True
     (no paper_order_id) as "ELIGIBLE" / "Paper eligible" — NOT "Paper order
     placed" / "PAPER BUY".

All external state (DB, scan cache, market_hours) is mocked — no DB writes,
no network calls, PAPER ONLY.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _yesterday_ist_ts() -> str:
    """Return an ISO timestamp that is exactly 25 hours ago (safely previous IST day)."""
    return (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )


def _today_ist_ts() -> str:
    """Return an ISO timestamp at 09:30 IST today — always within today's IST calendar date.

    Using a fixed IST clock-time (09:30) avoids the IST-midnight boundary issue where
    "UTC minus 30 minutes" can cross into the previous IST calendar day if the test
    runs between 18:30–23:59 UTC (00:00–05:29 IST next day).
    """
    today_ist_dt = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    # 09:30 IST on today's IST calendar date
    today_09_30_ist = today_ist_dt.replace(hour=9, minute=30, second=0, microsecond=0)
    today_09_30_utc = today_09_30_ist - timedelta(hours=5, minutes=30)
    return today_09_30_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _make_scan(snapshot_ts: str) -> dict:
    """Build a minimal scan snapshot dict usable by phase15 and pipeline_stats."""
    return {
        "scan_id": "test_scan_001",
        "snapshot_ts": snapshot_ts,
        "recommendations": [
            {
                "symbol": "TCS",
                "sector": "IT",
                "final_action": "BUY",
                "effective_action": "BUY",
                "opportunity_score": 80.0,
                "technical_score": 75.0,
                "calibrated_confidence": 82.0,
                "data_quality": "LIVE",
                "all_gates_passed": True,
                "paper_eligible": True,
                "strategy_id": "s1",
                "strategy_name": "Breakout",
                "regime": "Bullish",
                "entry_price": 3800.0,
                "stop_loss": 3720.0,
                "target_price": 3960.0,
                "rr_ratio": 2.0,
                "adx": 28.0,
                "rsi": 55.0,
                "volume_ratio": 1.8,
                "above_ema20": True,
                "above_ema50": True,
                "gate_price": True,
                "gate_data_quality": True,
                "gate_rr": True,
                "gate_volume": True,
            }
        ],
        "universe_size": 50,
        "duration_s": 300.0,
    }


# ---------------------------------------------------------------------------
# 1. phase15_scan_context: is_today_session field
# ---------------------------------------------------------------------------

class TestPhase15SessionDate(unittest.TestCase):
    """phase15_scan_context.build_scan_context() exposes is_today_session."""

    def _run_with_stale_scan(self, snapshot_ts: str) -> dict:
        scan = _make_scan(snapshot_ts)
        # Patch the scan loader so we never touch real files / DB
        import phase15_scan_context as p15
        with patch.object(p15, "_load_scan", return_value=scan), \
             patch.object(p15, "canonical_regime", return_value="Bullish"):
            ctx = p15.build_scan_context()
        return ctx

    def test_previous_day_returns_is_today_false(self):
        ctx = self._run_with_stale_scan(_yesterday_ist_ts())
        self.assertIn("is_today_session", ctx)
        self.assertFalse(
            ctx["is_today_session"],
            f"Expected is_today_session=False for yesterday's scan, got: {ctx.get('is_today_session')}"
        )
        self.assertIn("snapshot_date_ist", ctx)
        self.assertIsNotNone(ctx["snapshot_date_ist"])

    def test_today_scan_returns_is_today_true(self):
        ctx = self._run_with_stale_scan(_today_ist_ts())
        self.assertIn("is_today_session", ctx)
        self.assertTrue(
            ctx["is_today_session"],
            f"Expected is_today_session=True for today's fresh scan, got: {ctx.get('is_today_session')}"
        )

    def test_missing_snapshot_ts_returns_is_today_false(self):
        import phase15_scan_context as p15
        scan = _make_scan("")
        scan.pop("snapshot_ts", None)
        with patch.object(p15, "_load_scan", return_value=scan), \
             patch.object(p15, "canonical_regime", return_value="UNKNOWN"):
            ctx = p15.build_scan_context()
        self.assertFalse(
            ctx.get("is_today_session", False),
            "Expected is_today_session=False when snapshot_ts is absent"
        )


# ---------------------------------------------------------------------------
# 2. pipeline_stats: session_mismatch gate
# ---------------------------------------------------------------------------

class TestPipelineStatsSessionMismatch(unittest.TestCase):
    """pipeline_stats.get_pipeline_stats() clears candidates when previous-day scan."""

    def _run_pipeline(self, snapshot_ts: str) -> dict:
        scan = _make_scan(snapshot_ts)
        stale = (datetime.now(timezone.utc) -
                 datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))).total_seconds() > 5400

        ctx = {
            "available": True,
            "scan_id": scan["scan_id"],
            "snapshot_ts": snapshot_ts,
            "stale": stale,
            "is_today_session": not stale and (
                # compute is_today_session directly
                snapshot_ts[:10] == (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
            ),
            "symbols": {
                "TCS": {
                    "symbol": "TCS",
                    "final_action": "BUY",
                    "data_quality": "LIVE",
                    "opportunity_score": 80.0,
                    "confidence": 82.0,
                    "technical_score": 75.0,
                    "rr_ratio": 2.0,
                    "regime": "Bullish",
                    "paper_eligible": True,
                }
            },
        }

        # Compute is_today_session more accurately using the same helper logic
        snap_date = (datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00")) +
                     timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        today_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        ctx["is_today_session"] = snap_date == today_ist

        import pipeline_stats as ps
        with patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch("phase20_gates.evaluate_entries", side_effect=Exception("no DB")), \
             patch("phase20_executor.get_ledger", return_value=[]), \
             patch("phase20_executor.get_open_trades", return_value=[]), \
             patch("phase20_store.get_settings", return_value={}), \
             patch("phase20_store.kv_get", return_value=None):
            result = ps.get_pipeline_stats()
        return result

    def test_previous_day_scan_clears_candidates(self):
        result = self._run_pipeline(_yesterday_ist_ts())
        self.assertTrue(
            result.get("session_mismatch"),
            "Expected session_mismatch=True for yesterday's scan"
        )
        self.assertEqual(
            result.get("top_buy_candidates"), [],
            "Expected top_buy_candidates=[] when session_mismatch=True"
        )
        self.assertEqual(
            result.get("candidate_gate_details"), [],
            "Expected candidate_gate_details=[] when session_mismatch=True"
        )
        self.assertIsNotNone(result.get("session_message"))

    def test_today_scan_shows_candidates(self):
        result = self._run_pipeline(_today_ist_ts())
        self.assertFalse(
            result.get("session_mismatch", False),
            "Expected session_mismatch=False for today's fresh scan"
        )
        # Candidates may be empty if evaluate_entries raised (mocked), but
        # the top_buy_candidates list should still come from scan context
        self.assertIsNotNone(result.get("top_buy_candidates"))


# ---------------------------------------------------------------------------
# 3. phase11 recommendation queue: session_mismatch gate
# ---------------------------------------------------------------------------

class TestPhase11RecommendationQueue(unittest.TestCase):
    """phase11_autonomous.get_recommendation_queue() returns [] when previous-day scan."""

    def _ctx_for_ts(self, snapshot_ts: str) -> dict:
        snap_date = (datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00")) +
                     timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        today_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        return {
            "available": True,
            "snapshot_ts": snapshot_ts,
            "is_today_session": snap_date == today_ist,
        }

    def test_previous_day_returns_empty_with_session_mismatch(self):
        import phase11_autonomous as p11
        ai_recs = [
            {"symbol": "TCS", "action": "BUY", "confidence": 82.0,
             "risk_level": "LOW", "expected_return": 4.2,
             "estimated_holding": "2-5 days", "entry": 3800.0,
             "stop_loss": 3720.0, "target": 3960.0,
             "reasoning": "Strong breakout", "strategy": "Breakout"}
        ]
        ctx = self._ctx_for_ts(_yesterday_ist_ts())
        with patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch.object(p11, "_get_ai_decision_recs", return_value=ai_recs), \
             patch.object(p11, "_get_scan_signal_recs", return_value=[]):
            result = p11.get_recommendation_queue()

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])
        self.assertTrue(result.get("session_mismatch"))

    def test_today_scan_returns_recommendations(self):
        import phase11_autonomous as p11
        ai_recs = [
            {"symbol": "TCS", "action": "BUY", "confidence": 82.0,
             "risk_level": "LOW", "expected_return": 4.2,
             "estimated_holding": "2-5 days", "entry": 3800.0,
             "stop_loss": 3720.0, "target": 3960.0,
             "reasoning": "Strong breakout", "strategy": "Breakout"}
        ]
        ctx = self._ctx_for_ts(_today_ist_ts())
        with patch("phase15_scan_context.build_scan_context", return_value=ctx), \
             patch.object(p11, "_get_ai_decision_recs", return_value=ai_recs), \
             patch.object(p11, "_get_scan_signal_recs", return_value=[]):
            result = p11.get_recommendation_queue()

        self.assertGreater(result["count"], 0)
        self.assertFalse(result.get("session_mismatch", False))


# ---------------------------------------------------------------------------
# 4. replay_engine: execution label for paper_eligible=True, no paper_order_id
# ---------------------------------------------------------------------------

class TestReplayEngineExecutionLabel(unittest.TestCase):
    """
    replay_engine._build_symbol_journey() must label paper_eligible=True records
    WITHOUT an ORDER_SUBMITTED / ORDER_EXECUTED event as 'ELIGIBLE' / 'Paper eligible'
    — NOT 'PAPER BUY' / 'Paper order placed'.
    """

    def _build_journey(self, paper_eligible: bool, execution_outcome: dict) -> list:
        import replay_engine as re_mod
        rec = {
            "symbol": "TCS",
            "sector": "IT",
            "data_quality": "LIVE",
            "final_action": "BUY",
            "calibrated_confidence": 82.0,
            "opportunity_score": 80.0,
            "technical_score": 75.0,
            "all_gates_passed": True,
            "paper_eligible": paper_eligible,
            "strategy_id": "s1",
            "strategy_name": "Breakout",
            "regime": "Bullish",
            "entry_price": 3800.0,
            "stop_loss": 3720.0,
            "target_price": 3960.0,
            "rr_ratio": 2.0,
            "gate_price": True,
            "gate_data_quality": True,
            "gate_rr": True,
            "gate_volume": True,
        }
        snapshot = {"snapshot_ts": _yesterday_ist_ts(), "scan_id": "test_scan"}
        return re_mod._build_symbol_journey(
            rec, snapshot, precheck=None,
            execution_outcome=execution_outcome
        )

    def test_paper_eligible_no_order_id_is_eligible(self):
        """paper_eligible=True with no execution event → ELIGIBLE, not PAPER BUY."""
        journey = self._build_journey(paper_eligible=True, execution_outcome={})
        exec_step = next(s for s in journey if s["stage"] == "execution")

        self.assertNotEqual(
            exec_step["result"], "PAPER BUY",
            "Execution result must NOT be 'PAPER BUY' when no actual order was placed"
        )
        self.assertNotIn(
            "Paper order placed", exec_step.get("reason", ""),
            "Execution reason must NOT say 'Paper order placed' without a paper_order_id"
        )
        self.assertEqual(
            exec_step["result"], "ELIGIBLE",
            f"Expected ELIGIBLE, got {exec_step['result']!r}"
        )
        self.assertEqual(
            exec_step["reason"], "Paper eligible — execution outcome not recorded for this scan",
            f"Expected explicit missing execution outcome, got {exec_step['reason']!r}"
        )

    def test_order_submitted_event_is_paper_buy(self):
        """ORDER_SUBMITTED event → PAPER BUY / 'Paper order placed and recorded'."""
        eo = {"event_type": "ORDER_SUBMITTED"}
        journey = self._build_journey(paper_eligible=True, execution_outcome=eo)
        exec_step = next(s for s in journey if s["stage"] == "execution")
        self.assertEqual(exec_step["result"], "PAPER BUY")
        self.assertIn("Paper order placed", exec_step["reason"])

    def test_not_paper_eligible_no_order_is_skipped(self):
        """paper_eligible=False with BUY decision and no execution event → REJECTED."""
        journey = self._build_journey(paper_eligible=False, execution_outcome={})
        exec_step = next(s for s in journey if s["stage"] == "execution")
        # When paper_eligible=False with a BUY action, the label is REJECTED
        self.assertIn(exec_step["result"], ("SKIPPED", "REJECTED"),
                      "Expected SKIPPED or REJECTED for non-paper-eligible BUY")
        self.assertNotIn("Paper order placed", exec_step.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
