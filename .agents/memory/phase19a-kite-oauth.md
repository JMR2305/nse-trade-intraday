---
name: Phase 19A Kite OAuth flow
description: Backend-only Zerodha Kite Connect token exchange design and test-stub pitfalls
---

# Kite OAuth (Phase 19A)

- Access token lives only in a chmod-600 file next to the python modules; `apply_to_env()` at process start makes all legacy env-readers pick it up. Stored token > env token.
- Request token flows Express → Python via env var `KITE_REQUEST_TOKEN`, never argv (argv is visible in `ps`).
- **Why:** Kite secrets (api_secret, checksum, request/access tokens) must never reach responses, logs, or frontend; pino serializer already strips query strings from logged URLs.
- Callback must require `status === "success"` strictly (missing status = reject) and validate request_token with `^[A-Za-z0-9]{8,64}$`.
- AUTH_FAILED connection state is persisted via a small `.kite_auth_state.json` marker with a 10-min TTL; cleared on successful exchange or disconnect. Check it *before* the credentials_present → LOGIN_REQUIRED early return.

# Test pitfall: module-level kiteconnect stubs collide

Both test_phase19.py and test_phase19a.py install a `kiteconnect` stub into `sys.modules` at import time. When unittest loads multiple modules, the last-loaded stub wins for ALL tests. **How to apply:** every test base class must re-install its own stub in `setUp()`, and re-patch `_STORE_PATH`/`_AUTH_STATE_PATH` after any `_reload("kite_session_manager")`.
