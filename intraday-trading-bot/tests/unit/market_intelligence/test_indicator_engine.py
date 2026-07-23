"""Unit tests for IndicatorEngine and pure indicator functions."""
from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal
from typing import List

import pytest

from market_data.contracts import CompletedBar
from market_intelligence.indicator_engine import (
    IndicatorEngine,
    compute_sma,
    compute_ema,
    compute_rsi,
    compute_atr,
    compute_adx,
    compute_macd,
    compute_vwap,
    compute_bollinger,
)


def make_bars(
    count: int, start_price: Decimal = Decimal("100"), token: str = "INFY"
) -> List[CompletedBar]:
    bars = []
    base = datetime(2026, 7, 23, 9, 15)
    price = start_price
    for i in range(count):
        o = price
        c = price + Decimal(str((i % 5) - 2))
        h = max(o, c) + Decimal("1")
        lo = min(o, c) - Decimal("1")
        bars.append(
            CompletedBar(
                instrument_token=token,
                timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=Decimal("1000"),
                interval="1m",
            )
        )
        price = c
    return bars


def make_trending_bars(
    count: int, token: str = "INFY", uptrend: bool = True
) -> List[CompletedBar]:
    bars = []
    base = datetime(2026, 7, 23, 9, 15)
    price = Decimal("100")
    for i in range(count):
        delta = Decimal("0.5") if uptrend else Decimal("-0.5")
        o = price
        c = price + delta
        h = max(o, c) + Decimal("0.3")
        lo = min(o, c) - Decimal("0.2")
        bars.append(
            CompletedBar(
                instrument_token=token,
                timestamp=(base + dt.timedelta(minutes=i)).isoformat(),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=Decimal("1000"),
                interval="1m",
            )
        )
        price = c
    return bars


class TestComputeSMA:
    def test_known_value_simple(self) -> None:
        bars = make_bars(10, Decimal("100"))
        sma = compute_sma(bars, 5)
        closes = [b.close for b in bars[-5:]]
        expected = sum(closes) / Decimal("5")
        assert sma == expected

    def test_insufficient_data_returns_none(self) -> None:
        bars = make_bars(3)
        assert compute_sma(bars, 5) is None

    def test_single_period(self) -> None:
        bars = make_bars(1, Decimal("100"))
        sma = compute_sma(bars, 1)
        assert sma == bars[0].close


class TestComputeEMA:
    def test_converges_to_price(self) -> None:
        bars = make_bars(50, Decimal("100"))
        ema = compute_ema(bars, 10)
        assert ema is not None
        assert abs(ema - bars[-1].close) < Decimal("10")

    def test_insufficient_data_returns_none(self) -> None:
        bars = make_bars(5)
        assert compute_ema(bars, 10) is None

    def test_ema_close_to_sma_stable(self) -> None:
        bars = make_bars(20, Decimal("100"))
        ema = compute_ema(bars, 10)
        sma = compute_sma(bars, 10)
        assert ema is not None and sma is not None
        assert abs(ema - sma) < Decimal("5")


class TestComputeRSI:
    def test_uptrend_rsi_high(self) -> None:
        bars = make_trending_bars(20, uptrend=True)
        rsi = compute_rsi(bars, 14)
        assert rsi is not None
        assert Decimal("0") <= rsi <= Decimal("100")
        assert rsi > Decimal("50")

    def test_downtrend_rsi_low(self) -> None:
        bars = make_trending_bars(20, uptrend=False)
        rsi = compute_rsi(bars, 14)
        assert rsi is not None
        assert rsi < Decimal("50")

    def test_ranging_rsi_mid(self) -> None:
        bars = make_bars(30, Decimal("100"))
        rsi = compute_rsi(bars, 14)
        assert rsi is not None
        assert Decimal("0") <= rsi <= Decimal("100")

    def test_insufficient_data_returns_none(self) -> None:
        bars = make_bars(10)
        assert compute_rsi(bars, 14) is None


class TestComputeATR:
    def test_positive_atr(self) -> None:
        bars = make_bars(20, Decimal("100"))
        atr = compute_atr(bars, 14)
        assert atr is not None
        assert atr > Decimal("0")

    def test_insufficient_data_returns_none(self) -> None:
        bars = make_bars(5)
        assert compute_atr(bars, 14) is None


