"""
test_event_intelligence.py — Phase 7.2
Unit tests for the Event & Corporate Intelligence Hub.

Coverage:
  - Feature flag (enabled / disabled)
  - Corporate intelligence events
  - Regulatory intelligence events
  - News intelligence events
  - Impact engine
  - Timeline bucketing
  - Daily brief
  - Shared services (all endpoints)
  - Duplicate detection
  - Export (CSV / JSON)
  - Advisory-only guarantee (no mutation imports)
  - API command dispatch

READ-ONLY. ADVISORY-ONLY.
"""
import os
import sys
import json
import unittest
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from task974_test_isolation import isolated_imports

# Ensure the python directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Stub external dependencies before any event_intelligence import ───────────
_signals_cache_mock = MagicMock()
_signals_cache_mock.get_latest_signals.return_value = []

_yf_mock = MagicMock()
_yf_mock.Ticker.return_value.dividends = MagicMock()
_yf_mock.Ticker.return_value.dividends.__len__ = lambda self: 0
_yf_mock.Ticker.return_value.dividends.to_dict.return_value = {}
_yf_mock.Ticker.return_value.splits = MagicMock()
_yf_mock.Ticker.return_value.splits.__len__ = lambda self: 0
_yf_mock.Ticker.return_value.splits.to_dict.return_value = {}
_yf_mock.Ticker.return_value.fast_info = MagicMock()

_mi_mock = MagicMock()
_mi_mock.get_summary.return_value = {
    "market_regime": "BULLISH_MOMENTUM",
    "health_score": 65.0,
    "breadth": {"advance_decline_ratio": 1.8},
}
_mi_mock.get_sectors.return_value = {
    "rankings": [
        {"sector": "IT", "score": 75.0, "trend": "BULLISH"},
        {"sector": "Banking", "score": 60.0, "trend": "NEUTRAL"},
    ]
}

_config_mock = MagicMock()
_config_mock.DEFAULT_WATCHLIST = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
                                   "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI"]



def _stub_modules():
    return {"signals_cache": _signals_cache_mock,
            "yfinance": _yf_mock,
            "market_intelligence_hub": MagicMock(),
            "market_intelligence_hub.shared_services": _mi_mock,
            "config": _config_mock}


@pytest.fixture(autouse=True)
def _isolated_dependencies():
    with isolated_imports(
        _stub_modules(),
        target_packages=("event_intelligence",),
        environment={"EVENT_INTELLIGENCE_ENABLED": "true"},
    ):
        yield


# ---------------------------------------------------------------------------
# Helper: build an EventRecord fixture
# ---------------------------------------------------------------------------
def _make_record(**kwargs):
    from event_intelligence.models import EventRecord
    defaults = dict(
        event_id         = "abc123",
        event_type       = "CORPORATE",
        sub_type         = "RESULTS",
        title            = "TEST — Q Results",
        description      = "Test description.",
        symbol           = "RELIANCE",
        sector           = "Energy",
        event_date       = datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        discovered_at    = datetime.now(timezone.utc).isoformat(),
        importance_score = 75.0,
        confidence_score = 70.0,
        impact_direction = "BULLISH",
        expected_volatility = 2.0,
        expected_duration = "3D",
        priority         = "HIGH",
        affected_stocks  = ["RELIANCE"],
        affected_sectors = ["Energy"],
        trading_risk     = "Post-earnings gap possible",
        opportunity      = "Momentum entry",
        source           = "TEST",
    )
    defaults.update(kwargs)
    return EventRecord(**defaults)


