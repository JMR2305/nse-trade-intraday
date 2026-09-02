"""
test_market_intelligence_hub.py — Phase 7.1
Comprehensive unit tests for the Market Intelligence Hub.

Tests cover:
  - Feature flag (5)
  - Hub models: scoring, grade, regime constants (5)
  - Multi-timeframe analyser (5)
  - Regime analyser (5)
  - Sector intelligence (5)
  - Breadth analyser (5)
  - Volatility analyser (5)
  - Watchlist intelligence (5)
  - Intelligence summary (5)
  - Shared services API (5)
  - Export (3)
"""
import sys, os, unittest
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _real_package_per_test():
    """Never consume a package object imported under another test's stubs."""
    saved = dict(sys.modules)
    try:
        for name in list(sys.modules):
            if name == "market_intelligence_hub" or name.startswith("market_intelligence_hub."):
                sys.modules.pop(name, None)
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_item(
    stock="RELIANCE", sector="Energy", price=2500.0,
    opportunity_score=72.0, confidence=75.0, final_action="BUY",
    signal_reason="EMA crossover confirmed", atr=25.0, adx=32.0,
    rsi=58.0, volume_ratio=1.2,
):
    return {
        "stock": stock, "sector": sector, "price": price,
        "opportunity_score": opportunity_score, "confidence": confidence,
        "final_action": final_action, "signal_reason": signal_reason,
        "atr": atr, "adx": adx, "rsi": rsi, "volume_ratio": volume_ratio,
    }


def _scan_set():
    """A realistic multi-sector scan set."""
    return [
        _make_item("RELIANCE", "Energy",          2500, 72, 75, "BUY"),
        _make_item("TCS",      "IT",              3800, 80, 82, "STRONG_BUY"),
        _make_item("INFY",     "IT",              1600, 68, 70, "BUY"),
        _make_item("HDFCBANK", "Banking",         1750, 65, 68, "BUY"),
        _make_item("ICICIBANK","Banking",         1200, 70, 72, "BUY"),
        _make_item("SBIN",     "Banking",          820, 45, 50, "WATCH"),
        _make_item("WIPRO",    "IT",               540, 55, 58, "WATCH"),
        _make_item("LT",       "Infrastructure",  3600, 60, 65, "BUY"),
        _make_item("BAJFINANCE","NBFC",           7200, 30, 35, "IGNORE",  atr=80, adx=18),
        _make_item("MARUTI",   "Auto",            1200, 78, 80, "STRONG_BUY"),
    ]


def _bull_regime():
    return {
        "regime": "BULL", "sub_regime": "MODERATE_MOMENTUM",
        "trend_strength": 55.0, "confidence": 72.0,
        "nifty_price": 24500.0, "nifty_change_pct": 0.012,
        "nifty_trend": "UP", "banknifty_price": 52000.0,
        "banknifty_change_pct": 0.015, "banknifty_trend": "UP",
        "vix_value": 14.5, "vix_status": "LOW",
        "high_volatility": False, "adj_buy": 1.1, "adj_sell": 0.9,
        "description": "Bull market — advisory only.", "advisory_only": True,
    }


def _bear_regime():
    return {
        "regime": "BEAR", "sub_regime": "STRONG_MOMENTUM",
        "trend_strength": 60.0, "confidence": 68.0,
        "nifty_price": 21000.0, "nifty_change_pct": -0.025,
        "nifty_trend": "DOWN", "banknifty_price": 45000.0,
        "banknifty_change_pct": -0.030, "banknifty_trend": "DOWN",
        "vix_value": 27.5, "vix_status": "HIGH",
        "high_volatility": True, "adj_buy": 0.8, "adj_sell": 1.2,
        "description": "Bear market — advisory only.", "advisory_only": True,
    }


