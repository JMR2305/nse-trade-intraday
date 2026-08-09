"""
test_analytics_30plus_integration.py — Task: confirm Strategy Intelligence
(Phase 5D.3) and AI Performance (Phase 5D.4) stay accurate after 30+ real
paper trades, not just on an empty dataset.

Seeds portfolio_store with 36 realistic closed BUY/SELL paper-trade records
covering 3 strategies, 3 market regimes, multiple sectors and the full
confidence range, then exercises the REAL endpoint entrypoints:

  strategy_intelligence.api.get_rankings   → /api/strategy/rankings
  strategy_intelligence.api.get_regimes    → /api/strategy/regimes
  strategy_intelligence.api.get_summary    → /api/strategy/summary
  ai_performance.api.get_calibration       → /api/ai/calibration
  ai_performance.api.get_confidence        → /api/ai/confidence
  ai_performance.api.get_summary           → /api/ai/summary

and asserts meaningful non-zero values plus cross-endpoint consistency of
win_rate, profit_factor and health_score.

Run: python -m pytest test_analytics_30plus_integration.py -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Stub heavy neighbours (same pattern as the module unit tests) ────────────
_scanner = types.ModuleType("market_scanner")
_SECTOR_MAP = {
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "AXISBANK": "Banking",
    "INFY": "IT", "TCS": "IT", "WIPRO": "IT",
    "RELIANCE": "Energy", "ONGC": "Energy",
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma",
}
_scanner._sector_of = lambda sym: _SECTOR_MAP.get(sym, "Unknown")
sys.modules.setdefault("market_scanner", _scanner)

_eq_stub = types.ModuleType("execution_quality")
_eq_metrics = types.ModuleType("execution_quality.metrics")
_eq_metrics.build_execution_records = lambda: []
_eq_stub.metrics = _eq_metrics
sys.modules.setdefault("execution_quality", _eq_stub)
sys.modules.setdefault("execution_quality.metrics", _eq_metrics)


# ── Realistic seeded dataset: 36 closed paper trades ─────────────────────────

def _ts(offset_hours: float, day: int) -> str:
    # Base: Monday 2026-06-01 09:30 IST = 04:00 UTC
    base = datetime(2026, 6, 1, 4, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=offset_hours, days=day)).isoformat()


_SYMBOLS = ["INFY", "HDFCBANK", "RELIANCE", "TCS", "ICICIBANK",
            "SUNPHARMA", "AXISBANK", "WIPRO", "ONGC", "CIPLA"]
_REGIMES = ["Bullish", "Bearish", "High Volatility"]

# (strategy_id, strategy_name, wins, losses)
_STRATEGIES = [
    ("s1", "Momentum",       8, 4),
    ("s2", "Mean Reversion", 6, 6),
    ("s3", "Breakout",       4, 8),
]

# Confidence values spanning the bucket range; winners lean high, losers low,
# with deliberate overlap so calibration buckets are non-trivial.
_WIN_CONF  = [0.92, 0.86, 0.81, 0.77, 0.74, 0.68, 0.63, 0.55]
_LOSS_CONF = [0.88, 0.72, 0.66, 0.58, 0.52, 0.46, 0.44, 0.41]
_WIN_PNL   = [820.0, 640.0, 510.0, 470.0, 390.0, 330.0, 260.0, 180.0]
_LOSS_PNL  = [-540.0, -460.0, -380.0, -310.0, -260.0, -220.0, -170.0, -120.0]


def build_seed_trades():
    """Return (trades, per_strategy_expected) for 36 closed trades."""
    trades = []
    expected = {}   # name -> dict(total, wins, gross_profit, gross_loss, net)
    day = 0
    for sid, name, n_win, n_loss in _STRATEGIES:
        exp = {"total": n_win + n_loss, "wins": n_win,
               "gross_profit": 0.0, "gross_loss": 0.0, "net": 0.0,
               "pnls": []}
        outcomes = ([("W", _WIN_CONF[i], _WIN_PNL[i]) for i in range(n_win)] +
                    [("L", _LOSS_CONF[i], _LOSS_PNL[i]) for i in range(n_loss)])
        for k, (kind, conf, pnl) in enumerate(outcomes):
            sym = _SYMBOLS[(day + k) % len(_SYMBOLS)]
            regime = _REGIMES[day % len(_REGIMES)]
            qty, entry = 10, 1000.0
            exit_price = entry + pnl / qty
            exit_type = ("TARGET_HIT" if kind == "W" else
                         ("TIME_EXIT" if k % 5 == 4 else "STOP_HIT"))
            trades.append({
                "id": f"buy-{sid}-{day}", "symbol": sym, "action": "BUY",
                "quantity": qty, "price": entry, "total": qty * entry,
                "timestamp": _ts(0.5, day), "reason": "signal",
                "strategy_id": sid, "strategy_name": name,
                "stop_loss": 950.0, "target": 1080.0,
                "market_regime_at_entry": regime,
                "signal_confidence": conf,
            })
            trades.append({
                "id": f"sell-{sid}-{day}", "symbol": sym, "action": "SELL",
                "quantity": qty, "price": exit_price, "total": qty * exit_price,
                "timestamp": _ts(3.0, day), "reason": "exit",
                "pnl": pnl, "pnl_pct": pnl / (qty * entry) * 100,
                "exit_type": exit_type,
            })
            exp["pnls"].append(pnl)
            exp["net"] += pnl
            if pnl > 0:
                exp["gross_profit"] += pnl
            else:
                exp["gross_loss"] += -pnl
            day += 1
        expected[name] = exp
    return trades, expected


SEED_TRADES, EXPECTED = build_seed_trades()
TOTAL_TRADES = sum(e["total"] for e in EXPECTED.values())        # 36
TOTAL_WINS = sum(e["wins"] for e in EXPECTED.values())           # 18


class _Base(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        self._patch = patch("portfolio_store.load_all_trades_any",
                            return_value=list(SEED_TRADES))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        os.environ.pop("STRATEGY_INTELLIGENCE_ENABLED", None)
        os.environ.pop("AI_PERFORMANCE_ENABLED", None)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Seed sanity
# ══════════════════════════════════════════════════════════════════════════════
class TestSeedSanity(_Base):
    def test_thirty_plus_closed_trades(self):
        self.assertGreaterEqual(TOTAL_TRADES, 30)
        self.assertEqual(len(SEED_TRADES), TOTAL_TRADES * 2)


# ══════════════════════════════════════════════════════════════════════════════
# 2. /api/strategy/rankings — non-zero, per-strategy accuracy
# ══════════════════════════════════════════════════════════════════════════════
class TestStrategyRankings(_Base):
    def _rankings(self):
        from strategy_intelligence.api import get_rankings
        return get_rankings()

    def test_all_strategies_profiled(self):
        r = self._rankings()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total"], 3)
        names = {p["strategy_name"] for p in r["profiles"]}
        self.assertEqual(names, {"Momentum", "Mean Reversion", "Breakout"})

    def test_per_strategy_win_rate_and_profit_factor(self):
        r = self._rankings()
        for p in r["profiles"]:
            exp = EXPECTED[p["strategy_name"]]
            self.assertEqual(p["total_trades"], exp["total"])
            self.assertEqual(p["winning_trades"], exp["wins"])
            self.assertAlmostEqual(p["win_rate"],
                                   exp["wins"] / exp["total"] * 100, places=1)
            self.assertAlmostEqual(p["net_pnl"], exp["net"], places=1)
            self.assertAlmostEqual(p["profit_factor"],
                                   exp["gross_profit"] / exp["gross_loss"],
                                   places=2)
            self.assertGreater(p["profit_factor"], 0.0)

    def test_leaderboard_non_empty_and_ordered(self):
        r = self._rankings()
        lb = r["leaderboard"]
        self.assertEqual(len(lb), 3)
        scores = [row["rank_score"] for row in lb]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreater(scores[0], 0.0)

    def test_criterion_rankings_non_empty(self):
        r = self._rankings()
        cr = r["criterion_rankings"]
        for key in ("highest_win_rate", "highest_net_profit", "lowest_drawdown"):
            self.assertIn(key, cr)


# ══════════════════════════════════════════════════════════════════════════════
# 3. /api/strategy/regimes — non-zero regime matrix
# ══════════════════════════════════════════════════════════════════════════════
class TestStrategyRegimes(_Base):
    def test_regime_matrix_covers_all_regimes(self):
        from strategy_intelligence.api import get_regimes
        r = get_regimes()
        self.assertEqual(r["status"], "ENABLED")
        for regime in _REGIMES:
            self.assertIn(regime, r["matrix"])

    def test_regime_trade_counts_sum_to_total(self):
        from strategy_intelligence.api import get_regimes
        r = get_regimes()
        total = sum(m["trades"] for m in r["matrix"].values())
        self.assertEqual(total, TOTAL_TRADES)
        for regime, m in r["matrix"].items():
            self.assertGreater(m["trades"], 0, msg=regime)
            self.assertGreaterEqual(m["win_rate"], 0.0)
            self.assertLessEqual(m["win_rate"], 100.0)

    def test_best_per_regime_populated(self):
        from strategy_intelligence.api import get_regimes
        r = get_regimes()
        self.assertTrue(r["best_per_regime"])


# ══════════════════════════════════════════════════════════════════════════════
# 4. /api/strategy summary ↔ rankings consistency
# ══════════════════════════════════════════════════════════════════════════════
class TestStrategySummaryConsistency(_Base):
    def test_summary_totals_match_seed(self):
        from strategy_intelligence.api import get_summary
        s = get_summary()
        self.assertEqual(s["status"], "ENABLED")
        self.assertEqual(s["total_closed_trades"], TOTAL_TRADES)
        self.assertAlmostEqual(
            s["total_net_pnl"],
            sum(e["net"] for e in EXPECTED.values()), places=1)

    def test_summary_leaderboard_matches_rankings_profiles(self):
        from strategy_intelligence.api import get_summary, get_rankings
        s = get_summary()
        r = get_rankings()
        profiles = {p["strategy_name"]: p for p in r["profiles"]}
        for row in s["leaderboard"]:
            p = profiles[row["strategy_name"]]
            self.assertAlmostEqual(row["win_rate"], p["win_rate"], places=2)
            self.assertAlmostEqual(row["net_pnl"], p["net_pnl"], places=2)
            self.assertAlmostEqual(row["rank_score"], p["rank_score"], places=2)


# ══════════════════════════════════════════════════════════════════════════════
# 5. /api/ai/calibration — meaningful curve on real data
# ══════════════════════════════════════════════════════════════════════════════
class TestAICalibration(_Base):
    def test_calibration_curve_non_empty(self):
        from ai_performance.api import get_calibration
        r = get_calibration()
        self.assertEqual(r["status"], "ENABLED")
        curve = r["calibration_curve"]
        self.assertGreater(len(curve), 1)
        self.assertEqual(sum(b["sample_count"] for b in curve), TOTAL_TRADES)

    def test_calibration_metrics_in_range(self):
        from ai_performance.api import get_calibration
        r = get_calibration()
        self.assertGreater(r["ece"], 0.0)
        self.assertLess(r["ece"], 1.0)
        self.assertGreater(r["reliability_score"], 0.0)
        self.assertLessEqual(r["reliability_score"], 100.0)

    def test_bucket_win_rates_are_real(self):
        from ai_performance.api import get_calibration
        r = get_calibration()
        for b in r["calibration_curve"]:
            self.assertGreaterEqual(b["actual_success_rate"], 0.0)
            self.assertLessEqual(b["actual_success_rate"], 1.0)
            self.assertGreater(b["sample_count"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# 6. /api/ai/confidence — distribution over real buckets
# ══════════════════════════════════════════════════════════════════════════════
class TestAIConfidence(_Base):
    def test_distribution_non_empty_and_sums(self):
        from ai_performance.api import get_confidence
        r = get_confidence()
        self.assertEqual(r["status"], "ENABLED")
        buckets = r["distribution"]["buckets"]
        self.assertGreater(len(buckets), 1)
        self.assertEqual(sum(b["count"] for b in buckets), TOTAL_TRADES)
        self.assertEqual(r["distribution"]["total_signals"], TOTAL_TRADES)
        # Higher-confidence buckets should genuinely win more often on this seed
        by_name = {b["bucket"]: b for b in buckets}
        self.assertGreater(by_name["90–100"]["win_rate"],
                           by_name["Below 60"]["win_rate"])

    def test_cross_analyses_populated(self):
        from ai_performance.api import get_confidence
        r = get_confidence()
        self.assertTrue(r["vs_regime"])
        self.assertTrue(r["vs_sector"])
        self.assertAlmostEqual(r["confidence_threshold"], 0.60, places=2)


# ══════════════════════════════════════════════════════════════════════════════
# 7. /api/ai summary — non-zero KPIs + health_score consistency
# ══════════════════════════════════════════════════════════════════════════════
class TestAISummaryConsistency(_Base):
    def test_summary_non_zero(self):
        from ai_performance.api import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_signals"], TOTAL_TRADES)
        self.assertEqual(r["successful_signals"], TOTAL_WINS)
        self.assertAlmostEqual(r["signal_success_rate"],
                               TOTAL_WINS / TOTAL_TRADES * 100, places=1)
        self.assertGreater(r["avg_confidence"], 0.0)

    def test_health_score_meaningful(self):
        from ai_performance.api import get_summary
        r = get_summary()
        h = r["health_score"]
        self.assertGreater(h["total_score"], 0.0)
        self.assertLessEqual(h["total_score"], 100.0)
        self.assertIn(h["label"], ["Excellent", "Good", "Fair", "Poor", "Critical"])
        for key in ("prediction_accuracy", "calibration_quality", "consistency",
                    "execution_outcome", "risk_awareness", "recommendation_quality"):
            self.assertIn(key, h["components"])

    def test_health_score_consistent_with_shared_service(self):
        from ai_performance.api import get_summary
        from ai_performance.shared_services import get_health_score
        s = get_summary()["health_score"]
        d = get_health_score()
        self.assertAlmostEqual(s["total_score"], d["total_score"], places=1)
        self.assertEqual(s["label"], d["label"])

    def test_calibration_kpis_consistent_with_detail_endpoint(self):
        from ai_performance.api import get_summary, get_calibration
        s = get_summary()
        c = get_calibration()
        self.assertAlmostEqual(s["calibration_ece"], round(c["ece"], 4), places=4)
        self.assertAlmostEqual(s["calibration_reliability"],
                               c["reliability_score"], places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
