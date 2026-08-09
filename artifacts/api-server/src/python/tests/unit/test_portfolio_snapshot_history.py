"""Unit tests for portfolio_snapshot.py — pnl_history & daily_pnl (Task 24).

Confirms that get_portfolio_snapshot():
  1. Exposes pnl_history from paper trader state, normalised to
     {timestamp, value} (accepting legacy `equity` keys, skipping junk rows).
  2. Builds daily_pnl from ALL trades (current session + archived) via
     paper_trader.get_all_trades(), bucketed by IST trading day, counting
     only SELL/close records.
"""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ["PORTFOLIO_OVERRIDES_DISABLED"] = "1"

import portfolio_snapshot


def _snapshot_with(state: dict, all_trades: list[dict]) -> dict:
    """Run get_portfolio_snapshot with paper_trader state & trades stubbed."""
    import paper_trader

    with patch.object(paper_trader, "_load_state", return_value=state), \
         patch.object(paper_trader, "get_trades", return_value=[]), \
         patch.object(paper_trader, "get_all_trades", return_value=all_trades):
        return portfolio_snapshot.get_portfolio_snapshot()


class TestPnlHistory:
    def test_history_normalised_to_timestamp_value(self):
        state = {
            "cash": 50_000.0,
            "positions": {},
            "trades": [],
            "pnl_history": [
                {"timestamp": "2026-08-05T10:00:00", "value": 50_000.0},
                {"timestamp": "2026-08-06T10:00:00", "equity": 50_500.0},  # legacy key
                {"no_timestamp": True},                                    # junk row
                "not-a-dict",                                              # junk row
            ],
        }
        snap = _snapshot_with(state, [])
        hist = snap["pnl_history"]
        assert hist == [
            {"timestamp": "2026-08-05T10:00:00", "value": 50_000.0},
            {"timestamp": "2026-08-06T10:00:00", "value": 50_500.0},
        ]

    def test_empty_state_gives_empty_history(self):
        snap = _snapshot_with({"cash": 50_000.0, "positions": {}, "trades": []}, [])
        assert snap["pnl_history"] == []


class TestDailyPnl:
    def test_multiple_sessions_from_archived_and_current_trades(self):
        """daily_pnl must span multiple IST trading days from get_all_trades()."""
        all_trades = [
            # current session
            {"action": "SELL", "timestamp": "2026-08-09T11:00:00", "pnl": 150.0},
            # archived earlier sessions
            {"action": "SELL", "timestamp": "2026-08-07T14:30:00", "pnl": -80.0,
             "archived_at": "2026-08-08T00:00:00"},
            {"action": "SELL", "timestamp": "2026-08-07T10:00:00", "pnl": 40.0,
             "archived_at": "2026-08-08T00:00:00"},
            {"action": "SELL", "timestamp": "2026-08-06T12:00:00", "pnl": 200.0,
             "archived_at": "2026-08-07T00:00:00"},
            # BUY rows never contribute realised P&L
            {"action": "BUY", "timestamp": "2026-08-07T09:30:00", "pnl": 0.0},
            # unparseable timestamp is skipped, not crashed on
            {"action": "SELL", "timestamp": "garbage", "pnl": 999.0},
        ]
        snap = _snapshot_with({"cash": 50_000.0, "positions": {}, "trades": []}, all_trades)
        daily = snap["daily_pnl"]
        assert daily == [
            {"date": "2026-08-06", "pnl": 200.0, "trades": 1},
            {"date": "2026-08-07", "pnl": -40.0, "trades": 2},
            {"date": "2026-08-09", "pnl": 150.0, "trades": 1},
        ]

    def test_ist_bucketing_of_utc_timestamps(self):
        """A late-evening UTC timestamp lands on the NEXT IST calendar day."""
        all_trades = [
            # 2026-08-06 20:00 UTC = 2026-08-07 01:30 IST
            {"action": "SELL", "timestamp": "2026-08-06T20:00:00+00:00", "pnl": 10.0},
        ]
        snap = _snapshot_with({"cash": 50_000.0, "positions": {}, "trades": []}, all_trades)
        assert snap["daily_pnl"] == [{"date": "2026-08-07", "pnl": 10.0, "trades": 1}]

    def test_no_trades_gives_empty_daily_pnl(self):
        snap = _snapshot_with({"cash": 50_000.0, "positions": {}, "trades": []}, [])
        assert snap["daily_pnl"] == []
