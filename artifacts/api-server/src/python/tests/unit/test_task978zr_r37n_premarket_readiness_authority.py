"""Task978ZR R37N — premarket readiness runtime-universe authority tests.

Offline only: every collaborator (runtime universe resolver, OHLCV cache
store, company master store, universe version store) is stubbed via
sys.modules. No network, no production DB, no sleeps.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest import mock

CUSTOM_23 = [
    "BANKBARODA", "BANKINDIA", "CANBK", "COALINDIA", "FEDERALBNK",
    "GAIL", "HUDCO", "IDFCFIRSTB", "IRCON", "IRFC", "KTKBANK",
    "MAHABANK", "MRPL", "NBCC", "NMDC", "NTPC", "PFC", "PNB",
    "RECLTD", "RVNL", "SAIL", "UNIONBANK", "WIPRO",
]
CUSTOM_HASH = "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016"

NIFTY_50_LEGACY = [f"LEGACY{i:02d}" for i in range(50)]


def _runtime_ctx(key: str, symbols: list, version: int = 1, universe_id: int = 3) -> dict:
    from universe_version_store import exact_set_hash, normalize_symbols
    syms = normalize_symbols(symbols)
    return {
        "natural_session": "2026-09-30",
        "universe_key": key,
        "universe_id": universe_id,
        "version": version,
        "enabled_symbols": syms,
        "symbol_count": len(syms),
        "exact_set_hash": exact_set_hash(syms),
        "effective_from": None,
        "pinned_at": None,
    }


class _Stubs:
    """Install/restore sys.modules stubs around each test."""

    def __init__(self):
        self._saved: dict = {}

    def __enter__(self):
        for name in ("universe_version_store", "ohlcv_cache_store",
                     "nifty50_company_master_store", "kite_quote_provider",
                     "phase20_store", "phase20_circuit_breaker",
                     "phase20_executor", "yfinance"):
            self._saved[name] = sys.modules.get(name)
        uv = types.ModuleType("universe_version_store")
        uv.normalize_symbols = lambda syms: [str(s).upper() for s in syms]
        uv.exact_set_hash = lambda syms: "HASH:" + ",".join(sorted(set(syms)))
        uv.get_members = mock.Mock(return_value=[])
        sys.modules["universe_version_store"] = uv

        ocs = types.ModuleType("ohlcv_cache_store")
        ocs.get_cache_status = mock.Mock(return_value={})
        ocs.MIN_BARS_REQUIRED = 120
        ocs._get_last_refresh_state = mock.Mock(return_value=None)
        sys.modules["ohlcv_cache_store"] = ocs

        ncm = types.ModuleType("nifty50_company_master_store")
        ncm.get_missing_symbols = mock.Mock(return_value=[])
        sys.modules["nifty50_company_master_store"] = ncm

        kqp = types.ModuleType("kite_quote_provider")
        kqp.kite_session_verified = mock.Mock(return_value=True)
        sys.modules["kite_quote_provider"] = kqp

        yf = types.ModuleType("yfinance")
        sys.modules["yfinance"] = yf

        p20 = types.ModuleType("phase20_store")
        p20.get_settings = mock.Mock(return_value={"initial_capital": 100000})
        sys.modules["phase20_store"] = p20

        cb = types.ModuleType("phase20_circuit_breaker")
        cb.get_state = mock.Mock(return_value={"tripped": False, "unreadable": False})
        sys.modules["phase20_circuit_breaker"] = cb

        ex = types.ModuleType("phase20_executor")
        ex.get_open_positions_view = mock.Mock(return_value=[])
        sys.modules["phase20_executor"] = ex
        return self

    def __exit__(self, *exc):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        return False


def _load_module():
    for name in list(sys.modules):
        if name == "pre_market_data_readiness":
            del sys.modules[name]
    import pre_market_data_readiness as mod
    importlib.reload(mod)
    return mod


def _patch_resolver(mod, ctx, *, raises: Exception | None = None):
    ru = types.ModuleType("runtime_universe")
    if raises is not None:
        ru.resolve_active_universe = mock.Mock(side_effect=raises)
    else:
        ru.resolve_active_universe = mock.Mock(return_value=ctx)
    return mock.patch.dict(sys.modules, {"runtime_universe": ru})


class TestR37NPremarketReadinessAuthority(unittest.TestCase):
    def test_1_custom_runtime_authority_used(self):
        """Default call resolves the durable 23-symbol universe; no NIFTY_50 fallback."""
        with _Stubs():
            mod = _load_module()
            ctx = _runtime_ctx("CUSTOM_LOW_PRICE_SECTOR", CUSTOM_23)
            uv = sys.modules["universe_version_store"]
            uv.get_members = mock.Mock(return_value=[
                {"symbol": s, "exchange": "NSE", "sector": "X",
                 "instrument_token": i, "mapping_status": "MAPPED",
                 "enabled": True}
                for i, s in enumerate(CUSTOM_23)
            ])
            with _patch_resolver(mod, ctx):
                result = mod.run_pre_market_readiness_check()
            # Advisory-only warnings (postmarket refresh, build identity) may
            # downgrade to READY_WITH_WARNINGS; BLOCKED would be a defect.
            self.assertTrue(result["verdict"].startswith("READY"), result["verdict"])
            ocs = sys.modules["ohlcv_cache_store"]
            requested = list(ocs.get_cache_status.call_args[0][0])
            self.assertEqual(sorted(requested), sorted(CUSTOM_23))
            au = result["checks"]["active_universe"]
            self.assertEqual(au["universe_key"], "CUSTOM_LOW_PRICE_SECTOR")
            self.assertEqual(au["universe_id"], 3)
            self.assertEqual(au["universe_version"], 1)
            self.assertEqual(au["symbol_count"], 23)
            self.assertEqual(au["exact_set_hash"], ctx["exact_set_hash"])

    def test_2_resolver_failure_fails_closed(self):
        """RuntimeUniverseUnavailable → BLOCKED, no NIFTY_50 fallback."""
        with _Stubs():
            mod = _load_module()
            ru_exc = type("RuntimeUniverseUnavailable", (RuntimeError,), {})
            with _patch_resolver(mod, None, raises=ru_exc("durable store unavailable")):
                result = mod.run_pre_market_readiness_check()
            self.assertEqual(result["verdict"], "BLOCKED")
            self.assertTrue(any("Durable runtime universe unavailable" in r for r in result["blocking_reasons"]))
            ocs = sys.modules["ohlcv_cache_store"]
            ocs.get_cache_status.assert_not_called()

    def test_3_custom_metadata_authority_versioned_members(self):
        """Custom mode reads versioned members of the SAME universe; not the NIFTY store."""
        with _Stubs():
            mod = _load_module()
            ctx = _runtime_ctx("CUSTOM_LOW_PRICE_SECTOR", CUSTOM_23)
            uv = sys.modules["universe_version_store"]
            uv.get_members = mock.Mock(return_value=[
                {"symbol": s, "exchange": "NSE", "sector": "X",
                 "instrument_token": i, "mapping_status": "MAPPED",
                 "enabled": True}
                for i, s in enumerate(CUSTOM_23)
            ])
            with _patch_resolver(mod, ctx):
                result = mod.run_pre_market_readiness_check()
            uv.get_members.assert_called_once()
            self.assertEqual(uv.get_members.call_args.kwargs.get("universe_key"), "CUSTOM_LOW_PRICE_SECTOR")
            self.assertEqual(uv.get_members.call_args.kwargs.get("version"), 1)
            cm = result["checks"]["company_master"]
            self.assertEqual(cm["metadata_source"], "versioned_universe_members")
            self.assertEqual(cm["expected_count"], 23)
            self.assertEqual(cm["member_count"], 23)
            self.assertEqual(cm["coverage_pct"], 100.0)
            ncm = sys.modules["nifty50_company_master_store"]
            ncm.get_missing_symbols.assert_not_called()

    def test_4_mismatched_member_set_fails_closed(self):
        """One missing member → explicit fail-closed condition, never silent acceptance."""
        with _Stubs():
            mod = _load_module()
            ctx = _runtime_ctx("CUSTOM_LOW_PRICE_SECTOR", CUSTOM_23)
            uv = sys.modules["universe_version_store"]
            short_set = [s for s in CUSTOM_23 if s != "SAIL"]
            uv.get_members = mock.Mock(return_value=[
                {"symbol": s, "exchange": "NSE", "sector": "X",
                 "instrument_token": 1, "mapping_status": "MAPPED", "enabled": True}
                for s in short_set
            ])
            with _patch_resolver(mod, ctx):
                result = mod.run_pre_market_readiness_check()
            self.assertEqual(result["verdict"], "BLOCKED")
            cm = result["checks"]["company_master"]
            self.assertEqual(cm["member_count"], 22)
            self.assertEqual(cm["missing_symbols"], ["SAIL"])

    def test_5_nifty_semantics_preserved(self):
        """Resolved NIFTY_50 runtime mode still uses the NIFTY company master path."""
        with _Stubs():
            mod = _load_module()
            ctx = _runtime_ctx("NIFTY_50", NIFTY_50_LEGACY, universe_id=1)
            ncm = sys.modules["nifty50_company_master_store"]
            ncm.get_missing_symbols = mock.Mock(return_value=[])
            uv = sys.modules["universe_version_store"]
            uv.get_members = mock.Mock()
            with _patch_resolver(mod, ctx):
                result = mod.run_pre_market_readiness_check()
            ncm.get_missing_symbols.assert_called_once()
            uv.get_members.assert_not_called()
            self.assertNotIn("metadata_source", result["checks"]["company_master"])

    def test_6_explicit_symbols_preserved(self):
        """Explicit symbol list is evaluated exactly as supplied."""
        with _Stubs():
            mod = _load_module()
            explicit = ["AAA", "BBB", "CCC"]
            with mock.patch.dict(sys.modules, {"runtime_universe": types.ModuleType("runtime_universe")}):
                with mock.patch("builtins.__import__", side_effect=__import__):
                    result = mod.run_pre_market_readiness_check(symbols=explicit)
            ocs = sys.modules["ohlcv_cache_store"]
            requested = list(ocs.get_cache_status.call_args[0][0])
            self.assertEqual(requested, explicit)
            self.assertNotIn("authority_source", result["checks"]["active_universe"])

    def test_7_blocking_denominator_corrected(self):
        """Stale/missing percentages use the resolved 23-symbol denominator."""
        with _Stubs():
            mod = _load_module()
            ctx = _runtime_ctx("CUSTOM_LOW_PRICE_SECTOR", CUSTOM_23)
            ocs = sys.modules["ohlcv_cache_store"]
            status = {s: {"cached": True, "missing_required": False,
                          "data_quality": "LIVE", "latest_date": "2026-09-30"}
                      for s in CUSTOM_23}
            # 5 stale of 23 = 21.7% → BLOCKED (>20%). With a 50 denominator this
            # would have been 10% and silently passed.
            for s in CUSTOM_23[:5]:
                status[s]["data_quality"] = "STALE"
            ocs.get_cache_status = mock.Mock(return_value=status)
            uv = sys.modules["universe_version_store"]
            uv.get_members = mock.Mock(return_value=[
                {"symbol": s, "exchange": "NSE", "sector": "X",
                 "instrument_token": 1, "mapping_status": "MAPPED", "enabled": True}
                for s in CUSTOM_23
            ])
            with _patch_resolver(mod, ctx):
                result = mod.run_pre_market_readiness_check()
            self.assertEqual(result["verdict"], "BLOCKED")
            self.assertTrue(any("STALE cache" in r for r in result["blocking_reasons"]))

    def test_8_exact_telemetry_identity(self):
        """active_universe telemetry matches the resolved context exactly."""
        with _Stubs():
            mod = _load_module()
            ctx = _runtime_ctx("CUSTOM_LOW_PRICE_SECTOR", CUSTOM_23)
            uv = sys.modules["universe_version_store"]
            uv.get_members = mock.Mock(return_value=[
                {"symbol": s, "exchange": "NSE", "sector": "X",
                 "instrument_token": 1, "mapping_status": "MAPPED", "enabled": True}
                for s in CUSTOM_23
            ])
            with _patch_resolver(mod, ctx):
                result = mod.run_pre_market_readiness_check()
            au = result["checks"]["active_universe"]
            self.assertEqual(au["universe_id"], ctx["universe_id"])
            self.assertEqual(au["universe_version"], ctx["version"])
            self.assertEqual(au["symbol_count"], ctx["symbol_count"])
            self.assertEqual(au["exact_set_hash"], ctx["exact_set_hash"])
            self.assertEqual(au["authority_source"], "runtime_universe.resolve_active_universe")


if __name__ == "__main__":
    unittest.main()
