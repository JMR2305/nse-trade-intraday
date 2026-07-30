"""
test_strategy_optimisation_integration.py — Phase 6.2 integration smoke test.

Tagged [integration] — skipped by default in CI; run manually before releases.

Usage
-----
  # From workspace root:
  RUN_INTEGRATION_TESTS=1 \\
    STRATEGY_OPTIMISATION_ENABLED=true \\
    python -m pytest artifacts/api-server/src/python/strategy_optimisation/ \\
      -v -m integration

  # Or run directly:
  RUN_INTEGRATION_TESTS=1 \\
    STRATEGY_OPTIMISATION_ENABLED=true \\
    python artifacts/api-server/src/python/strategy_optimisation/ \\
      test_strategy_optimisation_integration.py

What it covers
--------------
- Full DB → validation_collector → strategy_optimisation stack with ≥30 real trades
- FIFO BUY→SELL matching with real DB rows
- Regime normalisation from trade metadata
- Pattern discovery needing ≥3 trades per cluster
- All assertions from task spec: ≥1 strategy profiled, no NaN health scores,
  all parameter recs carry advisory_only=True, export CSV/JSON non-empty
"""
from __future__ import annotations

import json
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Availability guards ───────────────────────────────────────────────────────

_INTEGRATION = bool(os.environ.get("RUN_INTEGRATION_TESTS"))
_DB_AVAILABLE = bool(os.environ.get("DATABASE_URL"))
_SKIP_REASON = (
    "Integration test: set RUN_INTEGRATION_TESTS=1 and DATABASE_URL to run."
)

# ── Fixture constants ─────────────────────────────────────────────────────────

_TEST_ID_PREFIX = "inttest_stratopt_"   # prefix for all rows we own; used for cleanup

STRATEGIES = ["Momentum", "MeanReversion", "BreakoutScanner"]
REGIMES    = ["Bullish", "Bearish", "Neutral", "High Volatility"]
SECTORS    = ["Energy", "Financials", "Technology"]
SYMBOLS    = ["RELIANCE", "HDFC", "INFY", "TCS", "AXISBANK", "SUNPHARMA"]

# 12 trades per strategy × 3 strategies = 36 total; 8 winners / 4 losers each
_TRADES_PER_STRATEGY = 12
_WINNERS_PER_STRATEGY = 8
_EXPECTED_WIN_RATE = _WINNERS_PER_STRATEGY / _TRADES_PER_STRATEGY   # 0.667


# ── Trade fixture builders ────────────────────────────────────────────────────

def _make_pair(
    index: int,
    strategy: str,
    regime: str,
    sector: str,
    symbol: str,
    winner: bool,
    base_ts: datetime,
) -> tuple[dict, dict]:
    """Return (buy_dict, sell_dict) ready for portfolio_store._insert_new_trades."""
    buy_ts  = base_ts + timedelta(hours=1, minutes=(index * 17) % 120)
    sell_ts = buy_ts  + timedelta(minutes=45 + (index % 60))
    entry   = 2000.0 + (index % 20) * 50
    exit_p  = entry * (1.02 if winner else 0.98)
    qty     = 10 + (index % 5) * 2

    # metadata dict is stored as-is under the "metadata" key so that
    # portfolio_store._load_all_trades unpacks it back via trade.update(meta),
    # giving trade["metadata"] = {...}, which _build_record then reads.
    meta = {
        "strategy":                 strategy,
        "market_regime":            regime,
        "sector":                   sector,
        "ai_confidence":            round(0.75 + (0.1 if winner else -0.25), 4),
        "ai_recommendation":        "BUY",
        "signal_validation_status": "VALID",
        "risk_score":               0.22 if winner else 0.42,
        "portfolio_value_at_entry": 500_000.0,
        "execution_quality_score":  85.0 if winner else 60.0,
    }

    buy = {
        "id":       f"{_TEST_ID_PREFIX}{index:04d}_B",
        "symbol":   symbol,
        "action":   "BUY",
        "quantity": qty,
        "price":    entry,
        "total":    entry * qty,
        "timestamp": buy_ts.isoformat(),
        "reason":   "Signal",
        # stored as a nested key so _build_record can recover it via buy.get("metadata")
        "metadata": meta,
    }
    sell = {
        "id":       f"{_TEST_ID_PREFIX}{index:04d}_S",
        "symbol":   symbol,
        "action":   "SELL",
        "quantity": qty,
        "price":    exit_p,
        "total":    exit_p * qty,
        "timestamp": sell_ts.isoformat(),
        "reason":   "Target" if winner else "StopLoss",
        "metadata": {},
    }
    return buy, sell


