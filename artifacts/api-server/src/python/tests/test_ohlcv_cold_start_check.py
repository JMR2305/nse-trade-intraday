"""
tests/test_ohlcv_cold_start_check.py
Unit tests for phase20_scheduler.check_cold_cache_on_startup().

All tests are self-contained: no DB, no yfinance, no live modules.
Every external dependency is stubbed via sys.modules injection.

Covers:
  - Warm cache (no claim acquired, no backfill)
  - Owner path: claim acquired, backfill runs, done_key written
  - Owner failure: exception raised, claim released, backfill_failed returned
  - Non-owner path: claim already taken, polls done_key, returns on completion
  - Non-owner timeout: polls until timeout, returns peer_timeout
  - OHLCV_CACHE_ENABLED=false guard
  - Config / store import error paths
  - Result key completeness
"""

from __future__ import annotations

import sys
import types
import time
import unittest
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Minimal stub infrastructure
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------------------
# sys.modules isolation
# ---------------------------------------------------------------------------
# This file needs `phase20_store` in sys.modules so that
# `import phase20_scheduler as sched` succeeds at module load time.
# Other test files collected before this one (e.g. test_eod_reconciliation.py)
# may have already installed their own stub for that name.  We must NOT
# replace their stub object: their setUp methods hold a reference to the
# same object and set attributes (like `_kv`) directly on it; replacing the
# object with a new one breaks those tests.
#
# Strategy
# ─────────
# 1. _install_base_stubs()  ← module level, runs once at collection time
#    • If phase20_store already exists → leave it alone (only create the
#      stub if the slot is empty).
#    • phase3f_logging is always created fresh (no other test file uses it).
#    • ohlcv_cache_store and config are created fresh per-test via
#      _install_cache_stubs() / _make_stub("config") — they are never
#      installed here.
#
# 2. ColdStartTestCase.setUp()  ← per-test
#    • Saves the current kv_get/kv_set/… attributes on whichever
#      phase20_store module is in sys.modules (could be ours or another
#      test file's), then overwrites them with _KV's methods.
#    • Registers addCleanup(_restore_store) so the attributes are put back
#      after each test, leaving the shared module in its pre-test state.
#
# 3. teardown_module()  ← after all cold-start tests finish
#    • Removes ohlcv_cache_store and config from sys.modules (both are
#      created fresh per-test; leaving them risks polluting integration
#      tests that try to patch real attributes on the stub).
#    • Does NOT touch phase20_store or phase3f_logging (other test files
#      may still need them).

_COLD_START_KV_ATTRS = (
    "kv_get", "kv_set", "kv_claim_once", "kv_release", "add_notification",
    "get_settings", "update_scheduler_state", "record_scan_run", "get_scheduler_health",
    # New primitives used by check_cold_cache_on_startup:
    "kv_claim_with_value", "kv_acquire_expiring_claim", "kv_release_if_owned",
)

# Names installed per-test that must be cleaned up after this suite.
_PER_TEST_STUB_NAMES = ("ohlcv_cache_store", "config")


def teardown_module(module: object) -> None:  # noqa: ARG001
    """Remove per-test stub modules so later test files import the real ones."""
    for name in _PER_TEST_STUB_NAMES:
        sys.modules.pop(name, None)


class _KVStore:
    """In-memory KV store mirroring phase20_store's kv_* API.

    Includes the three new primitives used by check_cold_cache_on_startup:
    * kv_claim_with_value — atomic claim storing a dict value
    * kv_acquire_expiring_claim — claim or overwrite expired record
    * kv_release_if_owned — token-conditional delete
    """

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self.notifications: List[Dict[str, Any]] = []

    def kv_get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def kv_set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def kv_claim_once(self, key: str, ttl_seconds: int = 0) -> bool:
        if key in self._data:
            return False
        self._data[key] = True
        return True

    def kv_claim_with_value(self, key: str, value: Any) -> bool:
        """Atomic claim: only the first caller wins; stores value (not True)."""
        if key in self._data:
            return False
        self._data[key] = value
        return True

    def kv_acquire_expiring_claim(self, key: str, value: Any) -> bool:
        """Claim or overwrite an expired record whose value['expires_at'] < now.

        This is the crash-safe takeover primitive.  A dead owner that never
        ran cleanup leaves a record with an expires_at.  Once that time passes
        any peer can overwrite it — atomically — and become the new owner.
        """
        from datetime import datetime, timezone
        existing = self._data.get(key)
        if existing is not None:
            if isinstance(existing, dict):
                exp_iso = str(existing.get("expires_at") or "")
                if exp_iso:
                    try:
                        exp_dt = datetime.fromisoformat(exp_iso)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc).timestamp() < exp_dt.timestamp():
                            return False  # Fresh record; cannot overwrite
                    except Exception:
                        pass
                    # Expired or malformed → overwrite below
                else:
                    return False  # No expiry info → treat as permanent
            else:
                return False  # Non-dict claim → treat as permanent
        self._data[key] = value
        return True

    def kv_release(self, key: str) -> None:
        self._data.pop(key, None)

    def kv_release_if_owned(self, key: str, token: str) -> bool:
        """Delete key only if the stored value['token'] matches token."""
        existing = self._data.get(key)
        if not (isinstance(existing, dict) and existing.get("token") == token):
            return False
        del self._data[key]
        return True

    def add_notification(self, kind: str, title: str, body: str = "",
                         severity: str = "INFO", context: Any = None) -> None:
        self.notifications.append({"kind": kind, "title": title})

    def reset(self) -> None:
        self._data.clear()
        self.notifications.clear()


