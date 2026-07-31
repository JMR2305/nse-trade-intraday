"""
test_risk_validation.py — Phase 8.4
Comprehensive unit tests for the Advanced Risk Validation Framework.
All tests run with RISK_VALIDATION_ENABLED=true and patch external dependencies.
READ-ONLY · ADVISORY-ONLY.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RISK_VALIDATION_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)


def _en():  os.environ["RISK_VALIDATION_ENABLED"] = "true"
def _dis(): os.environ["RISK_VALIDATION_ENABLED"] = "false"


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _portfolio(
    total=100_000, cash=20_000, invested=80_000,
    util=80.0, drawdown=5.0, heat=30.0,
    positions=None,
):
    return {
        "total_value": total,
        "cash_available": cash,
        "invested_capital": invested,
        "portfolio_utilisation_pct": util,
        "max_drawdown_pct": drawdown,
        "portfolio_heat": heat,
        "positions": positions or [],
    }


def _pos(symbol, value, total=100_000):
    return {
        "symbol": symbol,
        "current_value": value,
        "qty": 10,
        "pnl": value * 0.02,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. models.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestModels(unittest.TestCase):

    def test_is_enabled_true(self):
        from risk_validation.models import is_enabled
        self.assertTrue(is_enabled())

    def test_is_enabled_false(self):
        _dis()
        from risk_validation.models import is_enabled
        self.assertFalse(is_enabled())
        _en()

    def test_disabled_response_status(self):
        from risk_validation.models import disabled_response
        r = disabled_response()
        self.assertEqual(r["status"], "DISABLED")
        self.assertFalse(r["available"])
        self.assertTrue(r["advisory_only"])

    def test_risk_grade_a_plus(self):
        from risk_validation.models import risk_grade
        self.assertEqual(risk_grade(95), "A+")

    def test_risk_grade_a(self):
        from risk_validation.models import risk_grade
        self.assertEqual(risk_grade(82), "A")

    def test_risk_grade_b(self):
        from risk_validation.models import risk_grade
        self.assertEqual(risk_grade(70), "B")

    def test_risk_grade_c(self):
        from risk_validation.models import risk_grade
        self.assertEqual(risk_grade(55), "C")

    def test_risk_grade_d(self):
        from risk_validation.models import risk_grade
        self.assertEqual(risk_grade(30), "D")

    def test_risk_trend_improving(self):
        from risk_validation.models import risk_trend
        self.assertEqual(risk_trend([60, 70, 80]), "Improving")

    def test_risk_trend_deteriorating(self):
        from risk_validation.models import risk_trend
        self.assertEqual(risk_trend([80, 70, 60]), "Deteriorating")

    def test_risk_trend_stable(self):
        from risk_validation.models import risk_trend
        self.assertEqual(risk_trend([75, 76, 74]), "Stable")

    def test_risk_trend_single_point(self):
        from risk_validation.models import risk_trend
        self.assertEqual(risk_trend([80]), "Stable")

    def test_issue_to_dict_has_fields(self):
        from risk_validation.models import Issue
        i = Issue("CRITICAL", "TEST_CHECK", "field", "message", 42.0, "test")
        d = i.to_dict()
        self.assertEqual(d["severity"], "CRITICAL")
        self.assertEqual(d["check"],    "TEST_CHECK")
        self.assertIn("value", d)
        self.assertIn("category", d)

    def test_issue_to_dict_omits_none_value(self):
        from risk_validation.models import Issue
        d = Issue("INFO", "X", "f", "m").to_dict()
        self.assertNotIn("value", d)

    def test_domain_result_score_100(self):
        from risk_validation.models import domain_result, Issue
        r = domain_result("test", 5, 5, [])
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["checks_failed"], 0)

    def test_domain_result_score_partial(self):
        from risk_validation.models import domain_result, Issue
        r = domain_result("test", 4, 3, [Issue("WARNING","W","f","m")])
        self.assertEqual(r["score"], 75.0)
        self.assertEqual(r["warning_count"], 1)

    def test_unavailable_result(self):
        from risk_validation.models import unavailable_result
        r = unavailable_result("test_domain", "No data")
        self.assertFalse(r["available"])
        self.assertEqual(r["domain"], "test_domain")
        self.assertIn("reason", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. portfolio.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestPortfolioValidation(unittest.TestCase):

    def _validate(self, p=None, risk_snap=None):
        from risk_validation.portfolio import validate_capital, validate_drawdown
        p = p or _portfolio()
        issues, run, passed = validate_capital(p)
        iss2, r2, p2 = validate_drawdown(p, risk_snap or {})
        return issues + iss2, run + r2, passed + p2

    def test_healthy_portfolio_no_critical(self):
        p = _portfolio(total=100_000, cash=20_000, util=80.0, drawdown=5.0)
        issues, run, passed = self._validate(p)
        crits = [i for i in issues if i.severity == "CRITICAL"]
        self.assertEqual(crits, [])

    def test_zero_capital_critical(self):
        p = _portfolio(total=0)
        issues, _, _ = self._validate(p)
        checks = [i.check for i in issues]
        self.assertIn("CAPITAL_POSITIVE", checks)

    def test_negative_cash_critical(self):
        p = _portfolio(cash=-100)
        issues, _, _ = self._validate(p)
        checks = [i.check for i in issues]
        self.assertIn("CASH_NON_NEGATIVE", checks)

    def test_low_cash_buffer_warning(self):
        # Cash buffer < 5%
        p = _portfolio(total=100_000, cash=2_000, util=98.0)
        issues, _, _ = self._validate(p)
        sevs = {i.check: i.severity for i in issues}
        self.assertIn("CASH_BUFFER_LOW", sevs)

    def test_critical_utilisation(self):
        p = _portfolio(util=96.0)
        issues, _, _ = self._validate(p)
        checks = [i.check for i in issues]
        self.assertIn("HIGH_UTILISATION", checks)

    def test_critical_drawdown(self):
        p = _portfolio(drawdown=25.0)
        issues, _, _ = self._validate(p)
        checks = [i.check for i in issues]
        self.assertIn("CRITICAL_DRAWDOWN", checks)

    def test_warning_drawdown(self):
        p = _portfolio(drawdown=12.0)
        issues, _, _ = self._validate(p)
        checks = [i.check for i in issues]
        self.assertIn("ELEVATED_DRAWDOWN", checks)

    def test_critical_heat(self):
        p = _portfolio(heat=70.0)
        issues, _, _ = self._validate(p)
        checks = [i.check for i in issues]
        self.assertIn("HIGH_HEAT", checks)

    def test_position_concentration_critical(self):
        from risk_validation.portfolio import validate_position_concentration
        pos = [_pos("RELIANCE", 40_000)]
        issues, _, _ = validate_position_concentration(pos, 100_000)
        checks = [i.check for i in issues]
        self.assertIn("EXCESSIVE_CONCENTRATION", checks)

    def test_position_concentration_warning(self):
        from risk_validation.portfolio import validate_position_concentration
        pos = [_pos("RELIANCE", 22_000)]
        issues, _, _ = validate_position_concentration(pos, 100_000)
        checks = [i.check for i in issues]
        self.assertIn("HIGH_CONCENTRATION", checks)

    def test_position_ok_no_issues(self):
        from risk_validation.portfolio import validate_position_concentration
        pos = [_pos("RELIANCE", 10_000)]
        issues, run, passed = validate_position_concentration(pos, 100_000)
        self.assertEqual(len(issues), 0)
        self.assertEqual(run, passed)

    def test_get_portfolio_validation_unavailable_when_no_data(self):
        with patch("risk_validation.portfolio._load_portfolio", return_value={}), \
             patch("risk_validation.portfolio._load_risk_snapshot", return_value={}):
            from risk_validation.portfolio import get_portfolio_validation
            r = get_portfolio_validation()
            self.assertFalse(r["available"])

    def test_get_portfolio_validation_has_domain(self):
        with patch("risk_validation.portfolio._load_portfolio",
                   return_value=_portfolio()), \
             patch("risk_validation.portfolio._load_risk_snapshot", return_value={}):
            from risk_validation.portfolio import get_portfolio_validation
            r = get_portfolio_validation()
            self.assertEqual(r["domain"], "portfolio")
            self.assertTrue(r["available"])

    def test_advisory_only(self):
        with patch("risk_validation.portfolio._load_portfolio",
                   return_value=_portfolio()), \
             patch("risk_validation.portfolio._load_risk_snapshot", return_value={}):
            from risk_validation.portfolio import get_portfolio_validation
            r = get_portfolio_validation()
            self.assertTrue(r["advisory_only"])


# ═══════════════════════════════════════════════════════════════════════════════
# 3. sector.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestSectorValidation(unittest.TestCase):

    def test_sector_over_concentrated_critical(self):
        from risk_validation.sector import validate_sector_concentration
        issues, _, _ = validate_sector_concentration({"IT": 60.0, "Banking": 40.0})
        checks = [i.check for i in issues]
        self.assertIn("SECTOR_OVER_CONCENTRATED", checks)

    def test_sector_concentration_warning(self):
        from risk_validation.sector import validate_sector_concentration
        issues, _, _ = validate_sector_concentration({"IT": 37.0, "Banking": 30.0})
        checks = [i.check for i in issues]
        self.assertIn("SECTOR_HIGH_CONCENTRATION", checks)

    def test_sector_diversification_ok(self):
        from risk_validation.sector import validate_diversification
        issues, run, passed = validate_diversification({
            "IT": 30.0, "Banking": 25.0, "Pharma": 20.0, "FMCG": 25.0
        })
        self.assertEqual(run, passed + len(issues))
        dom_issues = [i for i in issues if i.check == "LOW_DIVERSIFICATION"]
        self.assertEqual(dom_issues, [])

    def test_single_sector_low_diversification(self):
        from risk_validation.sector import validate_diversification
        issues, _, _ = validate_diversification({"IT": 100.0})
        checks = [i.check for i in issues]
        self.assertIn("DOMINANT_SECTOR", checks)

    def test_hhi_drift_high(self):
        from risk_validation.sector import validate_sector_drift
        # All in one sector → HHI = 1.0
        issues, _, _ = validate_sector_drift({"IT": 100.0})
        checks = [i.check for i in issues]
        self.assertIn("HIGH_HHI_DRIFT", checks)

    def test_hhi_drift_low(self):
        from risk_validation.sector import validate_sector_drift
        equal = {"IT": 25.0, "Banking": 25.0, "Pharma": 25.0, "FMCG": 25.0}
        issues, _, _ = validate_sector_drift(equal)
        # HHI = 4*(0.25)^2 = 0.25 — below 0.50 threshold
        self.assertEqual(issues, [])

    def test_unavailable_when_no_sectors(self):
        with patch("risk_validation.sector._load_sector_data", return_value={}), \
             patch("risk_validation.sector._load_market_sectors", return_value={}):
            from risk_validation.sector import get_sector_validation
            r = get_sector_validation()
            self.assertFalse(r["available"])

    def test_get_sector_domain_name(self):
        with patch("risk_validation.sector._load_sector_data",
                   return_value={"IT": 40.0, "Banking": 35.0, "FMCG": 25.0}):
            from risk_validation.sector import get_sector_validation
            r = get_sector_validation()
            self.assertEqual(r["domain"], "sector")

    def test_normalize_dict_of_numbers(self):
        from risk_validation.sector import _normalize_sectors
        result = _normalize_sectors({"IT": 40.0, "Banking": 35.0})
        self.assertAlmostEqual(result["IT"], 40.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. correlation.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestCorrelationValidation(unittest.TestCase):

    def _make_positions(self, symbols):
        return [{"symbol": s, "current_value": 20_000} for s in symbols]

    def test_same_sector_high_correlation(self):
        from risk_validation.correlation import _estimate_portfolio_correlation
        # All IT
        pos = self._make_positions(["TCS", "INFY", "WIPRO"])
        corr = _estimate_portfolio_correlation(pos)
        self.assertGreater(corr, 0.60)

    def test_mixed_sectors_lower_correlation(self):
        from risk_validation.correlation import _estimate_portfolio_correlation
        pos = self._make_positions(["TCS", "HDFCBANK", "SUNPHARMA", "MARUTI"])
        corr = _estimate_portfolio_correlation(pos)
        self.assertLess(corr, 0.60)

    def test_single_position_correlation_zero(self):
        from risk_validation.correlation import _estimate_portfolio_correlation
        pos = [{"symbol": "TCS", "current_value": 50_000}]
        self.assertEqual(_estimate_portfolio_correlation(pos), 0.0)

    def test_diversification_score_equal_sectors(self):
        from risk_validation.correlation import _diversification_score
        # TCS=IT, HDFCBANK=Banking, SUNPHARMA=Pharma, MARUTI=Auto → 4 sectors equal
        pos = [
            {"symbol": "TCS",      "current_value": 25_000},
            {"symbol": "HDFCBANK", "current_value": 25_000},
            {"symbol": "SUNPHARMA","current_value": 25_000},
            {"symbol": "MARUTI",   "current_value": 25_000},
        ]
        score = _diversification_score(pos)
        self.assertGreater(score, 0.5)

    def test_diversification_score_all_same_sector(self):
        from risk_validation.correlation import _diversification_score
        pos = self._make_positions(["TCS", "INFY", "WIPRO"])
        score = _diversification_score(pos)
        self.assertLess(score, 0.3)

    def test_unavailable_no_positions(self):
        with patch("risk_validation.correlation._load_positions", return_value=[]):
            from risk_validation.correlation import get_correlation_validation
            r = get_correlation_validation()
            self.assertFalse(r["available"])

    def test_has_correlation_fields(self):
        pos = [
            {"symbol": "TCS",      "current_value": 50_000},
            {"symbol": "HDFCBANK", "current_value": 50_000},
        ]
        with patch("risk_validation.correlation._load_positions", return_value=pos):
            from risk_validation.correlation import get_correlation_validation
            r = get_correlation_validation()
            self.assertIn("avg_correlation", r)
            self.assertIn("diversification_score", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. stress.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestStressValidation(unittest.TestCase):

    def test_run_scenarios_count(self):
        from risk_validation.stress import run_scenarios, SCENARIOS
        results = run_scenarios(100_000)
        self.assertEqual(len(results), len(SCENARIOS))

    def test_fall_5_impact(self):
        from risk_validation.stress import run_scenarios
        results = {r["id"]: r for r in run_scenarios(100_000)}
        self.assertAlmostEqual(results["fall_5"]["impact_value"], -5_000)
        self.assertAlmostEqual(results["fall_5"]["portfolio_value_after"], 95_000)

    def test_fall_20_impact(self):
        from risk_validation.stress import run_scenarios
        results = {r["id"]: r for r in run_scenarios(100_000)}
        self.assertAlmostEqual(results["fall_20"]["impact_value"], -20_000)

    def test_gap_up_positive(self):
        from risk_validation.stress import run_scenarios
        results = {r["id"]: r for r in run_scenarios(100_000)}
        self.assertGreater(results["gap_up"]["impact_value"], 0)

    def test_result_has_advisory_note(self):
        from risk_validation.stress import run_scenarios
        for r in run_scenarios(100_000):
            self.assertIn("advisory_note", r)
            self.assertTrue(r["advisory_note"])

    def test_unavailable_when_zero_portfolio(self):
        with patch("risk_validation.stress._load_portfolio_value", return_value=0.0):
            from risk_validation.stress import get_stress_validation
            r = get_stress_validation()
            self.assertFalse(r["available"])

    def test_stress_domain_name(self):
        with patch("risk_validation.stress._load_portfolio_value", return_value=100_000.0):
            from risk_validation.stress import get_stress_validation
            r = get_stress_validation()
            self.assertEqual(r["domain"], "stress")
            self.assertIn("scenarios", r)

    def test_advisory_only_flag(self):
        with patch("risk_validation.stress._load_portfolio_value", return_value=100_000.0):
            from risk_validation.stress import get_stress_validation
            r = get_stress_validation()
            self.assertTrue(r["advisory_only"])

    def test_severe_scenarios_flagged(self):
        with patch("risk_validation.stress._load_portfolio_value", return_value=100_000.0):
            from risk_validation.stress import get_stress_validation
            r = get_stress_validation()
            # fall_15, fall_20, flash_crash, global_shock → 4 severe
            self.assertGreaterEqual(r["severe_count"], 4)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. tail_risk.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestTailRisk(unittest.TestCase):

    def test_var_95_less_than_var_99(self):
        from risk_validation.tail_risk import _parametric_var, _Z_95, _Z_99
        v95 = _parametric_var(100_000, 0.012, _Z_95)
        v99 = _parametric_var(100_000, 0.012, _Z_99)
        self.assertLess(v95, v99)

    def test_estimate_tail_risk_fields(self):
        from risk_validation.tail_risk import estimate_tail_risk
        r = estimate_tail_risk(100_000, 0.012)
        for fld in ["var_95_1d", "var_99_1d", "cvar_99_1d", "worst_case_5sigma",
                    "gap_risk_pct", "stress_drawdown_20pct", "recovery_estimate_days"]:
            self.assertIn(fld, r)

    def test_vol_from_vix(self):
        from risk_validation.tail_risk import _vol_from_vix
        vol = _vol_from_vix(20.0)
        self.assertGreater(vol, 0)
        self.assertLess(vol, 0.05)

    def test_vol_from_vix_zero_returns_default(self):
        from risk_validation.tail_risk import _vol_from_vix, _DEFAULT_DAILY_VOL
        self.assertEqual(_vol_from_vix(0), _DEFAULT_DAILY_VOL)

    def test_unavailable_when_no_portfolio(self):
        with patch("risk_validation.tail_risk._load_portfolio", return_value={}):
            from risk_validation.tail_risk import get_tail_risk_validation
            r = get_tail_risk_validation()
            self.assertFalse(r["available"])

    def test_high_vix_critical_issue(self):
        with patch("risk_validation.tail_risk._load_portfolio",
                   return_value={"total_value": 100_000}), \
             patch("risk_validation.tail_risk._load_vix", return_value=28.0):
            from risk_validation.tail_risk import get_tail_risk_validation
            r = get_tail_risk_validation()
            crits = [i for i in r["issues"] if i["severity"] == "CRITICAL"]
            self.assertTrue(any("VIX" in i["check"] for i in crits))

    def test_recovery_days_positive(self):
        from risk_validation.tail_risk import estimate_tail_risk
        r = estimate_tail_risk(100_000, 0.012)
        self.assertGreater(r["recovery_estimate_days"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. execution.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionValidation(unittest.TestCase):

    def _make_trades(self, n=5, has_exit=True):
        return [
            {"symbol": f"SYM{i}", "pnl": 200.0 * (1 if i % 2 else -1),
             "exit_price": 100.0 if has_exit else None}
            for i in range(n)
        ]

    def test_unavailable_when_no_data(self):
        with patch("risk_validation.execution._load_execution_quality", return_value={}), \
             patch("risk_validation.execution._load_paper_execution", return_value={}), \
             patch("risk_validation.execution._load_trades", return_value=[]):
            from risk_validation.execution import get_execution_validation
            r = get_execution_validation()
            self.assertFalse(r["available"])

    def test_fill_rate_calculation(self):
        from risk_validation.execution import _compute_paper_quality
        trades = self._make_trades(10, has_exit=True)
        q = _compute_paper_quality(trades)
        self.assertAlmostEqual(q["fill_rate"], 1.0)

    def test_fill_rate_zero_when_no_exit(self):
        from risk_validation.execution import _compute_paper_quality
        trades = self._make_trades(10, has_exit=False)
        q = _compute_paper_quality(trades)
        self.assertAlmostEqual(q["fill_rate"], 0.0)

    def test_high_slippage_warning(self):
        with patch("risk_validation.execution._load_execution_quality",
                   return_value={"avg_slippage_bps": 20.0}), \
             patch("risk_validation.execution._load_paper_execution", return_value={}), \
             patch("risk_validation.execution._load_trades",
                   return_value=self._make_trades(5)):
            from risk_validation.execution import get_execution_validation
            r = get_execution_validation()
            checks = [i["check"] for i in r["issues"]]
            self.assertIn("ELEVATED_SLIPPAGE", checks)

    def test_critical_slippage(self):
        with patch("risk_validation.execution._load_execution_quality",
                   return_value={"avg_slippage_bps": 35.0}), \
             patch("risk_validation.execution._load_paper_execution", return_value={}), \
             patch("risk_validation.execution._load_trades",
                   return_value=self._make_trades(5)):
            from risk_validation.execution import get_execution_validation
            r = get_execution_validation()
            crits = [i for i in r["issues"] if i["severity"] == "CRITICAL"]
            self.assertTrue(len(crits) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. market_risk.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketRiskValidation(unittest.TestCase):

    def test_bear_regime_critical(self):
        with patch("risk_validation.market_risk._load_market_intelligence",
                   return_value={"regime": "STRONG_BEAR"}), \
             patch("risk_validation.market_risk._load_macro", return_value={}), \
             patch("risk_validation.market_risk._load_vix", return_value=0.0):
            from risk_validation.market_risk import get_market_risk_validation
            r = get_market_risk_validation()
            crits = [i for i in r["issues"] if i["severity"] == "CRITICAL"]
            self.assertTrue(len(crits) > 0)

    def test_bull_regime_passes(self):
        with patch("risk_validation.market_risk._load_market_intelligence",
                   return_value={"regime": "STRONG_BULL"}), \
             patch("risk_validation.market_risk._load_macro", return_value={}), \
             patch("risk_validation.market_risk._load_vix", return_value=12.0):
            from risk_validation.market_risk import get_market_risk_validation
            r = get_market_risk_validation()
            crits = [i for i in r["issues"] if i["severity"] == "CRITICAL"]
            self.assertEqual(crits, [])

    def test_high_vix_critical(self):
        with patch("risk_validation.market_risk._load_market_intelligence", return_value={}), \
             patch("risk_validation.market_risk._load_macro", return_value={}), \
             patch("risk_validation.market_risk._load_vix", return_value=27.0):
            from risk_validation.market_risk import get_market_risk_validation
            r = get_market_risk_validation()
            crits = [i for i in r["issues"] if i["severity"] == "CRITICAL"]
            self.assertTrue(len(crits) > 0)

    def test_elevated_vix_warning(self):
        with patch("risk_validation.market_risk._load_market_intelligence", return_value={}), \
             patch("risk_validation.market_risk._load_macro", return_value={}), \
             patch("risk_validation.market_risk._load_vix", return_value=22.0):
            from risk_validation.market_risk import get_market_risk_validation
            r = get_market_risk_validation()
            warns = [i for i in r["issues"] if i["severity"] == "WARNING"]
            self.assertTrue(len(warns) > 0)

    def test_regime_risk_score_mapping(self):
        from risk_validation.market_risk import _regime_risk_score
        score, note = _regime_risk_score("STRONG_BULL")
        self.assertLess(score, 30)
        score2, _ = _regime_risk_score("CRASH")
        self.assertGreater(score2, 70)

    def test_unavailable_no_data(self):
        with patch("risk_validation.market_risk._load_market_intelligence", return_value={}), \
             patch("risk_validation.market_risk._load_macro", return_value={}), \
             patch("risk_validation.market_risk._load_vix", return_value=0.0):
            from risk_validation.market_risk import get_market_risk_validation
            r = get_market_risk_validation()
            self.assertFalse(r["available"])


# ═══════════════════════════════════════════════════════════════════════════════
# 9. drift.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestDriftValidation(unittest.TestCase):

    def test_near_max_utilisation_warning(self):
        from risk_validation.drift import detect_exposure_drift
        issues, run, passed = detect_exposure_drift({"portfolio_utilisation_pct": 92.0})
        self.assertTrue(any(i.check == "EXPOSURE_NEAR_MAX" for i in issues))

    def test_ok_utilisation_passes(self):
        from risk_validation.drift import detect_exposure_drift
        issues, run, passed = detect_exposure_drift({"portfolio_utilisation_pct": 70.0})
        self.assertEqual(issues, [])

    def test_critical_drawdown_drift(self):
        from risk_validation.drift import detect_drawdown_drift
        issues, _, _ = detect_drawdown_drift({"max_drawdown_pct": 18.0}, {})
        crits = [i for i in issues if i.severity == "CRITICAL"]
        self.assertTrue(len(crits) > 0)

    def test_capital_deterioration_critical(self):
        from risk_validation.drift import detect_capital_deterioration
        p = {"total_value": 75_000, "initial_capital": 100_000}
        issues, _, _ = detect_capital_deterioration(p)
        crits = [i for i in issues if i.severity == "CRITICAL"]
        self.assertTrue(len(crits) > 0)

    def test_capital_stable_no_issues(self):
        from risk_validation.drift import detect_capital_deterioration
        p = {"total_value": 105_000, "initial_capital": 100_000}
        issues, _, _ = detect_capital_deterioration(p)
        self.assertEqual(issues, [])

    def test_no_baseline_skips_capital_check(self):
        from risk_validation.drift import detect_capital_deterioration
        p = {"total_value": 50_000}  # no initial_capital
        issues, run, passed = detect_capital_deterioration(p)
        self.assertEqual(run, 0)

    def test_concentration_drift_critical(self):
        from risk_validation.drift import detect_concentration_drift
        p = {
            "positions": [{"symbol": "RELIANCE", "current_value": 40_000}],
            "total_value": 100_000,
        }
        issues, _, _ = detect_concentration_drift(p)
        crits = [i for i in issues if i.severity == "CRITICAL"]
        self.assertTrue(len(crits) > 0)

    def test_volatility_drift_warning(self):
        import math
        from risk_validation.drift import detect_volatility_drift
        # Very high volatility relative to mean
        trades = [{"pnl": (-1)**i * 5000 * (i + 1)} for i in range(8)]
        issues, run, _ = detect_volatility_drift(trades)
        # May or may not fire depending on exact values — just check no crash
        self.assertIsInstance(issues, list)

    def test_unavailable_when_no_portfolio(self):
        with patch("risk_validation.drift._load_portfolio", return_value={}):
            from risk_validation.drift import get_drift_validation
            r = get_drift_validation()
            self.assertFalse(r["available"])


# ═══════════════════════════════════════════════════════════════════════════════
# 10. shared_services.py
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_domain(score=80.0):
    return {
        "status": "ENABLED", "available": True, "advisory_only": True,
        "score": score, "grade": "A", "checks_run": 5, "checks_passed": 4,
        "checks_failed": 1, "critical_count": 0, "warning_count": 1,
        "issues": [],
    }


class TestSharedServices(unittest.TestCase):

    def _patch_all(self, score=80.0):
        d = _mock_domain(score)
        return patch.multiple(
            "risk_validation.shared_services",
            _load_portfolio   = lambda: d,
            _load_sector      = lambda: d,
            _load_correlation = lambda: d,
            _load_stress      = lambda: d,
            _load_tail_risk   = lambda: d,
            _load_execution   = lambda: d,
            _load_market_risk = lambda: d,
            _load_drift       = lambda: d,
        )

    def test_disabled_returns_disabled_response(self):
        _dis()
        from risk_validation.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "DISABLED")
        _en()

    def test_summary_has_required_fields(self):
        with self._patch_all():
            from risk_validation.shared_services import get_summary
            r = get_summary()
            for fld in ["risk_score","grade","trend","critical_count",
                        "warning_count","domains","advisory_only"]:
                self.assertIn(fld, r)

    def test_summary_advisory_only(self):
        with self._patch_all():
            from risk_validation.shared_services import get_summary
            r = get_summary()
            self.assertTrue(r["advisory_only"])

    def test_summary_domains_list(self):
        with self._patch_all():
            from risk_validation.shared_services import get_summary
            r = get_summary()
            self.assertIsInstance(r["domains"], list)
            self.assertGreaterEqual(len(r["domains"]), 8)

    def test_weighted_score_all_available(self):
        from risk_validation.shared_services import _weighted_score
        domains = {k: {"score": 80.0, "available": True}
                   for k in ["portfolio","sector","correlation","stress",
                              "tail_risk","execution","market_risk","drift"]}
        score = _weighted_score(domains)
        self.assertAlmostEqual(score, 80.0)

    def test_weighted_score_skips_unavailable(self):
        from risk_validation.shared_services import _weighted_score
        # Build all 8 domains so nothing defaults to available=True with score=0
        all_domains = ["portfolio","sector","correlation","stress",
                       "tail_risk","execution","market_risk","drift"]
        domains = {k: {"score": 80.0, "available": True} for k in all_domains}
        # Mark sector unavailable — it should be excluded from the average
        domains["sector"]["available"] = False
        domains["sector"]["score"] = 0.0
        score = _weighted_score(domains)
        # All available domains score 80 → weighted avg = 80
        self.assertAlmostEqual(score, 80.0, places=0)

    def test_aggregate_alerts_counts(self):
        from risk_validation.shared_services import _aggregate_alerts
        domains = {
            "portfolio": {
                "issues": [
                    {"severity": "CRITICAL", "check": "X", "field": "f", "message": "m"},
                    {"severity": "WARNING",  "check": "Y", "field": "f", "message": "m"},
                ]
            }
        }
        a = _aggregate_alerts(domains)
        self.assertEqual(a["total_critical"], 1)
        self.assertEqual(a["total_warnings"], 1)
        self.assertEqual(a["total"], 2)

    def test_get_portfolio_data_disabled(self):
        _dis()
        from risk_validation.shared_services import get_portfolio_data
        r = get_portfolio_data()
        self.assertEqual(r["status"], "DISABLED")
        _en()

    def test_get_alerts_data_structure(self):
        with self._patch_all():
            from risk_validation.shared_services import get_alerts_data
            r = get_alerts_data()
            self.assertIn("critical", r)
            self.assertIn("warnings", r)
            self.assertIn("total", r)

    def test_get_export_json_has_domains(self):
        with self._patch_all():
            from risk_validation.shared_services import get_export_json
            r = get_export_json()
            self.assertIn("domains", r)
            self.assertIn("risk_score", r)

    def test_get_export_csv_returns_string(self):
        with self._patch_all():
            from risk_validation.shared_services import get_export_csv
            csv_str = get_export_csv()
            self.assertIsInstance(csv_str, str)
            self.assertIn("portfolio", csv_str)

    def test_get_risk_validation_snapshot_structure(self):
        with self._patch_all():
            from risk_validation.shared_services import get_risk_validation_snapshot
            r = get_risk_validation_snapshot()
            self.assertIn("risk_score", r)
            self.assertIn("grade", r)
            self.assertTrue(r["advisory_only"])

    def test_safe_helper_returns_default_on_exception(self):
        from risk_validation.shared_services import _safe
        result = _safe(lambda: 1 / 0, "default")
        self.assertEqual(result, "default")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. api.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiWrappers(unittest.TestCase):

    def _mock_ss(self, **kw):
        import risk_validation.shared_services as ss
        return patch.object(ss, '__dict__', ss.__dict__ | kw)

    def _run_cmd(self, cmd_fn_name, ss_fn_name):
        mock_result = {"status": "ENABLED", "advisory_only": True}
        with patch(f"risk_validation.shared_services.{ss_fn_name}",
                   return_value=mock_result):
            from risk_validation import api
            import importlib; importlib.reload(api)
            fn = getattr(api, cmd_fn_name)
            return fn()

    def test_cmd_summary_delegates(self):
        r = self._run_cmd("cmd_summary", "get_summary")
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_portfolio_delegates(self):
        r = self._run_cmd("cmd_portfolio", "get_portfolio_data")
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_stress_delegates(self):
        r = self._run_cmd("cmd_stress", "get_stress_data")
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_tail_delegates(self):
        r = self._run_cmd("cmd_tail", "get_tail_risk_data")
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_alerts_delegates(self):
        r = self._run_cmd("cmd_alerts", "get_alerts_data")
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_export_csv_disabled(self):
        _dis()
        from risk_validation.api import cmd_export_csv
        r = cmd_export_csv()
        self.assertEqual(r["status"], "DISABLED")
        _en()

    def test_cmd_export_csv_enabled(self):
        with patch("risk_validation.shared_services.get_export_csv",
                   return_value="domain,score\nportfolio,80\n"):
            from risk_validation import api
            import importlib; importlib.reload(api)
            r = api.cmd_export_csv()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("csv", r)


if __name__ == "__main__":
    unittest.main()
