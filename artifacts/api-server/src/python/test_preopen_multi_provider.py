"""
test_preopen_multi_provider.py — Phase 5D multi-provider test suite.

Tests:
  ✓ NSE provider working (parser + data validation)
  ✓ Zerodha provider working (graceful failure without session)
  ✓ Yahoo fallback working
  ✓ Automatic provider failover
  ✓ Gap calculations (all providers)
  ✓ Imbalance calculations (NSE only)
  ✓ Dashboard rendering data shape
  ✓ API response structure
  ✓ order_book_available flag

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ── NSE fixture data mirroring the real API structure ─────────────────────────

def _nse_item(symbol, prev_close, iep, buy_qty, sell_qty, traded, p_change):
    return {
        "metadata": {
            "symbol":            symbol,
            "previousClose":     prev_close,
            "pChange":           p_change,
            "IEP":               None,           # always null in metadata
            "totalBuyQuantity":  None,           # always null in metadata
            "totalSellQuantity": None,
            "finalQuantity":     traded,
        },
        "detail": {
            "preOpenMarket": {
                "IEP":                  iep,
                "finalPrice":           iep,
                "totalBuyQuantity":     buy_qty,
                "totalSellQuantity":    sell_qty,
                "totalTradedVolume":    traded,
                "lastUpdateTime":       "29-Jul-2026 09:07:35",
            }
        },
    }

NSE_FIXTURE = [
    _nse_item("INFY",      1105.7,  1147.0, 306884, 163277, 233660, 3.74),
    _nse_item("TCS",       2398.0,  2440.0,  37181,  93922,  35025, 1.75),
    _nse_item("RELIANCE",  1267.7,  1275.0, 228111, 717555,  46548, 0.58),
    _nse_item("HDFCBANK",   735.4,   743.0, 515271, 504039, 351846, 1.03),
    _nse_item("WIPRO",      181.1,   183.0, 329013,1081853, 201996, 1.04),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_nse_raw(sym):
    """Return the raw dict the NSE cache uses ({"meta":…, "detail":…})."""
    for item in NSE_FIXTURE:
        if item["metadata"]["symbol"] == sym:
            return {
                "meta":   item["metadata"],
                "detail": item["detail"]["preOpenMarket"],
            }
    return None


# ══════════════════════════════════════════════════════════════════════════════
# NSE PROVIDER TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestNSEProviderParsing(unittest.TestCase):
    """Test NSEPreOpenProvider normalisation logic against fixture data."""

    def setUp(self):
        from nse_preopen_provider import NSEPreOpenProvider
        with patch("config.DEFAULT_WATCHLIST", ["INFY","TCS","RELIANCE","HDFCBANK","WIPRO"]):
            with patch("config.SECTOR_MAP", {"IT":["INFY","TCS","WIPRO"],"Energy":["RELIANCE"],"Banking":["HDFCBANK"]}):
                self.p = NSEPreOpenProvider(["INFY","TCS","RELIANCE","HDFCBANK","WIPRO"])

    def _norm(self, sym):
        return self.p._normalize(_make_nse_raw(sym), sym)

    # Gap calculations
    def test_infy_gap(self):
        snap = self._norm("INFY")
        self.assertIsNotNone(snap)
        expected = round((1147.0 - 1105.7) / 1105.7 * 100, 4)
        self.assertAlmostEqual(snap.gap_percent, expected, places=2)

    def test_tcs_gap(self):
        snap = self._norm("TCS")
        expected = round((2440.0 - 2398.0) / 2398.0 * 100, 4)
        self.assertAlmostEqual(snap.gap_percent, expected, places=2)

    def test_zero_gap_when_iep_equals_prev(self):
        raw = {"meta": {"symbol":"X","previousClose":100.0,"pChange":0},"detail":{"IEP":100.0,"totalBuyQuantity":1000,"totalSellQuantity":1000,"totalTradedVolume":500,"lastUpdateTime":"29-Jul-2026 09:07:35"}}
        snap = self.p._normalize(raw, "X")
        # iep == prev_close → gap = 0
        self.assertEqual(snap.gap_percent, 0.0)

    # IEP extraction
    def test_iep_from_detail_not_meta(self):
        snap = self._norm("INFY")
        self.assertEqual(snap.indicative_equilibrium_price, 1147.0)
        self.assertEqual(snap.indicative_open_price,        1147.0)

    # Previous close
    def test_prev_close_populated(self):
        snap = self._norm("RELIANCE")
        self.assertAlmostEqual(snap.previous_close, 1267.7, places=1)

    # Imbalance calculations
    def test_imbalance_positive_infy(self):
        snap = self._norm("INFY")
        expected_imb = (306884 - 163277) / (306884 + 163277) * 100
        self.assertAlmostEqual(snap.imbalance_percent, expected_imb, places=1)
        self.assertGreater(snap.imbalance_percent, 0)          # buy-side heavy

    def test_imbalance_negative_wipro(self):
        snap = self._norm("WIPRO")
        self.assertLess(snap.imbalance_percent, 0)             # sell-side heavy

    def test_buy_sell_imbalance_field(self):
        snap = self._norm("INFY")
        self.assertEqual(snap.buy_sell_imbalance, 306884 - 163277)

    def test_imbalance_zero_when_equal(self):
        raw = {"meta":{"symbol":"Y","previousClose":200.0,"pChange":1},"detail":{"IEP":202.0,"totalBuyQuantity":1000,"totalSellQuantity":1000,"totalTradedVolume":800,"lastUpdateTime":"29-Jul-2026 09:07:35"}}
        snap = self.p._normalize(raw, "Y")
        self.assertAlmostEqual(snap.imbalance_percent, 0.0)

    # Order book flag
    def test_order_book_available_true_nse(self):
        snap = self._norm("TCS")
        self.assertTrue(snap.order_book_available)

    def test_order_book_available_false_when_no_qty(self):
        raw = {"meta":{"symbol":"Z","previousClose":100.0,"pChange":1},"detail":{"IEP":101.0,"totalBuyQuantity":0,"totalSellQuantity":0,"totalTradedVolume":0,"lastUpdateTime":"29-Jul-2026 09:07:35"}}
        snap = self.p._normalize(raw, "Z")
        self.assertFalse(snap.order_book_available)

    # Data source
    def test_data_source_nse_official(self):
        snap = self._norm("INFY")
        self.assertEqual(snap.data_source, "nse_official")

    def test_provider_label_nse_official(self):
        snap = self._norm("INFY")
        self.assertEqual(snap.provider_label, "NSE Official")

    # Reject records with no prev close
    def test_rejects_zero_prev_close(self):
        raw = {"meta":{"symbol":"BAD","previousClose":0,"pChange":0},"detail":{"IEP":100.0,"totalBuyQuantity":0,"totalSellQuantity":0,"totalTradedVolume":0,"lastUpdateTime":""}}
        snap = self.p._normalize(raw, "BAD")
        self.assertIsNone(snap)

    def test_rejects_missing_prev_close(self):
        raw = {"meta":{"symbol":"BAD2"},"detail":{"IEP":100.0}}
        snap = self.p._normalize(raw, "BAD2")
        self.assertIsNone(snap)

    # to_dict includes order_book_available
    def test_to_dict_has_order_book_available(self):
        snap = self._norm("INFY")
        d = snap.to_dict()
        self.assertIn("order_book_available", d)
        self.assertTrue(d["order_book_available"])


class TestNSEProviderFetchMarket(unittest.TestCase):
    """Test full market snapshot fetch with mocked network."""

    def test_fetch_market_snapshot_returns_all_valid(self):
        by_sym = {item["metadata"]["symbol"]: {"meta": item["metadata"], "detail": item["detail"]["preOpenMarket"]} for item in NSE_FIXTURE}
        with patch("nse_preopen_provider._fetch_raw", return_value=by_sym):
            with patch("config.DEFAULT_WATCHLIST", list(by_sym.keys())):
                with patch("config.SECTOR_MAP", {}):
                    from nse_preopen_provider import NSEPreOpenProvider
                    p = NSEPreOpenProvider(list(by_sym.keys()))
                    snaps = p.fetch_market_snapshot()
        self.assertEqual(len(snaps), len(NSE_FIXTURE))
        for s in snaps:
            self.assertIsNotNone(s.previous_close)
            self.assertIsNotNone(s.indicative_equilibrium_price)

    def test_fetch_market_snapshot_returns_empty_on_network_failure(self):
        with patch("nse_preopen_provider._fetch_raw", return_value=None):
            with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                with patch("config.SECTOR_MAP", {}):
                    from nse_preopen_provider import NSEPreOpenProvider
                    p = NSEPreOpenProvider(["INFY"])
                    snaps = p.fetch_market_snapshot()
        self.assertEqual(snaps, [])

    def test_health_check_live_on_success(self):
        by_sym = {"INFY": _make_nse_raw("INFY")}
        with patch("nse_preopen_provider._fetch_raw", return_value=by_sym):
            with patch("nse_preopen_provider._data_cache_ts", __import__("time").monotonic()):
                with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                    with patch("config.SECTOR_MAP", {}):
                        from nse_preopen_provider import NSEPreOpenProvider
                        p = NSEPreOpenProvider(["INFY"])
                        h = p.health_check()
        self.assertIn(h["status"], ("LIVE", "STALE"))
        self.assertEqual(h["provider"], "NSE Official")

    def test_health_check_unavailable_on_failure(self):
        with patch("nse_preopen_provider._fetch_raw", return_value=None):
            with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                with patch("config.SECTOR_MAP", {}):
                    from nse_preopen_provider import NSEPreOpenProvider
                    p = NSEPreOpenProvider(["INFY"])
                    h = p.health_check()
        self.assertEqual(h["status"], "UNAVAILABLE")


# ══════════════════════════════════════════════════════════════════════════════
# KITE PROVIDER TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestKiteProviderNoSession(unittest.TestCase):
    """Kite provider must degrade gracefully without KITE_ACCESS_TOKEN."""

    def setUp(self):
        self._env = {k: v for k, v in os.environ.items()
                     if k not in ("KITE_ACCESS_TOKEN", "ZERODHA_API_KEY")}

    def test_health_check_unavailable_without_token(self):
        with patch.dict(os.environ, self._env, clear=True):
            with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                with patch("config.SECTOR_MAP", {}):
                    from kite_preopen_provider import KitePreOpenProvider
                    p = KitePreOpenProvider(["INFY"])
                    h = p.health_check()
        self.assertEqual(h["status"], "UNAVAILABLE")

    def test_fetch_market_returns_empty_without_token(self):
        with patch.dict(os.environ, self._env, clear=True):
            with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                with patch("config.SECTOR_MAP", {}):
                    from kite_preopen_provider import KitePreOpenProvider
                    p = KitePreOpenProvider(["INFY"])
                    snaps = p.fetch_market_snapshot()
        self.assertEqual(snaps, [])

    def test_order_book_always_false(self):
        with patch.dict(os.environ, self._env, clear=True):
            with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                with patch("config.SECTOR_MAP", {}):
                    from kite_preopen_provider import KitePreOpenProvider
                    p = KitePreOpenProvider(["INFY"])
                    # Simulate a successful quote
                    quote = {"last_price": 1147.0, "volume": 50000, "ohlc": {"close": 1105.7, "open": 1000.0}}
                    snap = p._normalize(quote, "INFY")
        if snap:
            self.assertFalse(snap.order_book_available)

    def test_kite_gap_calculation(self):
        with patch.dict(os.environ, self._env, clear=True):
            with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
                with patch("config.SECTOR_MAP", {}):
                    from kite_preopen_provider import KitePreOpenProvider
                    p = KitePreOpenProvider(["INFY"])
                    quote = {"last_price": 1147.0, "volume": 50000, "ohlc": {"close": 1105.7, "open": 1000.0}}
                    snap = p._normalize(quote, "INFY")
        if snap:
            expected = round((1147.0 - 1105.7) / 1105.7 * 100, 4)
            self.assertAlmostEqual(snap.gap_percent, expected, places=2)
            self.assertEqual(snap.data_source, "zerodha_kite")

    def test_is_available_false_without_token(self):
        with patch.dict(os.environ, self._env, clear=True):
            from kite_preopen_provider import KitePreOpenProvider
            result = KitePreOpenProvider.is_available()
        self.assertFalse(result)


# ══════════════════════════════════════════════════════════════════════════════
# YAHOO FALLBACK TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestYahooFallback(unittest.TestCase):
    """Yahoo Finance provider must work correctly as a fallback."""

    def setUp(self):
        with patch("config.DEFAULT_WATCHLIST", ["INFY"]):
            with patch("config.SECTOR_MAP", {}):
                from preopen_provider import YFinancePreOpenProvider
                self.p = YFinancePreOpenProvider(["INFY"])

    def test_provider_label_is_fallback(self):
        self.assertEqual(self.p.PROVIDER_LABEL, "Yahoo Finance (Fallback)")

    def test_provider_id_is_yfinance(self):
        self.assertEqual(self.p.PROVIDER_ID, "yfinance")

    def test_order_book_not_available(self):
        raw = {"previous_close": 1105.7, "open_price": 1147.0, "volume": 50000,
               "buy_qty": 0, "sell_qty": 0, "age_seconds": 60, "company_name": "INFY"}
        snap = self.p.normalize_response(raw, "INFY")
        self.assertIsNotNone(snap)
        self.assertFalse(snap.order_book_available)

    def test_data_source_yfinance(self):
        raw = {"previous_close": 1105.7, "open_price": 1147.0, "volume": 50000,
               "buy_qty": 0, "sell_qty": 0, "age_seconds": 60, "company_name": "INFY"}
        snap = self.p.normalize_response(raw, "INFY")
        self.assertEqual(snap.data_source, "yfinance")
        self.assertEqual(snap.provider_label, "Yahoo Finance (Fallback)")

    def test_gap_computed_from_open_price(self):
        raw = {"previous_close": 1105.7, "open_price": 1147.0, "volume": 50000,
               "buy_qty": 0, "sell_qty": 0, "age_seconds": 60, "company_name": "INFY"}
        snap = self.p.normalize_response(raw, "INFY")
        expected = round((1147.0 - 1105.7) / 1105.7 * 100, 4)
        self.assertAlmostEqual(snap.gap_percent, expected, places=2)

    def test_gap_zero_when_no_open_price(self):
        raw = {"previous_close": 1105.7, "open_price": None, "volume": 50000,
               "buy_qty": 0, "sell_qty": 0, "age_seconds": 60, "company_name": "INFY"}
        snap = self.p.normalize_response(raw, "INFY")
        self.assertEqual(snap.gap_percent, 0.0)

    def test_rejected_when_no_prev_close(self):
        raw = {"previous_close": 0, "open_price": 1147.0, "volume": 50000,
               "buy_qty": 0, "sell_qty": 0}
        snap = self.p.normalize_response(raw, "INFY")
        self.assertIsNone(snap)

    def test_imbalance_zero_not_supplied(self):
        raw = {"previous_close": 1105.7, "open_price": 1147.0, "volume": 50000,
               "buy_qty": 0, "sell_qty": 0, "age_seconds": 60, "company_name": "INFY"}
        snap = self.p.normalize_response(raw, "INFY")
        self.assertEqual(snap.imbalance_percent, 0.0)
        self.assertFalse(snap.order_book_available)  # 0 is "not supplied", not real 0


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER MANAGER / FAILOVER TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestProviderManagerFailover(unittest.TestCase):
    """Provider manager must select the highest-priority available provider."""

    def setUp(self):
        # Reset manager cache before each test
        import preopen_provider_manager as mgr
        mgr._cached_provider    = None
        mgr._cached_provider_ts = 0.0
        mgr._cached_symbol_key  = None

    def test_nse_wins_when_available(self):
        from preopen_data_model import ProviderState
        mock_nse = MagicMock()
        mock_nse.health_check.return_value = {"status": ProviderState.LIVE, "provider": "NSE Official"}
        mock_nse.PROVIDER_LABEL = "NSE Official"

        with patch("preopen_provider_manager._try_nse", return_value=(mock_nse, "NSE Official")):
            from preopen_provider_manager import get_best_provider
            p, label = get_best_provider(["INFY"], force=True)
        self.assertEqual(label, "NSE Official")
        self.assertIs(p, mock_nse)

    def test_kite_wins_when_nse_unavailable(self):
        from preopen_data_model import ProviderState
        mock_kite = MagicMock()
        mock_kite.PROVIDER_LABEL = "Zerodha Kite"
        mock_kite.health_check.return_value = {"status": ProviderState.LIVE}

        with patch("preopen_provider_manager._try_nse",  return_value=(None, "")):
            with patch("preopen_provider_manager._try_kite", return_value=(mock_kite, "Zerodha Kite")):
                from preopen_provider_manager import get_best_provider
                p, label = get_best_provider(["INFY"], force=True)
        self.assertEqual(label, "Zerodha Kite")

    def test_kite_uses_a_durable_session_without_legacy_env_token(self):
        """Fresh processes must select Kite from Phase-20 state alone."""
        from preopen_data_model import ProviderState
        import preopen_provider_manager as mgr

        with patch.dict(os.environ, {"ZERODHA_API_KEY": "test-key"}, clear=True):
            with patch("kite_preopen_provider.resolve_preopen_token",
                       return_value="durable-token"):
                with patch("kite_preopen_provider.KitePreOpenProvider") as MockKite:
                    MockKite.PROVIDER_LABEL = "Zerodha Kite"
                    MockKite.return_value.health_check.return_value = {
                        "status": ProviderState.LIVE,
                    }
                    provider, label = mgr._try_kite(["INFY"])
        self.assertIs(provider, MockKite.return_value)
        self.assertEqual(label, "Zerodha Kite")
        MockKite.assert_called_once_with(["INFY"])

    def test_kite_refuses_legacy_token_when_durable_store_is_unreachable(self):
        """A Phase-20 outage must fail closed rather than revive a stale token."""
        import preopen_provider_manager as mgr

        with patch.dict(os.environ, {
            "ZERODHA_API_KEY": "test-key",
            "KITE_ACCESS_TOKEN": "legacy-token",
        }, clear=True):
            with patch("kite_token_store._db_load",
                       side_effect=RuntimeError("durable store unavailable")):
                with patch("kite_preopen_provider.KitePreOpenProvider") as MockKite:
                    provider, label = mgr._try_kite(["INFY"])
        self.assertIsNone(provider)
        self.assertEqual(label, "")
        MockKite.assert_not_called()

    def test_yahoo_wins_when_nse_and_kite_unavailable(self):
        mock_yf = MagicMock()
        mock_yf.PROVIDER_LABEL = "Yahoo Finance (Fallback)"

        with patch("preopen_provider_manager._try_nse",      return_value=(None, "")):
            with patch("preopen_provider_manager._try_kite", return_value=(None, "")):
                with patch("preopen_provider_manager._try_yfinance", return_value=(mock_yf, "Yahoo Finance (Fallback)")):
                    from preopen_provider_manager import get_best_provider
                    p, label = get_best_provider(["INFY"], force=True)
        self.assertEqual(label, "Yahoo Finance (Fallback)")

    def test_provider_chain_status_shape(self):
        with patch("nse_preopen_provider.NSEPreOpenProvider") as MockNSE:
            with patch("kite_preopen_provider.KitePreOpenProvider") as MockKite:
                with patch("preopen_provider.YFinancePreOpenProvider") as MockYF:
                    from preopen_data_model import ProviderState
                    MockNSE.return_value.health_check.return_value = {"status": ProviderState.LIVE, "provider": "NSE Official"}
                    MockKite.return_value.health_check.return_value = {"status": ProviderState.UNAVAILABLE}
                    MockYF.return_value.health_check.return_value  = {"status": ProviderState.DELAYED}
                    from preopen_provider_manager import provider_chain_status
                    result = provider_chain_status(["INFY"])
        self.assertIn("active_provider", result)
        self.assertIn("providers", result)
        self.assertIn("nse_official",  result["providers"])
        self.assertIn("zerodha_kite",  result["providers"])
        self.assertIn("yahoo_finance", result["providers"])

    def test_cache_reused_within_ttl(self):
        mock_nse = MagicMock()
        mock_nse.PROVIDER_LABEL = "NSE Official"
        call_count = [0]

        def side_effect(syms):
            call_count[0] += 1
            return (mock_nse, "NSE Official")

        with patch("preopen_provider_manager._try_nse", side_effect=side_effect):
            import preopen_provider_manager as mgr
            mgr._cached_provider    = None
            mgr._cached_provider_ts = 0.0
            p1, _ = mgr.get_best_provider(["INFY"], force=True)
            p2, _ = mgr.get_best_provider(["INFY"])       # should hit cache
        self.assertEqual(call_count[0], 1)                # only one real probe
        self.assertIs(p1, p2)

    def test_cache_is_not_reused_for_a_different_requested_universe(self):
        import preopen_provider_manager as mgr
        first = MagicMock()
        second = MagicMock()
        providers = iter([(first, "NSE Official"), (second, "NSE Official")])

        with patch("preopen_provider_manager._try_nse",
                   side_effect=lambda symbols: next(providers)) as choose:
            p1, _ = mgr.get_best_provider(["ALPHA", "BETA"], force=True)
            p2, _ = mgr.get_best_provider(["ALPHA", "BETA"])
            p3, _ = mgr.get_best_provider(["GAMMA"])

        self.assertIs(p1, first)
        self.assertIs(p2, first)
        self.assertIs(p3, second)
        self.assertEqual(choose.call_count, 2)
        self.assertEqual(choose.call_args_list[0].args[0], ["ALPHA", "BETA"])
        self.assertEqual(choose.call_args_list[1].args[0], ["GAMMA"])


# ══════════════════════════════════════════════════════════════════════════════
# MODEL / to_dict TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestModelFields(unittest.TestCase):
    """PreOpenSnapshot must expose order_book_available and provider_label."""

    def _snap(self, **kw):
        from preopen_data_model import PreOpenSnapshot
        defaults = dict(
            snapshot_id="t1", trading_date="2026-07-29",
            timestamp_ist="2026-07-29T09:00:00Z",
            symbol="INFY", company_name="INFY", sector="IT",
            previous_close=1105.7,
        )
        defaults.update(kw)
        return PreOpenSnapshot(**defaults)

    def test_order_book_available_default_false(self):
        s = self._snap()
        self.assertFalse(s.order_book_available)

    def test_order_book_available_in_to_dict(self):
        s = self._snap(order_book_available=True)
        d = s.to_dict()
        self.assertIn("order_book_available", d)
        self.assertTrue(d["order_book_available"])

    def test_provider_label_default(self):
        s = self._snap()
        self.assertEqual(s.provider_label, "Yahoo Finance (Fallback)")

    def test_provider_label_nse_in_to_dict(self):
        s = self._snap(provider_label="NSE Official")
        d = s.to_dict()
        self.assertEqual(d["provider_label"], "NSE Official")

    def test_gap_formula(self):
        from preopen_data_model import PreOpenSnapshot
        from preopen_analytics import calc_gap_percent
        gap = calc_gap_percent(1147.0, 1105.7)
        expected = round((1147.0 - 1105.7) / 1105.7 * 100, 4)
        self.assertAlmostEqual(gap, expected, places=2)

    def test_imbalance_formula(self):
        from preopen_analytics import calc_imbalance_percent
        result = calc_imbalance_percent(306884, 163277)
        total = 306884 + 163277
        expected = round((306884 - 163277) / total * 100, 4)
        self.assertAlmostEqual(result, expected, places=2)


# ══════════════════════════════════════════════════════════════════════════════
# AST SAFETY SCAN
# ══════════════════════════════════════════════════════════════════════════════

class TestASTSafety(unittest.TestCase):
    _FORBIDDEN = ["place_order","order_place","kite.order",
                  "execute_buy","execute_sell","submit_order"]
    _ADVISORY  = "PAPER TRADING / ADVISORY ONLY"

    def _files(self):
        import pathlib
        return [
            pathlib.Path(__file__).parent / "nse_preopen_provider.py",
            pathlib.Path(__file__).parent / "kite_preopen_provider.py",
            pathlib.Path(__file__).parent / "preopen_provider_manager.py",
        ]

    def test_no_forbidden_calls(self):
        import ast
        violations = []
        for fp in self._files():
            for node in ast.walk(ast.parse(fp.read_text())):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                    for bad in self._FORBIDDEN:
                        if bad in name:
                            violations.append(f"{fp.name}:{node.lineno}: {name}")
        self.assertEqual(violations, [])

    def test_advisory_label_present(self):
        missing = [fp.name for fp in self._files()
                   if self._ADVISORY not in fp.read_text()]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
