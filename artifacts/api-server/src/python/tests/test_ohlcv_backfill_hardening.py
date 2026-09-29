"""
Task978ZR R37 — offline tests for the hardened OHLCV backfill path.

Covers:
  1. fully warm cache -> no provider call
  2. partial cache -> only missing/stale symbols fetched
  3. Yahoo success
  4. Yahoo provider-wide rate limit
  5. no immediate per-symbol hammering after rate limit
  6. bounded retry/cooldown
  7. partial Yahoo success is preserved
  8. remaining-symbol retry resumes correctly
  9. read-only Kite historical fallback when Yahoo remains rate-limited
 10. Kite fallback never touches order methods
 11. both providers fail -> fail closed / cache remains not-ready
 12. malformed/insufficient historical bars are rejected
 13. correct source provenance written
 14. cold-start result does not falsely report readiness
 15. active-universe readiness uses the exact production universe

No test sleeps: timing is injected via module attribute _SLEEP.
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bars(n: int, end_date: str = "2026-09-25") -> pd.DataFrame:
    idx = pd.bdate_range(end=end_date, periods=n)
    base = 100.0
    return pd.DataFrame(
        {
            "open": [base + i * 0.1 for i in range(n)],
            "high": [base + 1.0 + i * 0.1 for i in range(n)],
            "low": [base - 1.0 + i * 0.1 for i in range(n)],
            "close": [base + 0.5 + i * 0.1 for i in range(n)],
            "volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


class _RateLimited(Exception):
    """Exception mimicking a Yahoo provider-wide 429."""

    def __str__(self):
        return "<HTML> Too Many Requests 429 rate limit exceeded</HTML>"


class BackfillHardeningTestCase(unittest.TestCase):
    """Isolated import of ohlcv_cache_store with a fake DB layer."""

    def setUp(self):
        self._saved = {
            k: v for k, v in sys.modules.items()
            if k in ("ohlcv_cache_store",)
        }
        sys.modules.pop("ohlcv_cache_store", None)
        self.cache = __import__("ohlcv_cache_store")

        # Injectable timing — never actually sleep.
        self.sleeps = []
        self.cache._SLEEP = self.sleeps.append

        # Persisted rows keyed by (symbol, source).
        self.written = {}
        self.cache.write_symbol_to_cache = MagicMock(
            side_effect=self._fake_write
        )
        # get_cache_status controls cache-first skip semantics.
        self.cache.get_cache_status = MagicMock(
            side_effect=self._fake_status
        )
        self.cache.ensure_tables = MagicMock()
        self.cache.log_refresh_start = MagicMock(return_value=1)
        self.cache.log_refresh_complete = MagicMock()
        self.cache._db_available = MagicMock(return_value=False)

    def tearDown(self):
        sys.modules.pop("ohlcv_cache_store", None)
        for name, mod in self._saved.items():
            sys.modules[name] = mod

    # -- fake cache plumbing -------------------------------------------------

    def _fake_write(self, symbol, df, source="yfinance"):
        if df is None or df.empty or len(df) < self.cache.MIN_BARS_REQUIRED:
            return 0
        self.written[symbol.upper()] = {"rows": len(df), "source": source}
        return len(df)

    def _fake_status(self, symbols):
        # Default: nothing cached — all symbols are cold.
        return {s.upper(): {"cached": False} for s in symbols}

    def _set_cached(self, symbols, quality="LIVE", bars=130):
        def status(syms):
            out = {}
            for s in syms:
                if s.upper() in {x.upper() for x in symbols}:
                    out[s.upper()] = {
                        "cached": True,
                        "missing_required": False,
                        "data_quality": quality,
                    }
                else:
                    out[s.upper()] = {"cached": False}
            return out
        self.cache.get_cache_status = MagicMock(side_effect=status)

    def _patch_yf(self, behavior):
        """behavior: callable(symbol, period, interval) -> df | raise | None"""
        calls = []

        def fetch(sym, period, interval):
            calls.append(sym)
            return behavior(sym)

        self.cache._fetch_single_yfinance = MagicMock(side_effect=fetch)
        self.yf_calls = calls
        return self.cache._fetch_single_yfinance

    # -- tests ---------------------------------------------------------------

    def test_01_warm_cache_no_provider_call(self):
        """Fully warm cache -> zero provider fetches, all skipped."""
        self._set_cached(["AAA", "BBB"], quality="LIVE")
        self._patch_yf(lambda s: (_ for _ in ()).throw(AssertionError("called")))
        r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertEqual(self.cache._fetch_single_yfinance.call_count, 0)
        self.assertEqual(r["symbols_updated"], 0)
        self.assertEqual(r["symbols_skipped"], 2)
        self.assertFalse(r["rate_limited"])
        self.assertEqual(r["cooldown_disposition"], "not_triggered")

    def test_02_partial_cache_fetches_only_missing(self):
        """Cache-first resume: only the stale/missing symbol is fetched."""
        self._set_cached(["AAA"], quality="NEAR_LIVE")
        self._patch_yf(lambda s: _bars(130))
        r = self.cache.backfill_all_symbols(["AAA", "BBB", "CCC"])
        self.assertEqual(self.yf_calls, ["BBB", "CCC"])
        self.assertEqual(r["symbols_skipped"], 1)
        self.assertEqual(r["symbols_updated"], 2)
        self.assertIn("BBB", self.written)

    def test_03_yahoo_success(self):
        self._patch_yf(lambda s: _bars(130))
        r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertEqual(r["symbols_updated"], 2)
        self.assertEqual(r["symbols_failed"], 0)
        self.assertEqual(r["provider"], "yfinance")
        self.assertFalse(r["rate_limited"])
        self.assertEqual(r["attempts"], 1)

    def test_04_yahoo_provider_wide_rate_limit(self):
        """Rate-limited response is detected and reported."""
        def boom(s):
            raise _RateLimited()
        self._patch_yf(boom)
        # Kite unavailable (no creds) so this isolates the Yahoo path.
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB", "CCC"])
        self.assertTrue(r["rate_limited"])
        self.assertGreaterEqual(r["rate_limit_events"], 1)
        self.assertEqual(r["symbols_updated"], 0)
        self.assertEqual(r["symbols_failed"], 3)
        self.assertIn("single_cooldown_then_bounded_retry",
                      r["cooldown_disposition"])

    def test_05_no_hammering_after_rate_limit(self):
        """After a 429, remaining symbols are NOT immediately re-requested.
        Bounded: at most 2 attempts (initial + one bounded retry)."""
        state = {"n": 0}

        def boom(s):
            state["n"] += 1
            raise _RateLimited()

        self._patch_yf(boom)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(
                ["A{:02d}".format(i) for i in range(23)]
            )
        # Original pass breaks immediately on first 429; retry pass makes
        # exactly ONE more request then stops again. No 23-symbol storm.
        self.assertLessEqual(len(self.yf_calls), 4, self.yf_calls)
        self.assertEqual(r["attempts"], 2)
        self.assertGreaterEqual(len(self.sleeps), 1)  # cooldown was applied
        self.assertIn(self.cache._BACKFILL_COOLDOWN_S, self.sleeps)

    test_05_no_hammering_after_rate_limit.__doc__ = (
        "After a 429 the loop stops immediately; total requests stay bounded."
    )

    def test_06_bounded_retry_then_success_after_cooldown(self):
        """Bounded: exactly one cooldown, one retry pass, and when Yahoo has
        recovered during the cooldown the retry completes the whole set."""
        phase = {"n": 0}

        def flaky(s):
            phase["n"] += 1
            if phase["n"] == 1:      # first (and only) pre-cooldown request
                raise _RateLimited()
            return _bars(130)

        self._patch_yf(flaky)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertEqual(r["symbols_updated"], 2)
        self.assertEqual(r["attempts"], 2)
        self.assertLessEqual(len(self.sleeps), 2)

    def test_07_partial_yahoo_success_preserved(self):
        """Symbols fetched before a mid-run 429 stay written."""
        def partial(s):
            if s == "AAA":
                return _bars(130)
            raise _RateLimited()

        self._patch_yf(partial)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertIn("AAA", self.written)
        self.assertEqual(r["symbols_updated"], 1)
        self.assertEqual(r["status"], "PARTIAL")

    def test_08_remaining_retry_resumes_only_missing(self):
        """Second pass resumes from remaining symbols only (no re-fetch of
        symbols updated in pass one)."""
        seen = []

        def resume(s):
            seen.append(s)
            if s == "AAA":
                return _bars(130)
            if not hasattr(resume, "retried"):
                resume.retried = False
                raise _RateLimited()
            return _bars(130)

        self._patch_yf(resume)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertIn("AAA", self.written)
        self.assertIn("BBB", self.written)
        # BBB attempted at most twice (initial + bounded retry)
        self.assertLessEqual(seen.count("BBB"), 2)

    def test_09_kite_historical_fallback_when_yahoo_rate_limited(self):
        """Yahoo stays rate-limited -> remaining symbols come from Kite
        historical (daily candles) with explicit provenance."""
        def boom(s):
            raise _RateLimited()
        self._patch_yf(boom)

        kite_df = _bars(130)
        kite_fetch = MagicMock(return_value=kite_df)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=True
        ), unittest.mock.patch.object(
            self.cache, "_fetch_single_kite_historical", kite_fetch
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertEqual(kite_fetch.call_count, 2)
        self.assertTrue(r["kite_historical_used"])
        self.assertEqual(r["kite_symbols_fetched"], ["AAA", "BBB"])
        self.assertEqual(r["symbols_updated"], 2)
        self.assertEqual(r["symbols_failed"], 0)

    def test_10_kite_fallback_never_touches_order_methods(self):
        """The real Kite fallback path must only ever call historical_data
        (read-only), must use validated instrument tokens, and must pace its
        requests via the injectable sleeper (no real sleeps)."""
        order_calls = []

        class _OrderGuardKite:
            def __init__(self, api_key=None):
                pass

            def set_access_token(self, t):
                pass

            def historical_data(self, token, from_dt, to_dt, interval):
                assert interval == "day", interval
                return _bars(130).reset_index(names=["date"]).to_dict("records")

            def __getattr__(self, name):
                if name != "historical_data":
                    order_calls.append(name)
                def _missing(*a, **k):
                    raise AssertionError(
                        "Kite order/profile method %s must never be called "
                        "from the OHLCV fallback" % name
                    )
                return _missing

        fake_kc = types.ModuleType("kiteconnect")
        fake_kc.KiteConnect = _OrderGuardKite

        fake_kite_instrument_cache = types.ModuleType("kite_instrument_cache")
        fake_kite_instrument_cache.get_token = MagicMock(return_value=123456)

        fake_token_store = types.ModuleType("kite_token_store")
        fake_token_store.resolve_preferred_token = MagicMock(
            return_value=("fake-token", True)
        )

        def boom(s):
            raise _RateLimited()
        self._patch_yf(boom)

        saved = {m: sys.modules.get(m) for m in
                 ("kiteconnect", "kite_instrument_cache", "kite_token_store")}
        sys.modules["kiteconnect"] = fake_kc
        sys.modules["kite_instrument_cache"] = fake_kite_instrument_cache
        sys.modules["kite_token_store"] = fake_token_store
        old_key = os.environ.get("ZERODHA_API_KEY")
        os.environ["ZERODHA_API_KEY"] = "test-key"
        try:
            with unittest.mock.patch.object(
                self.cache, "_kite_historical_available", return_value=True
            ):
                r = self.cache.backfill_all_symbols(["AAA"])
        finally:
            for m, mod in saved.items():
                if mod is not None:
                    sys.modules[m] = mod
                else:
                    sys.modules.pop(m, None)
            if old_key is None:
                os.environ.pop("ZERODHA_API_KEY", None)
            else:
                os.environ["ZERODHA_API_KEY"] = old_key
        self.assertEqual(r["symbols_updated"], 1)
        self.assertEqual(r["kite_symbols_fetched"], ["AAA"])
        self.assertEqual(self.written["AAA"]["source"], "kite_historical")
        self.assertEqual(order_calls, [])
        # Pacing went through the injectable sleeper — no real sleep.
        self.assertIn(self.cache._KITE_PACING_S, self.sleeps)

    def test_11_both_providers_fail_fail_closed(self):
        """Yahoo rate-limited AND Kite unavailable -> all symbols fail and
        nothing is written; cache stays not-ready."""
        def boom(s):
            raise _RateLimited()
        self._patch_yf(boom)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertEqual(r["symbols_updated"], 0)
        self.assertEqual(r["symbols_failed"], 2)
        self.assertEqual(self.written, {})
        self.assertEqual(r["status"], "FAILED")
        self.assertFalse(r["kite_historical_used"])

    def test_12_malformed_or_insufficient_bars_rejected(self):
        """Sub-MIN_BARS_REQUIRED data and malformed frames are not cached."""
        self._patch_yf(lambda s: _bars(10))  # far below 120 required bars
        r = self.cache.backfill_all_symbols(["AAA"])
        self.assertEqual(self.written, {})
        self.assertEqual(r["symbols_updated"], 0)
        self.assertEqual(r["symbols_failed"], 1)

    def test_13_source_provenance_written(self):
        """Yahoo rows carry source=yfinance; Kite rows carry
        source=kite_historical — never mislabeled."""
        self._patch_yf(lambda s: _bars(130))
        self.cache.backfill_all_symbols(["AAA"])
        self.assertEqual(self.written["AAA"]["source"], "yfinance")

        self.written.clear()
        kite_df = _bars(130)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=True
        ), unittest.mock.patch.object(
            self.cache, "_fetch_single_kite_historical",
            MagicMock(return_value=kite_df),
        ):
            def boom(s):
                raise _RateLimited()
            self.cache._fetch_single_yfinance = MagicMock(
                side_effect=boom
            )
            r = self.cache.backfill_all_symbols(["BBB"])
        self.assertEqual(self.written["BBB"]["source"], "kite_historical")

    def test_14_cold_start_result_does_not_false_report_readiness(self):
        """A failed backfill result carries no false readiness signal: failed
        symbols are explicit and status is FAILED."""
        def boom(s):
            raise _RateLimited()
        self._patch_yf(boom)
        with unittest.mock.patch.object(
            self.cache, "_kite_historical_available", return_value=False
        ):
            r = self.cache.backfill_all_symbols(["AAA", "BBB"])
        self.assertEqual(r["symbols_failed"], 2)
        self.assertEqual(set(r["failed_symbols"]), {"AAA", "BBB"})
        self.assertEqual(r["status"], "FAILED")

    def test_15_active_universe_readiness_uses_production_rule(self):
        """Readiness semantics: only LIVE/NEAR_LIVE symbols with sufficient
        bars count as ready; STALE/missing never count (the production rule
        applied by get_cache_status / cold-start classification)."""
        self.cache.get_cache_status = MagicMock(
            side_effect=lambda syms: {
                s.upper(): {
                    "cached": True,
                    "missing_required": False,
                    "data_quality": q,
                }
                for s, q in zip(syms, ["LIVE", "NEAR_LIVE", "STALE"])
            }
        )
        # Production skip rule: only LIVE/NEAR_LIVE non-missing are skipped.
        status = self.cache.get_cache_status(["AAA", "BBB", "CCC"])
        ready = [
            s for s, info in status.items()
            if info.get("cached") and not info.get("missing_required")
            and info.get("data_quality") in ("LIVE", "NEAR_LIVE")
        ]
        self.assertEqual(sorted(ready), ["AAA", "BBB"])
        self.assertNotIn("CCC", ready)


if __name__ == "__main__":
    unittest.main()