_KV = _KVStore()


def _install_base_stubs() -> None:
    """Install the minimum stubs needed to import phase20_scheduler.

    phase20_store: only created if not already in sys.modules.  If another
    test file already installed its stub, we leave it intact — we will
    overlay the kv_* functions per-test via ColdStartTestCase.setUp().

    phase3f_logging: always created fresh (no other test file uses it).
    """
    # phase20_store ─── leave existing stub untouched; create only if absent
    if "phase20_store" not in sys.modules:
        store = _make_stub("phase20_store")
        store.kv_get = _KV.kv_get
        store.kv_set = _KV.kv_set
        store.kv_claim_once = _KV.kv_claim_once
        store.kv_claim_with_value = _KV.kv_claim_with_value
        store.kv_acquire_expiring_claim = _KV.kv_acquire_expiring_claim
        store.kv_release = _KV.kv_release
        store.kv_release_if_owned = _KV.kv_release_if_owned
        store.add_notification = _KV.add_notification
        store.get_settings = MagicMock(return_value={
            "auto_scan_enabled": True, "scan_interval_minutes": 5,
        })
        store.update_scheduler_state = MagicMock()
        store.record_scan_run = MagicMock()
        store.get_scheduler_health = MagicMock(return_value={})

    p3f = _make_stub("phase3f_logging")
    p3f.get_logger = MagicMock(return_value=MagicMock())


_install_base_stubs()
import phase20_scheduler as sched  # noqa: E402


# ---------------------------------------------------------------------------
# Per-test KV stub isolation
# ---------------------------------------------------------------------------

class ColdStartTestCase(unittest.TestCase):
    """Base class for all cold-start tests.

    setUp() saves the current kv_*/get_settings/… attributes from the
    shared phase20_store module and replaces them with _KV's methods.
    addCleanup restores the originals so other test files' stubs are
    left intact after each test in this suite.
    """

    def setUp(self) -> None:  # noqa: N802
        _KV.reset()
        # config: install a fresh stub for every test so each test gets the
        # canonical NIFTY_50 symbol list; per-test overrides are isolated.
        _make_stub("config").NIFTY_50 = SYMBOLS_50
        store = sys.modules["phase20_store"]
        # Save current attribute values (may be from another test file's stub).
        self._orig_store_attrs: Dict[str, Any] = {
            attr: getattr(store, attr, None)
            for attr in _COLD_START_KV_ATTRS
        }
        # Install cold-start stubs on the shared module.
        store.kv_get = _KV.kv_get
        store.kv_set = _KV.kv_set
        store.kv_claim_once = _KV.kv_claim_once
        store.kv_claim_with_value = _KV.kv_claim_with_value
        store.kv_acquire_expiring_claim = _KV.kv_acquire_expiring_claim
        store.kv_release = _KV.kv_release
        store.kv_release_if_owned = _KV.kv_release_if_owned
        store.add_notification = _KV.add_notification
        store.get_settings = MagicMock(return_value={
            "auto_scan_enabled": True, "scan_interval_minutes": 5,
        })
        store.update_scheduler_state = MagicMock()
        store.record_scan_run = MagicMock()
        store.get_scheduler_health = MagicMock(return_value={})
        self.addCleanup(self._restore_store)

    def _restore_store(self) -> None:
        store = sys.modules.get("phase20_store")
        if store is None:
            return
        for attr, val in self._orig_store_attrs.items():
            if val is None:
                try:
                    delattr(store, attr)
                except AttributeError:
                    pass
            else:
                setattr(store, attr, val)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYMBOLS_50 = [f"SYM{i:02d}" for i in range(50)]

_CLAIM_KEY_PREFIX    = "ohlcv_cold_start_backfill:"
_DONE_KEY_PREFIX     = "ohlcv_cold_start_backfill_done:"
_LEASE_STARTED_PREFIX = "ohlcv_cold_start_lease_started:"
_TAKEOVER_KEY_PREFIX  = "ohlcv_cold_start_takeover:"


def _today() -> str:
    return sched._today_ist_date()


