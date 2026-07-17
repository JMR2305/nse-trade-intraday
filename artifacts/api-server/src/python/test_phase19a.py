"""
Phase 19A — Secure Zerodha Kite callback flow tests.
All tests run fully offline; no real Kite credentials required.
Paper trading is never affected. No real orders are placed.
"""
import sys, os, json, importlib, types, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── minimal kiteconnect stub (offline) ───────────────────────────────────────

def _stub_kiteconnect(generate_session_ok=True):
    kc_mod = types.ModuleType("kiteconnect")

    class KiteConnect:
        def __init__(self, api_key="", **kw): self.api_key = api_key
        def set_access_token(self, t): self._token = t
        def profile(self): return {"user_name": "TestUser", "user_id": "ZT0001"}
        def generate_session(self, request_token, api_secret=None):
            if not generate_session_ok:
                raise Exception("Token is invalid or has expired")
            assert api_secret, "api_secret must be passed backend-only"
            return {"access_token": "stub_access_token_abc123", "user_id": "ZT0001"}
        def login_url(self):
            return "https://kite.zerodha.com/connect/login?api_key=test"

    kc_mod.KiteConnect = KiteConnect
    exc = types.ModuleType("kiteconnect.exceptions")
    class KiteException(Exception): pass
    class TokenException(KiteException): pass
    exc.KiteException = KiteException
    exc.TokenException = TokenException
    kc_mod.exceptions = exc
    sys.modules["kiteconnect"] = kc_mod
    sys.modules["kiteconnect.exceptions"] = exc
    return kc_mod


_stub_kiteconnect()


def _reload(name):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


SECRET_STRINGS = ("stub_access_token_abc123", "test_secret_xyz", "req_token_12345678")


def _assert_no_secrets(payload, testcase):
    text = json.dumps(payload)
    for s in SECRET_STRINGS:
        testcase.assertNotIn(s, text, f"secret material '{s}' leaked in response")


class Phase19ABase(unittest.TestCase):
    def setUp(self):
        for k in ["ZERODHA_API_KEY", "ZERODHA_API_SECRET",
                  "ZERODHA_ACCESS_TOKEN", "ZERODHA_TOKEN_TIMESTAMP",
                  "KITE_REQUEST_TOKEN"]:
            os.environ.pop(k, None)
        _stub_kiteconnect()  # re-stub in case another test module replaced it
        self.store = _reload("kite_token_store")
        # isolate the token store file per test
        self._store_path = self.store._STORE_PATH + ".test"
        self._auth_path = self.store._AUTH_STATE_PATH + ".test"
        self.store._STORE_PATH = self._store_path
        self.store._AUTH_STATE_PATH = self._auth_path
        # isolate from the Postgres-durable token store (phase19b) — tests must
        # never read from or write to the real database
        self.store._db_load = lambda: None
        self.store._db_save = lambda record: None
        self.ksm = _reload("kite_session_manager")
        # session manager imports kite_token_store lazily; redirect its paths too
        sys.modules["kite_token_store"]._STORE_PATH = self._store_path
        sys.modules["kite_token_store"]._AUTH_STATE_PATH = self._auth_path

    def tearDown(self):
        for p in (self._store_path, self._auth_path):
            try: os.remove(p)
            except FileNotFoundError: pass