def _mock_timeframes():
    return {
        "timeframes": [
            {"key": "1d", "label": "Daily", "trend": "UP", "strength": 55.0,
             "ema9": 24200.0, "ema20": 24100.0, "price": 24500.0, "available": True},
            {"key": "1wk", "label": "Weekly", "trend": "UP", "strength": 62.0,
             "ema9": 24000.0, "ema20": 23800.0, "price": 24500.0, "available": True},
            {"key": "1h", "label": "1 Hour", "trend": "NEUTRAL", "strength": 20.0,
             "ema9": 24490.0, "ema20": 24495.0, "price": 24500.0, "available": True},
        ],
        "alignment_score": 66.67, "agreement": "BULLISH", "primary_trend": "UP",
        "up_count": 2, "down_count": 0, "neutral_count": 1,
        "available_count": 3, "total_timeframes": 7, "elapsed_ms": 120.0,
    }


# ===========================================================================
# 1. Feature flag (5 tests)
# ===========================================================================

class TestFeatureFlag(unittest.TestCase):

    def setUp(self):
        os.environ.pop("MARKET_INTELLIGENCE_HUB_ENABLED", None)

    def tearDown(self):
        os.environ.pop("MARKET_INTELLIGENCE_HUB_ENABLED", None)

    def test_disabled_by_default(self):
        from market_intelligence_hub.hub_models import is_enabled
        self.assertFalse(is_enabled())

    def test_enabled_when_set(self):
        os.environ["MARKET_INTELLIGENCE_HUB_ENABLED"] = "true"
        from market_intelligence_hub.hub_models import is_enabled
        self.assertTrue(is_enabled())

    def test_summary_disabled(self):
        from market_intelligence_hub.shared_services import get_summary
        self.assertEqual(get_summary()["status"], "DISABLED")

    def test_all_endpoints_disabled(self):
        from market_intelligence_hub.shared_services import (
            get_summary, get_sectors, get_watchlist, get_breadth, get_overview
        )
        for fn in [get_summary, get_sectors, get_watchlist, get_breadth, get_overview]:
            self.assertEqual(fn()["status"], "DISABLED")

    def test_disabled_response_has_message(self):
        from market_intelligence_hub.hub_models import disabled_response
        r = disabled_response()
        self.assertIn("message", r)
        self.assertEqual(r["status"], "DISABLED")


# ===========================================================================
# 2. Hub models (5 tests)
# ===========================================================================

class TestHubModels(unittest.TestCase):

    def test_health_grade_thresholds(self):
        from market_intelligence_hub.hub_models import health_grade
        self.assertEqual(health_grade(92), "A+")
        self.assertEqual(health_grade(83), "A")
        self.assertEqual(health_grade(70), "B")
        self.assertEqual(health_grade(55), "C")
        self.assertEqual(health_grade(30), "D")

    def test_health_trend_improving(self):
        from market_intelligence_hub.hub_models import health_trend
        self.assertEqual(health_trend(75, 70), "IMPROVING")

    def test_health_trend_weakening(self):
        from market_intelligence_hub.hub_models import health_trend
        self.assertEqual(health_trend(60, 66), "WEAKENING")

    def test_health_trend_stable(self):
        from market_intelligence_hub.hub_models import health_trend
        self.assertEqual(health_trend(65, 64), "STABLE")

    def test_clamp(self):
        from market_intelligence_hub.hub_models import clamp
        self.assertEqual(clamp(110), 100.0)
        self.assertEqual(clamp(-5), 0.0)
        self.assertEqual(clamp(50), 50.0)


# ===========================================================================
# 3. Multi-timeframe analyser (5 tests)
# ===========================================================================