def _cold_summary(
    n_uncached: int = 50,
    n_missing: int = 0,
    n_stale: int = 0,
) -> Dict[str, Any]:
    uncached = SYMBOLS_50[:n_uncached]
    missing  = SYMBOLS_50[n_uncached:n_uncached + n_missing]
    stale    = SYMBOLS_50[n_uncached + n_missing:n_uncached + n_missing + n_stale]
    live     = 50 - n_uncached - n_missing - n_stale
    return {
        "total_symbols": 50,
        "uncached_symbols": uncached,
        "missing_required_bars": missing,
        "stale_symbols": stale,
        "cache_hit_rate_pct": round(live / 50 * 100, 1),
    }


def _warm_summary() -> Dict[str, Any]:
    return {
        "total_symbols": 50,
        "uncached_symbols": [],
        "missing_required_bars": [],
        "stale_symbols": [],
        "cache_hit_rate_pct": 100.0,
    }


def _backfill_ok(n_updated: int = 50, n_failed: int = 0) -> Dict[str, Any]:
    return {
        "success": True,
        "refresh_type": "backfill",
        "symbols_requested": 50,
        "symbols_updated": n_updated,
        "symbols_skipped": 0,
        "symbols_failed": n_failed,
        "failed_symbols": SYMBOLS_50[:n_failed],
        "skipped_symbols": [],
        "duration_seconds": 143.7,
        "status": "SUCCESS" if n_failed == 0 else "PARTIAL",
    }


def _done_record(n_updated: int = 50, n_failed: int = 0) -> Dict[str, Any]:
    return {
        "status": "SUCCESS" if n_failed == 0 else "PARTIAL",
        "symbols_updated": n_updated,
        "symbols_skipped": 0,
        "symbols_failed": n_failed,
        "failed_symbols": SYMBOLS_50[:n_failed],
        "duration_seconds": 143.7,
        "completed_at": "2026-08-18T10:00:00Z",
    }


def _install_cache_stubs(
    summary: Dict[str, Any] = None,
    backfill_result: Dict[str, Any] = None,
    cache_enabled: bool = True,
    summary_raises: bool = False,
    backfill_raises: bool = False,
) -> types.ModuleType:
    if summary is None:
        summary = _warm_summary()
    if backfill_result is None:
        backfill_result = _backfill_ok()

    cache_mod = _make_stub("ohlcv_cache_store")
    cache_mod.OHLCV_CACHE_ENABLED = cache_enabled
    cache_mod.ensure_tables = MagicMock()
    cache_mod.get_overall_cache_summary = (
        MagicMock(side_effect=RuntimeError("db down"))
        if summary_raises
        else MagicMock(return_value=summary)
    )
    cache_mod.backfill_all_symbols = (
        MagicMock(side_effect=RuntimeError("yfinance failed"))
        if backfill_raises
        else MagicMock(return_value=backfill_result)
    )
    return cache_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestColdCacheCheckWarmCache(ColdStartTestCase):
    """Warm cache: claim is never acquired, backfill never runs."""


    def test_warm_returns_no_op(self):
        _install_cache_stubs(summary=_warm_summary())
        result = sched.check_cold_cache_on_startup()
        self.assertTrue(result.get("ran"))
        self.assertEqual(result.get("action"), "no_op")

    def test_warm_never_acquires_claim(self):
        _install_cache_stubs(summary=_warm_summary())
        sched.check_cold_cache_on_startup()
        claim_key = _CLAIM_KEY_PREFIX + _today()
        self.assertNotIn(claim_key, _KV._data)

    def test_warm_never_calls_backfill(self):
        cache_mod = _install_cache_stubs(summary=_warm_summary())
        sched.check_cold_cache_on_startup()
        cache_mod.backfill_all_symbols.assert_not_called()

    def test_warm_reports_hit_rate_and_total(self):
        _install_cache_stubs(summary=_warm_summary())
        result = sched.check_cold_cache_on_startup()
        self.assertEqual(result.get("cache_hit_rate_pct"), 100.0)
        self.assertEqual(result.get("total_symbols"), 50)

    def test_warm_no_op_keys_present(self):
        _install_cache_stubs(summary=_warm_summary())
        result = sched.check_cold_cache_on_startup()
        for k in ("ran", "action", "reason", "cache_hit_rate_pct", "total_symbols"):
            self.assertIn(k, result)