# ═══════════════════════════════════════════════════════════════════════════
# Token store
# ═══════════════════════════════════════════════════════════════════════════
class TestTokenStore(Phase19ABase):

    def test_load_empty(self):
        self.assertIsNone(self.store.load())

    def test_save_and_load(self):
        self.store.save_token("stub_access_token_abc123", user_id="ZT0001")
        data = self.store.load()
        self.assertEqual(data["access_token"], "stub_access_token_abc123")
        self.assertEqual(data["user_id"], "ZT0001")
        self.assertTrue(data["created_at"])

    def test_file_permissions_0600(self):
        self.store.save_token("stub_access_token_abc123")
        mode = os.stat(self._store_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_clear(self):
        self.store.save_token("stub_access_token_abc123")
        self.assertTrue(self.store.clear())
        self.assertIsNone(self.store.load())
        self.assertFalse(self.store.clear())

    def test_apply_to_env(self):
        self.store.save_token("stub_access_token_abc123")
        self.store.apply_to_env()
        self.assertEqual(os.environ.get("ZERODHA_ACCESS_TOKEN"), "stub_access_token_abc123")
        self.assertTrue(os.environ.get("ZERODHA_TOKEN_TIMESTAMP"))

    def test_metadata_never_contains_token(self):
        self.store.save_token("stub_access_token_abc123", user_id="ZT0001")
        meta = self.store.metadata()
        self.assertTrue(meta["stored"])
        self.assertNotIn("access_token", meta)
        self.assertNotIn("stub_access_token_abc123", json.dumps(meta))

    def test_save_empty_token_raises(self):
        with self.assertRaises(ValueError):
            self.store.save_token("")


# ═══════════════════════════════════════════════════════════════════════════
# Token exchange
# ═══════════════════════════════════════════════════════════════════════════
class TestExchange(Phase19ABase):

    def test_missing_api_key(self):
        r = self.ksm.exchange_request_token("req_token_12345678")
        self.assertFalse(r["success"])
        self.assertEqual(r["state"], "NOT_CONFIGURED")
        _assert_no_secrets(r, self)

    def test_missing_api_secret(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        r = self.ksm.exchange_request_token("req_token_12345678")
        self.assertFalse(r["success"])
        self.assertEqual(r["state"], "NOT_CONFIGURED")
        self.assertIn("SECRET", r["error"])
        _assert_no_secrets(r, self)

    def test_missing_request_token(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        r = self.ksm.exchange_request_token(None)
        self.assertFalse(r["success"])
        self.assertEqual(r["state"], "AUTH_FAILED")
        _assert_no_secrets(r, self)

    def test_successful_exchange_stores_token(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        r = self.ksm.exchange_request_token("req_token_12345678")
        self.assertTrue(r["success"])
        self.assertEqual(r["state"], "CONNECTED")
        _assert_no_secrets(r, self)
        # token stored on disk, not returned
        data = self.store.load()
        self.assertEqual(data["access_token"], "stub_access_token_abc123")
        # masked user id only
        self.assertNotIn("user_id", {k for k in r if k == "user_id"})
        self.assertIn("user_id_masked", r)
        self.assertNotEqual(r["user_id_masked"], "ZT0001")

    def test_failed_exchange_invalid_token(self):
        _stub_kiteconnect(generate_session_ok=False)
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        ksm = _reload("kite_session_manager")
        r = ksm.exchange_request_token("req_token_12345678")
        self.assertFalse(r["success"])
        self.assertEqual(r["state"], "AUTH_FAILED")
        self.assertIsNone(self.store.load())
        _assert_no_secrets(r, self)
        _stub_kiteconnect()  # restore

    def test_disconnect_clears_token(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        self.ksm.exchange_request_token("req_token_12345678")
        r = self.ksm.disconnect_session()
        self.assertTrue(r["success"])
        self.assertTrue(r["removed"])
        self.assertEqual(r["state"], "LOGIN_REQUIRED")
        self.assertIsNone(self.store.load())
        _assert_no_secrets(r, self)


# ═══════════════════════════════════════════════════════════════════════════
# Connection state + status payload hygiene
# ═══════════════════════════════════════════════════════════════════════════
class TestStatusHygiene(Phase19ABase):

    def test_state_not_configured(self):
        s = self.ksm.get_status(force_probe=True)
        self.assertEqual(s["connection_state"], "NOT_CONFIGURED")

    def test_state_login_required(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        self.ksm.invalidate_cache()
        s = self.ksm.get_status(force_probe=True)
        self.assertEqual(s["connection_state"], "LOGIN_REQUIRED")

    def test_state_connected_after_exchange(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        self.ksm.exchange_request_token("req_token_12345678")
        s = self.ksm.get_status(force_probe=True)
        self.assertEqual(s["connection_state"], "CONNECTED")
        self.assertTrue(s["connected"])
        self.assertTrue(s["token_stored"])
        _assert_no_secrets(s, self)

    def test_status_never_contains_secrets(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        self.ksm.exchange_request_token("req_token_12345678")
        s = self.ksm.get_status(force_probe=True)
        text = json.dumps(s)
        _assert_no_secrets(s, self)
        self.assertNotIn("api_secret", {k: v for k, v in s.items() if k == "api_secret"})
        self.assertNotIn("ZT0001", text)  # raw user id must be masked

    def test_status_exposes_login_endpoint_not_secret(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        s = self.ksm.get_status(force_probe=True)
        self.assertEqual(s.get("login_endpoint"), "/api/kite/login")
        self.assertIn("api_secret_configured", s)
        self.assertIsInstance(s["api_secret_configured"], bool)

    def test_state_auth_failed_after_failed_exchange(self):
        _stub_kiteconnect(generate_session_ok=False)
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        ksm = _reload("kite_session_manager")
        sys.modules["kite_token_store"]._STORE_PATH = self._store_path
        sys.modules["kite_token_store"]._AUTH_STATE_PATH = self._auth_path
        r = ksm.exchange_request_token("req_token_12345678")
        self.assertFalse(r["success"])
        s = ksm.get_status(force_probe=True)
        self.assertEqual(s["connection_state"], "AUTH_FAILED")
        _stub_kiteconnect()  # restore

    def test_auth_failed_cleared_by_successful_exchange(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        self.store.record_auth_failure()
        self.assertTrue(self.store.recent_auth_failure())
        self.ksm.exchange_request_token("req_token_12345678")
        self.assertFalse(self.store.recent_auth_failure())
        s = self.ksm.get_status(force_probe=True)
        self.assertEqual(s["connection_state"], "CONNECTED")

    def test_auth_failed_cleared_by_disconnect(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        os.environ["ZERODHA_API_SECRET"] = "test_secret_xyz"
        self.store.record_auth_failure()
        self.ksm.disconnect_session()
        self.assertFalse(self.store.recent_auth_failure())
        s = self.ksm.get_status(force_probe=True)
        self.assertEqual(s["connection_state"], "LOGIN_REQUIRED")

    def test_no_refresh_instructions_field(self):
        os.environ["ZERODHA_API_KEY"] = "key123"
        s = self.ksm.get_status(force_probe=True)
        self.assertNotIn("refresh_instructions", s)


# ═══════════════════════════════════════════════════════════════════════════
# Safety: no live-order capability
# ═══════════════════════════════════════════════════════════════════════════
class TestSafety(Phase19ABase):

    def test_no_place_order_in_session_manager(self):
        src = open(self.ksm.__file__).read()
        self.assertNotIn("place_order", src)
        self.assertNotIn("modify_order", src)
        self.assertNotIn("cancel_order", src)

    def test_no_order_placement_routes(self):
        route_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "routes", "kite.ts")
        src = open(route_file).read()
        self.assertNotIn("place_order", src)
        self.assertNotIn("modify_order", src)
        self.assertNotIn("cancel_order", src)
        # no POST/PUT/DELETE order endpoints (GET /kite/orders history is read-only)
        self.assertNotIn('router.post("/kite/order', src)
        self.assertNotIn('router.put("/kite/order', src)
        self.assertNotIn('router.delete("/kite/order', src)

    def test_request_token_never_in_argv_command(self):
        main_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        src = open(main_file).read()
        # kite_exchange must read from env, not argv
        self.assertIn("KITE_REQUEST_TOKEN", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
