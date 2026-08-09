"""
test_ai_performance_integration.py — Phase 5D.4 integration smoke test.

Tagged [integration] — skipped by default in CI; run manually before releases.

Usage
-----
  # From workspace root:
  RUN_INTEGRATION_TESTS=1 \\
    AI_PERFORMANCE_ENABLED=true \\
    python -m pytest artifacts/api-server/src/python/ai_performance/ \\
      -v -m integration

  # Or run directly:
  RUN_INTEGRATION_TESTS=1 \\
    AI_PERFORMANCE_ENABLED=true \\
    python artifacts/api-server/src/python/ai_performance/ \\
      test_ai_performance_integration.py

What it covers
--------------
- Full DB → strategy_intelligence → ai_performance stack with ≥30 real trades
- Varied signal_confidence values spanning every confidence bucket
- The exact payloads served by /api/ai/summary, /api/ai/calibration and
  /api/ai/confidence (routes call get_ai_summary / get_calibration_data /
  get_confidence_data via runPython)
- Assertions from task spec: status=ENABLED, no NaN in health_score,
  confidence buckets non-empty, calibration curve has ≥2 points
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Availability guards ───────────────────────────────────────────────────────

_INTEGRATION = bool(os.environ.get("RUN_INTEGRATION_TESTS"))
_DB_AVAILABLE = bool(os.environ.get("DATABASE_URL"))
_SKIP_REASON = (
    "Integration test: set RUN_INTEGRATION_TESTS=1 and DATABASE_URL to run."
)

# ── Fixture constants ─────────────────────────────────────────────────────────

_TEST_ID_PREFIX = "inttest_aiperf_"   # prefix for all rows we own; used for cleanup

STRATEGIES = ["Momentum", "MeanReversion", "BreakoutScanner"]
REGIMES    = ["Bullish", "Bearish", "Neutral", "High Volatility"]
SYMBOLS    = ["RELIANCE", "HDFC", "INFY", "TCS", "AXISBANK", "SUNPHARMA"]

# Confidence values chosen to populate every bucket defined in ai_models:
# 90–100 / 80–90 / 70–80 / 60–70 / Below 60
CONFIDENCES = [0.95, 0.92, 0.85, 0.82, 0.75, 0.72, 0.65, 0.62, 0.55, 0.45]

# 12 pairs per strategy × 3 strategies = 36 pairs (≥30 required)
_TRADES_PER_STRATEGY = 12
_TOTAL_PAIRS = _TRADES_PER_STRATEGY * len(STRATEGIES)


def _is_nan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


# ── Trade fixture builders ────────────────────────────────────────────────────

def _make_pair(
    index: int,
    strategy: str,
    regime: str,
    symbol: str,
    confidence: float,
    winner: bool,
    base_ts: datetime,
) -> tuple[dict, dict]:
    """Return (buy_dict, sell_dict) ready for portfolio_store._insert_new_trades."""
    buy_ts  = base_ts + timedelta(hours=1, minutes=(index * 17) % 120)
    sell_ts = buy_ts  + timedelta(minutes=45 + (index % 60))
    entry   = 2000.0 + (index % 20) * 50
    exit_p  = entry * (1.02 if winner else 0.98)
    qty     = 10 + (index % 5) * 2

    # Non-core keys are stored into the JSONB metadata column by
    # portfolio_store._insert_new_trades and flattened back onto the trade
    # dict on load (trade.update(meta)), so strategy_intelligence's
    # build_closed_trades reads them via buy.get("signal_confidence") etc.
    buy = {
        "id":        f"{_TEST_ID_PREFIX}{index:04d}_B",
        "symbol":    symbol,
        "action":    "BUY",
        "quantity":  qty,
        "price":     entry,
        "total":     entry * qty,
        "timestamp": buy_ts.isoformat(),
        "reason":    "Signal",
        "strategy_name":          strategy,
        "strategy_id":            strategy.lower(),
        "market_regime_at_entry": regime,
        "signal_confidence":      confidence,
        "ai_confidence":          confidence,
        "ai_recommendation":      "BUY",
    }
    sell = {
        "id":        f"{_TEST_ID_PREFIX}{index:04d}_S",
        "symbol":    symbol,
        "action":    "SELL",
        "quantity":  qty,
        "price":     exit_p,
        "total":     exit_p * qty,
        "timestamp": sell_ts.isoformat(),
        "reason":    "Target" if winner else "StopLoss",
        "metadata":  {},
    }
    return buy, sell


def _build_all_pairs() -> list[tuple[dict, dict]]:
    base = datetime(2026, 7, 1, 9, 15, tzinfo=timezone.utc)
    pairs: list[tuple[dict, dict]] = []
    idx = 0
    for strat_idx, strategy in enumerate(STRATEGIES):
        for i in range(_TRADES_PER_STRATEGY):
            regime     = REGIMES[i % len(REGIMES)]
            symbol     = SYMBOLS[(strat_idx * 2 + i) % len(SYMBOLS)]
            confidence = CONFIDENCES[idx % len(CONFIDENCES)]
            # High-confidence trades mostly win, low-confidence mostly lose —
            # gives the calibration curve a non-degenerate shape.
            winner     = (confidence >= 0.70) if (i % 4 != 3) else (confidence < 0.70)
            day_ts     = base + timedelta(days=i // 4)
            pairs.append(_make_pair(idx, strategy, regime, symbol,
                                    confidence, winner, day_ts))
            idx += 1
    return pairs


# ── DB helpers ────────────────────────────────────────────────────────────────

def _seed(conn, pairs: list) -> None:
    from portfolio_store import _insert_new_trades
    flat = [t for pair in pairs for t in pair]
    _insert_new_trades(conn, flat)
    conn.commit()


def _cleanup(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM paper_trades WHERE id LIKE %s", (f"{_TEST_ID_PREFIX}%",))
    conn.commit()


# ── Integration test class ────────────────────────────────────────────────────

@unittest.skipUnless(_INTEGRATION and _DB_AVAILABLE, _SKIP_REASON)
class TestAIPerformanceIntegration(unittest.TestCase):
    """
    Full-stack smoke test: seeds ≥30 BUY/SELL pairs with varied confidence
    values into paper_trades, then exercises the exact functions behind
    /api/ai/summary, /api/ai/calibration and /api/ai/confidence.
    """

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["AI_PERFORMANCE_ENABLED"] = "true"
        os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

        from portfolio_store import _connect, _ensure_schema
        cls.conn = _connect()
        _ensure_schema(cls.conn)

        _cleanup(cls.conn)                   # purge any stale rows from previous run
        cls.pairs = _build_all_pairs()       # 36 pairs
        _seed(cls.conn, cls.pairs)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            _cleanup(cls.conn)
        finally:
            try:
                cls.conn.close()
            except Exception:
                pass

    # ── convenience wrappers ─────────────────────────────────────────────────

    def _summary(self):
        from ai_performance.shared_services import get_ai_summary
        return get_ai_summary()

    def _calibration(self):
        from ai_performance.shared_services import get_calibration_data
        return get_calibration_data()

    def _confidence(self):
        from ai_performance.shared_services import get_confidence_data
        return get_confidence_data()

    # ── data pipeline smoke ───────────────────────────────────────────────────

    def test_00_signals_built_from_seeded_trades(self) -> None:
        """DB → strategy_intelligence → build_ai_signals must yield ≥30 signals."""
        from ai_performance.ai_engine import build_ai_signals
        signals = build_ai_signals()
        self.assertGreaterEqual(
            len(signals), _TOTAL_PAIRS,
            f"Expected ≥{_TOTAL_PAIRS} AI signals, got {len(signals)}",
        )

    def test_01_confidence_values_survive_round_trip(self) -> None:
        """Seeded confidence values must reach the signals with variety intact."""
        from ai_performance.ai_engine import build_ai_signals
        signals = build_ai_signals()
        seeded  = {s.signal_confidence for s in signals
                   if s.trade_id.startswith(_TEST_ID_PREFIX)}
        self.assertGreaterEqual(
            len(seeded), 5,
            f"Expected ≥5 distinct confidence values, got {sorted(seeded)}",
        )

    # ── /api/ai/summary ───────────────────────────────────────────────────────

    def test_10_summary_enabled(self) -> None:
        r = self._summary()
        self.assertEqual(r["status"], "ENABLED", f"summary not ENABLED: {r}")

    def test_11_summary_counts_seeded_signals(self) -> None:
        r = self._summary()
        self.assertGreaterEqual(r["total_signals"], _TOTAL_PAIRS)

    def test_12_health_score_has_no_nan(self) -> None:
        """Core requirement: no NaN anywhere in health_score."""
        r  = self._summary()
        hs = r.get("health_score")
        self.assertIsInstance(hs, dict, "health_score must be a dict")
        for key, val in hs.items():
            if isinstance(val, (int, float)):
                self.assertFalse(_is_nan(val),
                                 f"health_score['{key}'] is NaN")
        total = float(hs.get("total_score", -1))
        self.assertGreaterEqual(total, 0.0)
        self.assertLessEqual(total, 100.0)

    def test_13_summary_scalar_metrics_not_nan(self) -> None:
        r = self._summary()
        for key in ("signal_success_rate", "high_confidence_pct",
                    "avg_confidence", "calibration_ece",
                    "calibration_reliability"):
            self.assertFalse(_is_nan(r.get(key)),
                             f"summary['{key}'] is NaN")

    # ── /api/ai/confidence ───────────────────────────────────────────────────

    def test_20_confidence_enabled(self) -> None:
        r = self._confidence()
        self.assertEqual(r["status"], "ENABLED", f"confidence not ENABLED: {r}")

    def test_21_confidence_buckets_non_empty(self) -> None:
        """Core requirement: confidence buckets must be non-empty."""
        r       = self._confidence()
        dist    = r.get("distribution", {})
        buckets = dist.get("buckets", [])
        self.assertGreater(len(buckets), 0,
                           "Expected non-empty confidence buckets with 36 seeded trades")
        populated = [b for b in buckets if b.get("count", 0) > 0]
        self.assertGreaterEqual(
            len(populated), 2,
            "Seeded confidences span multiple buckets — expected ≥2 populated buckets",
        )

    def test_22_confidence_bucket_stats_not_nan(self) -> None:
        r = self._confidence()
        for b in r.get("distribution", {}).get("buckets", []):
            for key, val in b.items():
                if isinstance(val, (int, float)):
                    self.assertFalse(_is_nan(val),
                                     f"bucket '{b.get('bucket')}' field '{key}' is NaN")

    # ── /api/ai/calibration ──────────────────────────────────────────────────

    def test_30_calibration_enabled(self) -> None:
        r = self._calibration()
        self.assertEqual(r["status"], "ENABLED", f"calibration not ENABLED: {r}")

    def test_31_calibration_curve_has_at_least_two_points(self) -> None:
        """Core requirement: calibration curve must have ≥2 points."""
        r     = self._calibration()
        curve = r.get("calibration_curve", [])
        populated = [p for p in curve if p.get("total_signals", p.get("count", 1))]
        self.assertGreaterEqual(
            len(curve), 2,
            f"Expected ≥2 calibration curve points, got {len(curve)}: {curve}",
        )
        self.assertGreaterEqual(len(populated), 2)

    def test_32_calibration_metrics_not_nan(self) -> None:
        r = self._calibration()
        for key, val in r.items():
            if isinstance(val, (int, float)):
                self.assertFalse(_is_nan(val), f"calibration['{key}'] is NaN")
        for p in r.get("calibration_curve", []):
            for key, val in p.items():
                if isinstance(val, (int, float)):
                    self.assertFalse(_is_nan(val),
                                     f"curve point field '{key}' is NaN")

    # ── determinism ──────────────────────────────────────────────────────────

    def test_40_results_deterministic_across_two_calls(self) -> None:
        """Two consecutive calls on the same DB state must return identical results."""
        r1 = self._summary()
        r2 = self._summary()
        self.assertEqual(r1["total_signals"], r2["total_signals"])
        self.assertEqual(r1["health_score"]["total_score"],
                         r2["health_score"]["total_score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
