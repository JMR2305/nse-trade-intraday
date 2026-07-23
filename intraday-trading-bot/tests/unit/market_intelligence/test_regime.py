"""Unit tests for MarketRegimeDetector."""
from __future__ import annotations

from decimal import Decimal

from market_intelligence.multi_timeframe_context import MarketRegime
from market_intelligence.regime import MarketRegimeDetector


class TestMarketRegimeDetector:
    def test_strong_uptrend(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("45"),
            "plus_di_14": Decimal("35"),
            "minus_di_14": Decimal("15"),
            "atr_14": Decimal("2"),
            "close": Decimal("100"),
        }
        result = detector.detect("INFY", indicators)
        assert result.regime == MarketRegime.STRONG_UPTREND
        assert result.confidence > Decimal("0.8")
        assert result.confidence <= Decimal("1")

    def test_uptrend(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("30"),
            "plus_di_14": Decimal("28"),
            "minus_di_14": Decimal("18"),
            "atr_14": Decimal("1.5"),
            "close": Decimal("100"),
        }
        result = detector.detect("INFY", indicators)
        assert result.regime == MarketRegime.UPTREND
        assert result.confidence > Decimal("0.5")

    def test_strong_downtrend(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("42"),
            "plus_di_14": Decimal("12"),
            "minus_di_14": Decimal("38"),
            "atr_14": Decimal("2.5"),
            "close": Decimal("100"),
        }
        result = detector.detect("INFY", indicators)
        assert result.regime == MarketRegime.STRONG_DOWNTREND

    def test_downtrend(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("28"),
            "plus_di_14": Decimal("15"),
            "minus_di_14": Decimal("30"),
            "atr_14": Decimal("1.8"),
            "close": Decimal("100"),
        }
        result = detector.detect("INFY", indicators)
        assert result.regime == MarketRegime.DOWNTREND

    def test_ranging(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("15"),
            "plus_di_14": Decimal("20"),
            "minus_di_14": Decimal("18"),
            "atr_14": Decimal("0.3"),
            "close": Decimal("100"),
        }
        result = detector.detect("INFY", indicators)
        assert result.regime == MarketRegime.RANGING

    def test_expanding_range(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("25"),
            "plus_di_14": Decimal("22"),
            "minus_di_14": Decimal("20"),
            "atr_14": Decimal("3"),
            "close": Decimal("100"),
        }
        result = detector.detect("INFY", indicators)
        assert result.regime == MarketRegime.EXPANDING_RANGE

    def test_unknown_insufficient_data(self) -> None:
        detector = MarketRegimeDetector()
        result = detector.detect("INFY", {})
        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == Decimal("0")

    def test_confidence_clamped_to_1(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("60"),
            "plus_di_14": Decimal("40"),
            "minus_di_14": Decimal("10"),
        }
        result = detector.detect("INFY", indicators)
        assert result.confidence <= Decimal("1")

    def test_confidence_zero_when_adx_zero(self) -> None:
        detector = MarketRegimeDetector()
        indicators = {
            "adx_14": Decimal("0"),
            "plus_di_14": Decimal("20"),
            "minus_di_14": Decimal("20"),
        }
        result = detector.detect("INFY", indicators)
        assert result.confidence == Decimal("0")

    def test_different_instruments_independent(self) -> None:
        detector = MarketRegimeDetector()
        ind1 = {"adx_14": Decimal("35"), "plus_di_14": Decimal("30"), "minus_di_14": Decimal("10")}
        ind2 = {"adx_14": Decimal("35"), "plus_di_14": Decimal("10"), "minus_di_14": Decimal("30")}
        r1 = detector.detect("INFY", ind1)
        r2 = detector.detect("TCS", ind2)
        assert r1.regime == MarketRegime.UPTREND
        assert r2.regime == MarketRegime.DOWNTREND

    def test_instrument_token_preserved(self) -> None:
        detector = MarketRegimeDetector()
        result = detector.detect("RELIANCE", {})
        assert result.instrument_token == "RELIANCE"
