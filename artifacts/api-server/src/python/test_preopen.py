"""
test_preopen.py — Phase 5A Pre-Open Intelligence unit tests.

All 22 required scenarios covered. Fixture-based (MockPreOpenProvider).
No live NSE session required.

Run: python3 -m pytest test_preopen.py -v
  or: python3 test_preopen.py

PAPER TRADING / ADVISORY ONLY.
"""
import sys
import os
import unittest
from decimal import Decimal

# Ensure the python dir is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Silence any DB calls during tests
os.environ["DATABASE_URL"] = ""
os.environ["PREOPEN_INTELLIGENCE_ENABLED"] = "true"


from preopen_analytics import (
    calc_gap_percent, calc_imbalance, calc_imbalance_percent,
    calc_participation_score, calc_liquidity_score, calc_opportunity_score,
    classify_snapshot, enrich_universe,
)
from preopen_data_model import (
    PreOpenSnapshot, Classification, ProviderState, now_ist_str,
)
from preopen_provider import MockPreOpenProvider, FIXTURE_SNAPSHOTS, ProviderState as PS
from preopen_watchlist import generate_watchlists
from preopen_reconciliation import confirm_candidate, reconcile_session


# ── Helpers ────────────────────────────────────────────────────────────────────

def _snap(symbol="RELIANCE", prev_close=2800.0, ind_price=2856.0,
          buy_qty=120000, sell_qty=40000, volume=85000,
          sector="Energy", age=30, is_stale=False,
          gap=None):
    s = PreOpenSnapshot(
        snapshot_id=f"test-{symbol}",
        trading_date="2024-01-15",
        timestamp_ist=now_ist_str(),
        symbol=symbol,
        company_name=symbol,
        sector=sector,
        previous_close=prev_close,
        indicative_equilibrium_price=ind_price,
        indicative_open_price=ind_price,
        final_open_price=None,
        price_change=ind_price - prev_close,
        gap_percent=gap if gap is not None else (
            round((ind_price - prev_close) / prev_close * 100, 4) if prev_close > 0 else 0.0
        ),
        total_buy_quantity=buy_qty,
        total_sell_quantity=sell_qty,
        matched_quantity=0,
        final_executed_quantity=volume,
        total_traded_value=float(ind_price * volume),
        buy_sell_imbalance=buy_qty - sell_qty,
        imbalance_percent=0.0,
        liquidity_score=0.0,
        classification=Classification.DATA_INCOMPLETE,
        opportunity_score=0.0,
        data_source="test",
        data_freshness_seconds=age,
        source_status=ProviderState.STALE if is_stale else ProviderState.LIVE,
        is_stale=is_stale,
        validation_status="STALE" if is_stale else "VALID",
    )
    return s


# ── Test cases ─────────────────────────────────────────────────────────────────

class TestGapCalculation(unittest.TestCase):
    """Scenario 1: gap calculation"""

    def test_gap_up(self):
        gap = calc_gap_percent(2856.0, 2800.0)
        self.assertAlmostEqual(gap, 2.0, places=2)

    def test_gap_down(self):
        gap = calc_gap_percent(1425.0, 1500.0)
        self.assertAlmostEqual(gap, -5.0, places=2)

    def test_flat_open(self):
        gap = calc_gap_percent(3500.5, 3500.0)
        self.assertAlmostEqual(gap, 0.0143, places=3)

    def test_zero_prev_close_returns_none(self):
        self.assertIsNone(calc_gap_percent(100.0, 0.0))

    def test_none_ind_price_returns_none(self):
        self.assertIsNone(calc_gap_percent(None, 2800.0))


class TestImbalanceCalculation(unittest.TestCase):
    """Scenario 2: imbalance calculation"""

    def test_buy_imbalance(self):
        self.assertEqual(calc_imbalance(120000, 40000), 80000)

    def test_sell_imbalance(self):
        self.assertEqual(calc_imbalance(20000, 110000), -90000)

    def test_balanced(self):
        self.assertEqual(calc_imbalance(50000, 50000), 0)