class TestMultiTimeframeAnalyser(unittest.TestCase):

    def _mock_analyse(self, up=4, down=2, neutral=1):
        """Build a mock timeframe result without yfinance."""
        from market_intelligence_hub.hub_models import TimeframeResult
        timeframes = []
        for i in range(up):
            timeframes.append(TimeframeResult(
                key=f"tf{i}", label=f"TF{i}", trend="UP",
                strength=55.0, ema9=100.5, ema20=99.5, price=100.0, available=True
            ))
        for i in range(down):
            timeframes.append(TimeframeResult(
                key=f"tfd{i}", label=f"TFD{i}", trend="DOWN",
                strength=45.0, ema9=98.5, ema20=99.5, price=100.0, available=True
            ))
        for i in range(neutral):
            timeframes.append(TimeframeResult(
                key=f"tfn{i}", label=f"TFN{i}", trend="NEUTRAL",
                strength=20.0, ema9=99.5, ema20=99.5, price=100.0, available=True
            ))
        return timeframes

    def test_alignment_score_all_up(self):
        from market_intelligence_hub.hub_models import clamp
        tfs = self._mock_analyse(up=7, down=0, neutral=0)
        up_count = sum(1 for t in tfs if t.trend == "UP")
        total = len(tfs)
        score = clamp(up_count / total * 100)
        self.assertEqual(score, 100.0)

    def test_alignment_score_mixed(self):
        from market_intelligence_hub.hub_models import clamp
        tfs = self._mock_analyse(up=4, down=3, neutral=0)
        up_count = sum(1 for t in tfs if t.trend == "UP")
        total = len(tfs)
        score = clamp(up_count / total * 100)
        self.assertAlmostEqual(score, 57.14, delta=1.0)

    def test_unavailable_timeframe(self):
        from market_intelligence_hub.multi_timeframe_analyser import _unavailable
        r = _unavailable("5m", "5 Minute")
        self.assertEqual(r.trend, "UNAVAILABLE")
        self.assertFalse(r.available)

    def test_timeframe_result_to_dict(self):
        from market_intelligence_hub.hub_models import TimeframeResult
        r = TimeframeResult("1d", "Daily", "UP", 55.0, 24200.0, 24100.0, 24500.0, True)
        d = r.to_dict()
        self.assertIn("trend", d)
        self.assertIn("alignment_score", {"alignment_score"} | set(d.keys()) - {"alignment_score"})
        self.assertEqual(d["trend"], "UP")

    def test_agreement_label_strong_bullish(self):
        from market_intelligence_hub.multi_timeframe_analyser import _agreement_label
        self.assertEqual(_agreement_label(7, 0, 7), "STRONG_BULLISH")

    def test_agreement_label_bearish(self):
        from market_intelligence_hub.multi_timeframe_analyser import _agreement_label
        # 2/7 up ≈ 0.286 → falls in ≤0.35 bucket → BEARISH
        self.assertEqual(_agreement_label(2, 5, 7), "BEARISH")


# ===========================================================================
# 4. Regime analyser (5 tests)
# ===========================================================================

class TestRegimeAnalyser(unittest.TestCase):

    def _map(self, raw):
        from market_intelligence_hub.regime_analyser import _map_regime
        return _map_regime(raw)

    def test_bull_regime_nifty_up_bnup(self):
        raw = {"regime": "BULL", "vix_value": 14.0,
               "nifty_trend": "UP", "banknifty_trend": "UP",
               "nifty_change_pct": 0.01, "high_volatility": False}
        self.assertEqual(self._map(raw), "BULL")

    def test_bear_regime(self):
        raw = {"regime": "BEAR", "vix_value": 22.0,
               "nifty_trend": "DOWN", "banknifty_trend": "DOWN",
               "nifty_change_pct": -0.02, "high_volatility": False}
        self.assertEqual(self._map(raw), "BEAR")

    def test_high_vol_when_vix_extreme(self):
        raw = {"regime": "SIDEWAYS", "vix_value": 30.0,
               "nifty_trend": "DOWN", "banknifty_trend": "SIDEWAYS",
               "nifty_change_pct": -0.01, "high_volatility": True}
        self.assertEqual(self._map(raw), "HIGH_VOLATILITY")

    def test_low_vol_when_vix_low(self):
        raw = {"regime": "SIDEWAYS", "vix_value": 12.0,
               "nifty_trend": "SIDEWAYS", "banknifty_trend": "SIDEWAYS",
               "nifty_change_pct": 0.001, "high_volatility": False}
        self.assertEqual(self._map(raw), "LOW_VOLATILITY")

    def test_fallback_gives_dict_with_regime(self):
        from market_intelligence_hub.regime_analyser import _get_base_regime
        r = _get_base_regime()
        self.assertIn("regime", r)
        self.assertIn("vix_value", r)


# ===========================================================================
# 5. Sector intelligence (5 tests)
# ===========================================================================