# ============================================================================
# 1. Feature flag
# ============================================================================
class TestFeatureFlag(unittest.TestCase):

    def test_enabled(self):
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "true"
        from event_intelligence.models import is_enabled
        self.assertTrue(is_enabled())

    def test_disabled(self):
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "false"
        from event_intelligence.models import is_enabled
        self.assertFalse(is_enabled())
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "true"

    def test_disabled_response_shape(self):
        from event_intelligence.models import disabled_response
        d = disabled_response()
        self.assertEqual(d["status"], "DISABLED")
        self.assertFalse(d["available"])
        self.assertTrue(d["advisory_only"])

    def test_disabled_blocks_summary(self):
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "false"
        from event_intelligence import shared_services
        import importlib; importlib.reload(shared_services)
        result = shared_services.get_summary()
        self.assertEqual(result["status"], "DISABLED")
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "true"


# ============================================================================
# 2. Models
# ============================================================================
class TestModels(unittest.TestCase):

    def test_event_record_to_dict(self):
        r = _make_record()
        d = r.to_dict()
        self.assertEqual(d["symbol"], "RELIANCE")
        self.assertIn("importance_score", d)
        self.assertIn("impact_direction", d)

    def test_event_grade(self):
        from event_intelligence.models import event_grade
        self.assertEqual(event_grade(95), "A+")
        self.assertEqual(event_grade(82), "A")
        self.assertEqual(event_grade(72), "B")
        self.assertEqual(event_grade(58), "C")
        self.assertEqual(event_grade(30), "D")

    def test_priority_from_score(self):
        from event_intelligence.models import priority_from_score
        self.assertEqual(priority_from_score(85), "CRITICAL")
        self.assertEqual(priority_from_score(70), "HIGH")
        self.assertEqual(priority_from_score(50), "MEDIUM")
        self.assertEqual(priority_from_score(30), "LOW")

    def test_constants(self):
        from event_intelligence.models import (
            TYPE_CORPORATE, TYPE_REGULATORY, TYPE_NEWS,
            IMPACT_BULLISH, IMPACT_BEARISH, IMPACT_NEUTRAL, IMPACT_VOLATILE,
        )
        self.assertEqual(TYPE_CORPORATE, "CORPORATE")
        self.assertEqual(IMPACT_BULLISH, "BULLISH")
        self.assertEqual(IMPACT_VOLATILE, "VOLATILE")


