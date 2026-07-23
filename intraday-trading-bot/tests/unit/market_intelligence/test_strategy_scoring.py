"""Unit tests for StrategyScorer."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from market_intelligence.multi_timeframe_context import (
    InstrumentScore,
    MarketRegime,
    MarketRegimeSnapshot,
    StrategyScore,
    WatchlistRankingSnapshot,
)
from market_intelligence.strategy_scoring import StrategyScorer
from strategy.contracts import StrategyConfig


class TestStrategyScorer:
    def test_high_regime_alignment_for_trend_strategy(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="trend_1",
            strategy_type="trend",
            name="Test Trend",
            instrument_tokens=["INFY", "TCS"],
        )
        ranking = WatchlistRankingSnapshot(
            scores=[
                InstrumentScore(instrument_token="INFY", composite_score=Decimal("0.8"), computed_at=datetime.utcnow()),
                InstrumentScore(instrument_token="TCS", composite_score=Decimal("0.7"), computed_at=datetime.utcnow()),
            ]
        )
        regimes = {
            "INFY": MarketRegimeSnapshot(
                instrument_token="INFY", regime=MarketRegime.STRONG_UPTREND,
                confidence=Decimal("0.8"), detected_at=datetime.utcnow(),
            ),
            "TCS": MarketRegimeSnapshot(
                instrument_token="TCS", regime=MarketRegime.UPTREND,
                confidence=Decimal("0.6"), detected_at=datetime.utcnow(),
            ),
        }
        result = scorer.score(config, ranking, regimes)
        assert isinstance(result, StrategyScore)
        assert result.regime_alignment > Decimal("0.5")
        assert result.instrument_suitability > Decimal("0.5")
        assert Decimal("0") <= result.score <= Decimal("1")

    def test_low_score_for_counter_trend(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="trend_1",
            strategy_type="trend",
            name="Test Trend",
            instrument_tokens=["INFY"],
        )
        ranking = WatchlistRankingSnapshot(
            scores=[InstrumentScore(instrument_token="INFY", composite_score=Decimal("0.3"), computed_at=datetime.utcnow())]
        )
        regimes = {
            "INFY": MarketRegimeSnapshot(
                instrument_token="INFY", regime=MarketRegime.RANGING,
                confidence=Decimal("0.4"), detected_at=datetime.utcnow(),
            )
        }
        result = scorer.score(config, ranking, regimes)
        assert result.score < Decimal("0.6")

    def test_empty_instrument_list(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="empty",
            strategy_type="trend",
            name="Empty",
            instrument_tokens=[],
        )
        result = scorer.score(config, WatchlistRankingSnapshot(scores=[]), {})
        assert result.score == Decimal("0")
        assert result.regime_alignment == Decimal("0")
        assert result.instrument_suitability == Decimal("0")

    def test_mean_reversion_prefers_ranging(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="mr_1",
            strategy_type="mean_reversion",
            name="Mean Reversion",
            instrument_tokens=["INFY"],
        )
        ranking = WatchlistRankingSnapshot(
            scores=[InstrumentScore(instrument_token="INFY", composite_score=Decimal("0.6"), computed_at=datetime.utcnow())]
        )
        regimes_ranging = {
            "INFY": MarketRegimeSnapshot(
                instrument_token="INFY", regime=MarketRegime.RANGING,
                confidence=Decimal("0.7"), detected_at=datetime.utcnow(),
            )
        }
        regimes_trend = {
            "INFY": MarketRegimeSnapshot(
                instrument_token="INFY", regime=MarketRegime.STRONG_UPTREND,
                confidence=Decimal("0.9"), detected_at=datetime.utcnow(),
            )
        }
        result_ranging = scorer.score(config, ranking, regimes_ranging)
        result_trend = scorer.score(config, ranking, regimes_trend)
        assert result_ranging.regime_alignment > result_trend.regime_alignment

    def test_score_in_range(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="s1",
            strategy_type="trend",
            name="S",
            instrument_tokens=["A"],
        )
        ranking = WatchlistRankingSnapshot(
            scores=[InstrumentScore(instrument_token="A", composite_score=Decimal("0.5"), computed_at=datetime.utcnow())]
        )
        regimes = {
            "A": MarketRegimeSnapshot(
                instrument_token="A", regime=MarketRegime.UPTREND,
                confidence=Decimal("0.5"), detected_at=datetime.utcnow(),
            )
        }
        result = scorer.score(config, ranking, regimes)
        assert Decimal("0") <= result.score <= Decimal("1")
        assert Decimal("0") <= result.regime_alignment <= Decimal("1")
        assert Decimal("0") <= result.instrument_suitability <= Decimal("1")

    def test_no_regimes_still_scores(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="s2", strategy_type="trend", name="S2", instrument_tokens=["X"]
        )
        ranking = WatchlistRankingSnapshot(
            scores=[InstrumentScore(instrument_token="X", composite_score=Decimal("0.6"), computed_at=datetime.utcnow())]
        )
        result = scorer.score(config, ranking, {})
        assert result.score > Decimal("0")

    def test_strategy_id_preserved(self) -> None:
        scorer = StrategyScorer()
        config = StrategyConfig(
            strategy_id="my_strat", strategy_type="trend", name="Test", instrument_tokens=[]
        )
        result = scorer.score(config, WatchlistRankingSnapshot(scores=[]), {})
        assert result.strategy_id == "my_strat"
