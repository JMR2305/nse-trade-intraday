"""
tests/test_phase20_startup_overnight_check.py
Unit tests for phase20_scheduler.check_overnight_carry_on_startup().

All tests are self-contained: no DB, no broker API, no live Python
modules required.  Every external dependency is stubbed.
"""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stub infrastructure
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


class _KVStore:
    """In-memory KV store that mirrors kv_claim_once / kv_get / kv_set / kv_release."""

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self.notifications: List[Dict[str, Any]] = []

    def kv_get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def kv_set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def kv_claim_once(self, key: str, ttl_seconds: int = 0) -> bool:
        if key in self._data:
            return False
        self._data[key] = True
        return True

    def kv_release(self, key: str) -> None:
        self._data.pop(key, None)

    def add_notification(self, kind: str, title: str, body: str = "",
                         severity: str = "INFO", context: Any = None) -> None:
        self.notifications.append({"kind": kind, "title": title,
                                   "body": body, "severity": severity,
                                   "context": context or {}})

    def reset(self) -> None:
        self._data.clear()
        self.notifications.clear()


_KV = _KVStore()


def _install_stubs() -> None:
    """Install lightweight stubs for every import used by phase20_scheduler."""

    # phase20_store
    store = _make_stub("phase20_store")
    store.kv_get = _KV.kv_get
    store.kv_set = _KV.kv_set
    store.kv_claim_once = _KV.kv_claim_once
    store.kv_release = _KV.kv_release
    store.add_notification = _KV.add_notification
    store.get_settings = MagicMock(return_value={
        "auto_scan_enabled": True,
        "scan_interval_minutes": 5,
        "auto_paper_exits": True,
        "auto_paper_entries": False,
    })
    store.update_scheduler_state = MagicMock()
    store.record_scan_run = MagicMock()
    store.get_scheduler_health = MagicMock(return_value={})

    # phase20_exits
    exits_mod = _make_stub("phase20_exits")
    exits_mod.eod_force_close_open_positions = MagicMock(return_value={
        "evaluated": 0, "force_closed": [], "blocked": []})

    # phase20_settings
    settings_mod = _make_stub("phase20_settings")
    settings_mod.load_settings = MagicMock(return_value={
        "auto_paper_exits": True})

    # phase20_executor
    executor_mod = _make_stub("phase20_executor")
    executor_mod.get_open_trades = MagicMock(return_value=[])

    # pipeline_events
    pe_mod = _make_stub("pipeline_events")
    pe_mod.emit = MagicMock()

    # market_hours (needed by run_tick, not check_overnight_carry_on_startup)
    mh_mod = _make_stub("market_hours")
    mh_mod.market_status = MagicMock(return_value={"state": "OPEN"})

    # phase15_scan_context (needed by run_tick)
    p15_mod = _make_stub("phase15_scan_context")
    p15_mod.build_scan_context = MagicMock(return_value={})
    p15_mod.scan_age_seconds = MagicMock(return_value=None)

    # zoneinfo is a stdlib module — ensure it is available
    try:
        import zoneinfo  # noqa: F401
    except ImportError:
        zi_mod = _make_stub("zoneinfo")
        class _FakeZoneInfo:
            def __init__(self, key: str): self._key = key
        zi_mod.ZoneInfo = _FakeZoneInfo


_install_stubs()