class TestColdCacheCheckOwnerPath(ColdStartTestCase):
    """Owner path: kv_claim_once returns True, backfill runs."""


    def test_fully_cold_owner_runs_backfill(self):
        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(n_updated=50),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertTrue(result.get("ran"))
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "owner")
        cache_mod.backfill_all_symbols.assert_called_once()

    def test_partially_cold_owner_runs_backfill(self):
        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=10, n_missing=5),
            backfill_result=_backfill_ok(n_updated=15),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "owner")
        cache_mod.backfill_all_symbols.assert_called_once()

    def test_owner_writes_done_key_on_success(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(n_updated=50),
        )
        sched.check_cold_cache_on_startup()
        done_key = _DONE_KEY_PREFIX + _today()
        done = _KV._data.get(done_key)
        self.assertIsNotNone(done, "done_key must be written after successful backfill")
        self.assertIsInstance(done, dict)
        self.assertIn("status", done)
        self.assertIn("symbols_updated", done)

    def test_owner_claim_remains_after_success(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        sched.check_cold_cache_on_startup()
        claim_key = _CLAIM_KEY_PREFIX + _today()
        self.assertIn(claim_key, _KV._data)

    def test_owner_backfill_called_with_force_false(self):
        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        sched.check_cold_cache_on_startup()
        self.assertFalse(cache_mod.backfill_all_symbols.call_args.kwargs.get("force", True))

    def test_owner_partial_failure_provides_recovery_hint(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(n_updated=48, n_failed=3),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertIn("ohlcv-cache/backfill", str(result.get("recovery_hint", "")))

    def test_owner_success_no_recovery_hint(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(n_failed=0),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertIsNone(result.get("recovery_hint"))

    def test_owner_result_keys_complete(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        result = sched.check_cold_cache_on_startup()
        for k in ("ran", "action", "role", "was_fully_cold", "cold_symbol_count",
                   "total_symbols", "symbols_updated", "symbols_skipped",
                   "symbols_failed", "failed_symbols", "duration_seconds", "status"):
            self.assertIn(k, result, f"Missing key: {k}")

    def test_owner_was_fully_cold_true_when_all_uncached(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertTrue(result.get("was_fully_cold"))

    def test_owner_was_fully_cold_false_when_partial(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=10),
            backfill_result=_backfill_ok(n_updated=10),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertFalse(result.get("was_fully_cold"))


class TestColdCacheCheckOwnerFailure(ColdStartTestCase):
    """Owner path: backfill raises — claim released, backfill_failed returned."""


    def test_owner_exception_returns_backfill_failed(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        result = sched.check_cold_cache_on_startup()
        self.assertTrue(result.get("ran"))
        self.assertEqual(result.get("action"), "backfill_failed")
        self.assertEqual(result.get("role"), "owner")

    def test_owner_exception_releases_claim(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        sched.check_cold_cache_on_startup()
        claim_key = _CLAIM_KEY_PREFIX + _today()
        # Claim must be released so a subsequent instance can retry.
        self.assertNotIn(claim_key, _KV._data)

    def test_owner_exception_does_not_write_done_key(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        sched.check_cold_cache_on_startup()
        done_key = _DONE_KEY_PREFIX + _today()
        self.assertNotIn(done_key, _KV._data)

    def test_owner_exception_provides_recovery_hint(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        result = sched.check_cold_cache_on_startup()
        self.assertIn("ohlcv-cache/backfill", str(result.get("recovery_hint", "")))

    def test_owner_failure_result_keys_complete(self):
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        result = sched.check_cold_cache_on_startup()
        for k in ("ran", "action", "role", "was_fully_cold", "cold_symbol_count",
                   "total_symbols", "error", "recovery_hint"):
            self.assertIn(k, result, f"Missing key: {k}")

    def test_second_call_after_failure_can_become_owner(self):
        """After claim is released on failure, a new call can claim and retry."""
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        sched.check_cold_cache_on_startup()

        # Now install a successful backfill stub and call again.
        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "owner")
        cache_mod.backfill_all_symbols.assert_called_once()


class TestColdCacheCheckNonOwnerPath(ColdStartTestCase):
    """Non-owner path: another instance already holds the claim."""


    def _pre_claim(self):
        """Simulate another instance having acquired the backfill claim."""
        from datetime import datetime, timezone
        claim_key = _CLAIM_KEY_PREFIX + _today()
        _KV._data[claim_key] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }

    def _write_done(self, record: Dict[str, Any] = None):
        """Simulate the owning instance having written the done record."""
        done_key = _DONE_KEY_PREFIX + _today()
        _KV._data[done_key] = record or _done_record()

    def test_non_owner_returns_completed_by_peer_when_done_key_present(self):
        self._pre_claim()
        self._write_done()
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        # Patch sleep to avoid actual delays.
        with patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        self.assertFalse(result.get("ran"))
        self.assertEqual(result.get("reason"), "completed_by_peer")

    def test_non_owner_does_not_run_backfill(self):
        self._pre_claim()
        self._write_done()
        cache_mod = _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        with patch("time.sleep"):
            sched.check_cold_cache_on_startup()

        cache_mod.backfill_all_symbols.assert_not_called()

    def test_non_owner_returns_peer_result_from_done_key(self):
        self._pre_claim()
        done = _done_record(n_updated=49, n_failed=2)
        self._write_done(done)
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        with patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        peer = result.get("peer_result", {})
        self.assertEqual(peer.get("symbols_updated"), 49)

    def test_non_owner_timeout_returns_peer_timeout(self):
        """Non-owner: done key never appears → timeout → peer_timeout result."""
        self._pre_claim()
        # Do NOT write done key — peer never completes.
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        # Use -1 so deadline_mono is strictly in the past; the while condition
        # is immediately False and the else: branch fires regardless of clock
        # resolution on the test machine.
        with patch.object(sched, "_COLD_START_WAIT_TIMEOUT_S", -1), \
             patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        self.assertFalse(result.get("ran"))
        self.assertEqual(result.get("reason"), "peer_timeout")
        self.assertIn("ohlcv-cache/backfill", str(result.get("recovery_hint", "")))

    def test_non_owner_timeout_result_keys_complete(self):
        self._pre_claim()
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        with patch.object(sched, "_COLD_START_WAIT_TIMEOUT_S", -1), \
             patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        for k in ("ran", "reason", "wait_timeout_s", "total_symbols", "recovery_hint"):
            self.assertIn(k, result, f"Missing key: {k}")

    def test_non_owner_polls_and_finds_done_key_after_one_sleep(self):
        """Simulate done key appearing after first sleep (owner finishes mid-poll)."""
        self._pre_claim()
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))
        done_key = _DONE_KEY_PREFIX + _today()

        call_count = 0
        def mock_sleep(s):
            nonlocal call_count
            call_count += 1
            # Write the done key after the first sleep.
            _KV._data[done_key] = _done_record()

        with patch("time.sleep", side_effect=mock_sleep):
            result = sched.check_cold_cache_on_startup()

        self.assertEqual(result.get("reason"), "completed_by_peer")
        self.assertEqual(call_count, 1)


class TestColdCacheCheckStaleCacheDetection(ColdStartTestCase):
    """Stale symbols (>MAX_CACHE_AGE_DAYS) must be treated as cold."""


    def test_stale_only_cache_triggers_backfill(self):
        """All 50 symbols present but stale → backfill must run (read_symbol_from_cache rejects them)."""
        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=0, n_missing=0, n_stale=50),
            backfill_result=_backfill_ok(n_updated=50),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "owner")
        cache_mod.backfill_all_symbols.assert_called_once()

    def test_partially_stale_cache_triggers_backfill(self):
        """Some symbols stale, some warm → backfill runs for stale ones."""
        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=0, n_missing=0, n_stale=10),
            backfill_result=_backfill_ok(n_updated=10),
        )
        result = sched.check_cold_cache_on_startup()
        self.assertEqual(result.get("action"), "backfill")
        cache_mod.backfill_all_symbols.assert_called_once()

    def test_stale_symbols_included_in_cold_symbol_count(self):
        """cold_symbol_count must include stale symbols, not just uncached."""
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=5, n_missing=3, n_stale=7),
            backfill_result=_backfill_ok(n_updated=15),
        )
        result = sched.check_cold_cache_on_startup()
        # cold_set = uncached(5) | missing(3) | stale(7) — no overlap in test data
        self.assertEqual(result.get("cold_symbol_count"), 15)

    def test_warm_cache_with_no_stale_is_no_op(self):
        """Fully warm cache with zero stale symbols returns no_op."""
        _install_cache_stubs(summary=_warm_summary())
        result = sched.check_cold_cache_on_startup()
        self.assertEqual(result.get("action"), "no_op")

    def test_stale_cache_writes_done_key(self):
        """Owner path for stale-only cold set must write the done_key on success."""
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=0, n_missing=0, n_stale=50),
            backfill_result=_backfill_ok(),
        )
        sched.check_cold_cache_on_startup()
        done_key = f"ohlcv_cold_start_backfill_done:{sched._today_ist_date()}"
        self.assertIn(done_key, _KV._data)


