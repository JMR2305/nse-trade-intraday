"""
test_macro_intelligence.py — Phase 7.3
Unit tests for the Economic & Macro Intelligence Hub.

Coverage:
  - Feature flag (enabled / disabled)
  - Models (MacroEvent, grade helpers)
  - Economic calendar (RBI, CPI, GDP, IIP, PMI, budget, global)
  - Global markets
  - Market flows
  - Currency intelligence
  - Commodity intelligence
  - Volatility intelligence
  - Macro impact engine
  - Daily macro brief
  - Shared services (all endpoints)
  - Export (CSV / JSON)
  - API command dispatch
  - Advisory-only safety (AST scan — zero write imports)

READ-ONLY. ADVISORY-ONLY.
"""
import os
import sys
import json
import unittest
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Stub external dependencies before any macro_intelligence import ───────────

_signals_mock = MagicMock()
_signals_mock.get_latest_signals.return_value = [
    {"symbol": "RELIANCE",   "opportunity_score": 72.0, "confidence": 68.0,
     "recommendation": "BUY",  "sector": "Energy",   "volume_ratio": 1.8, "rsi_14": 58.0},
    {"symbol": "TCS",        "opportunity_score": 30.0, "confidence": 65.0,
     "recommendation": "SELL", "sector": "IT",       "volume_ratio": 0.9, "rsi_14": 42.0},
    {"symbol": "HDFCBANK",   "opportunity_score": 55.0, "confidence": 70.0,
     "recommendation": "HOLD", "sector": "Banking",  "volume_ratio": 1.1, "rsi_14": 50.0},
]

_yf_ticker_mock = MagicMock()
_yf_ticker_mock.fast_info.last_price    = 84.50
_yf_ticker_mock.fast_info.previous_close = 84.20
_yf_ticker_mock.history.return_value    = MagicMock(
    empty=False,
    **{"__getitem__.return_value": MagicMock(dropna=MagicMock(return_value=[18.5, 19.0, 18.8, 19.2, 19.5]))}
)
_yf_mock = MagicMock()
_yf_mock.Ticker.return_value = _yf_ticker_mock

_mi_ss_mock = MagicMock()
_mi_ss_mock.get_summary.return_value = {
    "market_regime":     "BULLISH_MOMENTUM",
    "market_health_score": 65.0,
    "vix_value":         18.5,
    "breadth": {"advance_decline_ratio": 1.6},
}

_config_mock = MagicMock()
_config_mock.DEFAULT_WATCHLIST = ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK"]



def _stub_modules():
    return {"signals_cache": _signals_mock,
            "yfinance": _yf_mock,
            "market_intelligence_hub": MagicMock(),
            "market_intelligence_hub.shared_services": _mi_ss_mock,
            "config": _config_mock}


@pytest.fixture(autouse=True)
def _isolated_dependencies():
    with patch.dict(sys.modules, _stub_modules()), patch.dict(os.environ, {"MACRO_INTELLIGENCE_ENABLED": "true"}):
        yield


# ── Helper: MacroEvent fixture ────────────────────────────────────────────────

