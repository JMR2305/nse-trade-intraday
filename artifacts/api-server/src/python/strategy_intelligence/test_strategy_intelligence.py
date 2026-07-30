"""
test_strategy_intelligence.py — Phase 5D.3 unit tests.

Covers all spec scenarios:
  ✓ Zero trades
  ✓ One strategy
  ✓ Multiple strategies
  ✓ Winning strategy
  ✓ Losing strategy
  ✓ Mixed performance
  ✓ Market regime calculations
  ✓ Sector calculations
  ✓ Time analysis
  ✓ Recommendation generation
  ✓ Shared service reuse
  ✓ API responses
  ✓ Restart persistence

Run: python -m pytest strategy_intelligence/test_strategy_intelligence.py -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

# Disable feature flag by default
os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

# Stub market_scanner
_scanner = types.ModuleType("market_scanner")
_SECTOR_MAP = {
    "HDFCBANK": "Banking", "ICICIBANK": "Banking",
    "INFY": "IT", "TCS": "IT",
    "RELIANCE": "Energy",
    "SUNPHARMA": "Pharma",
}
_scanner._sector_of = lambda sym: _SECTOR_MAP.get(sym, "Unknown")
sys.modules.setdefault("market_scanner", _scanner)

# Stub execution_quality
_eq_stub = types.ModuleType("execution_quality")
_eq_metrics = types.ModuleType("execution_quality.metrics")
_eq_metrics.build_execution_records = lambda: []
_eq_stub.metrics = _eq_metrics
sys.modules.setdefault("execution_quality", _eq_stub)
sys.modules.setdefault("execution_quality.metrics", _eq_metrics)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(offset_hours: float = 0, day_offset: int = 0) -> str:
    # Base: Monday 2026-07-27 09:30 IST = 04:00 UTC
    base = datetime(2026, 7, 27, 4, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=offset_hours, days=day_offset)).isoformat()


def _buy(symbol="INFY", qty=10, price=1000.0, offset=0, day=0,
         strategy_id="s1", strategy_name="Momentum",
         stop_loss=950.0, target=1080.0, regime="Bullish",
         confidence=0.75) -> dict:
    return {
        "id":                   f"buy-{symbol}-{day}-{offset}",
        "symbol":               symbol,
        "action":               "BUY",
        "quantity":             qty,
        "price":                price,
        "total":                qty * price,
        "timestamp":            _ts(offset, day),
        "reason":               "signal",
        "strategy_id":          strategy_id,
        "strategy_name":        strategy_name,
        "stop_loss":            stop_loss,
        "target":               target,
        "market_regime_at_entry": regime,
        "signal_confidence":    confidence,
    }


def _sell(symbol="INFY", qty=10, price=1100.0, pnl=1000.0,
          offset=2, day=0, exit_type="TARGET_HIT") -> dict:
    return {
        "id":        f"sell-{symbol}-{day}-{offset}",
        "symbol":    symbol,
        "action":    "SELL",
        "quantity":  qty,
        "price":     price,
        "total":     qty * price,
        "timestamp": _ts(offset, day),
        "reason":    "exit",
        "pnl":       pnl,
        "pnl_pct":   pnl / (qty * 1000.0) * 100,
        "exit_type": exit_type,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Feature flag
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlag(unittest.TestCase):
    def setUp(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def test_all_endpoints_disabled(self):
        from strategy_intelligence.api import (
            get_summary, get_rankings, get_regimes,
            get_sectors, get_timing, get_recommendations_api,
        )
        for fn in (get_summary, get_rankings, get_regimes,
                   get_sectors, get_timing, get_recommendations_api):
            r = fn()
            self.assertEqual(r["status"], "DISABLED", msg=fn.__name__)

    def test_shared_services_disabled(self):
        from strategy_intelligence.shared_services import (
            get_all_strategy_profiles, get_strategy_rankings,
            get_recommendations, get_criterion_rankings, get_summary_snapshot,
        )
        self.assertEqual(get_all_strategy_profiles(), [])
        self.assertEqual(get_strategy_rankings(), [])
        self.assertEqual(get_recommendations(), [])
        self.assertEqual(get_criterion_rankings(), {})
        self.assertEqual(get_summary_snapshot()["status"], "DISABLED")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Zero trades
# ══════════════════════════════════════════════════════════════════════════════

class TestZeroTrades(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _mock(self):
        return patch("portfolio_store.load_all_trades_any", return_value=[])

    def test_summary_zero_trades(self):
        from strategy_intelligence.api import get_summary
        with self._mock():
            r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_closed_trades"], 0)
        self.assertEqual(r["leaderboard"], [])

    def test_rankings_zero_trades(self):
        from strategy_intelligence.api import get_rankings
        with self._mock():
            r = get_rankings()
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["leaderboard"], [])

    def test_regime_zero_trades(self):
        from strategy_intelligence.api import get_regimes
        with self._mock():
            r = get_regimes()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["matrix"], {})

    def test_timing_zero_trades(self):
        from strategy_intelligence.api import get_timing
        with self._mock():
            r = get_timing()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIsNone(r["best_day"])


# ══════════════════════════════════════════════════════════════════════════════
# 3. Single strategy
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleStrategy(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _trades(self, pnls):
        trades = []
        for i, pnl in enumerate(pnls):
            trades.append(_buy("INFY", offset=i * 4, day=i,
                               strategy_name="Momentum"))
            exit_price = 1000.0 + pnl / 10
            trades.append(_sell("INFY", price=exit_price, pnl=pnl,
                                offset=i * 4 + 2, day=i))
        return trades

    def test_winning_strategy(self):
        from strategy_intelligence.api import get_rankings
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._trades([500, 700, 400])):
            r = get_rankings()
        self.assertEqual(r["total"], 1)
        p = r["profiles"][0]
        self.assertEqual(p["winning_trades"], 3)
        self.assertEqual(p["losing_trades"], 0)
        self.assertAlmostEqual(p["win_rate"], 100.0, places=1)
        self.assertGreater(p["net_pnl"], 0)

    def test_losing_strategy(self):
        from strategy_intelligence.api import get_rankings
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._trades([-300, -200, -500])):
            r = get_rankings()
        p = r["profiles"][0]
        self.assertEqual(p["winning_trades"], 0)
        self.assertLess(p["net_pnl"], 0)
        self.assertAlmostEqual(p["profit_factor"], 0.0, places=1)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Multiple strategies
# ══════════════════════════════════════════════════════════════════════════════

class TestMultipleStrategies(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _mixed_trades(self):
        return [
            # Momentum — 2 wins, 1 loss
            _buy("INFY",     offset=0, day=0, strategy_name="Momentum"),
            _sell("INFY",    offset=2, day=0, pnl=800.0),
            _buy("TCS",      offset=4, day=0, strategy_name="Momentum"),
            _sell("TCS",     offset=6, day=0, pnl=-300.0),
            _buy("HDFCBANK", offset=0, day=1, strategy_name="Momentum"),
            _sell("HDFCBANK",offset=2, day=1, pnl=600.0),
            # Mean Reversion — 1 win, 2 losses
            _buy("RELIANCE", offset=0, day=2, strategy_name="Mean Reversion",
                 strategy_id="s2"),
            _sell("RELIANCE",offset=2, day=2, pnl=1200.0),
            _buy("SUNPHARMA",offset=4, day=2, strategy_name="Mean Reversion",
                 strategy_id="s2"),
            _sell("SUNPHARMA",offset=6,day=2, pnl=-400.0),
            _buy("ICICIBANK",offset=0, day=3, strategy_name="Mean Reversion",
                 strategy_id="s2"),
            _sell("ICICIBANK",offset=2,day=3, pnl=-200.0),
        ]

    def test_two_strategies_detected(self):
        from strategy_intelligence.api import get_rankings
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._mixed_trades()):
            r = get_rankings()
        self.assertEqual(r["total"], 2)
        names = {p["strategy_name"] for p in r["profiles"]}
        self.assertIn("Momentum", names)
        self.assertIn("Mean Reversion", names)

    def test_ranking_order(self):
        from strategy_intelligence.api import get_rankings
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._mixed_trades()):
            r = get_rankings()
        # Momentum: net +1100, win_rate 66% vs Mean Reversion: net +600, win_rate 33%
        lb = r["leaderboard"]
        # rank=1 should have higher rank_score
        self.assertGreater(lb[0]["rank_score"], lb[1]["rank_score"])

    def test_criterion_rankings_populated(self):
        from strategy_intelligence.api import get_rankings
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._mixed_trades()):
            r = get_rankings()
        cr = r["criterion_rankings"]
        self.assertIn("highest_win_rate", cr)
        self.assertIn("highest_net_profit", cr)
        self.assertIn("lowest_drawdown", cr)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Mixed performance
# ══════════════════════════════════════════════════════════════════════════════

class TestMixedPerformance(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def test_profit_factor_calculation(self):
        from strategy_intelligence.strategy_statistics import build_strategy_profile
        from strategy_intelligence.strategy_models import ClosedTrade

        trades = [
            ClosedTrade(trade_id="t1", symbol="INFY", pnl=500.0,
                        strategy_name="Test", exit_ts="2026-07-27T10:00:00+00:00"),
            ClosedTrade(trade_id="t2", symbol="TCS",  pnl=-200.0,
                        strategy_name="Test", exit_ts="2026-07-27T11:00:00+00:00"),
            ClosedTrade(trade_id="t3", symbol="HDFCBANK", pnl=300.0,
                        strategy_name="Test", exit_ts="2026-07-27T12:00:00+00:00"),
        ]
        p = build_strategy_profile("Test", "t", trades)
        self.assertAlmostEqual(p.gross_profit, 800.0, places=1)
        self.assertAlmostEqual(p.gross_loss,   200.0, places=1)
        self.assertAlmostEqual(p.profit_factor,  4.0, places=1)
        self.assertAlmostEqual(p.net_pnl,       600.0, places=1)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Market regime analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketRegimeAnalysis(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _regime_trades(self):
        return [
            _buy("INFY",     offset=0, day=0, regime="Bullish"),
            _sell("INFY",    offset=2, day=0, pnl=600.0),
            _buy("TCS",      offset=0, day=1, regime="Bullish"),
            _sell("TCS",     offset=2, day=1, pnl=400.0),
            _buy("RELIANCE", offset=0, day=2, regime="Bearish"),
            _sell("RELIANCE",offset=2, day=2, pnl=-300.0),
            _buy("HDFCBANK", offset=0, day=3, regime="High Volatility"),
            _sell("HDFCBANK",offset=2, day=3, pnl=200.0),
        ]

    def test_regime_matrix_populated(self):
        from strategy_intelligence.api import get_regimes
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._regime_trades()):
            r = get_regimes()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("Bullish", r["matrix"])
        self.assertIn("Bearish", r["matrix"])
        self.assertIn("High Volatility", r["matrix"])

    def test_bullish_regime_stats(self):
        from strategy_intelligence.api import get_regimes
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._regime_trades()):
            r = get_regimes()
        bullish = r["matrix"]["Bullish"]
        self.assertEqual(bullish["trades"], 2)
        self.assertAlmostEqual(bullish["net_pnl"], 1000.0, places=1)
        self.assertAlmostEqual(bullish["win_rate"], 100.0, places=1)

    def test_best_per_regime(self):
        from strategy_intelligence.api import get_regimes
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._regime_trades()):
            r = get_regimes()
        self.assertIn("Bullish", r["best_per_regime"])


# ══════════════════════════════════════════════════════════════════════════════
# 7. Sector analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestSectorAnalysis(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _sector_trades(self):
        return [
            _buy("HDFCBANK", offset=0, day=0), _sell("HDFCBANK", offset=2, day=0, pnl=800.0),
            _buy("ICICIBANK",offset=0, day=1), _sell("ICICIBANK",offset=2, day=1, pnl=600.0),
            _buy("INFY",     offset=0, day=2), _sell("INFY",     offset=2, day=2, pnl=-200.0),
            _buy("RELIANCE", offset=0, day=3), _sell("RELIANCE", offset=2, day=3, pnl=400.0),
        ]

    def test_sector_matrix_populated(self):
        from strategy_intelligence.api import get_sectors
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._sector_trades()):
            r = get_sectors()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("Banking", r["matrix"])
        self.assertIn("IT", r["matrix"])

    def test_best_worst_sector(self):
        from strategy_intelligence.api import get_sectors
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._sector_trades()):
            r = get_sectors()
        self.assertIsNotNone(r["best_sector"])
        self.assertIsNotNone(r["worst_sector"])
        # Banking: +1400, IT: -200, Energy: +400
        self.assertEqual(r["best_sector"], "Banking")
        self.assertEqual(r["worst_sector"], "IT")

    def test_sector_summary_sorted(self):
        from strategy_intelligence.api import get_sectors
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._sector_trades()):
            r = get_sectors()
        pnls = [s["net_pnl"] for s in r["summary"]]
        self.assertEqual(pnls, sorted(pnls, reverse=True))


# ══════════════════════════════════════════════════════════════════════════════
# 8. Time analysis
# ══════════════════════════════════════════════════════════════════════════════

class TestTimeAnalysis(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _time_trades(self):
        # offset 0 = 04:00 UTC = 09:30 IST (Mon) → slot 09:15–10:00
        # offset 5 = 09:00 UTC = 14:30 IST (Mon) → slot 14:00–15:30
        # day=1 → Tuesday
        return [
            _buy("INFY", offset=0.25, day=0),   # 09:45 IST Mon
            _sell("INFY", offset=2.25, day=0, pnl=500.0),
            _buy("TCS",   offset=5.0,  day=0),   # 14:30 IST Mon
            _sell("TCS",  offset=7.0,  day=0, pnl=-100.0),
            _buy("HDFCBANK", offset=0.25, day=1),  # 09:45 IST Tue
            _sell("HDFCBANK",offset=2.25, day=1, pnl=300.0),
        ]

    def test_time_analysis_response(self):
        from strategy_intelligence.api import get_timing
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._time_trades()):
            r = get_timing()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("slot_matrix", r)
        self.assertIn("day_matrix", r)
        self.assertIn("hour_matrix", r)

    def test_best_day_detected(self):
        from strategy_intelligence.api import get_timing
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._time_trades()):
            r = get_timing()
        # Monday: +400 (500-100), Tuesday: +300
        self.assertEqual(r["best_day"], "Monday")
        self.assertEqual(r["worst_day"], "Tuesday")

    def test_slot_matrix_has_early_slot(self):
        from strategy_intelligence.api import get_timing
        with patch("portfolio_store.load_all_trades_any",
                   return_value=self._time_trades()):
            r = get_timing()
        slot = r["slot_matrix"].get("09:15–10:00", {})
        self.assertGreater(slot.get("trades", 0), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Recommendation generation
# ══════════════════════════════════════════════════════════════════════════════

class TestRecommendations(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _build_profile(self, win_rate, profit_factor, max_dd_pct, net_pnl, n=10):
        from strategy_intelligence.strategy_models import StrategyProfile
        p = StrategyProfile(
            strategy_name="Test",
            total_trades=n,
            winning_trades=int(n * win_rate / 100),
            losing_trades=n - int(n * win_rate / 100),
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd_pct,
            net_pnl=net_pnl,
            avg_profit=abs(net_pnl) * 0.6 / max(1, int(n * win_rate / 100)),
            avg_loss=-abs(net_pnl) * 0.4 / max(1, n - int(n * win_rate / 100)),
        )
        return p

    def test_increase_allocation(self):
        from strategy_intelligence.recommendations import _classify
        p = self._build_profile(65, 2.5, 5.0, 5000.0)
        self.assertEqual(_classify(p), "Increase Allocation")

    def test_high_drawdown(self):
        from strategy_intelligence.recommendations import _classify
        p = self._build_profile(55, 1.5, 30.0, 2000.0)
        self.assertEqual(_classify(p), "High Drawdown Risk")

    def test_underperforming(self):
        from strategy_intelligence.recommendations import _classify
        p = self._build_profile(30, 0.7, 8.0, -1000.0)
        self.assertEqual(_classify(p), "Underperforming")

    def test_promising_few_trades(self):
        from strategy_intelligence.recommendations import _classify
        p = self._build_profile(60, 1.8, 4.0, 800.0, n=3)
        self.assertEqual(_classify(p), "Promising — More Data Needed")

    def test_recommendations_api(self):
        from strategy_intelligence.api import get_recommendations_api
        trades = [
            _buy("INFY", offset=0, day=0), _sell("INFY", offset=2, day=0, pnl=500.0),
            _buy("TCS",  offset=0, day=1), _sell("TCS",  offset=2, day=1, pnl=-200.0),
        ] * 5
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r = get_recommendations_api()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIsInstance(r["recommendations"], list)
        for rec in r["recommendations"]:
            self.assertIn("recommendation", rec)
            self.assertIn("severity", rec)
            self.assertIn("rationale", rec)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Shared service reuse
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedServices(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def _trades(self):
        return [
            _buy("INFY", offset=0, day=0), _sell("INFY", offset=2, day=0, pnl=500.0),
            _buy("TCS",  offset=0, day=1), _sell("TCS",  offset=2, day=1, pnl=-200.0),
        ] * 3

    def test_get_all_profiles_returns_list(self):
        from strategy_intelligence.shared_services import get_all_strategy_profiles
        with patch("portfolio_store.load_all_trades_any", return_value=self._trades()):
            profiles = get_all_strategy_profiles()
        self.assertIsInstance(profiles, list)

    def test_get_strategy_stats_single(self):
        from strategy_intelligence.shared_services import get_strategy_stats
        with patch("portfolio_store.load_all_trades_any", return_value=self._trades()):
            r = get_strategy_stats("Momentum")
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("profile", r)
        self.assertEqual(r["profile"]["strategy_name"], "Momentum")

    def test_get_summary_snapshot(self):
        from strategy_intelligence.shared_services import get_summary_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=self._trades()):
            r = get_summary_snapshot()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("best_strategy", r)
        self.assertIn("total_strategies", r)
        self.assertIn("criterion_rankings", r)

    def test_shared_service_consistent_with_api(self):
        """shared_services returns same data as API endpoints — no duplication."""
        from strategy_intelligence.shared_services import get_strategy_rankings
        from strategy_intelligence.api import get_rankings
        trades = self._trades()
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            shared = get_strategy_rankings()
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            api    = get_rankings()["leaderboard"]
        # Both reference the same strategy names (may differ in length if API trims)
        shared_names = {r["strategy_name"] for r in shared}
        api_names    = {r["strategy_name"] for r in api}
        self.assertTrue(api_names.issubset(shared_names))


# ══════════════════════════════════════════════════════════════════════════════
# 11. Restart persistence
# ══════════════════════════════════════════════════════════════════════════════

class TestRestartPersistence(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    def test_two_calls_consistent(self):
        from strategy_intelligence.api import get_summary
        trades = [
            _buy("INFY", offset=0, day=0), _sell("INFY", offset=2, day=0, pnl=500.0),
        ]
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            r1 = get_summary()
            r2 = get_summary()
        self.assertEqual(r1["total_closed_trades"], r2["total_closed_trades"])
        self.assertAlmostEqual(r1["total_net_pnl"], r2["total_net_pnl"], places=2)


# ══════════════════════════════════════════════════════════════════════════════
# 12. best_regime always returns a string
# ══════════════════════════════════════════════════════════════════════════════

class TestBestRegimeString(unittest.TestCase):
    """
    Guard: get_summary_snapshot() must return best_regime as a plain str,
    never as a dict/None, so the executive dashboard KpiCard never crashes.
    """

    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)

    # ── _best_regime_str helper ────────────────────────────────────────────

    def test_helper_empty_matrix_returns_na(self):
        from strategy_intelligence.shared_services import _best_regime_str
        result = _best_regime_str({"matrix": {}, "best_per_regime": {}})
        self.assertIsInstance(result, str)
        self.assertEqual(result, "N/A")

    def test_helper_missing_matrix_returns_na(self):
        from strategy_intelligence.shared_services import _best_regime_str
        result = _best_regime_str({})
        self.assertIsInstance(result, str)
        self.assertEqual(result, "N/A")

    def test_helper_picks_highest_pnl_regime(self):
        from strategy_intelligence.shared_services import _best_regime_str
        rd = {
            "matrix": {
                "Bullish":       {"net_pnl": 1000.0, "win_rate": 80.0},
                "Bearish":       {"net_pnl": -300.0, "win_rate": 30.0},
                "High Volatility": {"net_pnl": 500.0, "win_rate": 60.0},
            },
            "best_per_regime": {
                "Bullish": "MACD_CROSS",
                "High Volatility": "RSI_BOUNCE",
            },
        }
        result = _best_regime_str(rd)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "Bullish")

    def test_helper_single_regime(self):
        from strategy_intelligence.shared_services import _best_regime_str
        rd = {
            "matrix": {"Bearish": {"net_pnl": -100.0, "win_rate": 40.0}},
            "best_per_regime": {"Bearish": "VWAP_PULL"},
        }
        result = _best_regime_str(rd)
        self.assertIsInstance(result, str)
        self.assertEqual(result, "Bearish")

    # ── get_summary_snapshot integration ──────────────────────────────────

    def test_snapshot_best_regime_is_string_with_zero_trades(self):
        """No trades → best_regime must be the string 'N/A', never {}."""
        from strategy_intelligence.shared_services import get_summary_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_summary_snapshot()
        self.assertIsInstance(snap.get("best_regime"), str,
            f"best_regime was {type(snap.get('best_regime')).__name__!r}, expected str")
        self.assertEqual(snap["best_regime"], "N/A")

    def test_snapshot_best_regime_is_string_with_trades(self):
        """With regime data, best_regime must still be a plain string."""
        from strategy_intelligence.shared_services import get_summary_snapshot
        trades = [
            _buy("INFY",  offset=0, day=0, regime="Bullish"),
            _sell("INFY", offset=2, day=0, pnl=800.0),
            _buy("TCS",   offset=0, day=1, regime="Bearish"),
            _sell("TCS",  offset=2, day=1, pnl=-200.0),
        ]
        with patch("portfolio_store.load_all_trades_any", return_value=trades):
            snap = get_summary_snapshot()
        regime = snap.get("best_regime")
        self.assertIsInstance(regime, str,
            f"best_regime was {type(regime).__name__!r}, expected str")
        # "Bullish" has higher net P&L (800) than "Bearish" (-200)
        self.assertEqual(regime, "Bullish")

    def test_snapshot_best_regime_not_dict(self):
        """Regression: best_regime must never be a dict (the original bug)."""
        from strategy_intelligence.shared_services import get_summary_snapshot
        with patch("portfolio_store.load_all_trades_any", return_value=[]):
            snap = get_summary_snapshot()
        self.assertNotIsInstance(snap.get("best_regime"), dict,
            "best_regime returned a dict — the API contract regression has returned")


if __name__ == "__main__":
    unittest.main()
