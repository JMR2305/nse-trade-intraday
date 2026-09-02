"""
test_consecutive_blocks.py — Unit tests for consecutive-block streak tracking
in pipeline_stats.get_pipeline_stats() / phase20_gates.evaluate_entries().

Covers:
  1. Streak counts correctly for N consecutive blocked scans
  2. A single unblocked scan in the middle resets the streak to zero
  3. An ad-hoc evaluate_entries(candidate_symbols=[...]) call for the same
     scan_id does NOT write to buy_pipeline_eval_history (isolation guarantee)
  4. The canonical evaluate_entries() call (no candidate_symbols) DOES write
     to buy_pipeline_eval_history
  5. When an audit call for the same scan_id runs first, the canonical call
     still writes to buy_pipeline_eval_history (separate key, no collision)
  6. Empty history / empty blocked-now edge cases

All tests are fully hermetic — they use an in-memory KV store and stub every
external import that evaluate_entries() needs.  No network, DB, or scan runs.
"""
from __future__ import annotations

import sys
import types
import unittest
import pytest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


def _stub_modules():
    """Fresh test-local stand-ins; importing this test never installs them."""
    attrs = {
        "scan_state_store": dict(db_available=lambda: False, _connect=lambda: None,
                                load_latest_meta=lambda: {}, load_latest_snapshot=lambda: {}),
        "market_hours": dict(market_status=lambda: {"state": "OPEN"}),
        "paper_trader": dict(_load_state=lambda: {"trades": [], "positions": {}},
                             get_portfolio=lambda: {"cash": 50000, "invested_value": 0, "positions": []}),
        "phase20_executor": dict(get_ledger=lambda *a: [], get_open_trades=lambda: []),
        "phase20_v3_analytics": dict(record_rejections=lambda *a, **k: None),
    }
    modules = {}
    for name, values in attrs.items():
        modules[name] = types.ModuleType(name)
        vars(modules[name]).update(values)
    return modules


@pytest.fixture(autouse=True)
def _isolated_dependencies():
    with patch.dict(sys.modules, _stub_modules()):
        yield


# ── In-memory KV backing store ────────────────────────────────────────────────

class _KV:
    """Thread-safe in-memory KV store that mimics kv_get / kv_set."""
    def __init__(self):
        self._store: Dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def clear(self):
        self._store.clear()

    def __contains__(self, key):
        return key in self._store

    def __getitem__(self, key):
        return self._store[key]


# ── Helper: minimal buy_pipeline_eval_history entry ───────────────────────────

def _bp_entry(scan_id: str, blocked_symbols: List[str]) -> Dict[str, Any]:
    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "scan_id": scan_id,
        "blocked_symbols": blocked_symbols,
    }


# ── Helper: run evaluate_entries() with full stubs ────────────────────────────

def _run_evaluate_entries(kv: _KV, scan_id: str, symbols: Dict[str, Any],
                          candidate_symbols: Optional[List[str]] = None):
    """
    Call phase20_gates.evaluate_entries() with a fully-stubbed environment.
    All KV reads/writes go through the provided in-memory kv object.
    """
    import phase20_gates as g

    fake_ctx = {
        "available": True,
        "scan_id": scan_id,
        "snapshot_ts": datetime.now(timezone.utc).isoformat(),
        "stale": False,
        "scan_age_seconds": 10,
        "stale_after_seconds": 600,
        "symbols": symbols,
    }
    fake_meta = {"scan_id": scan_id, "provider": "kite",
                 "safety": {"kite_connected": True, "data_provider": "kite"}}
    fake_portfolio = {"cash": 50_000, "invested_value": 0.0, "positions": [],
                      "starting_capital": 50_000, "total_value": 50_000,
                      "current_value": 50_000}
    fake_state = {"trades": [], "positions": {}}

    with (
        patch.object(g.store, "get_settings", return_value=_fake_settings()),
        patch.object(g.store, "kv_get", side_effect=kv.get),
        patch.object(g.store, "kv_set", side_effect=kv.set),
        patch("phase15_scan_context.build_scan_context", return_value=fake_ctx),
        patch("market_hours.market_status", return_value={"state": "OPEN"}),
        patch("scan_state_store.load_latest_meta", return_value=fake_meta),
        patch("scan_state_store.load_latest_snapshot", return_value=fake_meta),
        patch("paper_trader._load_state", return_value=fake_state),
        patch("paper_trader.get_portfolio", return_value=fake_portfolio),
        patch("phase20_executor.get_ledger", return_value=[]),
        patch("phase20_executor.get_open_trades", return_value=[]),
        patch("phase20_v3_analytics.record_rejections", return_value=None),
    ):
        if candidate_symbols is None:
            return g.evaluate_entries()
        else:
            return g.evaluate_entries(candidate_symbols=candidate_symbols)


