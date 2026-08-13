"""
test_get_symbol_journey_db.py

Integration-level tests for get_symbol_journey() that exercise the actual
DB-path code — including the priority-ordered execution-event SQL and the
"latest" → resolved scan_id mapping — by patching the DB helpers with
controlled return values.

Two guarantees verified here:
1. Priority race guard: when the DB path returns ORDER_EXECUTED (simulating
   the CASE-ordered SQL choosing it over EXECUTION_SKIPPED_WITH_REASON), the
   journey shows PAPER BUY, not SKIPPED.
2. "latest" resolution: precheck decisions are fetched with the concrete
   resolved scan_id, never the literal string "latest" or an empty string.

These tests complement the unit-level _pick_highest_priority_exec_event tests
by exercising get_symbol_journey() end-to-end with a mocked connection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import replay_engine  # noqa: E402
from replay_engine import get_symbol_journey  # noqa: E402


# ── Minimal test fixtures ────────────────────────────────────────────────────

def _minimal_rec(**overrides):
    base = {
        "symbol": "RELIANCE",
        "final_action": "BUY",
        "paper_eligible": True,
        "all_gates_passed": True,
        "strategy_id": "mean_reversion",
        "data_quality": "LIVE",
        "rr_ratio": 2.0,
        "technical_score": 75.0,
        "calibrated_confidence": 80.0,
        "opportunity_score": 70.0,
    }
    base.update(overrides)
    return base


def _snapshot(scan_id: str, recs: list | None = None) -> dict:
    return {
        "scan_id": scan_id,
        "snapshot_ts": "2026-08-13T09:30:00Z",
        "recommendations": recs or [_minimal_rec()],
    }


def _make_q1_responder(snap_json: str, scan_id: str,
                        exec_event_type: str | None = None):
    """Return a _q1 side-effect that answers the three DB queries in
    get_symbol_journey in order: scan_state, paper_trades, pipeline_events."""
    def _q1(conn, sql, params=()):
        if "scan_state" in sql:
            return {"scan_id": scan_id, "snapshot": snap_json}
        if "phase20_paper_trades" in sql:
            return None
        if "pipeline_events" in sql:
            if exec_event_type:
                return {"id": 1, "event_type": exec_event_type,
                        "payload": json.dumps({})}
            return None
        return None
    return _q1


# ── Tests ────────────────────────────────────────────────────────────────────

class TestGetSymbolJourneyDbPrioritySelection:
    """Verify the priority-ordered SQL path of get_symbol_journey()."""

    def test_order_executed_returned_by_db_produces_paper_buy(self):
        """When the priority-ordered DB query returns ORDER_EXECUTED (simulating
        it winning over a concurrent EXECUTION_SKIPPED_WITH_REASON), the
        journey step must show PAPER BUY — not SKIPPED."""
        snap = _snapshot("scan-race")
        q1 = _make_q1_responder(json.dumps(snap), "scan-race",
                                 exec_event_type="ORDER_EXECUTED")
        mock_conn = MagicMock()

        with patch.object(replay_engine, "_get_conn", return_value=mock_conn), \
             patch.object(replay_engine, "_q1", side_effect=q1), \
             patch.object(replay_engine, "_get_precheck_decisions",
                          return_value={}):
            result = get_symbol_journey("scan-race", "RELIANCE")

        exec_step = next(
            (s for s in result.get("journey", []) if s["stage"] == "execution"),
            None,
        )
        assert exec_step is not None, "execution step missing from journey"
        assert exec_step["result"] == "PAPER BUY", (
            f"Journey must show PAPER BUY when the DB returns ORDER_EXECUTED; "
            f"got {exec_step['result']!r}"
        )

    def test_skipped_returned_by_db_produces_skipped(self):
        """When the DB returns EXECUTION_SKIPPED_WITH_REASON (e.g. seal ran,
        no executor event), the journey step must show SKIPPED."""
        snap = _snapshot("scan-sealed")
        q1 = _make_q1_responder(json.dumps(snap), "scan-sealed",
                                 exec_event_type="EXECUTION_SKIPPED_WITH_REASON")
        mock_conn = MagicMock()

        with patch.object(replay_engine, "_get_conn", return_value=mock_conn), \
             patch.object(replay_engine, "_q1", side_effect=q1), \
             patch.object(replay_engine, "_get_precheck_decisions",
                          return_value={}):
            result = get_symbol_journey("scan-sealed", "RELIANCE")

        exec_step = next(
            (s for s in result.get("journey", []) if s["stage"] == "execution"),
            None,
        )
        assert exec_step is not None, "execution step missing from journey"
        assert exec_step["result"] == "SKIPPED", (
            f"Journey must show SKIPPED when DB returns EXECUTION_SKIPPED_WITH_REASON; "
            f"got {exec_step['result']!r}"
        )

    def test_no_exec_event_in_db_falls_back_to_eligible(self):
        """When the DB returns no execution event the journey shows ELIGIBLE
        (paper_eligible=True in snapshot) — never 'Paper order placed'."""
        snap = _snapshot("scan-noev")
        q1 = _make_q1_responder(json.dumps(snap), "scan-noev",
                                 exec_event_type=None)
        mock_conn = MagicMock()

        with patch.object(replay_engine, "_get_conn", return_value=mock_conn), \
             patch.object(replay_engine, "_q1", side_effect=q1), \
             patch.object(replay_engine, "_get_precheck_decisions",
                          return_value={}):
            result = get_symbol_journey("scan-noev", "RELIANCE")

        exec_step = next(
            (s for s in result.get("journey", []) if s["stage"] == "execution"),
            None,
        )
        assert exec_step is not None
        assert exec_step["result"] == "ELIGIBLE"
        assert "Paper order placed" not in exec_step.get("reason", "")


class TestGetSymbolJourneyLatestResolution:
    """Verify that scan_id='latest' is resolved to a concrete id before
    precheck decisions are fetched, so pipeline events stored under the
    real scan_id are correctly matched."""

    def test_precheck_called_with_resolved_scan_id_not_latest(self):
        snap = _snapshot("scan-concrete")
        q1 = _make_q1_responder(json.dumps(snap), "scan-concrete")
        mock_conn = MagicMock()
        precheck_calls: list[str] = []

        def _fake_precheck(sid: str):
            precheck_calls.append(sid)
            return {}

        with patch.object(replay_engine, "_get_conn", return_value=mock_conn), \
             patch.object(replay_engine, "_q1", side_effect=q1), \
             patch.object(replay_engine, "_get_precheck_decisions",
                          side_effect=_fake_precheck):
            get_symbol_journey("latest", "RELIANCE")

        assert precheck_calls, "precheck must have been called"
        assert precheck_calls[0] != "latest", (
            f"_get_precheck_decisions must not receive 'latest'; "
            f"got {precheck_calls[0]!r}"
        )
        assert precheck_calls[0] == "scan-concrete", (
            f"_get_precheck_decisions must receive the concrete resolved scan_id; "
            f"got {precheck_calls[0]!r}"
        )

    def test_no_db_returns_symbol_not_found_without_raising(self):
        """When _get_conn() returns None the function must return a clean
        error dict, not raise UnboundLocalError (regression guard)."""
        with patch.object(replay_engine, "_get_conn", return_value=None), \
             patch.object(replay_engine, "_get_precheck_decisions",
                          return_value={}):
            result = get_symbol_journey("scan-nodb", "RELIANCE")

        # snapshot is empty → rec is None → returns error dict cleanly
        assert "error" in result or result.get("journey") == [], (
            f"No-DB path must return cleanly without raising; got: {result!r}"
        )