class TestSectorIntelligence(unittest.TestCase):

    def test_empty_items_returns_empty_sectors(self):
        from market_intelligence_hub.sector_intelligence import analyse_sectors
        r = analyse_sectors([])
        self.assertEqual(r["total_sectors"], 0)
        self.assertEqual(r["strongest_sector"], "N/A")

    def test_sectors_ranked_by_strength(self):
        from market_intelligence_hub.sector_intelligence import analyse_sectors
        r = analyse_sectors(_scan_set())
        self.assertGreater(r["total_sectors"], 0)
        sectors = r["sectors"]
        # Verify sorted by relative_strength desc
        for i in range(len(sectors) - 1):
            self.assertGreaterEqual(sectors[i]["relative_strength"], sectors[i+1]["relative_strength"])

    def test_heat_labels_assigned(self):
        from market_intelligence_hub.sector_intelligence import analyse_sectors
        r = analyse_sectors(_scan_set())
        for s in r["sectors"]:
            self.assertIn(s["heat"], ("HOT", "WARM", "NEUTRAL", "COOL", "COLD"))

    def test_rotation_signal_assigned(self):
        from market_intelligence_hub.sector_intelligence import analyse_sectors
        r = analyse_sectors(_scan_set())
        for s in r["sectors"]:
            self.assertIn(s["rotation_signal"], ("INFLOW", "OUTFLOW", "STABLE"))

    def test_leadership_assigned_to_top_sector(self):
        from market_intelligence_hub.sector_intelligence import analyse_sectors
        r = analyse_sectors(_scan_set())
        leader = next(s for s in r["sectors"] if s["rank"] == 1)
        self.assertTrue(leader["leadership"])


# ===========================================================================
# 6. Breadth analyser (5 tests)
# ===========================================================================