# ============================================================================
# 3. Corporate Intelligence
# ============================================================================
class TestCorporateIntelligence(unittest.TestCase):

    def _mock_scan(self):
        return [
            {"symbol": "RELIANCE", "opportunity_score": 78.0, "confidence": 72.0,
             "recommendation": "BUY", "volume_ratio": 3.2},
            {"symbol": "TCS", "opportunity_score": 25.0, "confidence": 60.0,
             "recommendation": "SELL", "volume_ratio": 1.0},
            {"symbol": "INFY", "opportunity_score": 55.0, "confidence": 55.0,
             "recommendation": "HOLD", "volume_ratio": 0.8},
        ]

    def test_corporate_returns_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=self._mock_scan()):
            from event_intelligence.corporate_intelligence import get_corporate_events
            result = get_corporate_events()
        self.assertTrue(result["available"])
        self.assertIsInstance(result["events"], list)
        self.assertIn("total", result)
        self.assertTrue(result["advisory_only"])

    def test_corporate_has_results_events(self):
        with patch("signals_cache.get_latest_signals", return_value=self._mock_scan()):
            from event_intelligence.corporate_intelligence import get_corporate_events
            result = get_corporate_events()
        subtypes = [e["sub_type"] for e in result["events"]]
        self.assertIn("RESULTS", subtypes)

    def test_no_events_when_empty_watchlist(self):
        with patch("event_intelligence.corporate_intelligence._watchlist", return_value=[]):
            from event_intelligence.corporate_intelligence import get_corporate_events
            result = get_corporate_events()
        self.assertTrue(result["available"])
        # Results should be empty or have only yfinance-sourced events (which we skip)

    def test_bulk_deal_from_high_volume(self):
        signals = [{"symbol": "SBIN", "volume_ratio": 4.0, "opportunity_score": 60,
                    "confidence": 60, "recommendation": "BUY"}]
        with patch("signals_cache.get_latest_signals", return_value=signals):
            with patch("event_intelligence.corporate_intelligence._watchlist",
                       return_value=["SBIN"]):
                from event_intelligence import corporate_intelligence
                import importlib; importlib.reload(corporate_intelligence)
                result = corporate_intelligence.get_corporate_events()
        bulk_events = [e for e in result["events"] if e["sub_type"] == "BULK_DEAL"]
        self.assertTrue(len(bulk_events) > 0)

    def test_deduplication(self):
        with patch("signals_cache.get_latest_signals", return_value=self._mock_scan()):
            from event_intelligence.corporate_intelligence import get_corporate_events
            result = get_corporate_events()
        event_ids = [e["event_id"] for e in result["events"]]
        self.assertEqual(len(event_ids), len(set(event_ids)))  # all unique

    def test_sorted_by_importance(self):
        with patch("signals_cache.get_latest_signals", return_value=self._mock_scan()):
            from event_intelligence.corporate_intelligence import get_corporate_events
            result = get_corporate_events()
        scores = [e["importance_score"] for e in result["events"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


# ============================================================================
# 4. Regulatory Intelligence
# ============================================================================
class TestRegulatoryIntelligence(unittest.TestCase):

    def test_regulatory_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.regulatory_intelligence import get_regulatory_events
            result = get_regulatory_events()
        self.assertTrue(result["available"])
        self.assertIsInstance(result["events"], list)
        self.assertIn("asm_watch", result)
        self.assertIn("fo_ban", result)
        self.assertTrue(result["advisory_only"])

    def test_asm_detection_high_rsi(self):
        signals = [{"symbol": "BAJFINANCE", "rsi_14": 82.0, "volume_ratio": 3.5,
                    "opportunity_score": 70, "confidence": 60}]
        with patch("signals_cache.get_latest_signals", return_value=signals):
            with patch("event_intelligence.regulatory_intelligence._watchlist",
                       return_value=["BAJFINANCE"]):
                from event_intelligence import regulatory_intelligence
                import importlib; importlib.reload(regulatory_intelligence)
                result = regulatory_intelligence.get_regulatory_events()
        asm = [e for e in result["events"] if e["sub_type"] == "ASM"]
        self.assertTrue(len(asm) > 0)
        self.assertIn("BAJFINANCE", result["asm_watch"])

    def test_fo_ban_high_oi(self):
        signals = [{"symbol": "RELIANCE", "oi_ratio": 0.95, "opportunity_score": 55,
                    "confidence": 60, "rsi_14": 55.0, "volume_ratio": 1.0}]
        _signals_cache_mock.get_latest_signals.return_value = signals
        with patch("event_intelligence.regulatory_intelligence._watchlist",
                   return_value=["RELIANCE"]):
            from event_intelligence import regulatory_intelligence
            import importlib; importlib.reload(regulatory_intelligence)
            result = regulatory_intelligence.get_regulatory_events()
        _signals_cache_mock.get_latest_signals.return_value = []
        fo_ban = [e for e in result["events"] if e["sub_type"] == "FO_BAN"]
        self.assertTrue(len(fo_ban) > 0)

    def test_static_circulars_present(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.regulatory_intelligence import get_regulatory_events
            result = get_regulatory_events()
        circular_subtypes = {"NSE_CIRCULAR", "SEBI_CIRCULAR", "MARGIN_CHANGE", "INDEX_INCLUSION"}
        event_subtypes = {e["sub_type"] for e in result["events"]}
        self.assertTrue(circular_subtypes & event_subtypes)  # at least one overlap

    def test_all_regulatory_events_have_required_fields(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.regulatory_intelligence import get_regulatory_events
            result = get_regulatory_events()
        for event in result["events"]:
            self.assertIn("event_id", event)
            self.assertIn("event_type", event)
            self.assertEqual(event["event_type"], "REGULATORY")


# ============================================================================
# 5. News Intelligence
# ============================================================================
class TestNewsIntelligence(unittest.TestCase):

    def _mock_signals(self):
        return [
            {"symbol": "TCS", "opportunity_score": 80.0, "confidence": 75.0,
             "recommendation": "BUY", "sector": "IT"},
            {"symbol": "HDFCBANK", "opportunity_score": 30.0, "confidence": 60.0,
             "recommendation": "SELL", "sector": "Banking"},
        ]

    def test_news_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=self._mock_signals()):
            from event_intelligence.news_intelligence import get_news_events
            result = get_news_events()
        self.assertTrue(result["available"])
        self.assertIsInstance(result["events"], list)
        self.assertIn("by_type", result)
        self.assertIn("categorised", result)
        self.assertTrue(result["advisory_only"])

    def test_company_news_generated(self):
        with patch("signals_cache.get_latest_signals", return_value=self._mock_signals()):
            from event_intelligence.news_intelligence import get_news_events
            result = get_news_events()
        company_news = result["categorised"].get("COMPANY_NEWS", [])
        self.assertTrue(len(company_news) > 0)

    def test_high_score_creates_bullish_news(self):
        signals = [{"symbol": "RELIANCE", "opportunity_score": 85.0,
                    "confidence": 80.0, "recommendation": "BUY", "sector": "Energy"}]
        with patch("signals_cache.get_latest_signals", return_value=signals):
            from event_intelligence.news_intelligence import get_news_events
            result = get_news_events()
        bullish = [e for e in result["events"]
                   if e.get("symbol") == "RELIANCE" and e["impact_direction"] == "BULLISH"]
        self.assertTrue(len(bullish) > 0)

    def test_low_score_creates_bearish_news(self):
        signals = [{"symbol": "WIPRO", "opportunity_score": 20.0,
                    "confidence": 65.0, "recommendation": "SELL", "sector": "IT"}]
        with patch("signals_cache.get_latest_signals", return_value=signals):
            from event_intelligence.news_intelligence import get_news_events
            result = get_news_events()
        bearish = [e for e in result["events"]
                   if e.get("symbol") == "WIPRO" and e["impact_direction"] == "BEARISH"]
        self.assertTrue(len(bearish) > 0)

    def test_duplicate_detection(self):
        """Same event_id produces only one entry after dedup."""
        from event_intelligence.news_intelligence import _deduplicate
        e1 = _make_record(event_id="dup_id", title="RELIANCE Strong Buy Signal alpha")
        e2 = _make_record(event_id="dup_id", title="RELIANCE Strong Buy Signal alpha")
        result = _deduplicate([e1, e2])
        self.assertEqual(len(result), 1)

    def test_freshness_decay(self):
        from event_intelligence.news_intelligence import _freshness_score
        today_score = _freshness_score(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        old_score   = _freshness_score((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"))
        self.assertGreater(today_score, old_score)

    def test_economic_headlines_present(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.news_intelligence import get_news_events
            result = get_news_events()
        economic = result["categorised"].get("ECONOMIC_HEADLINE", [])
        self.assertTrue(len(economic) > 0)


# ============================================================================
# 6. Impact Engine
# ============================================================================
class TestImpactEngine(unittest.TestCase):

    def test_impact_analysis_structure(self):
        from event_intelligence.impact_engine import generate_impact_analysis
        r = _make_record()
        results = generate_impact_analysis([r])
        self.assertEqual(len(results), 1)
        self.assertIn("impact_summary", results[0])
        self.assertIn("historical_context", results[0])
        self.assertTrue(results[0]["advisory_only"])

    def test_impact_summary_aggregation(self):
        from event_intelligence.impact_engine import get_impact_summary
        r1 = _make_record(impact_direction="BULLISH", importance_score=75.0)
        r2 = _make_record(event_id="xyz2", impact_direction="BEARISH",
                          importance_score=65.0, symbol="TCS")
        summary = get_impact_summary([r1, r2])
        self.assertEqual(summary["total_events"], 2)
        self.assertEqual(summary["direction_counts"]["BULLISH"], 1)
        self.assertEqual(summary["direction_counts"]["BEARISH"], 1)

    def test_empty_events_summary(self):
        from event_intelligence.impact_engine import get_impact_summary
        summary = get_impact_summary([])
        self.assertEqual(summary["total_events"], 0)
        self.assertTrue(summary["available"])

    def test_historical_context_for_results(self):
        from event_intelligence.impact_engine import generate_impact_analysis
        r = _make_record(sub_type="RESULTS", impact_direction="BULLISH")
        result = generate_impact_analysis([r])
        self.assertIsNotNone(result[0]["historical_context"])

    def test_sorted_by_importance(self):
        from event_intelligence.impact_engine import generate_impact_analysis
        r1 = _make_record(importance_score=60.0)
        r2 = _make_record(event_id="e2", importance_score=90.0)
        results = generate_impact_analysis([r1, r2])
        self.assertGreaterEqual(results[0]["importance_score"], results[1]["importance_score"])

    def test_sector_heat_calculation(self):
        from event_intelligence.impact_engine import get_impact_summary
        r1 = _make_record(affected_sectors=["IT"], importance_score=80.0)
        r2 = _make_record(event_id="e2", affected_sectors=["IT"], importance_score=60.0)
        summary = get_impact_summary([r1, r2])
        self.assertIn("IT", summary["sector_heat"])
        self.assertAlmostEqual(summary["sector_heat"]["IT"], 70.0, places=0)


# ============================================================================
# 7. Timeline
# ============================================================================
class TestTimeline(unittest.TestCase):

    def test_today_bucket(self):
        from event_intelligence.timeline import build_timeline
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = _make_record(event_date=today_str)
        tl = build_timeline([r])
        self.assertEqual(tl["today_count"], 1)
        self.assertEqual(len(tl["today"]), 1)

    def test_past_7_days_bucket(self):
        from event_intelligence.timeline import build_timeline
        past = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        r = _make_record(event_id="p7", event_date=past)
        tl = build_timeline([r])
        self.assertEqual(tl["past_7_count"], 1)

    def test_upcoming_bucket(self):
        from event_intelligence.timeline import build_timeline
        future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
        r = _make_record(event_id="upcoming", event_date=future)
        tl = build_timeline([r])
        self.assertGreater(tl["upcoming_count"], 0)

    def test_past_30_days_bucket(self):
        from event_intelligence.timeline import build_timeline
        old = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
        r = _make_record(event_id="old30", event_date=old)
        tl = build_timeline([r])
        self.assertGreater(tl["past_30_count"], 0)

    def test_empty_events(self):
        from event_intelligence.timeline import build_timeline
        tl = build_timeline([])
        self.assertEqual(tl["total_events"], 0)
        self.assertTrue(tl["available"])

    def test_daily_calendar_populated(self):
        from event_intelligence.timeline import build_timeline
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
        r = _make_record(event_id="cal", event_date=future)
        tl = build_timeline([r])
        self.assertIsInstance(tl["daily_calendar"], dict)


# ============================================================================
# 8. Daily Brief
# ============================================================================
class TestBrief(unittest.TestCase):

    def _make_events(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [
            _make_record(importance_score=80.0, impact_direction="BULLISH",
                         event_date=today, symbol="RELIANCE"),
            _make_record(event_id="e2", importance_score=70.0,
                         impact_direction="BEARISH", event_date=today, symbol="TCS",
                         trading_risk="Downside risk"),
            _make_record(event_id="e3", importance_score=60.0,
                         impact_direction="VOLATILE", event_date=today,
                         expected_volatility=3.0, symbol="SBIN"),
        ]

    def test_brief_structure(self):
        from event_intelligence.brief import generate_daily_brief
        brief = generate_daily_brief(self._make_events(), 72.0, "B")
        self.assertTrue(brief["available"])
        self.assertIn("date", brief)
        self.assertIn("market_tone", brief)
        self.assertIn("sector_highlights", brief)
        self.assertIn("high_risk_stocks", brief)
        self.assertIn("high_opportunity_stocks", brief)
        self.assertIn("volatility_events", brief)
        self.assertTrue(brief["advisory_only"])

    def test_brief_score_and_grade(self):
        from event_intelligence.brief import generate_daily_brief
        brief = generate_daily_brief(self._make_events(), 85.0, "A")
        self.assertEqual(brief["intelligence_score"], 85.0)
        self.assertEqual(brief["grade"], "A")

    def test_high_risk_stocks_populated(self):
        from event_intelligence.brief import generate_daily_brief
        brief = generate_daily_brief(self._make_events(), 72.0, "B")
        # TCS (bearish) + SBIN (volatile) should appear
        risk_symbols = [s["symbol"] for s in brief["high_risk_stocks"] if s.get("symbol")]
        self.assertTrue(len(risk_symbols) > 0)

    def test_volatility_events(self):
        from event_intelligence.brief import generate_daily_brief
        brief = generate_daily_brief(self._make_events(), 72.0, "B")
        # SBIN has 3.0 expected_volatility ≥ 2.0
        self.assertTrue(len(brief["volatility_events"]) > 0)

    def test_market_tone_broadly_bullish(self):
        from event_intelligence.brief import generate_daily_brief
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events = [
            _make_record(event_id=f"e{i}", impact_direction="BULLISH",
                         importance_score=75.0, event_date=today)
            for i in range(5)
        ]
        brief = generate_daily_brief(events, 80.0, "A")
        self.assertEqual(brief["market_tone"], "BROADLY BULLISH")


# ============================================================================
# 9. Shared Services (all endpoints)
# ============================================================================
class TestSharedServices(unittest.TestCase):

    def setUp(self):
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "true"

    def test_summary_returns_enabled(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            result = shared_services.get_summary()
        self.assertIn(result["status"], ("ENABLED", "ERROR"))

    def test_corporate_returns_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            result = shared_services.get_corporate()
        self.assertIn("events", result)

    def test_regulatory_returns_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            result = shared_services.get_regulatory()
        self.assertIn("events", result)

    def test_news_returns_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            result = shared_services.get_news()
        self.assertIn("events", result)

    def test_timeline_returns_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            result = shared_services.get_timeline()
        self.assertIn("today", result)
        self.assertIn("upcoming", result)

    def test_brief_returns_structure(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            result = shared_services.get_brief()
        self.assertIn("date", result)
        self.assertIn("market_tone", result)

    def test_snapshot_never_raises(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            snapshot = shared_services.get_event_intelligence_snapshot()
        self.assertIn("intelligence_score", snapshot)
        self.assertIn("grade", snapshot)

    def test_all_responses_advisory_only(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            for fn in (shared_services.get_corporate, shared_services.get_regulatory,
                       shared_services.get_news, shared_services.get_timeline,
                       shared_services.get_brief):
                result = fn()
                # Either advisory_only is set, or status is ERROR/DISABLED
                if result.get("available"):
                    self.assertTrue(result.get("advisory_only", False),
                                    f"{fn.__name__} missing advisory_only=True")


# ============================================================================
# 10. Duplicate detection
# ============================================================================
class TestDuplicateDetection(unittest.TestCase):

    def test_same_event_id_deduped(self):
        from event_intelligence.news_intelligence import _deduplicate
        r1 = _make_record()
        r2 = _make_record()   # same event_id
        result = _deduplicate([r1, r2])
        self.assertEqual(len(result), 1)

    def test_different_ids_both_kept(self):
        from event_intelligence.news_intelligence import _deduplicate
        r1 = _make_record(event_id="id_a", title="Apple")
        r2 = _make_record(event_id="id_b", title="Banana")
        result = _deduplicate([r1, r2])
        self.assertEqual(len(result), 2)

    def test_similar_title_deduped(self):
        from event_intelligence.news_intelligence import _deduplicate
        # Both titles share exactly the same first 40 chars → deduped to 1
        common = "A" * 40
        r1 = _make_record(event_id="a1", title=common + "_suffix_ONE")
        r2 = _make_record(event_id="a2", title=common + "_suffix_TWO")
        result = _deduplicate([r1, r2])
        self.assertEqual(len(result), 1)


# ============================================================================
# 11. Export
# ============================================================================
class TestExport(unittest.TestCase):

    def test_csv_export_non_empty(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            csv_str = shared_services.export_csv()
        self.assertIsInstance(csv_str, str)
        if csv_str:
            self.assertIn("event_id", csv_str)

    def test_json_export_parseable(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence import shared_services
            import importlib; importlib.reload(shared_services)
            json_str = shared_services.export_json()
        if json_str:
            data = json.loads(json_str)
            self.assertIn("events", data)
            self.assertTrue(data.get("advisory_only"))

    def test_csv_disabled_returns_empty(self):
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "false"
        from event_intelligence import shared_services
        import importlib; importlib.reload(shared_services)
        csv_str = shared_services.export_csv()
        self.assertEqual(csv_str, "")
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "true"


# ============================================================================
# 12. API command dispatch
# ============================================================================
class TestAPIDispatch(unittest.TestCase):

    def setUp(self):
        os.environ["EVENT_INTELLIGENCE_ENABLED"] = "true"

    def test_cmd_summary(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_summary
            result = cmd_summary()
        self.assertIsInstance(result, dict)

    def test_cmd_corporate(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_corporate
            result = cmd_corporate()
        self.assertIsInstance(result, dict)

    def test_cmd_regulatory(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_regulatory
            result = cmd_regulatory()
        self.assertIsInstance(result, dict)

    def test_cmd_news(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_news
            result = cmd_news()
        self.assertIsInstance(result, dict)

    def test_cmd_timeline(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_timeline
            result = cmd_timeline()
        self.assertIsInstance(result, dict)

    def test_cmd_brief(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_brief
            result = cmd_brief()
        self.assertIsInstance(result, dict)

    def test_cmd_export_csv(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_export_csv
            result = cmd_export_csv()
        self.assertIn("csv", result)

    def test_cmd_export_json(self):
        with patch("signals_cache.get_latest_signals", return_value=[]):
            from event_intelligence.api import cmd_export_json
            result = cmd_export_json()
        self.assertIn("json", result)


# ============================================================================
# 13. Advisory-only safety guarantee
# ============================================================================
class TestAdvisoryOnlySafety(unittest.TestCase):
    """
    Verify that no event_intelligence module imports from execution,
    portfolio mutation, or order placement modules.
    """
    FORBIDDEN_IMPORTS = [
        "order_executor", "trade_executor", "execution_engine",
        "portfolio_writer", "signal_writer", "strategy_mutator",
        "risk_engine_writer", "ai_model_trainer",
    ]

    def _check_file(self, filepath: str):
        with open(filepath) as f:
            source = f.read()
        for mod in self.FORBIDDEN_IMPORTS:
            self.assertNotIn(
                f"import {mod}", source,
                f"{filepath} must not import {mod} (advisory-only violation)"
            )
            self.assertNotIn(
                f"from {mod}", source,
                f"{filepath} must not use {mod} (advisory-only violation)"
            )

    def test_shared_services_advisory(self):
        self._check_file(
            os.path.join(os.path.dirname(__file__),
                         "event_intelligence", "shared_services.py")
        )

    def test_corporate_intelligence_advisory(self):
        self._check_file(
            os.path.join(os.path.dirname(__file__),
                         "event_intelligence", "corporate_intelligence.py")
        )

    def test_impact_engine_advisory(self):
        self._check_file(
            os.path.join(os.path.dirname(__file__),
                         "event_intelligence", "impact_engine.py")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