def _build_all_pairs() -> list[tuple[dict, dict]]:
    base = datetime(2026, 7, 1, 9, 15, tzinfo=timezone.utc)
    pairs: list[tuple[dict, dict]] = []
    idx = 0
    for strat_idx, strategy in enumerate(STRATEGIES):
        for i in range(_TRADES_PER_STRATEGY):
            regime  = REGIMES[i % len(REGIMES)]
            sector  = SECTORS[strat_idx % len(SECTORS)]
            symbol  = SYMBOLS[(strat_idx * 2 + i) % len(SYMBOLS)]
            winner  = i < _WINNERS_PER_STRATEGY
            day_ts  = base + timedelta(days=i // 4)
            pairs.append(_make_pair(idx, strategy, regime, sector, symbol, winner, day_ts))
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
class TestStrategyOptimisationIntegration(unittest.TestCase):
    """
    Full-stack smoke test: seeds ≥30 trades into paper_trades DB, drives
    the complete collect_all_trade_records → strategy_optimisation pipeline.
    """

    # Patch targets: _get_exec_score_snapshot and _get_executive_snapshot in
    # validation_collector import heavy dashboard modules that trigger yfinance
    # network calls.  We stub them to None — the integration test is scoped to
    # the DB → FIFO-match → strategy_optimisation pipeline only.
    _PATCH_EXEC_SCORE  = "paper_trading_validation.validation_collector._get_exec_score_snapshot"
    _PATCH_EXEC_SNAP   = "paper_trading_validation.validation_collector._get_executive_snapshot"
    _PATCH_PORT_VAL    = "paper_trading_validation.validation_collector._get_portfolio_value"

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["STRATEGY_OPTIMISATION_ENABLED"] = "true"

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

    def _with_stubs(self):
        """Context manager that stubs out slow external snapshot calls."""
        from unittest.mock import patch
        return (
            patch(self._PATCH_EXEC_SCORE, return_value=None),
            patch(self._PATCH_EXEC_SNAP,  return_value=None),
            patch(self._PATCH_PORT_VAL,   return_value=500_000.0),
        )

    def _run_with_stubs(self, fn):
        """Call fn() with all slow-import stubs applied, return result."""
        from unittest.mock import patch
        with patch(self._PATCH_EXEC_SCORE, return_value=None), \
             patch(self._PATCH_EXEC_SNAP,  return_value=None), \
             patch(self._PATCH_PORT_VAL,   return_value=500_000.0):
            return fn()

    # ── convenience wrappers ─────────────────────────────────────────────────

    def _strategies(self):
        from strategy_optimisation.shared_services import get_strategies
        return self._run_with_stubs(get_strategies)

    def _summary(self):
        from strategy_optimisation.shared_services import get_summary
        return self._run_with_stubs(get_summary)

    def _recommendations(self):
        from strategy_optimisation.shared_services import get_recommendations
        return self._run_with_stubs(get_recommendations)

    def _patterns(self):
        from strategy_optimisation.shared_services import get_patterns
        return self._run_with_stubs(get_patterns)

    # ── collect_all_trade_records smoke ──────────────────────────────────────
    # Stubs are applied to _get_exec_score_snapshot / _get_executive_snapshot
    # in validation_collector because those helpers import heavy dashboard
    # modules that trigger yfinance network calls (can hang indefinitely).
    # The integration scope here is DB → FIFO-match → TradeRecord, not the
    # execution_quality or executive_dashboard modules.

    def test_00_collect_trade_records_non_empty(self) -> None:
        """Full DB → FIFO-match → TradeRecord pipeline must yield ≥30 records."""
        from paper_trading_validation.validation_collector import collect_all_trade_records
        records = self._run_with_stubs(collect_all_trade_records)
        self.assertGreaterEqual(
            len(records), len(self.pairs),
            f"Expected ≥{len(self.pairs)} trade records, got {len(records)}",
        )

    def test_01_collect_records_have_strategy_field(self) -> None:
        """Strategy field must survive the DB → FIFO-match round-trip."""
        from paper_trading_validation.validation_collector import collect_all_trade_records
        records = self._run_with_stubs(collect_all_trade_records)
        strategies_seen = {r.strategy for r in records if r.strategy and r.strategy != "Unknown"}
        for strat in STRATEGIES:
            self.assertIn(strat, strategies_seen,
                          f"Strategy '{strat}' lost during DB round-trip")

    # ── strategies endpoint ───────────────────────────────────────────────────

    def test_10_at_least_one_strategy_profiled(self) -> None:
        r = self._strategies()
        self.assertEqual(r["status"], "ENABLED")
        self.assertGreater(len(r["strategies"]), 0,
                           "Expected ≥1 strategy profile with 36 seeded trades")

    def test_11_all_three_strategies_profiled(self) -> None:
        r = self._strategies()
        names = {s["strategy"] for s in r["strategies"]}
        for strat in STRATEGIES:
            self.assertIn(strat, names,
                          f"Strategy '{strat}' not profiled")

    def test_12_no_health_score_is_nan(self) -> None:
        r = self._strategies()
        for s in r["strategies"]:
            hs = s.get("health_score", 0)
            self.assertFalse(
                math.isnan(float(hs)),
                f"health_score is NaN for strategy '{s.get('strategy')}'",
            )

    def test_13_health_scores_in_valid_range(self) -> None:
        r = self._strategies()
        for s in r["strategies"]:
            hs = float(s.get("health_score", 0))
            self.assertGreaterEqual(hs, 0.0)
            self.assertLessEqual(hs, 100.0)

    def test_14_win_rate_matches_seeded_proportion(self) -> None:
        """Each strategy was seeded with exactly 8/12 winners → ~0.667 win rate."""
        r = self._strategies()
        for s in r["strategies"]:
            wr = float(s.get("win_rate", -1))
            self.assertAlmostEqual(
                wr, _EXPECTED_WIN_RATE, delta=0.05,
                msg=f"Win rate {wr:.3f} for '{s['strategy']}' deviates from expected {_EXPECTED_WIN_RATE:.3f}",
            )

    def test_15_advisory_only_on_all_strategies(self) -> None:
        r = self._strategies()
        self.assertTrue(r.get("advisory_only"),
                        "Top-level advisory_only must be True")
        for s in r["strategies"]:
            self.assertTrue(
                s.get("advisory_only"),
                f"advisory_only missing/False for '{s.get('strategy')}'",
            )

    def test_16_grades_are_valid_values(self) -> None:
        r = self._strategies()
        valid_grades = {"A+", "A", "B", "C", "D"}
        for s in r["strategies"]:
            self.assertIn(s.get("grade"), valid_grades,
                          f"Unexpected grade '{s.get('grade')}' for '{s.get('strategy')}'")

    # ── summary endpoint ──────────────────────────────────────────────────────

    def test_20_summary_enabled_and_trade_count_correct(self) -> None:
        r = self._summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertEqual(r["total_trades"], len(self.pairs),
                         "summary.total_trades must equal seeded pair count")
        self.assertEqual(r["total_strategies"], len(STRATEGIES))

    def test_21_best_regime_populated(self) -> None:
        r = self._summary()
        self.assertIsNotNone(r.get("best_regime"),
                             "best_regime must be set with 36 seeded trades")

    def test_22_best_sector_populated(self) -> None:
        r = self._summary()
        self.assertIsNotNone(r.get("best_sector"),
                             "best_sector must be set with 36 seeded trades")

    # ── recommendations endpoint ──────────────────────────────────────────────

    def test_30_all_parameter_recs_advisory_only(self) -> None:
        """Core requirement: every parameter recommendation must carry advisory_only=True."""
        r = self._recommendations()
        self.assertEqual(r["status"], "ENABLED")
        param_recs = r.get("parameter_recommendations", [])
        self.assertGreater(len(param_recs), 0,
                           "Expected ≥1 parameter recommendation with 36 trades")
        for rec in param_recs:
            self.assertTrue(
                rec.get("advisory_only"),
                f"advisory_only is not True on recommendation: '{rec.get('parameter')}'",
            )

    def test_31_adaptive_learning_trend_valid(self) -> None:
        r = self._recommendations()
        trend = r.get("adaptive_learning", {}).get("overall_trend", "")
        self.assertIn(trend,
                      ["IMPROVING", "DECLINING", "STABLE", "INSUFFICIENT_DATA"],
                      f"Unexpected adaptive_learning.overall_trend: {trend!r}")

    # ── patterns endpoint ─────────────────────────────────────────────────────

    def test_40_patterns_returns_valid_structure(self) -> None:
        r = self._patterns()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("total_patterns", r,
                      "patterns response must contain total_patterns")
        self.assertGreaterEqual(r["total_patterns"], 0)

    # ── export functions ──────────────────────────────────────────────────────

    def test_50_export_csv_non_empty(self) -> None:
        from strategy_optimisation.shared_services import export_strategies_csv
        csv_text = self._run_with_stubs(export_strategies_csv)
        self.assertTrue(csv_text,
                        "export_strategies_csv() must return non-empty CSV with 36 trades")
        rows = [line for line in csv_text.splitlines() if line.strip()]
        # header + one data row per strategy
        self.assertGreaterEqual(len(rows), len(STRATEGIES) + 1,
                                "CSV must have a header row plus one row per strategy")
        self.assertIn("strategy", csv_text.lower(),
                      "CSV header must include a 'strategy' column")

    def test_51_export_json_non_empty_and_parseable(self) -> None:
        from strategy_optimisation.shared_services import export_recommendations_json
        json_text = self._run_with_stubs(export_recommendations_json)
        self.assertTrue(json_text,
                        "export_recommendations_json() must return non-empty JSON with 36 trades")
        data = json.loads(json_text)
        self.assertEqual(data.get("status"), "ENABLED",
                         "Exported JSON must have status=ENABLED")
        self.assertIn("parameter_recommendations", data,
                      "Exported JSON must include parameter_recommendations key")

    # ── optimisation_snapshot ─────────────────────────────────────────────────

    def test_60_snapshot_consistent_with_strategies(self) -> None:
        from strategy_optimisation.shared_services import get_optimisation_snapshot
        snap = self._run_with_stubs(get_optimisation_snapshot)
        self.assertEqual(snap["total_strategies"], len(STRATEGIES))
        self.assertIsNotNone(snap["best_strategy"],
                             "best_strategy must be set with 36 trades")
        hs = float(snap["best_strategy_health"])
        self.assertFalse(math.isnan(hs), "best_strategy_health must not be NaN")
        self.assertGreater(hs, 0.0,
                           "best_strategy_health must be > 0 given winning trades")

    def test_61_underperforming_count_is_non_negative(self) -> None:
        from strategy_optimisation.shared_services import get_optimisation_snapshot
        snap = self._run_with_stubs(get_optimisation_snapshot)
        self.assertGreaterEqual(snap.get("underperforming_count", 0), 0)
        self.assertLessEqual(snap.get("underperforming_count", 0), len(STRATEGIES))

    # ── determinism ──────────────────────────────────────────────────────────

    def test_70_results_deterministic_across_two_calls(self) -> None:
        """Two consecutive calls on the same DB state must return identical results."""
        from strategy_optimisation.shared_services import get_summary
        r1 = self._run_with_stubs(get_summary)
        r2 = self._run_with_stubs(get_summary)
        self.assertEqual(r1["total_strategies"], r2["total_strategies"])
        self.assertEqual(r1["total_trades"],     r2["total_trades"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