class TestColdCacheCheckLeaseExpiry(ColdStartTestCase):
    """Owner writes lease metadata; non-owners can detect expiry and take over.

    Takeover design:
      - kv_claim_once(takeover_key) is the atomic gate — only one peer wins.
      - Original claim_key is NEVER released during takeover (it belongs to the
        dead owner; releasing it unconditionally could clobber a fresh claim just
        won by another peer in a race).
      - Takeover owner releases takeover_key on backfill failure so a third peer
        can attempt recovery; initial owner releases claim_key on failure.
      - WAIT_TIMEOUT_S (30 min) > LEASE_TTL_S (25 min) guarantees peers always
        have remaining budget to observe the expired lease and attempt takeover.
      - Non-owner extends deadline_mono when lease_expires_at is in the future,
        so it never times out before the lease can expire.
    """


    # ── Owner lease metadata ──────────────────────────────────────────────────

    def test_owner_writes_lease_started_key(self):
        """Owner must write lease_started_key with started_at and lease_expires_at."""
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        sched.check_cold_cache_on_startup()
        today = sched._today_ist_date()
        lease_key = _LEASE_STARTED_PREFIX + today
        meta = _KV._data.get(lease_key)
        self.assertIsNotNone(meta, "Owner must write lease_started_key")
        self.assertIn("started_at", meta)
        self.assertIn("lease_expires_at", meta)
        self.assertIn("lease_ttl_s", meta)
        self.assertEqual(meta["lease_ttl_s"], sched._COLD_START_LEASE_TTL_S)

    def test_owner_lease_expires_at_is_future(self):
        """lease_expires_at must be strictly after the call started."""
        from datetime import datetime, timezone
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        before = datetime.now(timezone.utc).isoformat()
        sched.check_cold_cache_on_startup()
        meta = _KV._data.get(_LEASE_STARTED_PREFIX + sched._today_ist_date(), {})
        self.assertGreater(meta.get("lease_expires_at", ""), before)

    def test_owner_lease_role_field_is_owner(self):
        """Lease metadata must record role=owner for the initial claimer."""
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        sched.check_cold_cache_on_startup()
        meta = _KV._data.get(_LEASE_STARTED_PREFIX + sched._today_ist_date(), {})
        self.assertEqual(meta.get("role"), "owner")

    # ── Fenced takeover via takeover_key ─────────────────────────────────────

    def test_non_owner_takeover_when_lease_expired(self):
        """Non-owner: expired lease + no done_key → atomic takeover via takeover_key."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        # Simulate dead owner: claim_key taken, lease already expired, no done_key.
        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": past.isoformat(),
            "lease_expires_at": past.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }

        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        with patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        # Takeover succeeded — backfill ran.
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "takeover")
        cache_mod.backfill_all_symbols.assert_called_once()

    def test_takeover_uses_takeover_key_not_claim_key(self):
        """Takeover must be coordinated via takeover_key, not claim_key release."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": past.isoformat(),
            "lease_expires_at": past.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        with patch("time.sleep"):
            sched.check_cold_cache_on_startup()

        # original claim_key must NOT be released (still belongs to dead owner)
        self.assertIn(_CLAIM_KEY_PREFIX + today, _KV._data,
            "claim_key must not be released during takeover")
        # takeover_key must be claimed by the winner
        self.assertIn(_TAKEOVER_KEY_PREFIX + today, _KV._data,
            "takeover_key must be claimed atomically by the winner")

    def test_non_owner_takeover_writes_done_key(self):
        """Takeover owner must write done_key on success."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": past.isoformat(),
            "lease_expires_at": past.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        with patch("time.sleep"):
            sched.check_cold_cache_on_startup()

        self.assertIn(_DONE_KEY_PREFIX + today, _KV._data,
            "Takeover owner must write done_key after successful backfill")

    def test_takeover_owner_releases_takeover_key_on_failure(self):
        """Takeover owner failure must release takeover_key (not claim_key) for retry."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": past.isoformat(),
            "lease_expires_at": past.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_raises=True,
        )
        with patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        self.assertEqual(result.get("action"), "backfill_failed")
        self.assertEqual(result.get("role"), "takeover")
        # takeover_key must be released so a third peer can retry
        self.assertNotIn(_TAKEOVER_KEY_PREFIX + today, _KV._data,
            "takeover_key must be released on failure so another peer can retry")
        # claim_key of the original dead owner must remain untouched
        self.assertIn(_CLAIM_KEY_PREFIX + today, _KV._data,
            "claim_key (dead owner's) must NOT be released by takeover failure")

    def test_concurrent_takeover_only_one_peer_wins(self):
        """When another peer already holds a fresh takeover token, a competing peer falls back."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        # Dead owner with expired primary lease; another peer already wrote a
        # FRESH takeover token record (expires well into the future).
        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": past.isoformat(),
            "lease_expires_at": past.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        # Fresh takeover record — unexpired, owned by another peer.
        future = datetime.now(timezone.utc) + timedelta(seconds=sched._COLD_START_LEASE_TTL_S)
        _KV._data[_TAKEOVER_KEY_PREFIX + today] = {
            "token": "peer-winner-token",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": future.isoformat(),
        }
        cache_mod = _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        # Use -1 so the deadline_mono is immediately past after the failed
        # takeover attempt (no infinite loop in the test).
        with patch.object(sched, "_COLD_START_WAIT_TIMEOUT_S", -1), \
             patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        # Fresh takeover record → our peer cannot overwrite it → peer_timeout.
        self.assertEqual(result.get("reason"), "peer_timeout")
        cache_mod.backfill_all_symbols.assert_not_called()

    def test_takeover_owner_killed_without_cleanup_allows_recovery(self):
        """Expired takeover record (crash with no exception handler) can be overwritten."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        # Dead primary owner — expired primary lease.
        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        very_past = datetime.now(timezone.utc) - timedelta(seconds=sched._COLD_START_LEASE_TTL_S + 60)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": very_past.isoformat(),
            "lease_expires_at": very_past.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        # Takeover owner that was also killed mid-backfill (no kv_release call).
        # Its record has an expired expires_at — this is what the new peer must
        # detect and overwrite to recover.
        past_takeover = datetime.now(timezone.utc) - timedelta(seconds=10)
        _KV._data[_TAKEOVER_KEY_PREFIX + today] = {
            "token": "dead-takeover-owner-token",
            "started_at": (past_takeover - timedelta(seconds=sched._COLD_START_LEASE_TTL_S)).isoformat(),
            "expires_at": past_takeover.isoformat(),  # already expired
        }

        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        with patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        # New peer detects expired takeover record, overwrites it, runs backfill.
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "takeover")
        cache_mod.backfill_all_symbols.assert_called_once()
        # done_key must be written so any remaining polling peers can stop.
        self.assertIn(_DONE_KEY_PREFIX + today, _KV._data)

    # ── Dynamic deadline extension ────────────────────────────────────────────

    def test_deadline_extends_so_peer_waits_through_lease_ttl(self):
        """Non-owner extends deadline when lease is still valid; done_key appears → completed_by_peer."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        now = datetime.now(timezone.utc)
        # Fresh lease — expires in the future.
        future = now + timedelta(seconds=sched._COLD_START_LEASE_TTL_S)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": now.isoformat(),
            "lease_expires_at": future.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))

        done_key = _DONE_KEY_PREFIX + today
        call_count = 0

        def mock_sleep(s):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Owner completes on the first poll interval
                _KV._data[done_key] = _done_record()

        with patch("time.sleep", side_effect=mock_sleep):
            result = sched.check_cold_cache_on_startup()

        # Despite the fresh lease (which would extend deadline), the done_key
        # appears first → completed_by_peer, not peer_timeout.
        self.assertEqual(result.get("reason"), "completed_by_peer")

    def test_non_owner_does_not_trigger_takeover_when_lease_fresh_and_takeover_key_absent(self):
        """Fresh lease → no takeover attempt (takeover_key stays absent until expiry)."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        now = datetime.now(timezone.utc)
        future = now + timedelta(seconds=sched._COLD_START_LEASE_TTL_S)
        _KV._data[_LEASE_STARTED_PREFIX + today] = {
            "started_at": now.isoformat(),
            "lease_expires_at": future.isoformat(),
            "lease_ttl_s": sched._COLD_START_LEASE_TTL_S,
        }
        cache_mod = _install_cache_stubs(summary=_cold_summary(n_uncached=50))
        done_key = _DONE_KEY_PREFIX + today

        # Write done_key on first sleep so the loop terminates quickly.
        def mock_sleep(s):
            _KV._data[done_key] = _done_record()

        with patch("time.sleep", side_effect=mock_sleep):
            sched.check_cold_cache_on_startup()

        # takeover_key must NOT be claimed — lease was still fresh.
        self.assertNotIn(_TAKEOVER_KEY_PREFIX + today, _KV._data)
        cache_mod.backfill_all_symbols.assert_not_called()