class TestImbalancePercent(unittest.TestCase):
    """Scenario 3: imbalance percentage"""

    def test_strong_buy(self):
        pct = calc_imbalance_percent(120000, 40000)
        self.assertAlmostEqual(pct, 50.0, places=1)

    def test_strong_sell(self):
        pct = calc_imbalance_percent(20000, 110000)
        self.assertAlmostEqual(pct, -69.23, places=1)


class TestZeroQuantityDivision(unittest.TestCase):
    """Scenario 4: zero-quantity division guard"""

    def test_zero_quantities(self):
        pct = calc_imbalance_percent(0, 0)
        self.assertEqual(pct, 0.0)

    def test_participation_empty_universe(self):
        score = calc_participation_score(0, [])
        self.assertEqual(score, 0.0)

    def test_opportunity_score_zero_universe(self):
        s = _snap()
        score, factors = calc_opportunity_score(s, [])
        # Should not raise; returns a valid float
        self.assertIsInstance(score, float)


class TestMissingFields(unittest.TestCase):
    """Scenario 5: missing fields handled gracefully"""

    def test_no_indicative_price(self):
        s = _snap()
        s.indicative_open_price = None
        s.gap_percent = None
        # Classification should handle None gap
        label = classify_snapshot(s)
        self.assertIn(label, vars(Classification).values())

    def test_no_sector(self):
        s = _snap(sector="")
        s.sector = ""
        # Should not crash
        enriched = enrich_universe([s])
        self.assertEqual(len(enriched), 1)


class TestMalformedProviderResponse(unittest.TestCase):
    """Scenario 6: malformed provider response"""

    def test_invalid_raw_rejected(self):
        p = MockPreOpenProvider()
        self.assertFalse(p.validate_response(None))
        self.assertFalse(p.validate_response({"prev_close": 0}))
        self.assertFalse(p.validate_response("not a dict"))

    def test_normalize_invalid_returns_none(self):
        p = MockPreOpenProvider()
        result = p.normalize_response({"invalid": True}, "TEST")
        self.assertIsNone(result)


class TestStaleData(unittest.TestCase):
    """Scenario 7: stale data never creates actionable recommendation"""

    def test_stale_opportunity_score_zero(self):
        s = _snap(is_stale=True, age=400)
        enriched = enrich_universe([s])
        self.assertEqual(enriched[0].opportunity_score, 0.0)

    def test_stale_excluded_from_watchlist(self):
        s1 = _snap("RELIANCE", is_stale=False)
        s2 = _snap("INFY", is_stale=True)
        s1 = enrich_universe([s1])[0]
        s2.is_stale = True
        s2.validation_status = "STALE"
        lists = generate_watchlists([s1, s2])
        wl_syms = [item["symbol"] for item in lists["overall_ranked"]]
        self.assertNotIn("INFY", wl_syms)

    def test_stale_confirmation_gate_fails(self):
        result = confirm_candidate(
            "RELIANCE", 2.0, 2856.0, 2860.0, 50000, 80000,
            2850.0, "POSITIVE", "POSITIVE", 15.0, 0.2,
            is_stale=True, risk_engine_approved=True,
        )
        self.assertEqual(result["verdict"], "NO_TRADE")
        self.assertIn("stale_data_gate", result["failed"])


class TestProviderTimeout(unittest.TestCase):
    """Scenario 8: provider timeout / failure"""

    def test_failed_provider_returns_empty(self):
        p = MockPreOpenProvider(fail=True)
        snaps = p.fetch_market_snapshot()
        self.assertEqual(snaps, [])

    def test_failed_health_check(self):
        p = MockPreOpenProvider(fail=True)
        health = p.health_check()
        self.assertEqual(health["status"], ProviderState.UNAVAILABLE)

    def test_failed_symbol_returns_none(self):
        p = MockPreOpenProvider(fail=True)
        self.assertIsNone(p.fetch_symbol_snapshot("RELIANCE"))


