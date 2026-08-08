"""
test_portfolio_performance.py — Phase 5D.2 unit tests.

Covers:
  ✓ Zero trades
  ✓ Single trade
  ✓ Multiple trades
  ✓ Winning portfolio
  ✓ Losing portfolio
  ✓ Mixed portfolio
  ✓ Drawdown calculations
  ✓ Equity curve calculations
  ✓ Disabled feature flag
  ✓ API responses (all 5 endpoints)
  ✓ Restart persistence (no mutable state between calls)

Run: python -m pytest portfolio_performance/test_portfolio_performance.py -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

# ── Disable feature flag by default; tests opt in explicitly ──────────────────
os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

# ── Bypass the 30s raw-data file cache for the entire module ──────────────────
# The engine shares one /tmp TTL cache across processes. In tests it would
# (a) serve real dev data instead of the mocked store, and (b) leak one test's
# mocked state into the next. Patch reads to always miss and writes to no-op.
_cache_patchers: list = []


def setUpModule():
    import portfolio_performance.performance_engine as _pe
    _cache_patchers.append(patch.object(_pe, "_read_raw_cache", lambda: None))
    _cache_patchers.append(patch.object(_pe, "_write_raw_cache", lambda *a, **k: None))
    for p in _cache_patchers:
        p.start()


def tearDownModule():
    for p in _cache_patchers:
        p.stop()
    _cache_patchers.clear()

# Stub heavy dependencies before imports
_scanner_stub = types.ModuleType("market_scanner")
_scanner_stub._sector_of = lambda sym: {"RELIANCE": "ENERGY", "INFY": "IT", "HDFCBANK": "BANKING"}.get(sym, "Unknown")
sys.modules.setdefault("market_scanner", _scanner_stub)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts(offset_hours: float = 0) -> str:
    """Return an ISO timestamp offset from a fixed base."""
    base = datetime(2026, 7, 29, 9, 15, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=offset_hours)).isoformat()


def _buy(symbol="INFY", qty=10, price=1000.0, pnl=None, offset=0,
         strategy_id="s1", strategy_name="Momentum", stop_loss=950.0, target=1080.0) -> dict:
    total = qty * price
    t = {
        "id":            f"buy-{symbol}-{offset}",
        "symbol":        symbol,
        "action":        "BUY",
        "quantity":      qty,
        "price":         price,
        "total":         total,
        "timestamp":     _ts(offset),
        "reason":        "signal",
        "strategy_id":   strategy_id,
        "strategy_name": strategy_name,
        "stop_loss":     stop_loss,
        "target":        target,
    }
    return t


def _sell(symbol="INFY", qty=10, price=1100.0, pnl=None, pnl_pct=None,
          offset=2, exit_type="TARGET_HIT") -> dict:
    total = qty * price
    buy_total = qty * (price - (pnl / qty if pnl else 0))
    actual_pnl     = pnl if pnl is not None else total - qty * 1000.0
    actual_pnl_pct = pnl_pct if pnl_pct is not None else (actual_pnl / buy_total * 100)
    return {
        "id":        f"sell-{symbol}-{offset}",
        "symbol":    symbol,
        "action":    "SELL",
        "quantity":  qty,
        "price":     price,
        "total":     total,
        "timestamp": _ts(offset),
        "reason":    "exit",
        "pnl":       actual_pnl,
        "pnl_pct":   actual_pnl_pct,
        "exit_type": exit_type,
    }


def _pnl_hist(values: list[tuple[float, float]]) -> list[dict]:
    """Build pnl_history list from [(offset_hours, equity), ...]."""
    return [{"timestamp": _ts(h), "value": v} for h, v in values]


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlag(unittest.TestCase):
    """Disabled feature flag tests (module is enabled by default; explicit
    PORTFOLIO_PERFORMANCE_ENABLED=false disables it)."""

    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "false"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def test_disabled_summary(self):
        from portfolio_performance.api import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "DISABLED")
        self.assertIn("PORTFOLIO_PERFORMANCE_ENABLED", r["feature_flag"])

    def test_disabled_equity(self):
        from portfolio_performance.api import get_equity
        r = get_equity()
        self.assertEqual(r["status"], "DISABLED")

    def test_disabled_drawdown(self):
        from portfolio_performance.api import get_drawdown
        r = get_drawdown()
        self.assertEqual(r["status"], "DISABLED")

    def test_disabled_statistics(self):
        from portfolio_performance.api import get_statistics
        r = get_statistics()
        self.assertEqual(r["status"], "DISABLED")

    def test_disabled_portfolio(self):
        from portfolio_performance.api import get_portfolio
        r = get_portfolio()
        self.assertEqual(r["status"], "DISABLED")


class TestZeroTrades(unittest.TestCase):
    """No trades, default capital."""

    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def _mock_store(self):
        return (
            patch("portfolio_store.load_all_trades_any", return_value=[]),
            patch("portfolio_store.load_state", return_value={
                "cash": 500_000.0,
                "positions": {},
                "pnl_history": [{"timestamp": _ts(0), "value": 500_000.0}],
            }),
        )

    def test_summary_zero_trades(self):
        from portfolio_performance.api import get_summary
        p1, p2 = self._mock_store()
        with p1, p2:
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_trades"], 0)
        self.assertEqual(r["winning_trades"], 0)
        self.assertAlmostEqual(r["cash_available"], 500_000.0)
        self.assertAlmostEqual(r["total_net_pnl"], 0.0, places=1)

    def test_equity_zero_trades(self):
        from portfolio_performance.api import get_equity
        p1, p2 = self._mock_store()
        with p1, p2:
            r = get_equity()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIsInstance(r["series"], list)

    def test_drawdown_zero_trades(self):
        from portfolio_performance.api import get_drawdown
        p1, p2 = self._mock_store()
        with p1, p2:
            r = get_drawdown()
        self.assertEqual(r["status"], "ENABLED")
        self.assertAlmostEqual(r["max_drawdown"], 0.0, places=1)
        self.assertAlmostEqual(r["recovery_pct"], 100.0, places=1)

    def test_portfolio_zero_trades(self):
        from portfolio_performance.api import get_portfolio
        p1, p2 = self._mock_store()
        with p1, p2:
            r = get_portfolio()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["position_count"], 0)
        self.assertEqual(r["sector_allocation"], [])


class TestSingleTrade(unittest.TestCase):
    """One completed BUY→SELL round-trip."""

    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def _mock_store(self, pnl=1000.0):
        return (
            patch("portfolio_store.load_all_trades_any", return_value=[
                _buy("INFY", qty=10, price=1000.0, offset=0),
                _sell("INFY", qty=10, price=1100.0, pnl=pnl, offset=2),
            ]),
            patch("portfolio_store.load_state", return_value={
                "cash": 490_000.0,
                "positions": {},
                "pnl_history": _pnl_hist([(0, 500_000.0), (2, 501_000.0)]),
            }),
        )

    def test_single_winning_trade(self):
        from portfolio_performance.api import get_statistics
        p1, p2 = self._mock_store(pnl=1000.0)
        with p1, p2:
            r = get_statistics()
        self.assertEqual(r["status"], "ENABLED")
        ts = r["trade_statistics"]
        self.assertEqual(ts["total_trades"], 1)
        self.assertEqual(ts["winning_trades"], 1)
        self.assertEqual(ts["losing_trades"], 0)
        self.assertAlmostEqual(ts["win_rate"], 100.0, places=1)
        self.assertAlmostEqual(ts["largest_profit"], 1000.0, places=1)

    def test_single_losing_trade(self):
        from portfolio_performance.api import get_statistics
        p1, p2 = self._mock_store(pnl=-500.0)
        with p1, p2:
            r = get_statistics()
        ts = r["trade_statistics"]
        self.assertEqual(ts["losing_trades"], 1)
        self.assertEqual(ts["winning_trades"], 0)
        self.assertAlmostEqual(ts["largest_loss"], -500.0, places=1)


class TestMultipleTrades(unittest.TestCase):
    """Several BUY→SELL pairs across multiple symbols."""

    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def _make_store(self, trades, cash=450_000.0, hist=None):
        if hist is None:
            hist = _pnl_hist([(0, 500_000.0), (5, 502_000.0)])
        return (
            patch("portfolio_store.load_all_trades_any", return_value=trades),
            patch("portfolio_store.load_state", return_value={
                "cash": cash, "positions": {}, "pnl_history": hist,
            }),
        )

    def _make_trades_mixed(self):
        return [
            _buy("INFY",     qty=10, price=1000.0, offset=0),
            _sell("INFY",    qty=10, price=1100.0, pnl=1000.0,  offset=1),
            _buy("RELIANCE", qty=5,  price=2000.0, offset=2),
            _sell("RELIANCE",qty=5,  price=1900.0, pnl=-500.0,  offset=3),
            _buy("HDFCBANK", qty=20, price=740.0,  offset=4),
            _sell("HDFCBANK",qty=20, price=800.0,  pnl=1200.0,  offset=5),
        ]

    def test_mixed_portfolio_stats(self):
        from portfolio_performance.api import get_statistics
        p1, p2 = self._make_store(self._make_trades_mixed())
        with p1, p2:
            r = get_statistics()
        ts = r["trade_statistics"]
        self.assertEqual(ts["total_trades"], 3)
        self.assertEqual(ts["winning_trades"], 2)
        self.assertEqual(ts["losing_trades"], 1)
        self.assertAlmostEqual(ts["win_rate"], 200/3, places=1)   # 66.66…

    def test_profit_factor(self):
        from portfolio_performance.api import get_statistics
        p1, p2 = self._make_store(self._make_trades_mixed())
        with p1, p2:
            r = get_statistics()
        rm = r["risk_metrics"]
        # gross_profit = 2200, gross_loss = 500 → PF = 4.4
        self.assertAlmostEqual(rm["gross_profit"], 2200.0, places=1)
        self.assertAlmostEqual(rm["gross_loss"],    500.0, places=1)
        self.assertAlmostEqual(rm["profit_factor"],   4.4, places=1)

    def test_strategy_contribution(self):
        from portfolio_performance.api import get_statistics
        p1, p2 = self._make_store(self._make_trades_mixed())
        with p1, p2:
            r = get_statistics()
        sc = r["strategy_contribution"]
        # All trades use default strategy_name="Momentum"
        self.assertTrue(any(s["strategy_name"] == "Momentum" for s in sc))

    def test_top_winners_top_losers(self):
        from portfolio_performance.api import get_statistics
        p1, p2 = self._make_store(self._make_trades_mixed())
        with p1, p2:
            r = get_statistics()
        self.assertTrue(len(r["top_winners"]) <= 10)
        self.assertTrue(len(r["top_losers"])  <= 10)
        # top_winners are sorted descending by P&L — first element is the best
        if len(r["top_winners"]) >= 2:
            self.assertGreaterEqual(r["top_winners"][0]["pnl"], r["top_winners"][-1]["pnl"])
        # top_losers are sorted ascending by P&L — first element is the worst
        if len(r["top_losers"]) >= 2:
            self.assertLessEqual(r["top_losers"][0]["pnl"], r["top_losers"][-1]["pnl"])
        # RELIANCE (pnl=-500) must appear in top_losers
        loser_syms = [t["symbol"] for t in r["top_losers"]]
        self.assertIn("RELIANCE", loser_syms)


class TestWinningPortfolio(unittest.TestCase):
    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def test_all_winning_summary(self):
        from portfolio_performance.api import get_summary
        trades = [
            _buy("INFY",     10, 1000.0, offset=0),
            _sell("INFY",    10, 1100.0, pnl=1000.0, offset=1),
            _buy("RELIANCE", 5,  2000.0, offset=2),
            _sell("RELIANCE",5,  2200.0, pnl=1000.0, offset=3),
        ]
        with patch("portfolio_store.load_all_trades_any", return_value=trades), \
             patch("portfolio_store.load_state", return_value={
                 "cash": 480_000.0, "positions": {},
                 "pnl_history": _pnl_hist([(0, 500_000.0), (4, 502_000.0)]),
             }):
            r = get_summary()
        self.assertEqual(r["winning_trades"], 2)
        self.assertEqual(r["losing_trades"],  0)
        self.assertGreater(r["realised_pnl"], 0)


class TestLosingPortfolio(unittest.TestCase):
    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def test_all_losing_summary(self):
        from portfolio_performance.api import get_summary
        trades = [
            _buy("INFY", 10, 1000.0, offset=0),
            _sell("INFY", 10, 900.0, pnl=-1000.0, offset=1),
        ]
        with patch("portfolio_store.load_all_trades_any", return_value=trades), \
             patch("portfolio_store.load_state", return_value={
                 "cash": 499_000.0, "positions": {},
                 "pnl_history": _pnl_hist([(0, 500_000.0), (2, 499_000.0)]),
             }):
            r = get_summary()
        self.assertEqual(r["losing_trades"], 1)
        self.assertLess(r["realised_pnl"], 0)
        self.assertAlmostEqual(r["profit_factor"], 0.0, places=1)


class TestDrawdownCalculations(unittest.TestCase):
    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def test_max_drawdown(self):
        from portfolio_performance.equity_curve import _points_from_history, _annotate_drawdown
        from portfolio_performance.drawdown import compute_drawdown_stats

        hist = _pnl_hist([
            (0, 500_000.0),
            (1, 510_000.0),   # new peak
            (2, 495_000.0),   # drawdown 15k
            (3, 488_000.0),   # drawdown 22k — max
            (4, 505_000.0),   # partial recovery
        ])
        pts = _points_from_history(hist)
        _annotate_drawdown(pts)
        stats = compute_drawdown_stats(pts, 500_000.0)

        self.assertAlmostEqual(stats["max_drawdown"], 22_000.0, places=0)
        self.assertAlmostEqual(stats["max_drawdown_pct"], 22_000 / 510_000 * 100, places=2)
        self.assertAlmostEqual(stats["all_time_peak"], 510_000.0, places=0)
        # current drawdown from 510k peak to 505k = 5k
        self.assertAlmostEqual(stats["current_drawdown"], 5_000.0, places=0)

    def test_no_drawdown_at_new_high(self):
        from portfolio_performance.equity_curve import _points_from_history, _annotate_drawdown
        from portfolio_performance.drawdown import compute_drawdown_stats

        hist = _pnl_hist([(0, 500_000.0), (1, 505_000.0), (2, 510_000.0)])
        pts  = _points_from_history(hist)
        _annotate_drawdown(pts)
        stats = compute_drawdown_stats(pts, 500_000.0)

        self.assertAlmostEqual(stats["max_drawdown"],     0.0, places=1)
        self.assertAlmostEqual(stats["current_drawdown"], 0.0, places=1)
        self.assertAlmostEqual(stats["recovery_pct"],   100.0, places=1)

    def test_drawdown_api_response(self):
        from portfolio_performance.api import get_drawdown
        with patch("portfolio_store.load_all_trades_any", return_value=[]), \
             patch("portfolio_store.load_state", return_value={
                 "cash": 490_000.0, "positions": {},
                 "pnl_history": _pnl_hist([(0, 500_000.0), (1, 510_000.0), (2, 495_000.0)]),
             }):
            r = get_drawdown()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("max_drawdown", r)
        self.assertIn("series", r)
        self.assertIsInstance(r["series"], list)


class TestEquityCurveCalculations(unittest.TestCase):
    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def test_daily_curve_sorted(self):
        from portfolio_performance.equity_curve import build_equity_curves
        hist = _pnl_hist([(0, 500_000.0), (24, 501_000.0), (48, 502_000.0)])
        curves = build_equity_curves(hist)
        daily = curves["daily"]
        self.assertGreater(len(daily), 0)
        timestamps = [p["timestamp"] for p in daily]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_weekly_is_subset_of_daily(self):
        from portfolio_performance.equity_curve import build_equity_curves
        hist = _pnl_hist([(h, 500_000.0 + h * 100) for h in range(0, 24 * 14, 24)])
        curves = build_equity_curves(hist)
        self.assertLessEqual(len(curves["weekly"]), len(curves["daily"]))

    def test_monthly_is_subset_of_weekly(self):
        from portfolio_performance.equity_curve import build_equity_curves
        hist = _pnl_hist([(h, 500_000.0 + h * 50) for h in range(0, 24 * 60, 24)])
        curves = build_equity_curves(hist)
        self.assertLessEqual(len(curves["monthly"]), len(curves["weekly"]))

    def test_daily_pnl_bars(self):
        from portfolio_performance.equity_curve import build_equity_curves
        hist = _pnl_hist([(0, 500_000.0), (24, 502_000.0), (48, 501_500.0)])
        curves = build_equity_curves(hist)
        bars = curves["daily_pnl"]
        self.assertIsInstance(bars, list)
        # second bar pnl = 502k - 500k = 2000
        if len(bars) >= 2:
            self.assertAlmostEqual(bars[1]["pnl"], 2_000.0, places=0)

    def test_equity_api_response(self):
        from portfolio_performance.api import get_equity
        hist = _pnl_hist([(0, 500_000.0), (24, 501_000.0)])
        with patch("portfolio_store.load_all_trades_any", return_value=[]), \
             patch("portfolio_store.load_state", return_value={
                 "cash": 501_000.0, "positions": {}, "pnl_history": hist,
             }):
            r = get_equity("daily")
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["period"], "daily")
        self.assertIn("series", r)
        self.assertIn("daily_pnl", r)
        self.assertIn("monthly_pnl", r)


class TestRestartPersistence(unittest.TestCase):
    """Verify no mutable module-level state corrupts repeated calls."""

    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    def test_two_summary_calls_consistent(self):
        from portfolio_performance.api import get_summary
        state = {
            "cash": 499_000.0, "positions": {},
            "pnl_history": _pnl_hist([(0, 500_000.0), (1, 499_000.0)]),
        }
        trades = [
            _buy("INFY", 10, 1000.0, offset=0),
            _sell("INFY", 10, 900.0, pnl=-1000.0, offset=1),
        ]
        with patch("portfolio_store.load_all_trades_any", return_value=trades), \
             patch("portfolio_store.load_state", return_value=state):
            r1 = get_summary()
            r2 = get_summary()
        self.assertEqual(r1["total_trades"], r2["total_trades"])
        self.assertAlmostEqual(r1["realised_pnl"], r2["realised_pnl"], places=2)


# ══════════════════════════════════════════════════════════════════════════════
# portfolio_performance/shared_services.py — string KPI coercion tests
# ══════════════════════════════════════════════════════════════════════════════

class TestStringKpiCoercion(unittest.TestCase):
    """
    Guard: grade and trend in get_portfolio_performance_snapshot() must always
    be plain strings, never a dict/None/list, regardless of upstream data.
    """

    def setUp(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("PORTFOLIO_PERFORMANCE_ENABLED", None)

    # ── _as_str helper unit tests ─────────────────────────────────────────────

    def test_as_str_none_returns_fallback(self):
        from portfolio_performance.shared_services import _as_str
        self.assertEqual(_as_str(None), "N/A")

    def test_as_str_dict_returns_fallback(self):
        from portfolio_performance.shared_services import _as_str
        self.assertEqual(_as_str({"key": "val"}), "N/A")

    def test_as_str_empty_string_returns_fallback(self):
        from portfolio_performance.shared_services import _as_str
        self.assertEqual(_as_str(""), "N/A")

    def test_as_str_valid_string_passes_through(self):
        from portfolio_performance.shared_services import _as_str
        self.assertEqual(_as_str("IMPROVING"), "IMPROVING")

    # ── _portfolio_grade helper ───────────────────────────────────────────────

    def test_grade_a_high_win_rate(self):
        from portfolio_performance.shared_services import _portfolio_grade
        self.assertEqual(_portfolio_grade(70.0), "A")

    def test_grade_b_mid_win_rate(self):
        from portfolio_performance.shared_services import _portfolio_grade
        self.assertEqual(_portfolio_grade(58.0), "B")

    def test_grade_c(self):
        from portfolio_performance.shared_services import _portfolio_grade
        self.assertEqual(_portfolio_grade(48.0), "C")

    def test_grade_d(self):
        from portfolio_performance.shared_services import _portfolio_grade
        self.assertEqual(_portfolio_grade(38.0), "D")

    def test_grade_f_zero_win_rate(self):
        from portfolio_performance.shared_services import _portfolio_grade
        self.assertEqual(_portfolio_grade(0.0), "F")

    # ── _portfolio_trend helper ───────────────────────────────────────────────

    def test_trend_improving_positive_weekly(self):
        from portfolio_performance.shared_services import _portfolio_trend
        self.assertEqual(_portfolio_trend(500.0, 1000.0), "IMPROVING")

    def test_trend_weakening_negative_weekly(self):
        from portfolio_performance.shared_services import _portfolio_trend
        self.assertEqual(_portfolio_trend(-200.0, 1000.0), "WEAKENING")

    def test_trend_stable_zero_weekly(self):
        from portfolio_performance.shared_services import _portfolio_trend
        self.assertEqual(_portfolio_trend(0.0, 0.0), "STABLE")

    # ── get_portfolio_performance_snapshot() disabled ─────────────────────────

    def test_disabled_returns_disabled_status(self):
        os.environ["PORTFOLIO_PERFORMANCE_ENABLED"] = "false"
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        snap = get_portfolio_performance_snapshot()
        self.assertEqual(snap["status"], "DISABLED")

    # ── get_portfolio_performance_snapshot() field types ─────────────────────

    def _make_summary(self, win_rate=55.0, weekly_pnl=200.0, monthly_pnl=600.0,
                      net_pnl=1000.0, total_ret=0.5, trades=5, opens=1):
        return {
            "status": "ENABLED", "win_rate": win_rate,
            "weekly_pnl": weekly_pnl, "monthly_pnl": monthly_pnl,
            "total_net_pnl": net_pnl, "total_return_pct": total_ret,
            "total_trades": trades, "open_trades": opens,
        }

    def test_grade_is_str(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary()):
            snap = get_portfolio_performance_snapshot()
        self.assertIsInstance(snap.get("grade"), str,
            f"grade type={type(snap.get('grade')).__name__!r}")

    def test_trend_is_str(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary()):
            snap = get_portfolio_performance_snapshot()
        self.assertIsInstance(snap.get("trend"), str,
            f"trend type={type(snap.get('trend')).__name__!r}")

    def test_grade_not_none(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary()):
            snap = get_portfolio_performance_snapshot()
        self.assertIsNotNone(snap.get("grade"), "grade was None")

    def test_trend_not_none(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary()):
            snap = get_portfolio_performance_snapshot()
        self.assertIsNotNone(snap.get("trend"), "trend was None")

    def test_grade_not_dict(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary()):
            snap = get_portfolio_performance_snapshot()
        self.assertNotIsInstance(snap.get("grade"), dict,
            "grade was a dict — coercion is missing")

    def test_grade_value_b_for_55_pct_win_rate(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary(win_rate=55.0)):
            snap = get_portfolio_performance_snapshot()
        self.assertEqual(snap["grade"], "B")

    def test_trend_improving_for_positive_weekly(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary(weekly_pnl=500.0)):
            snap = get_portfolio_performance_snapshot()
        self.assertEqual(snap["trend"], "IMPROVING")

    def test_trend_weakening_for_negative_weekly(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary(weekly_pnl=-200.0)):
            snap = get_portfolio_performance_snapshot()
        self.assertEqual(snap["trend"], "WEAKENING")

    def test_advisory_only_flag_present(self):
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        with patch("portfolio_performance.api.get_summary",
                   return_value=self._make_summary()):
            snap = get_portfolio_performance_snapshot()
        self.assertTrue(snap.get("advisory_only"))


if __name__ == "__main__":
    unittest.main()
