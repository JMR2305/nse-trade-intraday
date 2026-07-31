"""
test_data_quality.py — Phase 8.3
Comprehensive unit tests for the Data Quality & Validation Framework.

Tests cover: feature flag, market, preopen, paper, portfolio, AI, signal,
config validators, quality score, shared services, exports, and alerts.

All tests are ADVISORY-ONLY and READ-ONLY — no data is modified.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the python dir is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Flag helpers ───────────────────────────────────────────────────────────────
def _enable():  os.environ["DATA_QUALITY_ENABLED"] = "true"
def _disable(): os.environ["DATA_QUALITY_ENABLED"] = "false"


# ── Market fixtures ────────────────────────────────────────────────────────────
def _good_row(symbol="RELIANCE", **kw):
    row = dict(
        symbol=symbol, open=2800.0, high=2850.0, low=2780.0,
        close=2830.0, volume=500_000, timestamp="2026-07-30T09:15:00+05:30",
    )
    row.update(kw)
    return row


def _good_preopen(symbol="TCS", **kw):
    row = dict(
        symbol=symbol, iep=3500.0, prev_close=3480.0,
        buy_qty=12_000, sell_qty=9_000, gap_pct=0.57,
        provider="nse_official",
    )
    row.update(kw)
    return row


def _good_trade(**kw):
    t = dict(id="T001", symbol="INFY", side="SELL", qty=10, price=1500.0,
             entry_price=1480.0, exit_price=1500.0, pnl=200.0,
             entry_ts="2026-07-30T10:00:00", exit_ts="2026-07-30T14:00:00")
    t.update(kw)
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# Feature-flag tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestFeatureFlag(unittest.TestCase):

    def test_disabled_by_default(self):
        _disable()
        from data_quality.models import is_enabled
        self.assertFalse(is_enabled())

    def test_enabled_with_true(self):
        _enable()
        from data_quality.models import is_enabled
        self.assertTrue(is_enabled())

    def test_enabled_with_1(self):
        os.environ["DATA_QUALITY_ENABLED"] = "1"
        from data_quality.models import is_enabled
        self.assertTrue(is_enabled())
        _enable()

    def test_disabled_response_shape(self):
        from data_quality.models import disabled_response
        r = disabled_response()
        self.assertEqual(r["status"], "DISABLED")
        self.assertFalse(r["available"])
        self.assertTrue(r["advisory_only"])
        self.assertIn("DATA_QUALITY_ENABLED", r["message"])

    def test_summary_returns_disabled_when_flag_off(self):
        _disable()
        from data_quality.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "DISABLED")
        _enable()

    def tearDown(self):
        _enable()


# ═══════════════════════════════════════════════════════════════════════════════
# Market validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestMarketValidation(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _validate(self, rows):
        from data_quality.market import validate_market_snapshot
        return validate_market_snapshot(rows)

    def _ohlcv(self, row):
        from data_quality.market import validate_ohlcv
        return validate_ohlcv(row, row.get("symbol", ""))

    def test_good_row_no_issues(self):
        issues = self._ohlcv(_good_row())
        self.assertEqual(issues, [])

    def test_high_less_than_low_is_critical(self):
        issues = self._ohlcv(_good_row(high=2700.0, low=2800.0))
        checks = [i.check for i in issues]
        self.assertIn("OHLC_CONSISTENCY", checks)
        sevs = [i.severity for i in issues]
        self.assertIn("CRITICAL", sevs)

    def test_close_above_high_is_critical(self):
        issues = self._ohlcv(_good_row(close=2900.0, high=2850.0))
        self.assertTrue(any(i.check == "OHLC_CONSISTENCY" for i in issues))

    def test_close_below_low_is_critical(self):
        issues = self._ohlcv(_good_row(close=2770.0, low=2780.0))
        self.assertTrue(any(i.check == "OHLC_CONSISTENCY" for i in issues))

    def test_open_above_high_is_critical(self):
        issues = self._ohlcv(_good_row(open=2900.0, high=2850.0))
        self.assertTrue(any(i.check == "OHLC_CONSISTENCY" for i in issues))

    def test_open_below_low_is_critical(self):
        issues = self._ohlcv(_good_row(open=2760.0, low=2780.0))
        self.assertTrue(any(i.check == "OHLC_CONSISTENCY" for i in issues))

    def test_negative_price_is_critical(self):
        issues = self._ohlcv(_good_row(close=-100.0))
        self.assertTrue(any(i.check == "NEGATIVE_PRICE" for i in issues))

    def test_zero_price_is_critical(self):
        issues = self._ohlcv(_good_row(open=0.0, high=0.0, low=0.0, close=0.0))
        self.assertTrue(any(i.check == "NEGATIVE_PRICE" for i in issues))

    def test_negative_volume_is_critical(self):
        issues = self._ohlcv(_good_row(volume=-1000))
        self.assertTrue(any(i.check == "NEGATIVE_VOLUME" for i in issues))

    def test_zero_volume_is_warning(self):
        issues = self._ohlcv(_good_row(volume=0))
        self.assertTrue(any(i.severity == "WARNING" and i.check == "ZERO_VOLUME"
                            for i in issues))

    def test_snapshot_passes_with_good_data(self):
        result = self._validate([_good_row("RELIANCE"), _good_row("TCS")])
        self.assertTrue(result["available"])
        self.assertEqual(result["checks_failed"], 0)

    def test_snapshot_detects_duplicate_symbol(self):
        result = self._validate([_good_row("RELIANCE"), _good_row("RELIANCE")])
        self.assertTrue(any(i["severity"] == "DUPLICATE" for i in result["issues"]))

    def test_empty_snapshot_unavailable(self):
        result = self._validate([])
        self.assertFalse(result["available"])

    def test_snapshot_result_has_required_fields(self):
        result = self._validate([_good_row()])
        for fld in ("domain", "score", "grade", "checks_run", "checks_passed",
                    "checks_failed", "issues", "generated_at", "advisory_only"):
            self.assertIn(fld, result)

    def test_score_is_100_for_perfect_data(self):
        result = self._validate([_good_row("RELIANCE"), _good_row("TCS")])
        self.assertEqual(result["score"], 100.0)

    def test_future_timestamp_is_warning(self):
        from data_quality.market import validate_timestamps
        import time
        future_ts = str(int(time.time()) + 3600)
        issues = validate_timestamps([{"timestamp": future_ts}])
        self.assertTrue(any(i.check == "FUTURE_TIMESTAMP" for i in issues))

    def test_non_monotonic_timestamps_flagged(self):
        from data_quality.market import validate_timestamps
        rows = [{"timestamp": "2026-07-30T10:00:00"},
                {"timestamp": "2026-07-30T09:00:00"}]  # earlier second
        issues = validate_timestamps(rows)
        self.assertTrue(any(i.check == "TIMESTAMP_ORDER" for i in issues))


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-open validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestPreopenValidation(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _sym(self, row):
        from data_quality.preopen import validate_preopen_symbol
        return validate_preopen_symbol(row)

    def _snap(self, rows):
        from data_quality.preopen import validate_preopen_snapshot
        return validate_preopen_snapshot(rows)

    def test_good_symbol_no_issues(self):
        self.assertEqual(self._sym(_good_preopen()), [])

    def test_missing_iep_flagged(self):
        r = _good_preopen()
        r.pop("iep")
        issues = self._sym(r)
        self.assertTrue(any(i.check == "IEP_PRESENT" for i in issues))

    def test_negative_iep_is_critical(self):
        issues = self._sym(_good_preopen(iep=-100))
        self.assertTrue(any(i.severity == "CRITICAL" for i in issues))

    def test_extreme_gap_is_warning(self):
        issues = self._sym(_good_preopen(iep=5000.0, prev_close=3480.0))  # ~44% gap
        self.assertTrue(any(i.check == "PREOPEN_SPIKE" for i in issues))

    def test_negative_buy_qty_critical(self):
        issues = self._sym(_good_preopen(buy_qty=-100))
        self.assertTrue(any(i.check == "NEGATIVE_QTY" for i in issues))

    def test_negative_sell_qty_critical(self):
        issues = self._sym(_good_preopen(sell_qty=-500))
        self.assertTrue(any(i.check == "NEGATIVE_QTY" for i in issues))

    def test_extreme_gap_pct_flagged(self):
        issues = self._sym(_good_preopen(gap_pct=35.0))
        self.assertTrue(any(i.check == "GAP_SPIKE" for i in issues))

    def test_empty_snapshot_unavailable(self):
        r = self._snap([])
        self.assertFalse(r["available"])

    def test_duplicate_symbols_flagged(self):
        r = self._snap([_good_preopen("TCS"), _good_preopen("TCS")])
        self.assertTrue(any(i["severity"] == "DUPLICATE" for i in r["issues"]))

    def test_good_snapshot_passes(self):
        r = self._snap([_good_preopen("TCS"), _good_preopen("INFY")])
        self.assertEqual(r["checks_failed"], 0)

    def test_provider_mismatch_flagged(self):
        from data_quality.preopen import validate_provider_consistency
        syms = [
            {"provider": "nse_official", "symbol": "TCS"},
            {"provider": "yahoo",        "symbol": "INFY"},
        ]
        issues = validate_provider_consistency(syms)
        self.assertTrue(any(i.check == "PROVIDER_MISMATCH" for i in issues))

    def test_fallback_active_is_info(self):
        from data_quality.preopen import validate_provider_consistency
        syms = [{"provider": "yahoo", "symbol": "TCS", "is_fallback": True}]
        issues = validate_provider_consistency(syms)
        self.assertTrue(any(i.check == "FALLBACK_ACTIVE" for i in issues))


# ═══════════════════════════════════════════════════════════════════════════════
# Paper trading validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestPaperValidation(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _trade(self, t):
        from data_quality.paper import validate_trade_record
        return validate_trade_record(t)

    def test_good_trade_no_issues(self):
        self.assertEqual(self._trade(_good_trade()), [])

    def test_missing_trade_id_is_critical(self):
        t = _good_trade()
        t.pop("id")
        issues = self._trade(t)
        self.assertTrue(any(i.check == "TRADE_ID_MISSING" for i in issues))

    def test_zero_quantity_is_critical(self):
        issues = self._trade(_good_trade(qty=0))
        self.assertTrue(any(i.check == "NEGATIVE_QTY" for i in issues))

    def test_negative_price_is_critical(self):
        issues = self._trade(_good_trade(price=-100))
        self.assertTrue(any(i.check == "NEGATIVE_PRICE" for i in issues))

    def test_pnl_inconsistency_flagged(self):
        # P&L reported as 10_000 but computed as (1500-1480)*10 = 200
        issues = self._trade(_good_trade(pnl=10_000))
        self.assertTrue(any(i.check == "PNL_INCONSISTENCY" for i in issues))

    def test_pnl_within_tolerance_ok(self):
        # Exact P&L: (1500-1480)*10 = 200
        issues = self._trade(_good_trade(pnl=200.0))
        self.assertFalse(any(i.check == "PNL_INCONSISTENCY" for i in issues))

    def test_duplicate_trade_ids_flagged(self):
        from data_quality.paper import validate_duplicate_trades
        trades = [_good_trade(id="T001"), _good_trade(id="T001", symbol="TCS")]
        issues = validate_duplicate_trades(trades)
        self.assertTrue(any(i.severity == "DUPLICATE" for i in issues))

    def test_oversell_flagged(self):
        from data_quality.paper import validate_trade_sequence
        trades = [
            {"symbol": "INFY", "side": "BUY",  "qty": 5},
            {"symbol": "INFY", "side": "SELL", "qty": 10},  # sell > held
        ]
        issues = validate_trade_sequence(trades)
        self.assertTrue(any(i.check == "OVERSELL" for i in issues))

    def test_normal_sequence_no_issues(self):
        from data_quality.paper import validate_trade_sequence
        trades = [
            {"symbol": "INFY", "side": "BUY",  "qty": 10},
            {"symbol": "INFY", "side": "SELL", "qty": 10},
        ]
        self.assertEqual(validate_trade_sequence(trades), [])

    def test_negative_cash_is_critical(self):
        from data_quality.paper import validate_portfolio_cash
        issues = validate_portfolio_cash({"cash_available": -1000, "total_value": 500_000})
        self.assertTrue(any(i.check == "NEGATIVE_CASH" for i in issues))

    def test_portfolio_total_mismatch_is_warning(self):
        from data_quality.paper import validate_portfolio_cash
        # cash=100k + invested=100k = 200k but total=400k
        issues = validate_portfolio_cash({
            "cash_available": 100_000, "invested_capital": 100_000,
            "total_value": 400_000,
        })
        self.assertTrue(any(i.check == "PORTFOLIO_TOTAL" for i in issues))


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestPortfolioValidation(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _validate(self, data):
        from data_quality.portfolio import validate_portfolio
        return validate_portfolio(data)

    def _good_portfolio(self):
        return {
            "total_value": 500_000,
            "cash_available": 250_000,
            "invested_capital": 250_000,
            "portfolio_utilisation_pct": 50.0,
            "portfolio_heat": 35.0,
        }

    def test_good_portfolio_passes(self):
        r = self._validate(self._good_portfolio())
        self.assertEqual(r["checks_failed"], 0)

    def test_negative_total_value_critical(self):
        r = self._validate({**self._good_portfolio(), "total_value": -1000})
        self.assertTrue(any(i["check"] == "CAPITAL_NEGATIVE" for i in r["issues"]))

    def test_negative_cash_critical(self):
        r = self._validate({**self._good_portfolio(), "cash_available": -500})
        self.assertTrue(any(i["check"] == "CASH_NEGATIVE" for i in r["issues"]))

    def test_utilisation_over_100_is_warning(self):
        r = self._validate({**self._good_portfolio(), "portfolio_utilisation_pct": 120.0})
        self.assertTrue(any(i["check"] == "UTILISATION_RANGE" for i in r["issues"]))

    def test_portfolio_total_mismatch_is_warning(self):
        r = self._validate({
            "total_value": 500_000,
            "cash_available": 100_000,
            "invested_capital": 100_000,  # sum=200k ≠ 500k
        })
        self.assertTrue(any(i["check"] == "PORTFOLIO_TOTAL" for i in r["issues"]))

    def test_sector_sum_over_100_is_warning(self):
        data = {**self._good_portfolio(),
                "sectors": [{"pct": 70}, {"pct": 50}]}  # sum=120%
        r = self._validate(data)
        self.assertTrue(any(i["check"] == "SECTOR_SUM" for i in r["issues"]))

    def test_empty_portfolio_unavailable(self):
        r = self._validate({})
        self.assertFalse(r["available"])

    def test_negative_position_value_critical(self):
        data = {**self._good_portfolio(),
                "positions": [{"symbol": "TCS", "value": -10_000, "qty": 5}]}
        r = self._validate(data)
        self.assertTrue(any(i["check"] == "NEGATIVE_POSITION" for i in r["issues"]))


# ═══════════════════════════════════════════════════════════════════════════════
# AI validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestAIValidation(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _validate(self, snap):
        from data_quality.ai_check import validate_ai_snapshot
        return validate_ai_snapshot(snap)

    def _good_snap(self):
        return {
            "avg_confidence": 0.72,
            "recent_accuracy": 0.68,
            "calibration_ece": 0.08,
            "total_signals": 120,
            "executed_signals": 38,
            "health_score": {"total_score": 74.0, "label": "Good"},
        }

    def test_good_snapshot_passes(self):
        r = self._validate(self._good_snap())
        self.assertEqual(r["checks_failed"], 0)

    def test_confidence_above_1_is_critical(self):
        r = self._validate({**self._good_snap(), "avg_confidence": 1.5})
        self.assertTrue(any(i["check"] == "CONFIDENCE_RANGE" for i in r["issues"]))

    def test_confidence_below_0_is_critical(self):
        r = self._validate({**self._good_snap(), "avg_confidence": -0.1})
        self.assertTrue(any(i["check"] == "CONFIDENCE_RANGE" for i in r["issues"]))

    def test_missing_confidence_flagged(self):
        snap = self._good_snap()
        snap.pop("avg_confidence")
        r = self._validate(snap)
        self.assertTrue(any(i["check"] == "CONFIDENCE_PRESENT" for i in r["issues"]))

    def test_high_ece_is_warning(self):
        r = self._validate({**self._good_snap(), "calibration_ece": 0.30})
        self.assertTrue(any(i["check"] == "CALIBRATION_ECE" for i in r["issues"]))

    def test_executed_exceeding_total_is_warning(self):
        r = self._validate({**self._good_snap(), "executed_signals": 200})
        self.assertTrue(any(i["check"] == "EXECUTION_OVERFLOW" for i in r["issues"]))

    def test_health_score_over_100_is_warning(self):
        snap = {**self._good_snap(), "health_score": {"total_score": 150.0}}
        r = self._validate(snap)
        self.assertTrue(any(i["check"] == "HEALTH_SCORE_RANGE" for i in r["issues"]))

    def test_empty_snapshot_unavailable(self):
        r = self._validate({})
        self.assertFalse(r["available"])


# ═══════════════════════════════════════════════════════════════════════════════
# Signal validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestSignalValidation(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _good_signal(self, **kw):
        s = dict(id="SIG001", symbol="TCS", status="APPROVED",
                 confidence=0.78, created_at="2026-07-30T09:15:00")
        s.update(kw)
        return s

    def _validate_set(self, sigs):
        from data_quality.signals import validate_signal_set
        return validate_signal_set(sigs)

    def test_no_signals_returns_ok(self):
        r = self._validate_set([])
        self.assertTrue(r["available"])
        self.assertIn("note", r)

    def test_good_signal_passes(self):
        r = self._validate_set([self._good_signal()])
        self.assertFalse(any(i["severity"] in ("CRITICAL", "DUPLICATE")
                             for i in r["issues"]))

    def test_missing_id_is_critical(self):
        sig = self._good_signal()
        sig.pop("id")
        r = self._validate_set([sig])
        self.assertTrue(any(i["check"] == "SIGNAL_ID_MISSING" for i in r["issues"]))

    def test_invalid_state_is_warning(self):
        r = self._validate_set([self._good_signal(status="ZOMBIE_STATE")])
        self.assertTrue(any(i["check"] == "INVALID_STATE" for i in r["issues"]))

    def test_confidence_out_of_range_is_warning(self):
        r = self._validate_set([self._good_signal(confidence=1.5)])
        self.assertTrue(any(i["check"] == "CONFIDENCE_RANGE" for i in r["issues"]))

    def test_duplicate_ids_flagged(self):
        r = self._validate_set([self._good_signal(), self._good_signal(symbol="INFY")])
        self.assertTrue(any(i["severity"] == "DUPLICATE" for i in r["issues"]))

    def test_executed_signal_without_linkage_warning(self):
        sig = self._good_signal(status="EXECUTED")
        r = self._validate_set([sig])
        self.assertTrue(any(i["check"] == "MISSING_LINKAGE" for i in r["issues"]))

    def test_executed_signal_with_linkage_ok(self):
        sig = self._good_signal(status="EXECUTED", paper_trade_id="PT001")
        r = self._validate_set([sig])
        self.assertFalse(any(i["check"] == "MISSING_LINKAGE" for i in r["issues"]))


# ═══════════════════════════════════════════════════════════════════════════════
# Config validation tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestConfigValidation(unittest.TestCase):

    def setUp(self):
        _enable()
        self._orig = {k: os.environ.get(k) for k in
                      ("DATABASE_URL", "SESSION_SECRET", "MARKET_DATA_PROVIDER")}

    def tearDown(self):
        _enable()
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _validate(self):
        from data_quality.config_check import validate_config
        return validate_config()

    def test_result_has_required_fields(self):
        r = self._validate()
        for fld in ("domain", "score", "grade", "checks_run", "advisory_only",
                    "flag_states", "provider"):
            self.assertIn(fld, r)

    def test_missing_database_url_is_critical(self):
        os.environ.pop("DATABASE_URL", None)
        r = self._validate()
        self.assertTrue(any(i["severity"] == "CRITICAL" and i["field"] == "DATABASE_URL"
                            for i in r["issues"]))

    def test_invalid_provider_is_warning(self):
        os.environ["MARKET_DATA_PROVIDER"] = "bloomberg"
        r = self._validate()
        self.assertTrue(any(i["check"] == "INVALID_PROVIDER" for i in r["issues"]))

    def test_valid_provider_passes(self):
        os.environ["MARKET_DATA_PROVIDER"] = "kite"
        r = self._validate()
        self.assertFalse(any(i["check"] == "INVALID_PROVIDER" for i in r["issues"]))

    def test_flag_states_reported(self):
        r = self._validate()
        self.assertIn("DATA_QUALITY_ENABLED", r["flag_states"])

    def test_advisory_only_always_true(self):
        self.assertTrue(self._validate()["advisory_only"])


# ═══════════════════════════════════════════════════════════════════════════════
# Quality grade and score tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestQualityScore(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def test_grade_a_plus_at_92(self):
        from data_quality.models import quality_grade
        self.assertEqual(quality_grade(92), "A+")

    def test_grade_a_at_80(self):
        from data_quality.models import quality_grade
        self.assertEqual(quality_grade(80), "A")

    def test_grade_b_at_68(self):
        from data_quality.models import quality_grade
        self.assertEqual(quality_grade(68), "B")

    def test_grade_c_at_50(self):
        from data_quality.models import quality_grade
        self.assertEqual(quality_grade(50), "C")

    def test_grade_d_below_50(self):
        from data_quality.models import quality_grade
        self.assertEqual(quality_grade(0), "D")
        self.assertEqual(quality_grade(49), "D")

    def test_domain_result_score_equals_pass_rate(self):
        from data_quality.models import domain_result, Issue
        r = domain_result("test", checks_run=10, checks_passed=8, issues=[])
        self.assertAlmostEqual(r["score"], 80.0)
        self.assertAlmostEqual(r["pass_rate"], 80.0)

    def test_domain_result_zero_checks_safe(self):
        from data_quality.models import domain_result
        r = domain_result("test", checks_run=0, checks_passed=0, issues=[])
        self.assertEqual(r["score"], 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared services / summary tests
# ═══════════════════════════════════════════════════════════════════════════════
class TestSharedServices(unittest.TestCase):

    def setUp(self):    _enable()
    def tearDown(self): _enable()

    def _mock_domain(self, score=80):
        return {
            "domain": "test", "status": "ENABLED", "available": True,
            "advisory_only": True, "score": score, "grade": "A",
            "checks_run": 10, "checks_passed": 8, "checks_failed": 2,
            "pass_rate": 80.0, "critical_count": 0, "warning_count": 1,
            "issues": [], "generated_at": "2026-07-30T00:00:00+00:00",
        }

    def test_summary_has_required_fields(self):
        from data_quality.shared_services import get_summary
        with patch("data_quality.shared_services._load_market",   return_value=self._mock_domain(90)), \
             patch("data_quality.shared_services._load_preopen",  return_value=self._mock_domain(85)), \
             patch("data_quality.shared_services._load_paper",    return_value=self._mock_domain(80)), \
             patch("data_quality.shared_services._load_portfolio",return_value=self._mock_domain(75)), \
             patch("data_quality.shared_services._load_ai",       return_value=self._mock_domain(88)), \
             patch("data_quality.shared_services._load_signals",  return_value=self._mock_domain(92)), \
             patch("data_quality.shared_services._load_config",   return_value=self._mock_domain(70)):
            r = get_summary()
        for fld in ("status", "available", "advisory_only", "quality_score",
                    "grade", "score_components", "domains", "generated_at",
                    "critical_count", "warning_count", "total_issues"):
            self.assertIn(fld, r)

    def test_summary_advisory_only(self):
        from data_quality.shared_services import get_summary
        with patch("data_quality.shared_services._load_market",   return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_preopen",  return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_paper",    return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_portfolio",return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_ai",       return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_signals",  return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_config",   return_value=self._mock_domain()):
            r = get_summary()
        self.assertTrue(r["advisory_only"])

    def test_summary_score_components_present(self):
        from data_quality.shared_services import get_summary
        m = self._mock_domain(90)
        with patch("data_quality.shared_services._load_market",   return_value=m), \
             patch("data_quality.shared_services._load_preopen",  return_value=m), \
             patch("data_quality.shared_services._load_paper",    return_value=m), \
             patch("data_quality.shared_services._load_portfolio",return_value=m), \
             patch("data_quality.shared_services._load_ai",       return_value=m), \
             patch("data_quality.shared_services._load_signals",  return_value=m), \
             patch("data_quality.shared_services._load_config",   return_value=m):
            comps = get_summary()["score_components"]
        for dim in ("completeness", "consistency", "accuracy",
                    "freshness", "integrity", "validity"):
            self.assertIn(dim, comps)

    def test_quality_score_weighted_average(self):
        from data_quality.shared_services import _weighted_score, _DOMAIN_WEIGHTS
        domains = {name: {"score": 100.0} for name in _DOMAIN_WEIGHTS}
        self.assertAlmostEqual(_weighted_score(domains), 100.0, places=1)

    def test_alerts_sorted_by_severity(self):
        from data_quality.shared_services import get_alerts
        critical_domain = {**self._mock_domain(50),
                           "issues": [{"severity": "CRITICAL", "check": "TEST",
                                       "field": "x", "message": "crit"}]}
        info_domain = {**self._mock_domain(90),
                       "issues": [{"severity": "INFO", "check": "TEST",
                                   "field": "y", "message": "info"}]}
        with patch("data_quality.shared_services._load_market",   return_value=critical_domain), \
             patch("data_quality.shared_services._load_preopen",  return_value=info_domain), \
             patch("data_quality.shared_services._load_paper",    return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_portfolio",return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_ai",       return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_signals",  return_value=self._mock_domain()), \
             patch("data_quality.shared_services._load_config",   return_value=self._mock_domain()):
            r = get_alerts()
        self.assertGreater(len(r["critical"]), 0)
        self.assertEqual(r["status"], "ENABLED")

    def test_export_csv_returns_string(self):
        from data_quality.shared_services import get_export_csv
        m = self._mock_domain()
        with patch("data_quality.shared_services._load_market",   return_value=m), \
             patch("data_quality.shared_services._load_preopen",  return_value=m), \
             patch("data_quality.shared_services._load_paper",    return_value=m), \
             patch("data_quality.shared_services._load_portfolio",return_value=m), \
             patch("data_quality.shared_services._load_ai",       return_value=m), \
             patch("data_quality.shared_services._load_signals",  return_value=m), \
             patch("data_quality.shared_services._load_config",   return_value=m):
            csv = get_export_csv()
        self.assertIsInstance(csv, str)
        self.assertTrue(csv.startswith("domain,severity"))

    def test_snapshot_has_quality_score(self):
        from data_quality.shared_services import get_data_quality_snapshot
        m = self._mock_domain(85)
        with patch("data_quality.shared_services.get_summary", return_value={
            "quality_score": 85.0, "grade": "A", "critical_count": 0,
            "warning_count": 2, "total_issues": 2,
            "generated_at": "2026-07-30T00:00:00+00:00",
        }):
            snap = get_data_quality_snapshot()
        self.assertIn("quality_score", snap)
        self.assertTrue(snap["advisory_only"])
        self.assertTrue(snap["available"])


if __name__ == "__main__":
    unittest.main()
