"""Unit tests for phase4a_dashboard aggregation rules.

Covers the regression-prone rules:
- IST calendar-day windowing for historical performance (23:59 vs 00:01 IST)
- CLOSED rows without exit_ts excluded from windows and flagged in data quality
- Same-day round trip counted as ONE trade in today's statistics
- Empty ledger produces nulls, never division-by-zero
- EXIT_PENDING / CANCELLED status semantics

All stores are mocked; no DB, scan snapshot, or replay engine is touched.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import phase4a_dashboard as dash

IST = timezone(timedelta(hours=5, minutes=30))

# Fixed "now": 2026-08-08 12:00 IST
NOW_IST = datetime(2026, 8, 8, 12, 0, tzinfo=IST)
NOW_UTC = NOW_IST.astimezone(timezone.utc)
TODAY = NOW_IST.date().isoformat()  # 2026-08-08


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _row(trade_id, status="CLOSED", fill=None, exit_=None, pnl=0.0, symbol="X",
         fill_price=100.0, exit_price=None, quantity=1, **extra):
    r = {
        "trade_id": trade_id, "status": status, "symbol": symbol,
        "fill_ts": _iso(fill) if fill else None,
        "exit_ts": _iso(exit_) if exit_ else None,
        "realized_pnl": pnl if status == "CLOSED" else None,
        "fill_price": fill_price, "exit_price": exit_price, "quantity": quantity,
    }
    r.update(extra)
    return r


def build(rows):
    """Run build_validation_dashboard with all external stores mocked."""
    with patch.object(dash, "_now_utc", return_value=NOW_UTC), \
         patch.object(dash, "_load_ledger", return_value=rows), \
         patch.object(dash, "_load_snapshot", return_value=None), \
         patch.object(dash, "_load_market_context", return_value={}), \
         patch.object(dash, "_load_ai_decisions", return_value=[]), \
         patch.object(dash, "_build_replay_cached", return_value=None):
        return dash.build_validation_dashboard()


class TestISTWindowing(unittest.TestCase):
    def test_midnight_ist_boundary(self):
        """7d cutoff is an IST calendar date: 23:59 IST on cutoff-1 is out,
        00:01 IST on the cutoff day is in — even though the two UTC instants
        are 2 minutes apart."""
        cutoff = NOW_IST.date() - timedelta(days=6)  # 2026-08-02
        just_out = datetime(cutoff.year, cutoff.month, cutoff.day, 23, 59, tzinfo=IST) - timedelta(days=1)
        just_in = datetime(cutoff.year, cutoff.month, cutoff.day, 0, 1, tzinfo=IST)
        rows = [
            _row("out", fill=just_out - timedelta(hours=1), exit_=just_out, pnl=10.0),
            _row("in", fill=just_in, exit_=just_in + timedelta(hours=1), pnl=20.0),
        ]
        h = build(rows)["historical_performance"]
        self.assertEqual(h["7d"]["trades"], 1)
        self.assertEqual(h["7d"]["net_pnl"], 20.0)
        self.assertEqual(h["30d"]["trades"], 2)
        self.assertEqual(h["all"]["trades"], 2)

    def test_utc_instant_does_not_leak_into_window(self):
        """A trade whose UTC timestamp is within 7*24h but whose IST date is
        before the cutoff must be excluded."""
        cutoff = NOW_IST.date() - timedelta(days=6)
        # 23:00 IST on cutoff-1 == 17:30 UTC cutoff-1; well within 7*24h of NOW.
        ts = datetime(cutoff.year, cutoff.month, cutoff.day, 23, 0, tzinfo=IST) - timedelta(days=1)
        self.assertLess(NOW_UTC - ts.astimezone(timezone.utc), timedelta(days=7))
        h = build([_row("t", fill=ts - timedelta(hours=2), exit_=ts, pnl=5.0)])["historical_performance"]
        self.assertEqual(h["7d"]["trades"], 0)
        self.assertEqual(h["all"]["trades"], 1)


class TestMissingExitTs(unittest.TestCase):
    def test_closed_without_exit_ts_excluded_and_flagged(self):
        rows = [
            _row("bad", exit_=None, fill=NOW_IST - timedelta(days=1), pnl=99.0),
            _row("good", fill=NOW_IST - timedelta(days=1),
                 exit_=NOW_IST - timedelta(hours=1), pnl=1.0),
        ]
        out = build(rows)
        h = out["historical_performance"]
        for k in ("7d", "30d", "90d", "180d", "all"):
            self.assertEqual(h[k]["trades"], 1, k)
            self.assertEqual(h[k]["net_pnl"], 1.0, k)
        q = out["data_quality"]
        self.assertEqual(q["closed_missing_exit_ts"], 1)
        self.assertIsNotNone(q["closed_missing_exit_ts_note"])

    def test_no_flag_when_all_closed_have_exit_ts(self):
        q = build([_row("a", fill=NOW_IST, exit_=NOW_IST, pnl=1.0)])["data_quality"]
        self.assertEqual(q["closed_missing_exit_ts"], 0)
        self.assertIsNone(q["closed_missing_exit_ts_note"])


class TestSameDayRoundTrip(unittest.TestCase):
    def test_round_trip_counts_once(self):
        r = _row("rt", fill=NOW_IST - timedelta(hours=3), exit_=NOW_IST - timedelta(hours=1),
                 pnl=15.0, exit_price=115.0)
        t = build([r])["trading_statistics"]
        self.assertEqual(t["trades"], 1)        # one trade record
        self.assertEqual(t["buy_orders"], 1)    # entry today
        self.assertEqual(t["sell_orders"], 1)   # exit today
        self.assertEqual(t["net_pnl"], 15.0)

    def test_entry_and_exit_on_different_days(self):
        r = _row("carry", fill=NOW_IST - timedelta(days=2), exit_=NOW_IST - timedelta(hours=1),
                 pnl=7.0, exit_price=107.0)
        t = build([r])["trading_statistics"]
        self.assertEqual(t["trades"], 1)
        self.assertEqual(t["buy_orders"], 0)    # fill was 2 days ago
        self.assertEqual(t["sell_orders"], 1)


class TestEmptyLedger(unittest.TestCase):
    def test_no_division_by_zero(self):
        out = build([])
        t = out["trading_statistics"]
        self.assertEqual(t["trades"], 0)
        self.assertEqual(t["net_pnl"], 0.0)
        self.assertIsNone(t["avg_rr"])
        h = out["historical_performance"]
        for k in ("7d", "30d", "90d", "180d", "all"):
            self.assertEqual(h[k]["trades"], 0, k)
            self.assertIsNone(h[k]["win_rate_pct"], k)
            self.assertIsNone(h[k]["profit_factor"], k)
            self.assertIsNone(h[k]["sharpe"], k)
            self.assertIsNone(h[k]["sortino"], k)
            self.assertIsNone(h[k]["recovery_factor"], k)


class TestStatusSemantics(unittest.TestCase):
    def test_exit_pending_and_cancelled(self):
        rows = [
            _row("ep", status="EXIT_PENDING", fill=NOW_IST - timedelta(hours=2)),
            _row("cx", status="CANCELLED", fill=NOW_IST - timedelta(hours=2)),
            _row("op", status="OPEN", fill=NOW_IST - timedelta(hours=2)),
        ]
        out = build(rows)
        t = out["trading_statistics"]
        # CANCELLED never counts as a fill; EXIT_PENDING and OPEN do.
        self.assertEqual(t["buy_orders"], 2)
        self.assertEqual(t["cancelled"], 1)
        self.assertEqual(t["sell_orders"], 0)
        # EXIT_PENDING is deployed capital in the cash identity.
        cc = out["data_quality"]["portfolio_cash_check"]
        self.assertEqual(cc["deployed"], 200.0)  # 2 × 100 × 1 (EXIT_PENDING + OPEN)
        # None of these appear in historical closed stats.
        self.assertEqual(out["historical_performance"]["all"]["trades"], 0)


if __name__ == "__main__":
    unittest.main()