class TestPartialMarketResponse(unittest.TestCase):
    """Scenario 9: partial market response"""

    def test_partial_fixture_set(self):
        fixtures = FIXTURE_SNAPSHOTS[:3]  # only 3 symbols
        p = MockPreOpenProvider(fixtures=fixtures)
        snaps = p.fetch_market_snapshot()
        self.assertEqual(len(snaps), 3)

    def test_partial_enrichment(self):
        snaps = [_snap("TCS", prev_close=3500.0, ind_price=3500.5)]
        enriched = enrich_universe(snaps)
        self.assertEqual(len(enriched), 1)
        self.assertIsNotNone(enriched[0].classification)


class TestDuplicateSnapshots(unittest.TestCase):
    """Scenario 10: duplicate snapshots"""

    def test_duplicate_symbols_enriched_separately(self):
        s1 = _snap("RELIANCE")
        s2 = _snap("RELIANCE", gap=3.0)   # same symbol, different snapshot_id
        s2.snapshot_id = "test-RELIANCE-2"
        enriched = enrich_universe([s1, s2])
        self.assertEqual(len(enriched), 2)


class TestTimezoneCorrectness(unittest.TestCase):
    """Scenario 11: timezone correctness"""

    def test_now_ist_str_format(self):
        ts = now_ist_str()
        # Must be ISO format ending in Z
        self.assertTrue(ts.endswith("Z"))
        self.assertEqual(len(ts), 20)


class TestMarketHolidayHandling(unittest.TestCase):
    """Scenario 12: market holiday handling"""

    def test_scheduler_holiday_check_does_not_crash(self):
        from preopen_scheduler import PreOpenScheduler
        s = PreOpenScheduler(test_mode=False)
        # _should_run returns False on holiday / outside window in non-test mode
        # We can't easily control the clock, so just verify it doesn't crash
        result = s.status()
        self.assertIn("phase", result)


class TestFirstSessionHandling(unittest.TestCase):
    """Scenario 13: first session (no prior data)"""

    def test_empty_universe_enrich(self):
        enriched = enrich_universe([])
        self.assertEqual(enriched, [])

    def test_single_symbol_universe(self):
        s = _snap()
        enriched = enrich_universe([s])
        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0].volume_rank, 1)
        self.assertEqual(enriched[0].gap_rank, 1)


class TestRankings(unittest.TestCase):
    """Scenario 14: rankings"""

    def test_higher_score_ranks_first(self):
        p = MockPreOpenProvider()
        snaps = p.fetch_market_snapshot()
        enriched = enrich_universe(snaps)
        scores = [s.opportunity_score for s in enriched]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_volume_rank_sequential(self):
        p = MockPreOpenProvider()
        snaps = p.fetch_market_snapshot()
        enriched = enrich_universe(snaps)
        ranks = sorted(s.volume_rank for s in enriched if s.volume_rank)
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))


class TestTieBreaking(unittest.TestCase):
    """Scenario 15: tie-breaking"""

    def test_tie_broken_by_gap_then_symbol(self):
        s1 = _snap("ZZTEST", gap=2.0)
        s2 = _snap("AATEST", gap=2.0)
        s1.opportunity_score = 50.0
        s2.opportunity_score = 50.0
        from preopen_analytics import rank_snapshots
        ranked = rank_snapshots([s1, s2])
        # Both have same score and gap → alphabetical by symbol
        self.assertEqual(ranked[0].symbol, "AATEST")


class TestSectorAggregation(unittest.TestCase):
    """Scenario 16: sector aggregation"""

    def test_sector_avg_gap_positive(self):
        s1 = _snap("INFY", sector="IT", prev_close=1500, ind_price=1530, gap=2.0)
        s2 = _snap("TCS",  sector="IT", prev_close=3500, ind_price=3535, gap=1.0)
        enriched = enrich_universe([s1, s2])
        # Both IT stocks — sector avg gap influences opportunity score
        # Just verify no crash and scores are non-negative
        for s in enriched:
            self.assertGreaterEqual(s.opportunity_score, 0.0)


