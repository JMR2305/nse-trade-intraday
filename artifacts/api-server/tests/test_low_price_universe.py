"""Unit coverage for the paper-only custom low-price sector universe.

All external providers and persistence are mocked or avoided. These tests must
never make a network request or instantiate an order client.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PYTHON_DIR = Path(__file__).resolve().parents[1] / "src" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import custom_universe_store as store
import low_price_universe_refresh as refresh
import low_price_universe_report as universe_report


def _bars(volume: float = 800_000, close: float = 100.0, count: int = 120) -> pd.DataFrame:
    return pd.DataFrame({
        "volume": [volume] * count,
        "close": [close] * count,
    })


class LowPriceUniverseTests(unittest.TestCase):
    def _candidate(self, sector="Information Technology", ltp=100.0,
                   frame=None, source="kite_ltp"):
        if frame is None:
            frame = _bars()
        instrument = {"symbol": "TEST", "name": "Test Ltd", "token": 1}
        with patch.object(refresh, "_master_metadata", return_value={"sector": sector}), \
             patch.object(refresh, "_cached_ohlcv", return_value=(frame, frame is not None)):
            return refresh._candidate_row(instrument, ltp, source)

    def test_01_nse_eq_filter(self):
        self.assertTrue(refresh.is_nse_equity({"exchange": "NSE", "instrument_type": "EQ"}))
        self.assertFalse(refresh.is_nse_equity({"exchange": "BSE", "instrument_type": "EQ"}))
        self.assertFalse(refresh.is_nse_equity({"exchange": "NSE", "instrument_type": "FUT"}))
        import kite_instrument_cache
        legacy = {
            "tradingsymbol": "LEGACY", "instrument_token": 42,
            "name": "Legacy Ltd", "exchange": "NSE", "instrument_type": "EQ",
        }
        with patch.object(kite_instrument_cache, "_load_cache", return_value={"instruments": [legacy]}):
            normalized = kite_instrument_cache.get_cached_instruments()
        self.assertEqual(normalized[0]["symbol"], "LEGACY")
        self.assertEqual(normalized[0]["token"], 42)

    def test_02_price_band_inclusive(self):
        self.assertTrue(refresh.in_price_band(20.0))
        self.assertTrue(refresh.in_price_band(200.0))
        self.assertFalse(refresh.in_price_band(19.99))
        self.assertFalse(refresh.in_price_band(200.01))

    def test_03_it_infra_bank_aliases_include(self):
        for sector in ("IT", "Construction", "Private Bank"):
            row = self._candidate(sector=sector)
            self.assertTrue(row["is_active"], sector)
            self.assertIn(row["sector"], {"IT", "INFRA", "BANK"})

    def test_04_low_liquidity_excluded(self):
        row = self._candidate(frame=_bars(volume=50_000))
        self.assertFalse(row["is_active"])
        self.assertIn("avg volume", row["reason_excluded"])

    def test_05_missing_ohlcv_excluded(self):
        instrument = {"symbol": "TEST", "name": "Test Ltd", "token": 1}
        with patch.object(refresh, "_master_metadata", return_value={"sector": "IT"}), \
             patch.object(refresh, "_cached_ohlcv", return_value=(None, False)):
            row = refresh._candidate_row(instrument, 100.0, "kite_ltp")
        self.assertFalse(row["is_active"])
        self.assertIn("missing OHLCV", row["reason_excluded"])

    def test_06_kite_ltp_fallback_is_labelled(self):
        row = self._candidate(ltp=120.0, source="yfinance_close")
        self.assertTrue(row["is_active"])
        self.assertEqual(row["last_ltp_source"], "yfinance_close")
        import ohlcv_cache_store
        with patch.object(refresh, "_cached_ohlcv", return_value=(None, False)), \
             patch.object(ohlcv_cache_store, "backfill_all_symbols", return_value={"updated": ["TEST"], "failed": []}) as backfill:
            hydration = refresh._hydrate_missing_ohlcv(["TEST"])
        backfill.assert_called_once_with(["TEST"], period="8mo")
        self.assertEqual(hydration["updated"], 1)

    def test_07_price_outside_band_excluded(self):
        row = self._candidate(ltp=250.0)
        self.assertFalse(row["is_active"])
        self.assertIn("outside", row["reason_excluded"])

    def test_08_non_sector_excluded(self):
        row = self._candidate(sector="Healthcare")
        self.assertFalse(row["is_active"])
        self.assertIn("sector not", row["reason_excluded"])

    def test_09_scanner_custom_resolution_uses_store(self):
        import config
        source = inspect.getsource(__import__("live_scan_engine"))
        self.assertIn("get_active_symbols()", source)
        self.assertIn("CUSTOM_LOW_PRICE_SECTOR", source)
        with patch("phase20_store.get_settings", return_value={
            "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR",
        }):
            self.assertEqual(
                config.get_active_intraday_universe().value,
                "CUSTOM_LOW_PRICE_SECTOR",
            )
        import phase20_store
        with self.assertRaises(ValueError):
            phase20_store._validate_patch(
                {"active_intraday_universe": "LIVE_BROKER"}, {}
            )

    def test_10_scanner_retains_nifty_default(self):
        source = inspect.getsource(__import__("live_scan_engine"))
        self.assertIn("universe = list(NIFTY_50)", source)

    def test_11_no_broker_order_calls(self):
        source = inspect.getsource(refresh)
        for forbidden in ("place_order(", "modify_order(", "cancel_order(", "KiteConnect("):
            self.assertNotIn(forbidden, source)

    def test_12_risk_caps_unchanged(self):
        import phase15_risk_gate
        self.assertEqual(phase15_risk_gate.MAX_DAILY_LOSS_PCT, 3.0)
        self.assertEqual(phase15_risk_gate.MAX_SECTOR_EXPOSURE_PCT, 40.0)
        self.assertEqual(phase15_risk_gate.MAX_EXPOSURE_PCT, 80.0)
        import phase20_store
        settings = phase20_store.DEFAULT_SETTINGS
        self.assertEqual(settings["per_stock_exposure_cap_pct"], 25.0)
        self.assertEqual(settings["sector_exposure_cap_pct"], 40.0)
        self.assertEqual(settings["portfolio_deployed_cap_pct"], 80.0)
        self.assertEqual(settings["daily_loss_limit_pct"], 3.0)

    def test_13_backtest_no_lookahead(self):
        import backtest_runner
        with patch("custom_universe_store.get_historical_universe_resolution", return_value={
            "status": "HISTORICAL_SNAPSHOT",
            "symbols": ["OLD"],
            "as_of_date": "2025-01-10",
            "snapshot_at": "2025-01-09T10:00:00+00:00",
        }), patch("custom_universe_store.get_active_symbols", return_value=["TODAY"]):
            self.assertEqual(
                backtest_runner.resolve_universe(
                    {"universe_mode": "CUSTOM_LOW_PRICE_SECTOR", "end": "2025-01-10"}
                ),
                ["OLD"],
            )
        self.assertIn(
            "custom_universe_membership_history",
            inspect.getsource(store.get_historical_universe_resolution),
        )
        no_history = {"universe_mode": "CUSTOM_LOW_PRICE_SECTOR", "end": "2020-01-01"}
        unavailable = {
            "status": "HISTORICAL_SNAPSHOT_UNAVAILABLE",
            "symbols": [],
            "as_of_date": "2020-01-01",
        }
        with patch("custom_universe_store.get_historical_universe_resolution", return_value=unavailable), \
             patch("custom_universe_store.get_active_symbols", return_value=["TODAY"]) as current:
            self.assertEqual(backtest_runner.resolve_universe(no_history), [])
        current.assert_not_called()
        self.assertEqual(no_history["universe_evidence"], "HISTORICAL_SNAPSHOT_UNAVAILABLE")
        for falsey_lookalike in (False, "false", "true", 1):
            cfg = {
                "universe_mode": "CUSTOM_LOW_PRICE_SECTOR",
                "end": "2020-01-01",
                "allow_current_universe_fallback": falsey_lookalike,
            }
            with patch("custom_universe_store.get_historical_universe_resolution", return_value=unavailable), \
                 patch("custom_universe_store.get_active_symbols", return_value=["TODAY"]) as current:
                self.assertEqual(backtest_runner.resolve_universe(cfg), [])
            current.assert_not_called()

    def test_14_status_reports_active_count(self):
        rows = [
            {"symbol": "A", "is_active": True, "sector": "IT", "ohlcv_available": True,
             "last_ltp_source": "kite_ltp", "last_verified_at": "2025-01-01T00:00:00Z"},
            {"symbol": "B", "is_active": True, "sector": "BANK", "ohlcv_available": False,
             "last_ltp_source": "yfinance_close", "last_verified_at": "2025-01-01T00:00:00Z"},
            {"symbol": "C", "is_active": False, "sector": "BANK", "ohlcv_available": False,
             "last_ltp_source": "unavailable", "last_verified_at": "2025-01-01T00:00:00Z"},
        ]
        with patch.object(store, "get_all_symbols", return_value=rows):
            status = store.get_status()
        self.assertEqual(status["active_count"], 2)
        self.assertEqual(status["sector_counts"], {"IT": 1, "BANK": 1})
        evidence = status["membership_price_evidence"]
        self.assertEqual(evidence["scope"], "LAST_MEMBERSHIP_REFRESH")
        self.assertEqual(evidence["kite_ltp_symbols"], 1)
        self.assertEqual(evidence["yahoo_close_symbols"], 1)
        self.assertEqual(evidence["unavailable_symbols"], 0)
        self.assertEqual(evidence["source_counts"], {
            "kite_ltp": 1,
            "yfinance_close": 1,
        })
        self.assertIn("not current market quote provenance", evidence["note"])
        report = universe_report.build_report(status, rows)
        self.assertIn("Membership refresh price evidence", report)
        self.assertNotIn("Kite LTP status", report)


if __name__ == "__main__":
    unittest.main()