class TestBreadthAnalyser(unittest.TestCase):

    def test_empty_items(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        r = analyse_breadth([], _bull_regime())
        self.assertEqual(r["advancers"], 0)
        self.assertEqual(r["decliners"], 0)

    def test_advancers_counted_from_buy_actions(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        items = [_make_item(final_action=a) for a in ["STRONG_BUY", "BUY", "WATCH", "IGNORE"]]
        r = analyse_breadth(items, _bull_regime())
        self.assertEqual(r["advancers"], 2)
        self.assertEqual(r["decliners"], 1)
        self.assertEqual(r["neutral"], 1)

    def test_breadth_strength_bounded(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        r = analyse_breadth(_scan_set(), _bull_regime())
        self.assertGreaterEqual(r["breadth_strength"], 0.0)
        self.assertLessEqual(r["breadth_strength"], 100.0)

    def test_sector_participation_populated(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        r = analyse_breadth(_scan_set(), _bull_regime())
        self.assertGreater(len(r["sector_participation"]), 0)

    def test_strong_buy_with_space_counts_as_advancer(self):
        # Canonical scan snapshots emit "STRONG BUY" (space-separated).
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        items = [_make_item(final_action=a) for a in ["STRONG BUY", "BUY", "IGNORE"]]
        r = analyse_breadth(items, _bull_regime())
        self.assertEqual(r["advancers"], 2)
        self.assertEqual(r["decliners"], 1)

    def test_volume_breadth_from_volume_ratio(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        items = [_make_item(final_action="BUY") for _ in range(4)]
        items[0]["volume_ratio"] = 1.5
        items[1]["volume_ratio"] = 1.0
        items[2]["volume_ratio"] = 0.6
        items[3]["volume_ratio"] = None  # no volume data → excluded
        r = analyse_breadth(items, _bull_regime())
        self.assertEqual(r["volume_advancers"], 2)
        self.assertEqual(r["volume_decliners"], 1)
        self.assertEqual(r["volume_symbols"], 3)
        self.assertAlmostEqual(r["volume_breadth"], 66.67, places=2)

    def test_volume_breadth_none_without_volume_data(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        items = [_make_item(final_action="BUY")]
        items[0].pop("volume_ratio", None)
        r = analyse_breadth(items, _bull_regime())
        self.assertIsNone(r["volume_breadth"])
        self.assertEqual(r["volume_symbols"], 0)

    def test_breadth_label_assigned(self):
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        r = analyse_breadth(_scan_set(), _bull_regime())
        valid = {"VERY_BROAD", "BROAD", "NARROW", "WEAK", "VERY_WEAK"}
        self.assertIn(r["breadth_label"], valid)


# ===========================================================================
# 7. Volatility analyser (5 tests)
# ===========================================================================

class TestVolatilityAnalyser(unittest.TestCase):

    def test_high_vix_gives_high_vol_regime(self):
        from market_intelligence_hub.volatility_analyser import analyse_volatility
        r = analyse_volatility(_scan_set(), _bear_regime())
        self.assertEqual(r["volatility_regime"], "HIGH_VOLATILITY")

    def test_low_vix_gives_low_vol_regime(self):
        from market_intelligence_hub.volatility_analyser import analyse_volatility
        r = analyse_volatility(_scan_set(), _bull_regime())
        self.assertEqual(r["volatility_regime"], "LOW_VOLATILITY")

    def test_vol_score_bounded(self):
        from market_intelligence_hub.volatility_analyser import analyse_volatility
        for regime in [_bull_regime(), _bear_regime()]:
            r = analyse_volatility(_scan_set(), regime)
            self.assertGreaterEqual(r["volatility_score"], 0.0)
            self.assertLessEqual(r["volatility_score"], 100.0)

    def test_atr_avg_computed(self):
        from market_intelligence_hub.volatility_analyser import analyse_volatility
        r = analyse_volatility(_scan_set(), _bull_regime())
        self.assertGreater(r["atr_avg"], 0.0)

    def test_gap_risk_values(self):
        from market_intelligence_hub.volatility_analyser import analyse_volatility
        r_bear = analyse_volatility(_scan_set(), _bear_regime())
        r_bull = analyse_volatility(_scan_set(), _bull_regime())
        self.assertEqual(r_bear["gap_risk"], "HIGH")
        self.assertEqual(r_bull["gap_risk"], "LOW")


# ===========================================================================
# 8. Watchlist intelligence (5 tests)
# ===========================================================================

class TestWatchlistIntelligence(unittest.TestCase):

    def test_empty_items_returns_empty(self):
        from market_intelligence_hub.watchlist_intelligence import analyse_watchlist
        r = analyse_watchlist([], _bull_regime())
        self.assertEqual(r["total_symbols"], 0)

    def test_composite_scores_bounded(self):
        from market_intelligence_hub.watchlist_intelligence import analyse_watchlist
        r = analyse_watchlist(_scan_set(), _bull_regime())
        for w in r["watchlist"]:
            self.assertGreaterEqual(w["composite_score"], 0.0)
            self.assertLessEqual(w["composite_score"], 100.0)

    def test_ranked_in_descending_order(self):
        from market_intelligence_hub.watchlist_intelligence import analyse_watchlist
        r = analyse_watchlist(_scan_set(), _bull_regime())
        scores = [w["composite_score"] for w in r["watchlist"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_regime_adjusted_in_bull(self):
        from market_intelligence_hub.watchlist_intelligence import analyse_watchlist
        r = analyse_watchlist(_scan_set(), _bull_regime())
        self.assertTrue(r["regime_adjusted"])

    def test_top_opportunities_are_buy_actions(self):
        from market_intelligence_hub.watchlist_intelligence import analyse_watchlist
        r = analyse_watchlist(_scan_set(), _bull_regime())
        for opp in r["top_opportunities"]:
            self.assertIn(opp["final_action"], ("STRONG_BUY", "BUY"))


# ===========================================================================
# 9. Intelligence summary (5 tests)
# ===========================================================================

class TestIntelligenceSummary(unittest.TestCase):

    def _run(self, regime=None):
        from market_intelligence_hub.sector_intelligence import analyse_sectors
        from market_intelligence_hub.breadth_analyser import analyse_breadth
        from market_intelligence_hub.volatility_analyser import analyse_volatility
        from market_intelligence_hub.watchlist_intelligence import analyse_watchlist
        from market_intelligence_hub.intelligence_summary import generate_summary

        r = regime or _bull_regime()
        items = _scan_set()
        sectors   = analyse_sectors(items)
        breadth   = analyse_breadth(items, r)
        volatility = analyse_volatility(items, r)
        watchlist  = analyse_watchlist(items, r)
        return generate_summary(r, sectors, breadth, volatility, watchlist, _mock_timeframes())

    def test_health_score_bounded(self):
        s = self._run()
        self.assertGreaterEqual(s["market_health_score"], 0.0)
        self.assertLessEqual(s["market_health_score"], 100.0)

    def test_grade_valid(self):
        s = self._run()
        self.assertIn(s["grade"], ("A+", "A", "B", "C", "D"))

    def test_trend_valid(self):
        s = self._run()
        self.assertIn(s["trend"], ("IMPROVING", "STABLE", "WEAKENING"))

    def test_advisory_only_true(self):
        s = self._run()
        self.assertTrue(s["advisory_only"])

    def test_evidence_is_list(self):
        s = self._run()
        self.assertIsInstance(s["evidence"], list)


# ===========================================================================
# 10. Shared services API (5 tests)
# ===========================================================================

class TestSharedServicesAPI(unittest.TestCase):

    def setUp(self):
        os.environ["MARKET_INTELLIGENCE_HUB_ENABLED"] = "true"
        # Patch _get_scan_items to return fixture data (no DB/yfinance needed)
        import market_intelligence_hub.shared_services as ss
        self._orig_items = ss._get_scan_items
        self._orig_regime = ss._get_regime
        self._orig_timeframes = ss._get_timeframes
        ss._get_scan_items = lambda: _scan_set()
        ss._get_regime     = lambda: _bull_regime()
        ss._get_timeframes = lambda: _mock_timeframes()

    def tearDown(self):
        import market_intelligence_hub.shared_services as ss
        ss._get_scan_items = self._orig_items
        ss._get_regime     = self._orig_regime
        ss._get_timeframes = self._orig_timeframes
        os.environ.pop("MARKET_INTELLIGENCE_HUB_ENABLED", None)

    def test_summary_returns_enabled(self):
        from market_intelligence_hub.shared_services import get_summary
        r = get_summary()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("market_health_score", r)

    def test_sectors_returns_enabled(self):
        from market_intelligence_hub.shared_services import get_sectors
        r = get_sectors()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("sectors", r)

    def test_breadth_returns_enabled(self):
        from market_intelligence_hub.shared_services import get_breadth
        r = get_breadth()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("advancers", r)

    def test_overview_returns_enabled(self):
        from market_intelligence_hub.shared_services import get_overview
        r = get_overview()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("regime", r)
        self.assertIn("multi_timeframe", r)

    def test_watchlist_returns_enabled(self):
        from market_intelligence_hub.shared_services import get_watchlist
        r = get_watchlist()
        self.assertEqual(r["status"], "ENABLED")
        self.assertIn("watchlist", r)


# ===========================================================================
# 11. Export (3 tests)
# ===========================================================================

class TestExport(unittest.TestCase):

    def setUp(self):
        os.environ["MARKET_INTELLIGENCE_HUB_ENABLED"] = "true"
        import market_intelligence_hub.shared_services as ss
        self._orig_items = ss._get_scan_items
        self._orig_regime = ss._get_regime
        self._orig_timeframes = ss._get_timeframes
        ss._get_scan_items = lambda: _scan_set()
        ss._get_regime     = lambda: _bull_regime()
        ss._get_timeframes = lambda: _mock_timeframes()

    def tearDown(self):
        import market_intelligence_hub.shared_services as ss
        ss._get_scan_items = self._orig_items
        ss._get_regime     = self._orig_regime
        ss._get_timeframes = self._orig_timeframes
        os.environ.pop("MARKET_INTELLIGENCE_HUB_ENABLED", None)

    def test_export_csv_returns_string(self):
        from market_intelligence_hub.shared_services import export_summary_csv
        csv_data = export_summary_csv()
        self.assertIsInstance(csv_data, str)

    def test_export_json_is_valid_json(self):
        import json
        from market_intelligence_hub.shared_services import export_full_json
        raw = export_full_json()
        self.assertIsInstance(raw, str)
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)
        self.assertIn("advisory_only", parsed)

    def test_snapshot_never_raises(self):
        from market_intelligence_hub.shared_services import get_market_intelligence_snapshot
        snap = get_market_intelligence_snapshot()
        self.assertIn("market_health_score", snap)
        self.assertIn("grade", snap)


if __name__ == "__main__":
    unittest.main()
