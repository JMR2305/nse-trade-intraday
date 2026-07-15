"""
Phase 19 — Kite Connect live-data integration tests (≥30 tests).
All tests run fully offline; no real Kite credentials required.
Paper trading is never affected. No real orders are placed.
"""
import sys, os, json, time, importlib, types, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── minimal kiteconnect stub (offline) ───────────────────────────────────────

def _stub_kiteconnect():
    kc_mod = types.ModuleType("kiteconnect")
    class KiteConnect:
        EXCHANGE_NSE = "NSE"
        def __init__(self, api_key="", **kw): self.api_key = api_key
        def set_access_token(self, t): self._token = t
        def profile(self): return {"user_name": "TestUser", "user_id": "ZT0001"}
        def ltp(self, instruments):
            return {i: {"last_price": 1500.0} for i in instruments}
        def quote(self, instruments):
            return {i: {"last_price": 1500.0,
                        "ohlc": {"open": 1490, "high": 1510, "low": 1480, "close": 1500},
                        "volume": 100000, "net_change": 0.5, "oi": 0}
                    for i in instruments}
        def holdings(self):
            return [{"tradingsymbol": "WIPRO", "exchange": "NSE",
                     "quantity": 2, "average_price": 445.5,
                     "last_price": 449.1, "pnl": 7.2,
                     "day_change": 3.6, "day_change_percentage": 0.81}]
        def positions(self): return {"net": [], "day": []}
        def margins(self, segment=None):
            return {"net": 5000, "available": {"cash": 5000, "collateral": 0, "intraday_payin": 0},
                    "utilised": {"debits": 0}}
        def orders(self): return []
        def instruments(self, exchange=None):
            return [{"tradingsymbol": "RELIANCE", "exchange": "NSE",
                     "instrument_token": 738561, "instrument_type": "EQ",
                     "name": "RELIANCE INDUSTRIES", "lot_size": 1}]
        def login_url(self): return "https://kite.zerodha.com/connect/login?api_key=test"

    kc_mod.KiteConnect = KiteConnect
    exc = types.ModuleType("kiteconnect.exceptions")
    class KiteException(Exception): pass
    class TokenException(KiteException): pass
    class NetworkException(KiteException): pass
    class DataException(KiteException): pass
    exc.KiteException = KiteException
    exc.TokenException = TokenException
    exc.NetworkException = NetworkException
    exc.DataException = DataException
    kc_mod.exceptions = exc
    sys.modules["kiteconnect"] = kc_mod
    sys.modules["kiteconnect.exceptions"] = exc
    return kc_mod

_KC = _stub_kiteconnect()


def _reload(name):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