# ---------------------------------------------------------------------------
# Import the module under test (after stubs are in place)
# ---------------------------------------------------------------------------
import importlib
import phase20_scheduler as sched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fill_ts_days_ago(n: int) -> str:
    """Return an ISO timestamp string n days before today (UTC, as used in fill_ts)."""
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _trade(symbol: str = "RELIANCE", trade_id: str = "T1",
           fill_ts: str | None = None, days_ago: int = 1) -> Dict[str, Any]:
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "quantity": 10,
        "fill_price": 2500.0,
        "stop_loss": 2450.0,
        "target": 2600.0,
        "fill_ts": fill_ts if fill_ts is not None else _fill_ts_days_ago(days_ago),
        "status": "OPEN",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckOvernightCarryOnStartup(unittest.TestCase):

    def setUp(self):
        _KV.reset()
        sys.modules["phase20_exits"].eod_force_close_open_positions.reset_mock()
        sys.modules["phase20_executor"].get_open_trades.reset_mock()
        sys.modules["pipeline_events"].emit.reset_mock()
        sys.modules["phase20_exits"].eod_force_close_open_positions.return_value = {
            "evaluated": 0, "force_closed": [], "blocked": []}

    # ── already-ran guard ────────────────────────────────────────────────────

    def test_returns_already_ran_today_when_startup_claim_exists(self):
        """Second call within the same IST day must be a no-op."""
        # Pre-claim the startup guard
        from zoneinfo import ZoneInfo
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        _KV.kv_claim_once(f"startup_overnight_check:{today_ist}")

        result = sched.check_overnight_carry_on_startup()

        self.assertFalse(result.get("ran"))
        self.assertEqual(result.get("reason"), "already_ran_today")
        sys.modules["phase20_executor"].get_open_trades.assert_not_called()

    # ── eod_squareoff already taken ─────────────────────────────────────────

    def test_skips_when_eod_squareoff_was_claimed_yesterday(self):
        """If yesterday's eod_squareoff key exists, do nothing."""
        from zoneinfo import ZoneInfo
        yesterday = (datetime.now(ZoneInfo("Asia/Kolkata")).date()
                     - timedelta(days=1)).isoformat()
        _KV.kv_claim_once(f"eod_squareoff:{yesterday}")

        result = sched.check_overnight_carry_on_startup()

        self.assertTrue(result.get("ran"))
        self.assertTrue(result.get("eod_claimed"))
        self.assertEqual(result.get("reason"), "eod_squareoff_ran_yesterday")
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_not_called()

    # ── no open positions ────────────────────────────────────────────────────

    def test_no_open_positions_claims_eod_key_and_returns_cleanly(self):
        """No OPEN positions → claim yesterday's EOD key, return cleanly."""
        sys.modules["phase20_executor"].get_open_trades.return_value = []

        result = sched.check_overnight_carry_on_startup()

        self.assertTrue(result.get("ran"))
        self.assertFalse(result.get("eod_claimed"))
        self.assertEqual(result.get("open_count"), 0)
        self.assertEqual(result.get("reason"), "no_open_positions")
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_not_called()

        # Verify yesterday's eod_squareoff key was claimed
        from zoneinfo import ZoneInfo
        yesterday = (datetime.now(ZoneInfo("Asia/Kolkata")).date()
                     - timedelta(days=1)).isoformat()
        self.assertTrue(_KV.kv_get(f"eod_squareoff:{yesterday}"))

    # ── all open trades are today's (no prior-session carries) ──────────────

    def test_no_prior_session_trades_when_all_fills_are_today(self):
        """Trades opened today must not be treated as overnight carries."""
        today_fill = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(fill_ts=today_fill)]

        result = sched.check_overnight_carry_on_startup()

        self.assertTrue(result.get("ran"))
        self.assertEqual(result.get("prior_session_count"), 0)
        self.assertEqual(result.get("reason"), "no_prior_session_trades")
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_not_called()
        sys.modules["pipeline_events"].emit.assert_not_called()

    # ── overnight carry detected ─────────────────────────────────────────────

    def test_prior_session_trade_triggers_force_close(self):
        """A trade from yesterday's session must trigger eod_force_close."""
        sys.modules["phase20_exits"].eod_force_close_open_positions.return_value = {
            "evaluated": 1,
            "force_closed": [{"trade_id": "T1", "symbol": "RELIANCE",
                               "exit_price": 2500.0}],
            "blocked": [],
        }
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(symbol="RELIANCE", trade_id="T1", days_ago=1)]

        result = sched.check_overnight_carry_on_startup()

        self.assertTrue(result.get("ran"))
        self.assertFalse(result.get("eod_claimed"))
        self.assertEqual(result.get("prior_session_count"), 1)
        self.assertIn("RELIANCE", result.get("symbols", []))

        # Force-close must have been called
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_called_once()

    def test_pipeline_event_emitted_per_prior_session_trade(self):
        """MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED must be emitted for each trade."""
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(symbol="RELIANCE", trade_id="T1", days_ago=1),
            _trade(symbol="TCS", trade_id="T2", days_ago=2),
        ]

        sched.check_overnight_carry_on_startup()

        emitted_kinds = [call.args[0]
                         for call in sys.modules["pipeline_events"].emit.call_args_list]
        self.assertEqual(
            emitted_kinds.count("MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED"), 2,
            "Expected one pipeline event per prior-session trade")

    def test_notification_emitted_for_overnight_carry(self):
        """A WARN notification must be added when prior-session trades are found."""
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(symbol="INFY", trade_id="T3", days_ago=1)]

        sched.check_overnight_carry_on_startup()

        kinds = [n["kind"] for n in _KV.notifications]
        self.assertIn("MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED", kinds)
        notif = next(n for n in _KV.notifications
                     if n["kind"] == "MARKET_CLOSE_OVERNIGHT_CARRY_DETECTED")
        self.assertEqual(notif["severity"], "WARN")

    def test_yesterday_eod_key_claimed_after_force_close(self):
        """After running force-close, yesterday's eod_squareoff must be claimed."""
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(days_ago=1)]

        sched.check_overnight_carry_on_startup()

        from zoneinfo import ZoneInfo
        yesterday = (datetime.now(ZoneInfo("Asia/Kolkata")).date()
                     - timedelta(days=1)).isoformat()
        self.assertTrue(_KV.kv_get(f"eod_squareoff:{yesterday}"),
                        "eod_squareoff:<yesterday> must be claimed to prevent "
                        "the POST_CLOSE tick from double-firing")

    # ── trades with missing or malformed fill_ts ────────────────────────────

    def test_trade_with_no_fill_ts_treated_as_prior_session(self):
        """A trade with no fill_ts must be conservatively treated as prior-session."""
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            {"trade_id": "T5", "symbol": "HDFCBANK", "quantity": 5,
             "fill_price": 1700.0, "fill_ts": None, "status": "OPEN"}]

        result = sched.check_overnight_carry_on_startup()

        self.assertEqual(result.get("prior_session_count"), 1)
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_called_once()

    def test_trade_with_malformed_fill_ts_treated_as_prior_session(self):
        """A trade with a malformed fill_ts must be treated as prior-session."""
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            {"trade_id": "T6", "symbol": "WIPRO", "quantity": 3,
             "fill_price": 450.0, "fill_ts": "not-a-timestamp", "status": "OPEN"}]

        result = sched.check_overnight_carry_on_startup()

        self.assertEqual(result.get("prior_session_count"), 1)
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_called_once()

    # ── idempotency ──────────────────────────────────────────────────────────

    def test_startup_claim_prevents_double_execution_within_same_day(self):
        """Two consecutive calls on the same day must only run force-close once."""
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(days_ago=1)]

        result1 = sched.check_overnight_carry_on_startup()
        result2 = sched.check_overnight_carry_on_startup()

        self.assertTrue(result1.get("ran"))
        self.assertFalse(result2.get("ran"))
        self.assertEqual(result2.get("reason"), "already_ran_today")
        # Force-close must only have been called once
        self.assertEqual(
            sys.modules["phase20_exits"].eod_force_close_open_positions.call_count, 1)

    # ── error recovery ───────────────────────────────────────────────────────

    def test_startup_claim_released_on_error_so_next_restart_retries(self):
        """If an unexpected error occurs, the startup claim must be released."""
        sys.modules["phase20_executor"].get_open_trades.side_effect = \
            RuntimeError("DB unavailable")

        result = sched.check_overnight_carry_on_startup()

        self.assertFalse(result.get("ran"))
        self.assertIn("error", result)

        # Startup claim must have been released so the next cold-start retries
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        self.assertIsNone(_KV.kv_get(f"startup_overnight_check:{today}"),
                          "startup_overnight_check claim must be released on error")

        # Now a retry should be allowed
        sys.modules["phase20_executor"].get_open_trades.side_effect = None
        sys.modules["phase20_executor"].get_open_trades.return_value = []
        result2 = sched.check_overnight_carry_on_startup()
        self.assertTrue(result2.get("ran"))

    # ── mixed today + yesterday trades ───────────────────────────────────────

    def test_only_prior_session_trades_are_force_closed_not_todays(self):
        """Today's trades must NOT be treated as overnight carries."""
        today_fill = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(symbol="RELIANCE", trade_id="OLD", days_ago=1),
            _trade(symbol="TCS", trade_id="NEW", fill_ts=today_fill),
        ]

        result = sched.check_overnight_carry_on_startup()

        # Only the yesterday trade is a prior-session carry
        self.assertEqual(result.get("prior_session_count"), 1)
        self.assertIn("RELIANCE", result.get("symbols", []))
        self.assertNotIn("TCS", result.get("symbols", []))
        # Force-close still runs (because there IS at least one prior-session trade)
        sys.modules["phase20_exits"].eod_force_close_open_positions.assert_called_once()

    def test_eod_force_close_result_included_in_return(self):
        """The return value must include the eod_force_close sub-result."""
        sys.modules["phase20_exits"].eod_force_close_open_positions.return_value = {
            "evaluated": 1,
            "force_closed": [{"trade_id": "T1", "symbol": "SBIN"}],
            "blocked": [],
        }
        sys.modules["phase20_executor"].get_open_trades.return_value = [
            _trade(days_ago=1)]

        result = sched.check_overnight_carry_on_startup()

        eod = result.get("eod_force_close") or {}
        self.assertEqual(eod.get("evaluated"), 1)
        self.assertEqual(len(eod.get("force_closed", [])), 1)


if __name__ == "__main__":
    unittest.main()