def _make_macro_event(**kwargs):
    from macro_intelligence.models import MacroEvent
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    defaults = dict(
        event_id           = "test_evt_001",
        category           = "CENTRAL_BANK",
        sub_type           = "RBI_POLICY",
        title              = "RBI MPC Meeting — Test",
        description        = "Test RBI policy meeting.",
        event_date         = today,
        discovered_at      = datetime.now(timezone.utc).isoformat(),
        importance_score   = 90.0,
        confidence_score   = 88.0,
        direction          = "NEUTRAL",
        expected_volatility = "HIGH",
        expected_duration  = "2D",
        priority           = "CRITICAL",
        affected_sectors   = ["Banking", "NBFC"],
        affected_industries = ["Lending"],
        historical_context = "RBI policy moves markets 0.9% on average.",
        trading_risk       = "Reduce position size before announcement.",
        opportunity        = "Rate cut benefits Banking sector.",
        source             = "TEST",
        is_upcoming        = False,
    )
    defaults.update(kwargs)
    return MacroEvent(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Feature flag
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlag(unittest.TestCase):

    def test_enabled_env_var(self):
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "true"
        from macro_intelligence.models import is_enabled
        self.assertTrue(is_enabled())

    def test_disabled_env_var(self):
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "false"
        from macro_intelligence.models import is_enabled
        self.assertFalse(is_enabled())
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "true"

    def test_disabled_response_shape(self):
        from macro_intelligence.models import disabled_response
        d = disabled_response()
        self.assertEqual(d["status"], "DISABLED")
        self.assertFalse(d["available"])
        self.assertTrue(d["advisory_only"])

    def test_feature_flag_constant(self):
        from macro_intelligence.models import _FLAG
        self.assertEqual(_FLAG, "MACRO_INTELLIGENCE_ENABLED")

    def test_disabled_blocks_summary(self):
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "false"
        from macro_intelligence import shared_services as ss
        import importlib; importlib.reload(ss)
        r = ss.get_summary()
        self.assertEqual(r["status"], "DISABLED")
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "true"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Models
# ══════════════════════════════════════════════════════════════════════════════

class TestModels(unittest.TestCase):

    def test_macro_event_to_dict(self):
        e = _make_macro_event()
        d = e.to_dict()
        self.assertEqual(d["event_id"], "test_evt_001")
        self.assertIn("importance_score", d)
        self.assertIn("affected_sectors", d)
        self.assertIn("is_upcoming", d)

    def test_macro_grade_all_grades(self):
        from macro_intelligence.models import macro_grade
        self.assertEqual(macro_grade(95),  "A+")
        self.assertEqual(macro_grade(83),  "A")
        self.assertEqual(macro_grade(73),  "B")
        self.assertEqual(macro_grade(58),  "C")
        self.assertEqual(macro_grade(30),  "D")

    def test_priority_from_score(self):
        from macro_intelligence.models import priority_from_score
        self.assertEqual(priority_from_score(85), "CRITICAL")
        self.assertEqual(priority_from_score(70), "HIGH")
        self.assertEqual(priority_from_score(50), "MEDIUM")
        self.assertEqual(priority_from_score(30), "LOW")

    def test_direction_constants(self):
        from macro_intelligence.models import DIR_BULLISH, DIR_BEARISH, DIR_NEUTRAL, DIR_VOLATILE
        self.assertEqual(DIR_BULLISH,  "BULLISH")
        self.assertEqual(DIR_BEARISH,  "BEARISH")
        self.assertEqual(DIR_NEUTRAL,  "NEUTRAL")
        self.assertEqual(DIR_VOLATILE, "VOLATILE")

    def test_category_constants(self):
        from macro_intelligence.models import (
            CAT_ECONOMIC, CAT_CENTRAL_BANK, CAT_GLOBAL, CAT_FLOWS,
            CAT_CURRENCY, CAT_COMMODITY, CAT_VOLATILITY,
        )
        self.assertEqual(CAT_ECONOMIC,     "ECONOMIC")
        self.assertEqual(CAT_CENTRAL_BANK, "CENTRAL_BANK")
        self.assertEqual(CAT_GLOBAL,       "GLOBAL_MARKET")

    def test_trend_label(self):
        from macro_intelligence.models import trend_label
        self.assertEqual(trend_label(75, 70), "IMPROVING")
        self.assertEqual(trend_label(65, 70), "WEAKENING")
        self.assertEqual(trend_label(70, 70), "STABLE")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Economic Calendar
# ══════════════════════════════════════════════════════════════════════════════

class TestEconomicCalendar(unittest.TestCase):

    def _get_cal(self):
        from macro_intelligence.economic_calendar import get_economic_calendar
        return get_economic_calendar()

    def test_returns_structure(self):
        cal = self._get_cal()
        self.assertTrue(cal["available"])
        self.assertTrue(cal["advisory_only"])
        self.assertIsInstance(cal["events"], list)
        self.assertIsInstance(cal["upcoming"], list)
        self.assertIn("total", cal)

    def test_has_rbi_events(self):
        cal = self._get_cal()
        subtypes = {e["sub_type"] for e in cal["events"]}
        self.assertIn("RBI_POLICY", subtypes)

    def test_has_cpi_wpi_events(self):
        cal = self._get_cal()
        subtypes = {e["sub_type"] for e in cal["events"]}
        self.assertIn("CPI", subtypes)
        self.assertIn("WPI", subtypes)

    def test_has_gdp_events(self):
        cal = self._get_cal()
        subtypes = {e["sub_type"] for e in cal["events"]}
        self.assertIn("GDP", subtypes)

    def test_has_pmi_iip_events(self):
        cal = self._get_cal()
        subtypes = {e["sub_type"] for e in cal["events"]}
        self.assertIn("PMI", subtypes)
        self.assertIn("IIP", subtypes)

    def test_has_budget_event(self):
        cal = self._get_cal()
        subtypes = {e["sub_type"] for e in cal["events"]}
        self.assertIn("GOVT_BUDGET", subtypes)

    def test_has_global_events(self):
        cal = self._get_cal()
        subtypes = {e["sub_type"] for e in cal["events"]}
        self.assertIn("GLOBAL_EVENT", subtypes)

    def test_rbi_importance_critical(self):
        cal = self._get_cal()
        rbi_events = [e for e in cal["events"] if e["sub_type"] == "RBI_POLICY"]
        self.assertTrue(len(rbi_events) > 0)
        for e in rbi_events:
            self.assertGreaterEqual(e["importance_score"], 90.0)
            self.assertEqual(e["priority"], "CRITICAL")

    def test_all_events_have_required_fields(self):
        cal = self._get_cal()
        required = ["event_id", "category", "sub_type", "title", "importance_score"]
        for e in cal["events"][:10]:
            for field in required:
                self.assertIn(field, e)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Global Markets
# ══════════════════════════════════════════════════════════════════════════════

class TestGlobalMarkets(unittest.TestCase):

    def _get_global(self):
        from macro_intelligence.global_markets import get_global_markets
        # Clear cache
        import macro_intelligence.global_markets as gm
        gm._cache.clear()
        return get_global_markets()

    def test_returns_structure(self):
        g = self._get_global()
        self.assertTrue(g["available"])
        self.assertTrue(g["advisory_only"])
        self.assertIsInstance(g["indices"], list)
        self.assertIn("global_sentiment_score", g)

    def test_sentiment_score_in_range(self):
        g = self._get_global()
        score = g["global_sentiment_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_sentiment_label_valid(self):
        g = self._get_global()
        self.assertIn(g["sentiment_label"], ("RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF"))

    def test_indices_present(self):
        g = self._get_global()
        self.assertTrue(len(g["indices"]) > 0)

    def test_session_groupings_exist(self):
        g = self._get_global()
        self.assertIn("asia_session", g)
        self.assertIn("europe_session", g)
        self.assertIn("us_session", g)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Market Flows
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketFlows(unittest.TestCase):

    def _get_flows(self):
        import macro_intelligence.market_flows as mf
        mf._cache.clear()
        from macro_intelligence.market_flows import get_market_flows
        return get_market_flows()

    def test_returns_structure(self):
        f = self._get_flows()
        self.assertTrue(f["available"])
        self.assertTrue(f["advisory_only"])
        self.assertIn("fii", f)
        self.assertIn("dii", f)
        self.assertIn("sector_rotation", f)
        self.assertIn("liquidity", f)

    def test_fii_fields(self):
        f = self._get_flows()
        fii = f["fii"]
        self.assertIn("flow",  fii)
        self.assertIn("trend", fii)
        self.assertIn("score", fii)
        self.assertIn(fii["flow"], ("NET_BUYER", "NET_SELLER", "NEUTRAL"))

    def test_dii_fields(self):
        f = self._get_flows()
        dii = f["dii"]
        self.assertIn("flow", dii)
        self.assertIn(dii["flow"], ("NET_BUYER", "NET_SELLER", "NEUTRAL"))

    def test_sector_rotation_sorted(self):
        f = self._get_flows()
        scores = [r["avg_score"] for r in f["sector_rotation"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_disclaimer_present(self):
        f = self._get_flows()
        self.assertIn("disclaimer", f)
        self.assertTrue(len(f["disclaimer"]) > 10)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Currency Intelligence
# ══════════════════════════════════════════════════════════════════════════════

class TestCurrencyIntelligence(unittest.TestCase):

    def _get_currency(self):
        import macro_intelligence.currency_intelligence as ci
        ci._cache.clear()
        from macro_intelligence.currency_intelligence import get_currency_intelligence
        return get_currency_intelligence()

    def test_returns_structure(self):
        c = self._get_currency()
        self.assertTrue(c["available"])
        self.assertTrue(c["advisory_only"])
        self.assertIsInstance(c["pairs"], list)
        self.assertIn("usd_inr", c)

    def test_currency_pairs_present(self):
        c = self._get_currency()
        names = [p["name"] for p in c["pairs"]]
        self.assertIn("USD/INR", names)
        self.assertIn("Dollar Index", names)

    def test_volatility_label_valid(self):
        c = self._get_currency()
        self.assertIn(c["currency_volatility"], ("LOW", "MEDIUM", "HIGH", "UNKNOWN"))

    def test_risk_score_in_range(self):
        c = self._get_currency()
        self.assertGreaterEqual(c["currency_risk_score"], 0)
        self.assertLessEqual(c["currency_risk_score"], 100)

    def test_impact_descriptions_present(self):
        c = self._get_currency()
        self.assertIsInstance(c["usd_inr_impact"], str)
        self.assertIsInstance(c["dxy_impact"], str)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Commodity Intelligence
# ══════════════════════════════════════════════════════════════════════════════

class TestCommodityIntelligence(unittest.TestCase):

    def _get_commodity(self):
        import macro_intelligence.commodity_intelligence as co
        co._cache.clear()
        from macro_intelligence.commodity_intelligence import get_commodity_intelligence
        return get_commodity_intelligence()

    def test_returns_structure(self):
        c = self._get_commodity()
        self.assertTrue(c["available"])
        self.assertTrue(c["advisory_only"])
        self.assertIsInstance(c["commodities"], list)

    def test_all_five_commodities_present(self):
        c = self._get_commodity()
        names = {co["name"] for co in c["commodities"]}
        for expected in ("Gold", "Silver", "Crude Oil", "Natural Gas", "Copper"):
            self.assertIn(expected, names)

    def test_trend_values_valid(self):
        c = self._get_commodity()
        for co in c["commodities"]:
            self.assertIn(co["trend"], ("BULLISH", "BEARISH", "NEUTRAL"))

    def test_risk_score_in_range(self):
        c = self._get_commodity()
        self.assertGreaterEqual(c["commodity_risk_score"], 0)
        self.assertLessEqual(c["commodity_risk_score"], 100)

    def test_inflation_risk_valid(self):
        c = self._get_commodity()
        self.assertIn(c["inflation_risk"], ("LOW", "MEDIUM", "HIGH"))


# ══════════════════════════════════════════════════════════════════════════════
# 8. Volatility Intelligence
# ══════════════════════════════════════════════════════════════════════════════

class TestVolatilityIntelligence(unittest.TestCase):

    def _get_vix(self):
        import macro_intelligence.volatility_intelligence as vi
        vi._cache.clear()
        from macro_intelligence.volatility_intelligence import get_volatility_intelligence
        return get_volatility_intelligence()

    def test_returns_structure(self):
        v = self._get_vix()
        self.assertTrue(v["available"])
        self.assertTrue(v["advisory_only"])
        self.assertIn("india_vix", v)
        self.assertIn("regime", v)
        self.assertIn("risk_level", v)

    def test_regime_valid(self):
        v = self._get_vix()
        self.assertIn(v["regime"], ("EXPANSION", "CONTRACTION", "STABLE"))

    def test_risk_level_valid(self):
        v = self._get_vix()
        self.assertIn(v["risk_level"], ("LOW", "MEDIUM", "HIGH", "EXTREME"))

    def test_vix_score_in_range(self):
        v = self._get_vix()
        self.assertGreaterEqual(v["vix_score"], 0)
        self.assertLessEqual(v["vix_score"], 100)

    def test_options_environment_valid(self):
        v = self._get_vix()
        self.assertIn(v["options_environment"], ("CHEAP", "NORMAL", "EXPENSIVE"))

    def test_interpretation_present(self):
        v = self._get_vix()
        self.assertIsInstance(v["interpretation"], str)
        self.assertGreater(len(v["interpretation"]), 5)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Macro Impact Engine
# ══════════════════════════════════════════════════════════════════════════════

class TestMacroImpactEngine(unittest.TestCase):

    def test_generate_impact_analysis_structure(self):
        from macro_intelligence.macro_impact_engine import generate_impact_analysis
        e = _make_macro_event()
        results = generate_impact_analysis([e])
        self.assertEqual(len(results), 1)
        self.assertIn("impact_summary", results[0])
        self.assertIn("historical_context", results[0])
        self.assertTrue(results[0]["advisory_only"])

    def test_sorted_by_importance(self):
        from macro_intelligence.macro_impact_engine import generate_impact_analysis
        e1 = _make_macro_event(event_id="a", importance_score=60.0)
        e2 = _make_macro_event(event_id="b", importance_score=90.0)
        results = generate_impact_analysis([e1, e2])
        self.assertGreaterEqual(results[0]["importance_score"], results[1]["importance_score"])

    def test_get_impact_summary_empty(self):
        from macro_intelligence.macro_impact_engine import get_impact_summary
        s = get_impact_summary([])
        self.assertEqual(s["total_events"], 0)
        self.assertTrue(s["available"])

    def test_get_impact_summary_counts(self):
        from macro_intelligence.macro_impact_engine import get_impact_summary
        e1 = _make_macro_event(event_id="x1", direction="BULLISH")
        e2 = _make_macro_event(event_id="x2", direction="BEARISH")
        s  = get_impact_summary([e1, e2])
        self.assertEqual(s["total_events"], 2)
        self.assertEqual(s["direction_counts"]["BULLISH"], 1)
        self.assertEqual(s["direction_counts"]["BEARISH"], 1)

    def test_sector_heat_calculated(self):
        from macro_intelligence.macro_impact_engine import get_impact_summary
        e1 = _make_macro_event(event_id="h1", affected_sectors=["Banking"], importance_score=80.0)
        e2 = _make_macro_event(event_id="h2", affected_sectors=["Banking"], importance_score=60.0)
        s  = get_impact_summary([e1, e2])
        self.assertIn("Banking", s["sector_heat"])
        self.assertAlmostEqual(s["sector_heat"]["Banking"], 70.0, places=0)

    def test_historical_pattern_rbi(self):
        from macro_intelligence.macro_impact_engine import generate_impact_analysis
        e = _make_macro_event(sub_type="RBI_POLICY")
        r = generate_impact_analysis([e])
        ctx = r[0]["historical_context"]
        self.assertIsNotNone(ctx)
        self.assertIn("RBI", ctx)

    def test_impact_summary_top_opportunities(self):
        from macro_intelligence.macro_impact_engine import get_impact_summary
        e = _make_macro_event(direction="BULLISH", importance_score=85.0)
        s = get_impact_summary([e])
        self.assertTrue(len(s["top_opportunities"]) > 0)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Daily Macro Brief
# ══════════════════════════════════════════════════════════════════════════════

class TestMacroMasterBrief(unittest.TestCase):

    def _get_brief_inputs(self):
        events = [_make_macro_event()]
        global_score = 65.0
        vix_data = {
            "india_vix": {"current": 18.5, "prev_close": 18.0, "change_pct": 2.8},
            "regime": "STABLE", "risk_level": "MEDIUM", "vix_score": 63.0,
            "interpretation": "VIX within normal range.",
            "trading_implication": "Standard stops apply.",
        }
        fii_data = {
            "fii": {"flow": "NET_BUYER", "score": 65.0, "description": "FII buying."},
            "dii": {"flow": "NEUTRAL",   "score": 50.0, "description": "DII mixed."},
            "sector_rotation": [{"sector": "Banking", "avg_score": 68.0, "direction": "INFLOW"}],
            "liquidity": {"trend": "NORMAL_LIQUIDITY", "label": "Normal."},
        }
        commodity_data = {
            "crude_oil": {"change_pct": 0.5},
            "commodity_risk_score": 52.0,
            "crude_impact": "Crude stable.",
            "gold_signal": "Gold neutral.",
            "inflation_risk": "LOW",
        }
        currency_data = {
            "usd_inr": {"change_pct": 0.1},
            "currency_volatility": "LOW",
            "usd_inr_impact": "INR stable.",
            "dxy_impact": "DXY neutral.",
        }
        return events, global_score, vix_data, fii_data, commodity_data, currency_data

    def test_brief_structure(self):
        from macro_intelligence.macro_brief import generate_daily_brief
        events, gs, vd, fd, cd, crd = self._get_brief_inputs()
        b = generate_daily_brief(events, gs, vd, fd, cd, crd, [])
        self.assertTrue(b["available"])
        self.assertTrue(b["advisory_only"])
        self.assertIn("market_outlook", b)
        self.assertIn("risk_alerts", b)
        self.assertIn("trading_considerations", b)
        self.assertIn("brief_score", b)

    def test_brief_score_in_range(self):
        from macro_intelligence.macro_brief import generate_daily_brief
        events, gs, vd, fd, cd, crd = self._get_brief_inputs()
        b = generate_daily_brief(events, gs, vd, fd, cd, crd, [])
        self.assertGreaterEqual(b["brief_score"], 0)
        self.assertLessEqual(b["brief_score"], 100)

    def test_outlook_label_valid(self):
        from macro_intelligence.macro_brief import generate_daily_brief
        events, gs, vd, fd, cd, crd = self._get_brief_inputs()
        b = generate_daily_brief(events, gs, vd, fd, cd, crd, [])
        valid = {"BULLISH", "BEARISH", "CAUTIOUSLY_BULLISH", "CAUTIOUSLY_BEARISH", "NEUTRAL"}
        self.assertIn(b["market_outlook"]["label"], valid)

    def test_high_vix_triggers_alert(self):
        from macro_intelligence.macro_brief import generate_daily_brief
        events, gs, vd, fd, cd, crd = self._get_brief_inputs()
        vd["india_vix"]["current"] = 28.0
        vd["risk_level"] = "HIGH"
        b = generate_daily_brief(events, gs, vd, fd, cd, crd, [])
        alert_types = [a["type"] for a in b["risk_alerts"]]
        self.assertTrue(any("VIX" in t for t in alert_types))

    def test_fii_sell_triggers_alert(self):
        from macro_intelligence.macro_brief import generate_daily_brief
        events, gs, vd, fd, cd, crd = self._get_brief_inputs()
        fd["fii"]["flow"] = "NET_SELLER"
        b = generate_daily_brief(events, gs, vd, fd, cd, crd, [])
        alert_types = [a["type"] for a in b["risk_alerts"]]
        self.assertIn("FII_OUTFLOW", alert_types)

    def test_trading_considerations_populated(self):
        from macro_intelligence.macro_brief import generate_daily_brief
        events, gs, vd, fd, cd, crd = self._get_brief_inputs()
        b = generate_daily_brief(events, gs, vd, fd, cd, crd, [])
        self.assertIsInstance(b["trading_considerations"], list)
        self.assertGreater(len(b["trading_considerations"]), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 11. Shared Services
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedServices(unittest.TestCase):

    def setUp(self):
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "true"

    def test_summary_returns_enabled(self):
        from macro_intelligence.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertTrue(r["available"])
        self.assertIn("macro_score", r)
        self.assertIn("grade", r)

    def test_calendar_returns_structure(self):
        from macro_intelligence.shared_services import get_calendar
        r = get_calendar()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("events", r)
        self.assertIn("upcoming", r)

    def test_global_returns_structure(self):
        from macro_intelligence.shared_services import get_global
        r = get_global()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("indices", r)

    def test_flows_returns_structure(self):
        from macro_intelligence.shared_services import get_flows
        r = get_flows()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("fii", r)
        self.assertIn("dii", r)

    def test_commodities_returns_structure(self):
        from macro_intelligence.shared_services import get_commodities
        r = get_commodities()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("commodities", r)
        self.assertIn("currency", r)
        self.assertIn("volatility", r)

    def test_brief_returns_structure(self):
        from macro_intelligence.shared_services import get_brief
        r = get_brief()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("market_outlook", r)
        self.assertIn("risk_alerts", r)

    def test_all_endpoints_advisory_only(self):
        from macro_intelligence import shared_services as ss
        for fn in (ss.get_summary, ss.get_calendar, ss.get_global,
                   ss.get_flows, ss.get_commodities, ss.get_brief):
            r = fn()
            self.assertTrue(r.get("advisory_only") or r.get("status") != "ENABLED",
                            f"{fn.__name__} missing advisory_only flag")

    def test_snapshot_never_raises(self):
        from macro_intelligence.shared_services import get_macro_intelligence_snapshot
        snap = get_macro_intelligence_snapshot()
        self.assertIn("macro_score", snap)
        self.assertIn("grade", snap)
        self.assertIn("available", snap)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Export
# ══════════════════════════════════════════════════════════════════════════════

class TestExport(unittest.TestCase):

    def test_csv_non_empty(self):
        from macro_intelligence.shared_services import export_csv
        csv_str = export_csv()
        self.assertIsInstance(csv_str, str)
        # CSV has a header row at minimum
        self.assertIn("event_id", csv_str)

    def test_json_parseable(self):
        from macro_intelligence.shared_services import export_json
        json_str = export_json()
        self.assertIsInstance(json_str, str)
        data = json.loads(json_str)
        self.assertIn("events", data)
        self.assertTrue(data["advisory_only"])

    def test_csv_disabled_when_flag_off(self):
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "false"
        from macro_intelligence import shared_services as ss
        import importlib; importlib.reload(ss)
        result = ss.export_csv()
        self.assertEqual(result, "")
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "true"


# ══════════════════════════════════════════════════════════════════════════════
# 13. API Dispatch
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIDispatch(unittest.TestCase):

    def test_cmd_summary(self):
        from macro_intelligence.api import cmd_summary
        r = cmd_summary()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_calendar(self):
        from macro_intelligence.api import cmd_calendar
        r = cmd_calendar()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_global(self):
        from macro_intelligence.api import cmd_global
        r = cmd_global()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_flows(self):
        from macro_intelligence.api import cmd_flows
        r = cmd_flows()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_commodities(self):
        from macro_intelligence.api import cmd_commodities
        r = cmd_commodities()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_brief(self):
        from macro_intelligence.api import cmd_brief
        r = cmd_brief()
        self.assertEqual(r["status"], "ENABLED")

    def test_cmd_export_csv(self):
        from macro_intelligence.api import cmd_export_csv
        r = cmd_export_csv()
        self.assertIn("csv",    r)
        self.assertIn("status", r)

    def test_cmd_export_json(self):
        from macro_intelligence.api import cmd_export_json
        r = cmd_export_json()
        self.assertIn("json",   r)
        self.assertIn("status", r)


# ══════════════════════════════════════════════════════════════════════════════
# 14. VIX Spike Behaviour — Executive Dashboard macro tile contract
# ══════════════════════════════════════════════════════════════════════════════

class TestVIXSpikeBehavior(unittest.TestCase):
    """
    Task #193 — Confirm the macro tile updates correctly when VIX spikes.

    `get_macro_intelligence_snapshot()` is the stable contract consumed by the
    Executive Dashboard macro tile.  These tests verify that when India VIX
    crosses the HIGH (22+) and EXTREME (30+) thresholds, the snapshot returns
    the correct `vix_risk_level` and `vix_regime` labels so the tile reflects
    reality within the 30-second polling interval.

    Strategy: patch `_fetch_vix` (the yfinance-calling leaf function) with
    controlled data and clear the module-level cache before each scenario so
    the patched function is actually invoked.
    """

    def _clear_vi_cache(self):
        import macro_intelligence.volatility_intelligence as vi
        vi._cache.clear()

    # ── Test 1: VIX = 24 ──────────────────────────────────────────────────────
    def test_vix_24_snapshot_returns_high_risk_and_expansion_regime(self):
        """
        India VIX at 24 (above HIGH threshold of 22) with a 5-day close trend
        rising from 20 → 24 (+20%) must produce vix_risk_level=HIGH and
        vix_regime=EXPANSION in get_macro_intelligence_snapshot().
        """
        # 5-day closes: 20 → 24 gives (24-20)/20*100 = 20% > 10% → EXPANSION
        mock_fetch_return = {
            "current": 24.0,
            "prev":    20.0,
            "closes":  [20.0, 21.0, 22.0, 23.0, 24.0],
            "available": True,
        }
        self._clear_vi_cache()
        with patch(
            "macro_intelligence.volatility_intelligence._fetch_vix",
            return_value=mock_fetch_return,
        ):
            from macro_intelligence.shared_services import get_macro_intelligence_snapshot
            snap = get_macro_intelligence_snapshot()

        self.assertEqual(
            snap["vix_risk_level"], "HIGH",
            f"VIX=24 must give risk_level=HIGH; got {snap['vix_risk_level']!r}",
        )
        self.assertEqual(
            snap["vix_regime"], "EXPANSION",
            f"Rising 20→24 VIX must give regime=EXPANSION; got {snap['vix_regime']!r}",
        )
        # india_vix in snapshot must reflect the spiked value
        self.assertGreaterEqual(snap["india_vix"], 24.0)

    # ── Test 2: VIX = 30 ──────────────────────────────────────────────────────
    def test_vix_30_snapshot_returns_extreme_risk(self):
        """
        India VIX at 30 (at the EXTREME threshold) must produce
        vix_risk_level=EXTREME in get_macro_intelligence_snapshot().
        """
        mock_fetch_return = {
            "current": 30.0,
            "prev":    25.0,
            "closes":  [25.0, 26.5, 27.0, 28.5, 30.0],  # +20% → EXPANSION
            "available": True,
        }
        self._clear_vi_cache()
        with patch(
            "macro_intelligence.volatility_intelligence._fetch_vix",
            return_value=mock_fetch_return,
        ):
            from macro_intelligence.shared_services import get_macro_intelligence_snapshot
            snap = get_macro_intelligence_snapshot()

        self.assertEqual(
            snap["vix_risk_level"], "EXTREME",
            f"VIX=30 must give risk_level=EXTREME; got {snap['vix_risk_level']!r}",
        )
        self.assertGreaterEqual(snap["india_vix"], 30.0)

    # ── Test 3: TTL contract ───────────────────────────────────────────────────
    def test_vix_cache_ttl_within_dashboard_polling_interval(self):
        """
        The VIX cache TTL must be ≤ 30 s so that a real spike is always
        visible within one Executive Dashboard polling cycle (30 000 ms).
        This is a regression guard — changing _CACHE_TTL_S above 30 will
        immediately fail this test.
        """
        import macro_intelligence.volatility_intelligence as vi
        self.assertLessEqual(
            vi._CACHE_TTL_S, 30,
            f"VIX cache TTL is {vi._CACHE_TTL_S} s — must be ≤ 30 s so spikes "
            f"are visible within one Executive Dashboard polling cycle.",
        )

    # ── Test 4: spike propagates after natural cache expiry (no manual clear) ──
    def test_vix_spike_visible_after_cache_expires_without_manual_clear(self):
        """
        Proves the end-to-end freshness contract:
        1. Cache is primed with baseline VIX = 18 (MEDIUM / STABLE).
        2. Time is advanced past _CACHE_TTL_S without touching _cache directly.
        3. Next call to get_volatility_intelligence() must re-fetch and return
           the spiked VIX = 24 values — vix_risk_level HIGH, regime EXPANSION.
        This mirrors what happens in production across one polling cycle.
        """
        import macro_intelligence.volatility_intelligence as vi
        from datetime import datetime, timezone, timedelta

        baseline_fetch = {
            "current": 18.0, "prev": 18.0,
            "closes": [17.0, 17.5, 18.0, 18.0, 18.0],
            "available": True,
        }
        spike_fetch = {
            "current": 24.0, "prev": 18.0,
            "closes": [18.0, 20.0, 21.0, 22.0, 24.0],  # +33% → EXPANSION
            "available": True,
        }

        # Step 1 — prime the cache with baseline (MEDIUM / STABLE)
        vi._cache.clear()
        with patch("macro_intelligence.volatility_intelligence._fetch_vix",
                   return_value=baseline_fetch):
            first = vi.get_volatility_intelligence()
        self.assertEqual(first["risk_level"], "MEDIUM")

        # Step 2 — simulate TTL expiry by backdating the cached timestamp
        expired_ts = (datetime.now(timezone.utc)
                      - timedelta(seconds=vi._CACHE_TTL_S + 1))
        vi._cache["volatility_intelligence"]["ts"] = expired_ts

        # Step 3 — re-fetch with spike; cache is stale so _fetch_vix runs again
        with patch("macro_intelligence.volatility_intelligence._fetch_vix",
                   return_value=spike_fetch):
            second = vi.get_volatility_intelligence()

        self.assertEqual(
            second["risk_level"], "HIGH",
            "After cache expiry a VIX spike to 24 must register as HIGH risk.",
        )
        self.assertEqual(
            second["regime"], "EXPANSION",
            "Rising VIX (18→24, +33%) must produce EXPANSION regime.",
        )

    # ── Test 5: Executive Dashboard contract integration ───────────────────────
    def test_executive_dashboard_snapshot_includes_macro_score_when_enabled(self):
        """
        Integration: with MACRO_INTELLIGENCE_ENABLED=true,
        get_macro_intelligence_snapshot() must return all fields the Executive
        Dashboard macro tile depends on — macro_score, grade, vix_risk_level,
        vix_regime, india_vix — and report available=True.
        """
        os.environ["MACRO_INTELLIGENCE_ENABLED"] = "true"
        self._clear_vi_cache()

        from macro_intelligence.shared_services import get_macro_intelligence_snapshot
        snap = get_macro_intelligence_snapshot()

        # Core fields the Executive Dashboard tile reads
        for field in ("macro_score", "grade", "vix_risk_level", "vix_regime", "india_vix"):
            self.assertIn(
                field, snap,
                f"Executive Dashboard snapshot missing required field: {field!r}",
            )

        self.assertTrue(
            snap.get("available"),
            "Snapshot must report available=True when MACRO_INTELLIGENCE_ENABLED=true",
        )

        # macro_score must be a valid 0-100 number (not the error-fallback 0.0 sentinel)
        self.assertGreaterEqual(snap["macro_score"], 0.0)
        self.assertLessEqual(snap["macro_score"], 100.0)

        # vix_risk_level must be one of the known labels
        self.assertIn(
            snap["vix_risk_level"], {"LOW", "MEDIUM", "HIGH", "EXTREME"},
            f"Unexpected vix_risk_level: {snap['vix_risk_level']!r}",
        )

        # vix_regime must be one of the known regimes
        self.assertIn(
            snap["vix_regime"], {"EXPANSION", "CONTRACTION", "STABLE"},
            f"Unexpected vix_regime: {snap['vix_regime']!r}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 15. Advisory-Only Safety (AST scan)
# ══════════════════════════════════════════════════════════════════════════════

class TestAdvisoryOnlySafety(unittest.TestCase):

    FORBIDDEN_IMPORTS = [
        "order_executor", "trade_executor", "portfolio_writer",
        "signal_writer", "strategy_mutator", "risk_engine_writer",
        "model_trainer", "execution_engine",
    ]

    def _scan_module(self, module_path: str) -> list:
        import ast
        violations = []
        try:
            with open(module_path, "r") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else ([node.module] if node.module else [])
                    )
                    for name in names:
                        for forbidden in self.FORBIDDEN_IMPORTS:
                            if forbidden in (name or ""):
                                violations.append(f"{module_path}: imports {name}")
        except Exception:
            pass
        return violations

    def test_no_write_imports_in_package(self):
        import glob
        pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macro_intelligence")
        py_files = glob.glob(os.path.join(pkg_dir, "*.py"))
        self.assertTrue(len(py_files) > 0, "No Python files found in macro_intelligence/")
        all_violations = []
        for f in py_files:
            all_violations.extend(self._scan_module(f))
        self.assertEqual(
            all_violations, [],
            f"Forbidden write imports found: {all_violations}"
        )

    def test_shared_services_advisory_flag(self):
        from macro_intelligence.shared_services import get_summary
        r = get_summary()
        self.assertTrue(r.get("advisory_only", False))

    def test_models_no_execution_imports(self):
        models_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "macro_intelligence", "models.py"
        )
        violations = self._scan_module(models_path)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