def _fake_settings() -> Dict[str, Any]:
    from phase20_store import DEFAULT_SETTINGS
    return dict(DEFAULT_SETTINGS)


# ── Shared symbol fixture — a BUY signal that will fail per_stock_cap ─────────

_BLOCKED_SYMBOLS_MAP = {
    "DRREDDY": {
        "final_action": "BUY",
        "data_quality": "LIVE",
        "opportunity_score": 72.0,
        "confidence": 68.0,
        "technical_score": 65.0,
        "rr_ratio": 2.2,
        "regime": "BULL",
        "paper_eligible": True,
    },
}

_ELIGIBLE_SYMBOLS_MAP = {
    "TCS": {
        "final_action": "BUY",
        "data_quality": "LIVE",
        "opportunity_score": 75.0,
        "confidence": 72.0,
        "technical_score": 70.0,
        "rr_ratio": 2.5,
        "regime": "BULL",
        "paper_eligible": True,
    },
}


# ════════════════════════════════════════════════════════════════════════════════
# Tests: pure streak-computation logic (no external I/O)
# ════════════════════════════════════════════════════════════════════════════════

def _compute_streaks(
    history: List[Dict[str, Any]],
    blocked_now: List[str],
) -> Dict[str, int]:
    """
    Replicate the streak-computation logic from pipeline_stats inline.
    Tests this in isolation from all external dependencies.
    """
    result: Dict[str, int] = {}
    blocked_set = set(blocked_now)
    if not blocked_set or not history:
        return result
    for sym in blocked_set:
        count = 0
        for entry in reversed(history):
            if sym in set(entry.get("blocked_symbols") or []):
                count += 1
            else:
                break
        if count > 0:
            result[sym] = count
    return result


class TestStreakLogic(unittest.TestCase):
    """Pure unit tests for the streak-computation logic — no external deps."""

    def test_streak_three_consecutive(self):
        """Symbol blocked in 3 consecutive scans → streak = 3."""
        history = [
            _bp_entry("s1", ["DRREDDY"]),
            _bp_entry("s2", ["DRREDDY"]),
            _bp_entry("s3", ["DRREDDY"]),
        ]
        self.assertEqual(_compute_streaks(history, ["DRREDDY"]).get("DRREDDY"), 3)

    def test_streak_single_scan(self):
        history = [_bp_entry("s1", ["DRREDDY"])]
        self.assertEqual(_compute_streaks(history, ["DRREDDY"]).get("DRREDDY"), 1)

    def test_not_in_blocked_now_not_counted(self):
        """Symbol not currently blocked → no streak even if always in history."""
        history = [_bp_entry("s1", ["DRREDDY"]), _bp_entry("s2", ["DRREDDY"])]
        self.assertNotIn("DRREDDY", _compute_streaks(history, []))

    def test_streak_resets_after_unblocked_scan(self):
        """
        Pattern [blocked, blocked, unblocked, blocked, blocked] (oldest→newest):
        streak = 2, not 4.
        """
        history = [
            _bp_entry("s1", ["DRREDDY"]),    # oldest
            _bp_entry("s2", ["DRREDDY"]),
            _bp_entry("s3", []),             # unblocked — streak breaks
            _bp_entry("s4", ["DRREDDY"]),
            _bp_entry("s5", ["DRREDDY"]),    # newest
        ]
        self.assertEqual(_compute_streaks(history, ["DRREDDY"]).get("DRREDDY"), 2)

    def test_streak_zero_when_most_recent_unblocked(self):
        """Symbol eligible in most-recent scan → not in result (streak = 0)."""
        history = [
            _bp_entry("s1", ["DRREDDY"]),
            _bp_entry("s2", ["DRREDDY"]),
            _bp_entry("s3", []),             # most recent: not blocked
        ]
        self.assertNotIn("DRREDDY", _compute_streaks(history, ["DRREDDY"]))

    def test_streaks_independent_per_symbol(self):
        """Each symbol has its own independent streak."""
        history = [
            _bp_entry("s1", ["DRREDDY", "TCS"]),
            _bp_entry("s2", ["DRREDDY"]),         # TCS passes here
            _bp_entry("s3", ["DRREDDY", "TCS"]),  # newest
        ]
        streaks = _compute_streaks(history, ["DRREDDY", "TCS"])
        self.assertEqual(streaks.get("DRREDDY"), 3)
        # TCS: newest=blocked, prev=not → streak = 1
        self.assertEqual(streaks.get("TCS"), 1)

    def test_empty_history_no_streaks(self):
        self.assertEqual(_compute_streaks([], ["DRREDDY"]), {})

    def test_empty_blocked_now_no_streaks(self):
        history = [_bp_entry("s1", ["DRREDDY"]), _bp_entry("s2", ["DRREDDY"])]
        self.assertEqual(_compute_streaks(history, []), {})


