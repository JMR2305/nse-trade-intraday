---
name: OHLCV cold-start check
description: Design of check_cold_cache_on_startup() and test isolation conventions for the cold-start test suite.
---

## New store primitives (phase20_store.py)

Three new functions added to support crash-safe coordination:

- `kv_claim_with_value(key, value) -> bool` — like kv_claim_once but stores a dict (not True). Used for the initial backfill claim so peers can read `claimed_at` timestamp for grace-period gap detection.
- `kv_acquire_expiring_claim(key, value) -> bool` — INSERT first; if conflict, UPDATE WHERE expires_at < NOW(). Atomically overwrites an expired record. Used for the takeover lease so a SIGKILL'd takeover owner's record can be recovered once its TTL passes.
- `kv_release_if_owned(key, token) -> bool` — DELETE WHERE token matches. Token-conditional: a stale owner whose TTL expired and whose key was overwritten by a new peer cannot delete the new peer's active record.

File-backed fallback: all three have flock-protected JSON equivalents matching the DB semantics.

## Design

`check_cold_cache_on_startup()` runs at server startup via the `ohlcv_cold_start_check` command (registered in `main.py`).

**Cold detection**: `cold_set` = uncached_symbols ∪ missing_required_bars ∪ stale_symbols (STALE/UNAVAILABLE quality that `read_symbol_from_cache` would reject).

**KV coordination keys** (all suffixed with `_today_ist_date()`):
- `ohlcv_cold_start_backfill:` — primary claim (kv_claim_once, never released during takeover)
- `ohlcv_cold_start_backfill_done:` — written on success; non-owners poll this
- `ohlcv_cold_start_lease_started:` — written by owner with `{started_at, lease_expires_at, role, lease_ttl_s}`
- `ohlcv_cold_start_takeover:` — token-fenced expiring record for dead-owner recovery

**Constants**: `_COLD_START_LEASE_TTL_S = 1500` (25 min, covers worst-case 22-min yfinance download), `_COLD_START_WAIT_TIMEOUT_S = 1800` (30 min, always > TTL so peers have budget for takeover), `_COLD_START_POLL_INTERVAL_S = 15`.

**Takeover design** (NOT kv_claim_once — that has no TTL):
- `_acquire_takeover_lease()` nested function reads `takeover_key`, checks its `expires_at`
- If existing record is fresh (unexpired): return False
- If absent or expired: write token record with new `expires_at`, read back to verify token matches (optimistic CAS)
- A takeover owner that is SIGKILL'd leaves an expired token record; next peer overwrites it
- Takeover owner releases `takeover_key` on failure (so a third peer can recover); never releases `claim_key` (dead first owner's claim)
- Dynamic deadline extension: non-owner extends `deadline_mono` when lease is still fresh so it never times out before TTL expires

**Node-side gate**: `_ohlcvColdStartPending` flag in `scanScheduler.ts`; set `true` at `startScanScheduler()` entry; cleared in `.finally()`; `_tick()` skips `scheduled_scan_tick` while flag is `true`. `_runTickForTests()` exported for tests.

## Test isolation (ColdStartTestCase)

`test_ohlcv_cold_start_check.py` injects stubs into `sys.modules`. Key rules:

1. **`_install_base_stubs()`**: only creates `phase20_store` if not already present (avoids replacing another test file's stub object and breaking tests that hold references to it via `sys.modules["phase20_store"]._kv`).

2. **`ColdStartTestCase` base class**: all 8 test classes inherit from it. `setUp()` saves current kv_*/get_settings/… attributes from the shared module and overlays `_KV`'s methods; `addCleanup(_restore_store)` restores originals after each test. This keeps the shared `phase20_store` object intact while giving cold-start tests a clean KV dict per test.

3. **`teardown_module()`**: removes only `ohlcv_cache_store` and `config` from sys.modules (per-test stubs that would confuse integration tests trying to patch real attributes). Does NOT remove `phase20_store` or `phase3f_logging`.

**Why:** `test_eod_reconciliation.py` (alphabetically before this file) installs its own `phase20_store` stub at module level and its setUp does `sys.modules["phase20_store"]._kv`. Replacing the module object in `_install_base_stubs()` broke eod tests. Overwriting `kv_get` at module level also broke eod (state in `_kv`, but `kv_get` now reads `_KV._data`). Per-test save/restore is the only isolation pattern that works.