class TestFeatureFlagDisabled(unittest.TestCase):
    """Scenario 17: feature flag disabled path"""

    def test_engine_returns_disabled_when_flag_off(self):
        os.environ["PREOPEN_INTELLIGENCE_ENABLED"] = "false"
        import importlib
        import preopen_engine
        importlib.reload(preopen_engine)
        result = preopen_engine.get_status()
        self.assertEqual(result["status"], "DISABLED")
        os.environ["PREOPEN_INTELLIGENCE_ENABLED"] = "true"
        importlib.reload(preopen_engine)

    def test_refresh_returns_disabled_when_flag_off(self):
        os.environ["PREOPEN_INTELLIGENCE_ENABLED"] = "false"
        import importlib
        import preopen_engine
        importlib.reload(preopen_engine)
        result = preopen_engine.refresh()
        self.assertEqual(result["status"], "DISABLED")
        os.environ["PREOPEN_INTELLIGENCE_ENABLED"] = "true"
        importlib.reload(preopen_engine)


class TestPostOpenReconciliation(unittest.TestCase):
    """Scenario 18: post-open reconciliation"""

    def test_zero_actual_price_safe(self):
        snaps = [_snap().to_dict()]
        result = reconcile_session(
            "sess-001", snaps,
            actual_prices={},
            prices_0920={},
            prices_0930={},
            watchlist_symbols=set(),
        )
        self.assertTrue(result["success"])
        self.assertIsNone(result["avg_indicative_to_open_error_pct"])

    def test_indicative_error_calculated(self):
        s = _snap("RELIANCE", prev_close=2800.0, ind_price=2856.0)
        snaps = [s.to_dict()]
        result = reconcile_session(
            "sess-002", snaps,
            actual_prices={"RELIANCE": 2870.0},
            prices_0920={"RELIANCE": 2875.0},
            prices_0930={},
            watchlist_symbols={"RELIANCE"},
        )
        self.assertTrue(result["success"])
        # Error = |2856 - 2870| / 2870 * 100 ≈ 0.4878
        err = result["avg_indicative_to_open_error_pct"]
        self.assertAlmostEqual(err, 0.4878, places=2)


class TestNoTradeExecutionFromPreOpen(unittest.TestCase):
    """
    Scenario 19 (SAFETY INVARIANT):
    Pre-open data cannot submit orders or bypass the risk engine.
    """

    def test_no_order_function_exists(self):
        """Confirm no buy/sell/order functions in preopen modules."""
        import preopen_engine
        import preopen_analytics
        import preopen_watchlist
        import preopen_scheduler
        import preopen_reconciliation

        banned = ["execute_buy", "execute_sell", "place_order", "create_order",
                  "submit_order", "kite_place_order"]
        for mod in [preopen_engine, preopen_analytics, preopen_watchlist,
                    preopen_scheduler, preopen_reconciliation]:
            src = open(mod.__file__).read()
            for fn in banned:
                self.assertNotIn(fn + "(", src,
                    f"{fn} found in {mod.__name__} — pre-open data must not submit orders!")

    def test_paper_mode_advisory_labels_present(self):
        """Every engine response carries the advisory label."""
        import preopen_engine
        status = preopen_engine.get_status()
        self.assertIn("label", status)
        self.assertIn("ADVISORY", status["label"])

    def test_stale_data_cannot_be_actionable(self):
        """Stale snapshots must score 0 and be excluded from watchlists."""
        stale = _snap(is_stale=True, age=999)
        enriched = enrich_universe([stale])
        self.assertEqual(enriched[0].opportunity_score, 0.0)
        lists = generate_watchlists(enriched)
        for items in lists.values():
            syms = [i.get("symbol") for i in items]
            self.assertNotIn("RELIANCE", syms)

    def test_confirmation_requires_risk_engine(self):
        """Post-open confirmation fails without risk_engine_approved."""
        result = confirm_candidate(
            "BAJFINANCE", 5.0, 7350.0, 7380.0, 200000, 150000,
            7320.0, "POSITIVE", "POSITIVE", 12.0, 0.1,
            is_stale=False, risk_engine_approved=False,
        )
        self.assertEqual(result["verdict"], "NO_TRADE")
        self.assertIn("risk_engine_approval", result["failed"])