class TestComputeADX:
    def test_returns_tuple_with_enough_bars(self) -> None:
        bars = make_trending_bars(40, uptrend=True)
        result = compute_adx(bars, 14)
        assert result is not None
        adx, plus_di, minus_di = result
        assert adx >= Decimal("0")
        assert plus_di >= Decimal("0")
        assert minus_di >= Decimal("0")

    def test_uptrend_plus_di_greater(self) -> None:
        bars = make_trending_bars(40, uptrend=True)
        result = compute_adx(bars, 14)
        assert result is not None
        _, plus_di, minus_di = result
        assert plus_di > minus_di

    def test_downtrend_minus_di_greater(self) -> None:
        bars = make_trending_bars(40, uptrend=False)
        result = compute_adx(bars, 14)
        assert result is not None
        _, plus_di, minus_di = result
        assert minus_di > plus_di

    def test_insufficient_data_returns_none(self) -> None:
        bars = make_bars(10)
        assert compute_adx(bars, 14) is None


class TestComputeVWAP:
    def test_positive_vwap(self) -> None:
        bars = make_bars(10, Decimal("100"))
        vwap = compute_vwap(bars)
        assert vwap is not None
        assert vwap > Decimal("0")

    def test_empty_bars_returns_none(self) -> None:
        assert compute_vwap([]) is None

    def test_vwap_reasonable_range(self) -> None:
        bars = make_bars(30, Decimal("100"))
        vwap = compute_vwap(bars)
        assert vwap is not None
        closes = [b.close for b in bars]
        assert min(closes) <= vwap <= max(closes) + Decimal("5")


class TestComputeBollinger:
    def test_upper_above_lower(self) -> None:
        bars = make_bars(25, Decimal("100"))
        result = compute_bollinger(bars, 20, 2)
        assert result is not None
        upper, middle, lower = result
        assert upper > lower
        assert upper > middle > lower

    def test_insufficient_data_returns_none(self) -> None:
        bars = make_bars(10)
        assert compute_bollinger(bars, 20, 2) is None


class TestIndicatorEngine:
    def test_known_indicator_keys(self) -> None:
        engine = IndicatorEngine(max_bars=100)
        bars = make_bars(30, Decimal("100"))
        for b in bars:
            engine.update(b, "1m")
        indicators = engine.get_indicators("INFY", "1m")
        assert "sma_20" in indicators
        assert "rsi_14" in indicators
        assert "atr_14" in indicators
        assert "macd_line" in indicators
        assert "vwap" in indicators
        assert "bb_upper_20" in indicators

    def test_buffer_bounded(self) -> None:
        engine = IndicatorEngine(max_bars=5)
        bars = make_bars(10, Decimal("100"))
        for b in bars:
            engine.update(b, "1m")
        stored = engine.get_bars("INFY", "1m")
        assert len(stored) == 5

    def test_insufficient_data_returns_partial(self) -> None:
        engine = IndicatorEngine(max_bars=100)
        bar = make_bars(1)[0]
        engine.update(bar, "1m")
        indicators = engine.get_indicators("INFY", "1m")
        assert "rsi_14" not in indicators
        assert "adx_14" not in indicators

    def test_get_all_timeframes(self) -> None:
        engine = IndicatorEngine(max_bars=50)
        bars = make_bars(30, Decimal("100"))
        for b in bars:
            engine.update(b, "1m")
            engine.update(b, "5m")
        all_tf = engine.get_all_timeframes("INFY")
        assert "1m" in all_tf
        assert "5m" in all_tf

    def test_determinism(self) -> None:
        engine1 = IndicatorEngine(max_bars=50)
        engine2 = IndicatorEngine(max_bars=50)
        bars = make_bars(40, Decimal("100"))
        for b in bars:
            engine1.update(b, "1m")
            engine2.update(b, "1m")
        ind1 = engine1.get_indicators("INFY", "1m")
        ind2 = engine2.get_indicators("INFY", "1m")
        assert set(ind1.keys()) == set(ind2.keys())
        for k in ind1:
            assert ind1[k] == ind2[k], f"Mismatch for {k}: {ind1[k]} != {ind2[k]}"

    def test_unknown_instrument_returns_empty(self) -> None:
        engine = IndicatorEngine()
        assert engine.get_indicators("UNKNOWN", "1m") == {}
        assert engine.get_all_timeframes("UNKNOWN") == {}
