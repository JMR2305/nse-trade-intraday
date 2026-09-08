"""
test_backtest_ohlcv_integration.py — Task: wire daily backtest fetches
through the local OHLCV cache (backtest_data_bridge).

All tests are unit-level: DB and yfinance are mocked. Never hits network.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

import pandas as pd

import backtest_data_bridge as bdb


def _make_df(n_bars: int = 150, end: date | None = None) -> pd.DataFrame:
    """Synthetic-but-valid OHLCV frame for mocking cache/yfinance returns."""
    end = end or date.today()
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n_bars)
    base = pd.Series(range(n_bars), index=idx, dtype=float) + 100.0
    return pd.DataFrame({
        "open": base, "high": base + 1, "low": base - 1,
        "close": base + 0.5, "volume": [10_000] * n_bars,
    }, index=idx)


class TestBacktestDataBridge(unittest.TestCase):

    # 1. Warm cache covering the window → served from cache, yfinance NOT called
    def test_cache_hit_skips_yfinance(self):
        end = date.today()
        start = end - timedelta(days=90)
        cached = _make_df(150, end=end)
        with patch("ohlcv_cache_store.read_symbol_from_cache", return_value=cached), \
             patch("market_data_engine.fetch_candles_df") as yf_mock:
            df, source = bdb.fetch_candles_for_backtest(
                "RELIANCE", interval="1d",
                start_date=start.isoformat(), end_date=end.isoformat(),
            )
        self.assertEqual(source, bdb.SOURCE_CACHE)
        self.assertFalse(df.empty)
        yf_mock.assert_not_called()
        # window sliced correctly
        self.assertGreaterEqual(df.index[0].date(), start)
        self.assertLessEqual(df.index[-1].date(), end)

    # 2. Cache miss → yfinance fetched AND written back to the cache
    def test_cache_miss_falls_to_yfinance_and_writes_back(self):
        fresh = _make_df(150)
        with patch("ohlcv_cache_store.read_symbol_from_cache", return_value=None), \
             patch("ohlcv_cache_store.write_symbol_to_cache", return_value=150) as wb, \
             patch("market_data_engine.fetch_candles_df", return_value=fresh), \
             patch("market_data_engine.get_last_source", return_value="yfinance"):
            df, source = bdb.fetch_candles_for_backtest("TCS", interval="1d", period="6mo")
        self.assertEqual(source, bdb.SOURCE_YFINANCE)
        self.assertEqual(len(df), 150)
        wb.assert_called_once()
        self.assertEqual(wb.call_args.kwargs.get("source", wb.call_args.args[-1] if len(wb.call_args.args) > 2 else "yfinance"), "yfinance")

    # 3. Mock candles are surfaced as source="mock" and NEVER cached
    def test_mock_candles_never_written_to_cache(self):
        mock_df = _make_df(150)
        with patch("ohlcv_cache_store.read_symbol_from_cache", return_value=None), \
             patch("ohlcv_cache_store.write_symbol_to_cache") as wb, \
             patch("market_data_engine.fetch_candles_df", return_value=mock_df), \
             patch("market_data_engine.get_last_source", return_value="mock"):
            df, source = bdb.fetch_candles_for_backtest("INFY", interval="1d", period="6mo")
        self.assertEqual(source, bdb.SOURCE_MOCK)
        wb.assert_not_called()

    # 4. Intraday intervals bypass the cache entirely
    def test_intraday_bypasses_cache(self):
        intraday = _make_df(200)
        with patch("ohlcv_cache_store.read_symbol_from_cache") as rc, \
             patch("market_data_engine.fetch_candles_df", return_value=intraday), \
             patch("market_data_engine.get_last_source", return_value="yfinance"):
            df, source = bdb.fetch_candles_for_backtest("HDFCBANK", interval="15m", period="3mo")
        self.assertEqual(source, bdb.SOURCE_YFINANCE)
        rc.assert_not_called()

    # 5. As-of read: end_date is forwarded to the cache read
    def test_as_of_end_date_forwarded_to_cache_read(self):
        end = (date.today() - timedelta(days=30)).isoformat()
        with patch("ohlcv_cache_store.read_symbol_from_cache", return_value=None) as rc, \
             patch("market_data_engine.fetch_candles_df", return_value=pd.DataFrame()), \
             patch("market_data_engine.get_last_source", return_value="yfinance"):
            df, source = bdb.fetch_candles_for_backtest("SBIN", interval="1d", end_date=end)
        self.assertEqual(rc.call_args.kwargs.get("end_date"), end)
        self.assertEqual(source, bdb.SOURCE_NONE)
        self.assertTrue(df.empty)

    # 6. Cache that does NOT cover the requested window falls through to yfinance
    def test_insufficient_cache_coverage_falls_to_yfinance(self):
        end = date.today()
        # cache only holds ~6 months; request 2 years
        cached = _make_df(124, end=end)
        start_2y = (end - timedelta(days=730)).isoformat()
        full = _make_df(500, end=end)
        with patch("ohlcv_cache_store.read_symbol_from_cache", return_value=cached), \
             patch("ohlcv_cache_store.write_symbol_to_cache", return_value=500), \
             patch("market_data_engine.fetch_candles_df", return_value=full) as yf_mock, \
             patch("market_data_engine.get_last_source", return_value="yfinance"):
            df, source = bdb.fetch_candles_for_backtest(
                "WIPRO", interval="1d",
                start_date=start_2y, end_date=end.isoformat(),
            )
        self.assertEqual(source, bdb.SOURCE_YFINANCE)
        yf_mock.assert_called_once()

    # 7. run_backtest() reports the bridge-returned data_source
    def test_run_backtest_data_source_from_bridge(self):
        import backtesting_engine as be
        cached = _make_df(400)
        end = date.today()
        start = (end - timedelta(days=365)).isoformat()
        with patch("backtest_data_bridge.fetch_candles_for_backtest",
                   return_value=(cached, bdb.SOURCE_CACHE)):
            result = be.run_backtest(
                symbol="RELIANCE", strategy_name="trend_rider",
                start_date=start, end_date=end.isoformat(),
                initial_capital=100000.0, interval="1d",
            )
        self.assertEqual(result["data_source"], bdb.SOURCE_CACHE)

    # 8. Period-only request against an oversized warm cache must be sliced
    #    down to the period window — never silently widened.
    def test_period_only_request_sliced_from_oversized_cache(self):
        end = date.today()
        cached = _make_df(520, end=end)  # ~2 years in cache
        with patch("ohlcv_cache_store.read_symbol_from_cache", return_value=cached), \
             patch("market_data_engine.fetch_candles_df") as yf_mock:
            df, source = bdb.fetch_candles_for_backtest("RELIANCE", interval="1d", period="3mo")
        self.assertEqual(source, bdb.SOURCE_CACHE)
        yf_mock.assert_not_called()
        self.assertGreaterEqual(
            df.index[0].date(), end - timedelta(days=bdb._PERIOD_DAYS["3mo"] + 1)
        )
        # ~3 months of business days, not 2 years
        self.assertLess(len(df), 80)

    # 9. run_backtest() blocks mock candles with an explicit error
    def test_run_backtest_blocks_mock(self):
        import backtesting_engine as be
        mock_df = _make_df(400)
        with patch("backtest_data_bridge.fetch_candles_for_backtest",
                   return_value=(mock_df, bdb.SOURCE_MOCK)):
            result = be.run_backtest(
                symbol="RELIANCE", strategy_name="trend_rider",
                start_date=(date.today() - timedelta(days=365)).isoformat(),
                end_date=date.today().isoformat(),
                initial_capital=100000.0, interval="1d",
            )
        self.assertEqual(result["total_trades"], 0)
        self.assertIn("mock", result["validation"]["reason"].lower()
                      if isinstance(result.get("validation"), dict) and "reason" in result["validation"]
                      else str(result).lower())

    # 10. run_strategy_lab() blocks mock candles with explicit error entries
    def test_strategy_lab_blocks_mock(self):
        import backtesting_engine as be
        mock_df = _make_df(400)
        with patch("backtest_data_bridge.fetch_candles_for_backtest",
                   return_value=(mock_df, bdb.SOURCE_MOCK)):
            entries = be.run_strategy_lab(
                symbol="RELIANCE",
                start_date=(date.today() - timedelta(days=180)).isoformat(),
                end_date=date.today().isoformat(),
            )
        self.assertTrue(entries)
        for e in entries:
            self.assertIn("mock", str(e).lower())

    # 11. Safety: the bridge module contains no live-order / paper-ledger writes
    def test_bridge_has_no_trading_side_effects(self):
        import inspect
        src = inspect.getsource(bdb)
        for forbidden in ("paper_trades", "paper_portfolio", "place_order",
                          "execute_buy", "execute_sell", "ORDER_"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