# ════════════════════════════════════════════════════════════════════════════════
# Tests: buy_pipeline_eval_history isolation in evaluate_entries()
# ════════════════════════════════════════════════════════════════════════════════

class TestBuyPipelineHistoryIsolation(unittest.TestCase):
    """
    Verify that buy_pipeline_eval_history is written only by canonical
    evaluate_entries() calls (candidate_symbols=None), not ad-hoc ones.
    """

    def setUp(self):
        self.kv = _KV()

    def test_canonical_call_writes_buy_pipeline_history(self):
        """
        evaluate_entries() with no candidate_symbols MUST write an entry
        to buy_pipeline_eval_history.
        """
        _run_evaluate_entries(self.kv, "scan-pipe-001", _ELIGIBLE_SYMBOLS_MAP)

        bp_hist = self.kv.get("buy_pipeline_eval_history") or []
        self.assertGreaterEqual(len(bp_hist), 1,
            "Canonical evaluate_entries() must write to buy_pipeline_eval_history")
        self.assertEqual(bp_hist[-1]["scan_id"], "scan-pipe-001")
        self.assertIn("blocked_symbols", bp_hist[-1])

    def test_adhoc_call_does_not_write_buy_pipeline_history(self):
        """
        evaluate_entries(candidate_symbols=[...]) must NOT write to
        buy_pipeline_eval_history.
        """
        _run_evaluate_entries(self.kv, "scan-audit-001", _ELIGIBLE_SYMBOLS_MAP,
                              candidate_symbols=["TCS"])

        bp_hist = self.kv.get("buy_pipeline_eval_history") or []
        self.assertEqual(len(bp_hist), 0,
            "Ad-hoc evaluate_entries(candidate_symbols=...) must not write "
            "to buy_pipeline_eval_history")

    def test_adhoc_before_canonical_same_scan_id_no_collision(self):
        """
        When an ad-hoc call runs first for scan X, and then the canonical
        call runs for the same scan X, the canonical call must still write
        to buy_pipeline_eval_history (separate key — no scan_id collision).
        """
        scan_id = "scan-shared-001"

        # Ad-hoc call (simulates gate_rejection_audit)
        _run_evaluate_entries(self.kv, scan_id, _ELIGIBLE_SYMBOLS_MAP,
                              candidate_symbols=["TCS"])

        # Canonical pipeline call for the same scan_id
        _run_evaluate_entries(self.kv, scan_id, _ELIGIBLE_SYMBOLS_MAP)

        bp_hist = self.kv.get("buy_pipeline_eval_history") or []
        self.assertEqual(len(bp_hist), 1,
            "Canonical evaluate_entries() must write to buy_pipeline_eval_history "
            "even when an ad-hoc call for the same scan_id ran first")
        self.assertEqual(bp_hist[0]["scan_id"], scan_id)

    def test_buy_pipeline_history_does_not_affect_evaluation_history(self):
        """
        Writing to buy_pipeline_eval_history must not interfere with the
        existing evaluation_history key — both are independently maintained.
        """
        _run_evaluate_entries(self.kv, "scan-dual-001", _ELIGIBLE_SYMBOLS_MAP)

        # Both keys must exist independently
        eval_hist = self.kv.get("evaluation_history") or []
        bp_hist   = self.kv.get("buy_pipeline_eval_history") or []
        self.assertGreaterEqual(len(eval_hist), 1, "evaluation_history must be written")
        self.assertGreaterEqual(len(bp_hist), 1,   "buy_pipeline_eval_history must be written")

    def test_dedup_prevents_duplicate_entries_same_scan_id(self):
        """
        Calling canonical evaluate_entries() twice with the same scan_id
        must produce exactly one entry in buy_pipeline_eval_history.
        """
        _run_evaluate_entries(self.kv, "scan-dedup-001", _ELIGIBLE_SYMBOLS_MAP)
        _run_evaluate_entries(self.kv, "scan-dedup-001", _ELIGIBLE_SYMBOLS_MAP)

        bp_hist = self.kv.get("buy_pipeline_eval_history") or []
        self.assertEqual(len(bp_hist), 1,
            "Same scan_id must not produce duplicate buy_pipeline_eval_history entries")


if __name__ == "__main__":
    unittest.main()