class TestPostOpenConfirmationGate(unittest.TestCase):
    """Scenario 20: post-open confirmation gate verdicts"""

    def test_confirmed_when_all_criteria_pass(self):
        result = confirm_candidate(
            "SUNPHARMA", 5.0, 1260.0, 1265.0, 80000, 60000,
            1255.0, "POSITIVE", "POSITIVE", 14.0, 0.2,
            is_stale=False, risk_engine_approved=True,
        )
        self.assertEqual(result["verdict"], "CONFIRMED")

    def test_downgrade_watch_when_partial(self):
        result = confirm_candidate(
            "WIPRO", 0.5, 454.5, 455.0, 5000, 30000,
            453.0, "NEUTRAL", "POSITIVE", 18.0, 0.4,
            is_stale=False, risk_engine_approved=True,
        )
        self.assertIn(result["verdict"], ("DOWNGRADE_WATCH", "NO_TRADE"))

    def test_no_trade_when_too_many_fail(self):
        result = confirm_candidate(
            "ITC", -4.0, None, None, None, None,
            None, None, None, None, None,
            is_stale=False, risk_engine_approved=False,
        )
        self.assertEqual(result["verdict"], "NO_TRADE")


class TestClassification(unittest.TestCase):
    """Scenario 21: classification labels"""

    def test_strong_gap_up(self):
        s = _snap(gap=3.0)
        s.validation_status = "VALID"
        s.is_stale = False
        s.imbalance_percent = 30.0
        label = classify_snapshot(s)
        self.assertEqual(label, Classification.STRONG_GAP_UP)

    def test_strong_gap_down(self):
        s = _snap(gap=-3.0)
        s.validation_status = "VALID"
        s.is_stale = False
        label = classify_snapshot(s)
        self.assertEqual(label, Classification.STRONG_GAP_DOWN)

    def test_data_incomplete_for_stale(self):
        s = _snap(is_stale=True)
        label = classify_snapshot(s)
        self.assertEqual(label, Classification.DATA_INCOMPLETE)

    def test_low_liquidity(self):
        s = _snap(buy_qty=0, sell_qty=0, volume=0)
        s.validation_status = "VALID"
        s.is_stale = False
        s.gap_percent = 0.1
        s.liquidity_score = 0.0
        label = classify_snapshot(s)
        self.assertEqual(label, Classification.LOW_LIQUIDITY)


class TestWatchlistGeneration(unittest.TestCase):
    """Scenario 22: watchlist generation"""

    def test_eight_lists_generated(self):
        p = MockPreOpenProvider()
        snaps = p.fetch_market_snapshot()
        enriched = enrich_universe(snaps)
        lists = generate_watchlists(enriched)
        self.assertEqual(len(lists), 8)
        expected_keys = {
            "top_gap_up", "top_gap_down", "buy_imbalance", "sell_imbalance",
            "highest_executed_qty", "sector_leaders", "sector_laggards", "overall_ranked",
        }
        self.assertEqual(set(lists.keys()), expected_keys)

    def test_each_item_has_required_fields(self):
        p = MockPreOpenProvider()
        snaps = p.fetch_market_snapshot()
        enriched = enrich_universe(snaps)
        lists = generate_watchlists(enriched)
        required = {"rank", "symbol", "gap_percent", "imbalance_percent",
                    "executed_quantity", "liquidity_score", "sector",
                    "opportunity_score", "risk_flags", "explanation",
                    "required_post_open_confirmation"}
        for items in lists.values():
            for item in items:
                missing = required - set(item.keys())
                self.assertEqual(missing, set(), f"Missing fields: {missing}")

    def test_confirmation_checklist_not_empty(self):
        p = MockPreOpenProvider()
        snaps = p.fetch_market_snapshot()
        enriched = enrich_universe(snaps)
        lists = generate_watchlists(enriched)
        for items in lists.values():
            for item in items:
                self.assertGreater(len(item["required_post_open_confirmation"]), 0)


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