class TestColdCacheCheckGuards(ColdStartTestCase):
    """Guard conditions: disabled flag, import errors, summary errors."""


    def test_cache_disabled_returns_no_op(self):
        _install_cache_stubs(cache_enabled=False)
        result = sched.check_cold_cache_on_startup()
        self.assertFalse(result.get("ran"))
        self.assertIn("OHLCV_CACHE_ENABLED=false", result.get("reason", ""))

    def test_summary_error_returns_error_dict(self):
        _install_cache_stubs(summary_raises=True)
        result = sched.check_cold_cache_on_startup()
        self.assertFalse(result.get("ran"))
        self.assertIn("error", result)

    def test_config_import_error_returns_error_dict(self):
        # Remove config so import fails
        orig = sys.modules.pop("config", None)
        sys.modules["config"] = types.ModuleType("config")  # empty module, no NIFTY_50
        try:
            result = sched.check_cold_cache_on_startup()
            self.assertFalse(result.get("ran"))
            self.assertIn("error", result)
        finally:
            if orig is not None:
                sys.modules["config"] = orig

    def test_ensure_tables_called_when_not_disabled(self):
        cache_mod = _install_cache_stubs(summary=_warm_summary())
        sched.check_cold_cache_on_startup()
        cache_mod.ensure_tables.assert_called_once()

    def test_ensure_tables_not_called_when_disabled(self):
        cache_mod = _install_cache_stubs(cache_enabled=False)
        sched.check_cold_cache_on_startup()
        cache_mod.ensure_tables.assert_not_called()