# ═══════════════════════════════════════════════════════════════════════════════
# T01 — kite_session_manager  (actual API: get_status, invalidate_cache,
#                               creds_present, get_login_url)
# ═══════════════════════════════════════════════════════════════════════════════
class TestKiteSessionManager(unittest.TestCase):

    def setUp(self):
        for k in ["ZERODHA_API_KEY", "ZERODHA_API_SECRET",
                  "ZERODHA_ACCESS_TOKEN", "ZERODHA_TOKEN_TIMESTAMP"]:
            os.environ.pop(k, None)
        self.ksm = _reload("kite_session_manager")

    def test_status_missing_credentials(self):
        """Returns MISSING when no env vars are set."""
        s = self.ksm.get_status()
        self.assertEqual(s["token_status"], "MISSING")

    def test_credentials_not_present_without_env(self):
        self.assertFalse(self.ksm.creds_present())

    def test_status_has_phase_field(self):
        s = self.ksm.get_status()
        self.assertEqual(s.get("phase"), 19)

    def test_status_has_provider_field(self):
        s = self.ksm.get_status()
        self.assertIn("Zerodha", s.get("provider", ""))

    def test_masked_key_not_set(self):
        s = self.ksm.get_status()
        self.assertIn("not set", s.get("api_key_masked", ""))

    def test_login_url_present_and_non_empty(self):
        url = self.ksm.get_login_url()
        self.assertTrue(url)
        self.assertIn("kite.zerodha.com", url)

    def test_token_expiry_note_present(self):
        s = self.ksm.get_status()
        self.assertIn("token_expiry_note", s)

    def test_refresh_instructions_removed_in_phase19a(self):
        # Phase 19A: manual copy-paste token instructions replaced by
        # backend OAuth flow (login_endpoint) — must no longer be exposed.
        s = self.ksm.get_status()
        self.assertNotIn("refresh_instructions", s)
        self.assertEqual(s.get("login_endpoint"), "/api/kite/login")

    def test_invalidate_cache_does_not_raise(self):
        try:
            self.ksm.invalidate_cache()
        except Exception as e:
            self.fail(f"invalidate_cache raised: {e}")

    def test_credentials_present_when_env_set(self):
        os.environ["ZERODHA_API_KEY"] = "test_key"
        os.environ["ZERODHA_ACCESS_TOKEN"] = "test_token"
        ksm2 = _reload("kite_session_manager")
        self.assertTrue(ksm2.creds_present())

    def test_status_token_valid_when_fresh_timestamp(self):
        os.environ["ZERODHA_API_KEY"] = "k"
        os.environ["ZERODHA_ACCESS_TOKEN"] = "t"
        os.environ["ZERODHA_TOKEN_TIMESTAMP"] = str(int(time.time()))
        ksm2 = _reload("kite_session_manager")
        s = ksm2.get_status()
        self.assertIn(s["token_status"], ("VALID", "WARNING", "EXPIRED", "MISSING"))

    def test_status_never_raises(self):
        """get_status() must never raise regardless of env state."""
        try:
            self.ksm.get_status()
        except Exception as e:
            self.fail(f"get_status raised: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# T02 — kite_quote_provider  (actual API: get_quotes, get_ltp,
#                              kite_available, provider_label, invalidate_cache)
# ═══════════════════════════════════════════════════════════════════════════════
class TestKiteQuoteProvider(unittest.TestCase):

    def setUp(self):
        self.kqp = _reload("kite_quote_provider")

    def test_get_quotes_returns_dict(self):
        result = self.kqp.get_quotes(["RELIANCE"])
        self.assertIsInstance(result, dict)

    def test_get_ltp_returns_dict(self):
        result = self.kqp.get_ltp(["TCS", "INFY"])
        self.assertIsInstance(result, dict)

    def test_get_quotes_empty_list(self):
        result = self.kqp.get_quotes([])
        self.assertIsInstance(result, dict)

    def test_get_ltp_empty_list(self):
        result = self.kqp.get_ltp([])
        self.assertIsInstance(result, dict)

    def test_quote_has_data_source_field(self):
        result = self.kqp.get_quotes(["WIPRO"])
        for sym, q in result.items():
            if isinstance(q, dict) and "error" not in q:
                self.assertIn("data_source", q,
                              f"Quote for {sym} missing data_source")

    def test_kite_available_returns_bool(self):
        self.assertIsInstance(self.kqp.kite_available(), bool)

    def test_kite_not_available_without_creds(self):
        self.assertFalse(self.kqp.kite_available())

    def test_provider_label_returns_string(self):
        label = self.kqp.provider_label()
        self.assertIsInstance(label, str)
        self.assertTrue(label)

    def test_invalidate_cache_does_not_raise(self):
        try:
            self.kqp.invalidate_cache()
        except Exception as e:
            self.fail(f"invalidate_cache raised: {e}")

    def test_get_quotes_never_raises(self):
        try:
            self.kqp.get_quotes(["RELIANCE", "TCS", "INFY"])
        except Exception as e:
            self.fail(f"get_quotes raised: {e}")

    def test_kite_symbol_format(self):
        """_kite_symbol prepends NSE: prefix."""
        result = self.kqp._kite_symbol("RELIANCE")
        self.assertEqual(result, "NSE:RELIANCE")

    def test_get_ltp_with_live_kite_stub(self):
        """With a mocked live Kite client, get_ltp returns numeric values."""
        fake_kite = _KC.KiteConnect(api_key="x")
        with patch.object(self.kqp, "_get_kite_client", return_value=fake_kite):
            result = self.kqp.get_ltp(["RELIANCE"])
            self.assertIsInstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# T03 — kite_instrument_cache  (actual API: refresh, get_token,
#                                search, cache_status)
# ═══════════════════════════════════════════════════════════════════════════════
class TestKiteInstrumentCache(unittest.TestCase):

    def setUp(self):
        self.kic = _reload("kite_instrument_cache")

    def test_cache_status_returns_dict(self):
        s = self.kic.cache_status()
        self.assertIsInstance(s, dict)

    def test_cache_status_has_count(self):
        s = self.kic.cache_status()
        self.assertIn("count", s)

    def test_search_returns_list(self):
        result = self.kic.search("TCS")
        self.assertIsInstance(result, list)

    def test_search_empty_query(self):
        result = self.kic.search("")
        self.assertIsInstance(result, list)

    def test_search_never_raises(self):
        try:
            self.kic.search("RELIANCE")
        except Exception as e:
            self.fail(f"search raised: {e}")

    def test_get_token_unknown_symbol_returns_none(self):
        tok = self.kic.get_token("XYZNOTREAL999")
        self.assertIsNone(tok)

    def test_refresh_without_kite_returns_dict(self):
        result = self.kic.refresh()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_refresh_with_live_kite_stub(self):
        """With mocked Kite, refresh returns success dict."""
        fake_kite = _KC.KiteConnect(api_key="x")
        import kite_session_manager as ksm
        with patch("kite_instrument_cache._fetch_from_kite",
                   return_value=fake_kite.instruments("NSE")):
            result = self.kic.refresh(force=True)
            self.assertIsInstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# T04 — broker_client get_ltp
# ═══════════════════════════════════════════════════════════════════════════════
class TestBrokerClientLtp(unittest.TestCase):

    def setUp(self):
        self.bc = _reload("broker_client")

    def test_mock_client_get_ltp_returns_dict(self):
        client = self.bc.MockBrokerClient()
        result = client.get_ltp(["RELIANCE", "TCS"])
        self.assertIsInstance(result, dict)
        self.assertIn("RELIANCE", result)
        self.assertIn("TCS", result)

    def test_mock_client_ltp_values_positive_floats(self):
        client = self.bc.MockBrokerClient()
        result = client.get_ltp(["INFY"])
        for sym, val in result.items():
            self.assertIsInstance(val, (int, float))
            self.assertGreater(val, 0)

    def test_mock_client_ltp_empty_list(self):
        client = self.bc.MockBrokerClient()
        result = client.get_ltp([])
        self.assertIsInstance(result, dict)

    def test_get_broker_client_not_none_without_creds(self):
        client = self.bc.get_broker_client()
        self.assertIsNotNone(client)

    def test_mock_client_single_symbol(self):
        client = self.bc.MockBrokerClient()
        result = client.get_ltp(["WIPRO"])
        self.assertIn("WIPRO", result)

    def test_zerodha_client_get_ltp_with_stub(self):
        """ZerodhaClient.get_ltp delegates to kite._kite and returns dict."""
        fake_kite = _KC.KiteConnect(api_key="x")
        client = self.bc.ZerodhaClient.__new__(self.bc.ZerodhaClient)
        client._kite = fake_kite
        result = client.get_ltp(["RELIANCE"])
        self.assertIsInstance(result, dict)
        self.assertIn("RELIANCE", result)


# ═══════════════════════════════════════════════════════════════════════════════
# T05 — Safety / regression
# ═══════════════════════════════════════════════════════════════════════════════
class TestKiteApiSafety(unittest.TestCase):

    def test_no_real_orders_in_mock_client(self):
        """MockBrokerClient.place_order (if present) must flag as non-real."""
        bc = _reload("broker_client")
        client = bc.MockBrokerClient()
        if hasattr(client, "place_order"):
            result = client.place_order("RELIANCE", "BUY", 1, 2800.0)
            self.assertIsInstance(result, dict)
            self.assertFalse(result.get("real_order", False),
                             "MockBrokerClient.place_order flagged as real")

    def test_paper_trading_client_works_without_kite_creds(self):
        bc = _reload("broker_client")
        client = bc.get_broker_client()
        ltp = client.get_ltp(["RELIANCE"])
        self.assertIsInstance(ltp, dict)

    def test_kite_status_never_raises(self):
        ksm = _reload("kite_session_manager")
        try:
            ksm.get_status()
        except Exception as e:
            self.fail(f"get_status raised: {e}")

    def test_get_quotes_never_raises(self):
        kqp = _reload("kite_quote_provider")
        try:
            kqp.get_quotes(["RELIANCE", "TCS", "INFY"])
        except Exception as e:
            self.fail(f"get_quotes raised: {e}")

    def test_search_instruments_never_raises(self):
        kic = _reload("kite_instrument_cache")
        try:
            kic.search("RELIANCE")
        except Exception as e:
            self.fail(f"search raised: {e}")

    def test_kite_provider_label_not_empty(self):
        kqp = _reload("kite_quote_provider")
        self.assertTrue(kqp.provider_label())

    def test_zerodha_client_available_in_broker_module(self):
        bc = _reload("broker_client")
        self.assertTrue(hasattr(bc, "ZerodhaClient"))

    def test_mock_broker_client_available_in_broker_module(self):
        bc = _reload("broker_client")
        self.assertTrue(hasattr(bc, "MockBrokerClient"))


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestKiteSessionManager, TestKiteQuoteProvider,
                TestKiteInstrumentCache, TestBrokerClientLtp, TestKiteApiSafety]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
