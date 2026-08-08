"""
test_execution_quality.py — Phase 5D.1 comprehensive test suite.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os
import sys
import copy
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ── helpers ───────────────────────────────────────────────────────────────────

def _buy(symbol="TCS", price=3500.0, qty=2, stop=3300.0, target=3800.0,
         ts="2026-07-29T09:16:00", trade_id="buy001",
         strategy_id="ai_scan", strategy_name="AI Scan",
         regime="BULLISH", est_slippage=1.75):
    return {
        "id": trade_id, "symbol": symbol, "action": "BUY",
        "quantity": qty, "price": price, "total": round(price * qty, 2),
        "timestamp": ts, "reason": "test",
        "stop_loss": stop, "target": target,
        "strategy_id": strategy_id, "strategy_name": strategy_name,
        "regime": regime, "est_slippage": est_slippage,
        "est_broker_charges": 0.0,
    }

def _sell(symbol="TCS", price=3750.0, qty=2, exit_type="TARGET_HIT",
          ts="2026-07-29T15:00:00", trade_id="sell001",
          buy_price=3500.0, est_slippage=1.87):
    pnl     = (price - buy_price) * qty
    pnl_pct = (price - buy_price) / buy_price * 100
    return {
        "id": trade_id, "symbol": symbol, "action": "SELL",
        "quantity": qty, "price": price, "total": round(price * qty, 2),
        "timestamp": ts, "reason": "test",
        "exit_type": exit_type, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        "entry_price": buy_price, "est_slippage": est_slippage,
    }


# ── Feature flag ─────────────────────────────────────────────────────────────

class TestFeatureFlag(unittest.TestCase):
    def test_disabled_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "EXECUTION_QUALITY_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            from execution_quality.models import is_enabled
            self.assertFalse(is_enabled())

    def test_enabled_when_true(self):
        with patch.dict(os.environ, {"EXECUTION_QUALITY_ENABLED": "true"}):
            from execution_quality.models import is_enabled
            self.assertTrue(is_enabled())

    def test_enabled_when_1(self):
        with patch.dict(os.environ, {"EXECUTION_QUALITY_ENABLED": "1"}):
            from execution_quality.models import is_enabled
            self.assertTrue(is_enabled())

    def test_enabled_when_yes(self):
        with patch.dict(os.environ, {"EXECUTION_QUALITY_ENABLED": "yes"}):
            from execution_quality.models import is_enabled
            self.assertTrue(is_enabled())

    def test_disabled_response_shape(self):
        from execution_quality.models import disabled_response
        d = disabled_response()
        self.assertEqual(d["status"], "DISABLED")
        self.assertIn("feature_flag", d)
        self.assertIn("EXECUTION_QUALITY_ENABLED", d["feature_flag"])


# ── API returns DISABLED when flag is off ─────────────────────────────────────

class TestApiDisabled(unittest.TestCase):
    def setUp(self):
        self._env = {k: v for k, v in os.environ.items() if k != "EXECUTION_QUALITY_ENABLED"}

    def _call(self, fn_path):
        with patch.dict(os.environ, self._env, clear=True):
            parts = fn_path.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(parts[0])
            importlib.reload(mod)
            fn = getattr(mod, parts[1])
            return fn()

    def test_summary_disabled(self):
        with patch.dict(os.environ, self._env, clear=True):
            from execution_quality.api import get_summary
            with patch("execution_quality.models.is_enabled", return_value=False):
                r = get_summary()
        self.assertEqual(r["status"], "DISABLED")

    def test_trades_disabled(self):
        with patch("execution_quality.models.is_enabled", return_value=False):
            from execution_quality.api import get_trades
            r = get_trades()
        self.assertEqual(r["status"], "DISABLED")

    def test_slippage_disabled(self):
        with patch("execution_quality.models.is_enabled", return_value=False):
            from execution_quality.api import get_slippage
            r = get_slippage()
        self.assertEqual(r["status"], "DISABLED")

    def test_fills_disabled(self):
        with patch("execution_quality.models.is_enabled", return_value=False):
            from execution_quality.api import get_fills
            r = get_fills()
        self.assertEqual(r["status"], "DISABLED")


# ── Score calculations ────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def _rec(self, **kw):
        from execution_quality.models import ExecutionRecord
        defaults = dict(
            trade_id="t1", symbol="TCS", is_complete=True,
            entry_slippage_pct=0.0, exit_type="TARGET_HIT",
            fill_delay_seconds=0.0, stop_loss_set=True, target_set=True,
        )
        defaults.update(kw)
        return ExecutionRecord(**defaults)

    def test_perfect_score(self):
        from execution_quality.report import score_trade
        rec = self._rec(
            entry_slippage_pct=0.0, exit_type="TARGET_HIT",
            fill_delay_seconds=0.0, stop_loss_set=True, target_set=True,
        )
        score, grade = score_trade(rec)
        self.assertEqual(score, 100)
        self.assertEqual(grade, "Excellent")

    def test_stop_hit_reduces_exit_score(self):
        from execution_quality.report import score_trade
        rec_target = self._rec(exit_type="TARGET_HIT")
        rec_stop   = self._rec(exit_type="STOP_HIT")
        s_t, _ = score_trade(rec_target)
        s_s, _ = score_trade(rec_stop)
        self.assertGreater(s_t, s_s)

    def test_high_slippage_reduces_entry_score(self):
        from execution_quality.report import score_trade
        rec_low  = self._rec(entry_slippage_pct=0.0)
        rec_high = self._rec(entry_slippage_pct=0.5)
        s_l, _ = score_trade(rec_low)
        s_h, _ = score_trade(rec_high)
        self.assertGreater(s_l, s_h)

    def test_delayed_fill_reduces_score(self):
        from execution_quality.report import score_trade
        rec_fast = self._rec(fill_delay_seconds=1.0)
        rec_slow = self._rec(fill_delay_seconds=120.0)
        s_f, _ = score_trade(rec_fast)
        s_s, _ = score_trade(rec_slow)
        self.assertGreater(s_f, s_s)

    def test_no_stop_reduces_score(self):
        from execution_quality.report import score_trade
        rec_stop   = self._rec(stop_loss_set=True)
        rec_nostop = self._rec(stop_loss_set=False)
        s_s, _ = score_trade(rec_stop)
        s_n, _ = score_trade(rec_nostop)
        self.assertGreater(s_s, s_n)

    def test_grade_labels(self):
        from execution_quality.report import grade
        self.assertEqual(grade(95),  "Excellent")
        self.assertEqual(grade(90),  "Excellent")
        self.assertEqual(grade(80),  "Good")
        self.assertEqual(grade(75),  "Good")
        self.assertEqual(grade(65),  "Fair")
        self.assertEqual(grade(60),  "Fair")
        self.assertEqual(grade(59),  "Poor")
        self.assertEqual(grade(0),   "Poor")

    def test_score_clamped_0_to_100(self):
        from execution_quality.report import score_trade
        rec = self._rec(entry_slippage_pct=100.0)  # extreme slippage
        score, _ = score_trade(rec)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


# ── ExecutionRecord model ─────────────────────────────────────────────────────

class TestExecutionRecord(unittest.TestCase):
    def test_to_dict_keys(self):
        from execution_quality.models import ExecutionRecord
        rec = ExecutionRecord(trade_id="x", symbol="INFY", quality_score=85, quality_grade="Good")
        d = rec.to_dict()
        for key in ("trade_id", "symbol", "quality_score", "quality_grade",
                    "entry_slippage_rs", "entry_slippage_pct", "fill_delay_seconds",
                    "exit_slippage_rs", "is_complete"):
            self.assertIn(key, d)

    def test_to_dict_rounds_floats(self):
        from execution_quality.models import ExecutionRecord
        rec = ExecutionRecord(entry_slippage_rs=1.23456789)
        d = rec.to_dict()
        self.assertEqual(d["entry_slippage_rs"], round(1.23456789, 2))


# ── Build execution records: zero trades ─────────────────────────────────────

class TestBuildRecordsZeroTrades(unittest.TestCase):
    def test_empty_input(self):
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=[]):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="Unknown"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(records, [])


# ── Build execution records: single completed trade ───────────────────────────

class TestBuildRecordsSingle(unittest.TestCase):
    def test_single_complete_roundtrip(self):
        trades = [_buy(), _sell()]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertTrue(r.is_complete)
        self.assertEqual(r.symbol, "TCS")
        self.assertEqual(r.exit_type, "TARGET_HIT")
        self.assertGreater(r.quality_score, 0)

    def test_open_position(self):
        trades = [_buy()]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].is_complete)


# ── Build execution records: canonical ledger path (primary) ─────────────────

def _ledger_open_row(**over):
    row = {
        "trade_id": "P20-abc123", "symbol": "TCS", "quantity": 10,
        "signal_price": 3500.0, "fill_price": 3502.5, "slippage": 25.0,
        "signal_ts": "2026-08-07T04:17:00+00:00", "fill_ts": "2026-08-07T04:17:38+00:00",
        "status": "OPEN", "strategy_id": "trend_rider", "strategy_name": "Trend Rider",
        "sector": "IT", "regime": "LOW_VOLATILITY", "stop_loss": 3430.0, "target": 3640.0,
    }
    row.update(over)
    return row


def _ledger_closed_row(**over):
    return _ledger_open_row(
        status="CLOSED", exit_ts="2026-08-07T06:30:00+00:00", exit_price=3620.0,
        exit_rule="TARGET_HIT", realized_pnl=1175.0, **over,
    )


class TestBuildRecordsCanonicalLedger(unittest.TestCase):
    """The canonical ledger is the primary source — these tests exercise it
    directly and prove legacy fallback is NOT used once rows are obtained."""

    def _build(self, rows):
        legacy = MagicMock(side_effect=AssertionError("legacy fallback must not be used"))
        with patch("canonical_portfolio._ledger_rows", return_value=rows), \
             patch("portfolio_store.load_all_trades_any", legacy), \
             patch("execution_quality.metrics._sv_fill_delay", return_value=None), \
             patch("execution_quality.metrics._sector_of", return_value="IT"):
            from execution_quality.metrics import build_execution_records
            records = build_execution_records()
        legacy.assert_not_called()
        return records

    def test_open_row_maps_fields(self):
        records = self._build([_ledger_open_row()])
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.trade_id, "P20-abc123")
        self.assertEqual(r.symbol, "TCS")
        self.assertFalse(r.is_complete)
        self.assertEqual(r.actual_entry_price, 3502.5)
        self.assertEqual(r.intended_entry_price, 3500.0)
        self.assertEqual(r.entry_slippage_rs, 25.0)
        self.assertAlmostEqual(r.fill_delay_seconds, 38.0)
        self.assertTrue(r.stop_loss_set)
        self.assertTrue(r.target_set)
        self.assertGreater(r.quality_score, 0)

    def test_closed_row_maps_exit(self):
        records = self._build([_ledger_closed_row()])
        r = records[0]
        self.assertTrue(r.is_complete)
        self.assertEqual(r.exit_type, "TARGET_HIT")
        self.assertEqual(r.actual_exit_price, 3620.0)
        self.assertEqual(r.pnl, 1175.0)
        self.assertAlmostEqual(r.pnl_pct, 1175.0 / (3502.5 * 10) * 100)
        self.assertGreater(r.exit_delay_seconds, 0)

    def test_unfilled_row_skipped(self):
        records = self._build([_ledger_open_row(fill_ts=None)])
        self.assertEqual(records, [])

    def test_malformed_row_skipped_without_fallback(self):
        # One bad row (quantity unparsable) must be skipped — never trigger
        # a wholesale switch to legacy data.
        rows = [_ledger_open_row(), _ledger_open_row(trade_id="BAD", quantity="not-a-number")]
        records = self._build(rows)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].trade_id, "P20-abc123")

    def test_rows_sorted_by_fill_ts(self):
        rows = [
            _ledger_open_row(trade_id="B", fill_ts="2026-08-07T05:00:00+00:00"),
            _ledger_open_row(trade_id="A", fill_ts="2026-08-07T04:00:00+00:00"),
        ]
        records = self._build(rows)
        self.assertEqual([r.trade_id for r in records], ["A", "B"])


# ── Build execution records: multiple trades ──────────────────────────────────

class TestBuildRecordsMultiple(unittest.TestCase):
    def test_two_symbols(self):
        trades = [
            _buy("TCS",  3500.0, trade_id="b1"),
            _buy("INFY", 1800.0, trade_id="b2"),
            _sell("TCS",  3700.0, trade_id="s1", buy_price=3500.0),
            _sell("INFY", 1900.0, trade_id="s2", buy_price=1800.0),
        ]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r.is_complete for r in records))
        symbols = {r.symbol for r in records}
        self.assertEqual(symbols, {"TCS", "INFY"})

    def test_fifo_matching(self):
        """Two buys of same symbol — each matched to its own sell in order."""
        trades = [
            _buy("TCS", 3500.0, ts="2026-07-29T09:00:00", trade_id="b1"),
            _buy("TCS", 3600.0, ts="2026-07-29T10:00:00", trade_id="b2"),
            _sell("TCS", 3700.0, ts="2026-07-29T14:00:00", trade_id="s1", buy_price=3500.0),
            _sell("TCS", 3800.0, ts="2026-07-29T15:00:00", trade_id="s2", buy_price=3600.0),
        ]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(len(records), 2)
        complete = [r for r in records if r.is_complete]
        self.assertEqual(len(complete), 2)


# ── Delayed fills ─────────────────────────────────────────────────────────────

class TestDelayedFills(unittest.TestCase):
    def test_sv_delay_applied(self):
        trades = [_buy()]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=45.0):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(records[0].fill_delay_seconds, 45.0)

    def test_sv_delay_none_stays_zero(self):
        trades = [_buy()]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    records = build_execution_records()
        self.assertEqual(records[0].fill_delay_seconds, 0.0)


# ── Slippage calculations ─────────────────────────────────────────────────────

class TestSlippageCalculations(unittest.TestCase):
    def _make_records(self, slip_values):
        from execution_quality.models import ExecutionRecord
        return [
            ExecutionRecord(
                trade_id=str(i), symbol=f"S{i}",
                entry_slippage_rs=s, entry_slippage_pct=s * 0.01,
                is_complete=False,
            )
            for i, s in enumerate(slip_values)
        ]

    def test_avg_slippage(self):
        from execution_quality.slippage import compute_slippage_stats
        records = self._make_records([1.0, 2.0, 3.0])
        stats = compute_slippage_stats(records)
        self.assertAlmostEqual(stats["entry_rs"]["avg"], 2.0)

    def test_median_slippage(self):
        from execution_quality.slippage import compute_slippage_stats
        records = self._make_records([1.0, 2.0, 10.0])
        stats = compute_slippage_stats(records)
        self.assertAlmostEqual(stats["entry_rs"]["median"], 2.0)

    def test_worst_best_slippage(self):
        from execution_quality.slippage import compute_slippage_stats
        records = self._make_records([1.0, 5.0, 3.0])
        stats = compute_slippage_stats(records)
        self.assertAlmostEqual(stats["entry_rs"]["worst"], 5.0)
        self.assertAlmostEqual(stats["entry_rs"]["best"],  1.0)

    def test_empty_slippage(self):
        from execution_quality.slippage import compute_slippage_stats
        stats = compute_slippage_stats([])
        self.assertIsNone(stats["entry_rs"]["avg"])

    def test_by_symbol_present(self):
        from execution_quality.slippage import compute_slippage_stats
        from execution_quality.models import ExecutionRecord
        records = [
            ExecutionRecord(trade_id="1", symbol="TCS",  entry_slippage_rs=2.0),
            ExecutionRecord(trade_id="2", symbol="INFY", entry_slippage_rs=3.0),
        ]
        stats = compute_slippage_stats(records)
        labels = [b["label"] for b in stats["by_symbol"]]
        self.assertIn("TCS", labels)
        self.assertIn("INFY", labels)


# ── Fill analytics ────────────────────────────────────────────────────────────

class TestFillAnalytics(unittest.TestCase):
    def _make_records(self, delays):
        from execution_quality.models import ExecutionRecord
        return [ExecutionRecord(trade_id=str(i), fill_delay_seconds=d)
                for i, d in enumerate(delays)]

    def test_zero_trades(self):
        from execution_quality.fill_analysis import compute_fill_stats
        stats = compute_fill_stats([])
        self.assertIsNone(stats["avg_delay_seconds"])
        self.assertEqual(stats["total_fills"], 0)

    def test_instant_fill_count(self):
        from execution_quality.fill_analysis import compute_fill_stats
        records = self._make_records([1.0, 2.0, 60.0])
        stats = compute_fill_stats(records)
        self.assertEqual(stats["instant_fills"], 2)

    def test_delayed_fill_count(self):
        from execution_quality.fill_analysis import compute_fill_stats
        records = self._make_records([1.0, 90.0, 120.0])
        stats = compute_fill_stats(records)
        self.assertEqual(stats["delayed_fills"], 2)

    def test_avg_median_max_min(self):
        from execution_quality.fill_analysis import compute_fill_stats
        records = self._make_records([10.0, 20.0, 30.0])
        stats = compute_fill_stats(records)
        self.assertAlmostEqual(stats["avg_delay_seconds"],    20.0)
        self.assertAlmostEqual(stats["median_delay_seconds"], 20.0)
        self.assertAlmostEqual(stats["max_delay_seconds"],    30.0)
        self.assertAlmostEqual(stats["min_delay_seconds"],    10.0)

    def test_instant_pct(self):
        from execution_quality.fill_analysis import compute_fill_stats
        records = self._make_records([1.0, 1.0, 100.0, 100.0])
        stats = compute_fill_stats(records)
        self.assertAlmostEqual(stats["instant_pct"], 50.0)


# ── Summary metrics ───────────────────────────────────────────────────────────

class TestSummaryMetrics(unittest.TestCase):
    def _records(self):
        from execution_quality.models import ExecutionRecord
        return [
            ExecutionRecord(trade_id="1", symbol="TCS",  strategy_name="AI Scan",
                            quality_score=90, is_complete=True,
                            entry_slippage_rs=1.0, entry_slippage_pct=0.01,
                            exit_slippage_rs=1.5, exit_slippage_pct=0.015,
                            fill_delay_seconds=2.0, quality_grade="Excellent"),
            ExecutionRecord(trade_id="2", symbol="INFY", strategy_name="AI Scan",
                            quality_score=60, is_complete=True,
                            entry_slippage_rs=3.0, entry_slippage_pct=0.03,
                            exit_slippage_rs=2.0, exit_slippage_pct=0.02,
                            fill_delay_seconds=45.0, quality_grade="Fair"),
        ]

    def test_summary_keys(self):
        from execution_quality.metrics import compute_summary
        s = compute_summary(self._records())
        for k in ("total_trades", "completed_trades", "avg_execution_score",
                  "avg_entry_slippage_rs", "avg_fill_delay_seconds",
                  "best_trade", "worst_trade", "most_efficient_strategy"):
            self.assertIn(k, s)

    def test_zero_summary(self):
        from execution_quality.metrics import compute_summary
        s = compute_summary([])
        self.assertEqual(s["total_trades"], 0)
        self.assertIsNone(s["avg_execution_score"])

    def test_best_worst(self):
        from execution_quality.metrics import compute_summary
        s = compute_summary(self._records())
        self.assertEqual(s["best_trade"]["score"],  90)
        self.assertEqual(s["worst_trade"]["score"], 60)

    def test_avg_score(self):
        from execution_quality.metrics import compute_summary
        s = compute_summary(self._records())
        self.assertAlmostEqual(s["avg_execution_score"], 75.0)


# ── Restart persistence (idempotency) ─────────────────────────────────────────

class TestRestartPersistence(unittest.TestCase):
    def test_deterministic_output(self):
        """build_execution_records() with same inputs returns same output."""
        trades = [_buy(), _sell()]
        with patch("canonical_portfolio._ledger_rows", side_effect=Exception("test: use legacy fallback")), patch("portfolio_store.load_all_trades_any", return_value=trades):
            with patch("execution_quality.metrics._sv_fill_delay", return_value=None):
                with patch("execution_quality.metrics._sector_of", return_value="IT"):
                    from execution_quality.metrics import build_execution_records
                    r1 = build_execution_records()
                    r2 = build_execution_records()
        self.assertEqual(len(r1), len(r2))
        self.assertEqual(r1[0].quality_score, r2[0].quality_score)
        self.assertEqual(r1[0].trade_id, r2[0].trade_id)


# ── AST safety scan ───────────────────────────────────────────────────────────

class TestASTSafety(unittest.TestCase):
    _FORBIDDEN = [
        "place_order", "order_place", "kite.order",
        "execute_buy", "execute_sell", "submit_order",
    ]
    _ADVISORY_LABEL = "PAPER TRADING / ADVISORY ONLY"

    def _phase5d_files(self):
        import pathlib
        pkg = pathlib.Path(__file__).parent / "execution_quality"
        return list(pkg.glob("*.py"))

    def test_no_forbidden_calls(self):
        import ast
        violations = []
        for fp in self._phase5d_files():
            src = fp.read_text()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = ""
                    if isinstance(func, ast.Name):
                        name = func.id
                    elif isinstance(func, ast.Attribute):
                        name = func.attr
                    for forbidden in self._FORBIDDEN:
                        if forbidden in name:
                            violations.append(f"{fp.name}:{node.lineno}: {name}")
        self.assertEqual(violations, [], f"Forbidden calls: {violations}")

    def test_advisory_label_in_all_files(self):
        missing = []
        for fp in self._phase5d_files():
            if self._ADVISORY_LABEL not in fp.read_text():
                missing.append(fp.name)
        self.assertEqual(missing, [], f"Missing advisory label: {missing}")

    def test_no_live_broker_import(self):
        import ast
        violations = []
        for fp in self._phase5d_files():
            src = fp.read_text()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in getattr(node, "names", [])]
                    mod = getattr(node, "module", "") or ""
                    for n in names + [mod]:
                        if "KiteConnect" in n or "broker_client" in n:
                            violations.append(f"{fp.name}: {n}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