class TestColdCacheCheckClaimWithoutLease(ColdStartTestCase):
    """Recovery when the initial owner dies before writing lease_started_key."""

    def test_peer_attempts_takeover_after_grace_period(self):
        """claim_key exists + no lease metadata + grace period elapsed → takeover."""
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()

        # Simulate: initial owner claimed but died before writing lease.
        # claimed_at is far enough in the past to exceed the grace period.
        past = datetime.now(timezone.utc) - timedelta(
            seconds=sched._COLD_START_CLAIM_GRACE_PERIOD_S + 30
        )
        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": past.isoformat(),
            "role": "owner",
        }
        # No lease_started_key, no done_key.

        cache_mod = _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        with patch("time.sleep"):
            result = sched.check_cold_cache_on_startup()

        # The peer should detect the stale claim, run takeover, then backfill.
        self.assertEqual(result.get("action"), "backfill")
        self.assertEqual(result.get("role"), "takeover")
        cache_mod.backfill_all_symbols.assert_called_once()

    def test_peer_does_not_takeover_within_grace_period(self):
        """claim_key exists + no lease + within grace period → poll, not takeover."""
        from datetime import datetime, timezone
        today = sched._today_ist_date()

        # Fresh claim: only 5 seconds old, well within the grace period.
        _KV._data[_CLAIM_KEY_PREFIX + today] = {
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "role": "owner",
        }
        # No lease_started_key.
        cache_mod = _install_cache_stubs(summary=_cold_summary(n_uncached=50))
        done_key = _DONE_KEY_PREFIX + today

        # Peer writes done_key on first sleep so the loop terminates.
        def mock_sleep(s):
            _KV._data[done_key] = _done_record()

        with patch("time.sleep", side_effect=mock_sleep):
            result = sched.check_cold_cache_on_startup()

        # Within grace period → no takeover; peer sees completed_by_peer from done_key.
        self.assertEqual(result.get("reason"), "completed_by_peer")
        cache_mod.backfill_all_symbols.assert_not_called()


class TestColdCacheCheckTokenRelease(ColdStartTestCase):
    """kv_release_if_owned prevents stale-owner from deleting a new peer's lease."""

    def test_stale_owner_release_does_not_delete_new_peer_lease(self):
        """A stale takeover owner whose token no longer matches cannot delete the
        active lease held by a peer that took over after the TTL expired."""
        token_a = "stale-owner-token"
        token_b = "active-owner-token"
        from datetime import datetime, timezone, timedelta

        # Set takeover_key to a FRESH record owned by the new peer (token_b).
        today = sched._today_ist_date()
        future = datetime.now(timezone.utc) + timedelta(seconds=sched._COLD_START_LEASE_TTL_S)
        _KV._data[_TAKEOVER_KEY_PREFIX + today] = {
            "token": token_b,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": future.isoformat(),
        }
        before = dict(_KV._data)

        # Stale owner (token_a) tries to release the key — should be a no-op.
        _KV.kv_release_if_owned(_TAKEOVER_KEY_PREFIX + today, token_a)

        # Record should be unchanged.
        self.assertEqual(_KV._data.get(_TAKEOVER_KEY_PREFIX + today), before[_TAKEOVER_KEY_PREFIX + today])

    def test_active_owner_release_succeeds(self):
        """An active takeover owner whose token matches can release the key."""
        token = "active-owner-token"
        from datetime import datetime, timezone, timedelta
        today = sched._today_ist_date()
        future = datetime.now(timezone.utc) + timedelta(seconds=sched._COLD_START_LEASE_TTL_S)
        _KV._data[_TAKEOVER_KEY_PREFIX + today] = {
            "token": token,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": future.isoformat(),
        }

        released = _KV.kv_release_if_owned(_TAKEOVER_KEY_PREFIX + today, token)

        self.assertTrue(released)
        self.assertNotIn(_TAKEOVER_KEY_PREFIX + today, _KV._data)


class TestColdCacheCheckIdempotency(ColdStartTestCase):
    """Warm-cache repeated calls are cheap and never trigger backfill."""


    def test_repeated_warm_calls_never_backfill(self):
        cache_mod = _install_cache_stubs(summary=_warm_summary())
        for _ in range(3):
            result = sched.check_cold_cache_on_startup()
            self.assertEqual(result.get("action"), "no_op")
        cache_mod.backfill_all_symbols.assert_not_called()

    def test_second_call_after_owner_success_is_non_owner_with_done_key(self):
        """After owner writes done_key the second instance sees completed_by_peer."""
        _install_cache_stubs(
            summary=_cold_summary(n_uncached=50),
            backfill_result=_backfill_ok(),
        )
        # First call: becomes owner, runs backfill, writes done_key.
        r1 = sched.check_cold_cache_on_startup()
        self.assertEqual(r1.get("role"), "owner")

        # Second call: claim already taken, done_key present → peer result.
        _install_cache_stubs(summary=_cold_summary(n_uncached=50))
        with patch("time.sleep"):
            r2 = sched.check_cold_cache_on_startup()
        self.assertEqual(r2.get("reason"), "completed_by_peer")


if __name__ == "__main__":
    unittest.main()
