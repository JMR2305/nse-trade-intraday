"""Unit tests for WatchlistRanker."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from market_intelligence.multi_timeframe_context import (
    InstrumentScore,
    MarketRegime,
    MarketRegimeSnapshot,
    WatchlistRankingSnapshot,
)
from market_intelligence.ranking import WatchlistRanker


class TestWatchlistRanker:
    def test_score_returns_instrument_score(self) -> None:
        ranker = WatchlistRanker()
        indicators = {"rsi_14": Decimal("55"), "atr_14": Decimal("2"), "close": Decimal("100")}
        regime = MarketRegimeSnapshot(
            instrument_token="INFY",
            regime=MarketRegime.UPTREND,
            confidence=Decimal("0.6"),
            detected_at=datetime.utcnow(),
        )
        score = ranker.score("INFY", indicators, regime)
        assert isinstance(score, InstrumentScore)
        assert score.instrument_token == "INFY"
        assert score.composite_score > Decimal("0")
        assert score.composite_score <= Decimal("1")

    def test_score_in_range_0_to_1(self) -> None:
        ranker = WatchlistRanker()
        for regime_type in MarketRegime:
            regime = MarketRegimeSnapshot(
                instrument_token="TEST",
                regime=regime_type,
                confidence=Decimal("0.5"),
                detected_at=datetime.utcnow(),
            )
            indicators = {"rsi_14": Decimal("50"), "atr_14": Decimal("2"), "close": Decimal("100")}
            score = ranker.score("TEST", indicators, regime)
            assert Decimal("0") <= score.composite_score <= Decimal("1")

    def test_rank_orders_descending(self) -> None:
        ranker = WatchlistRanker()
        scores = [
            InstrumentScore(instrument_token="A", composite_score=Decimal("0.9"), computed_at=datetime.utcnow()),
            InstrumentScore(instrument_token="B", composite_score=Decimal("0.5"), computed_at=datetime.utcnow()),
            InstrumentScore(instrument_token="C", composite_score=Decimal("0.7"), computed_at=datetime.utcnow()),
        ]
        ranking = ranker.rank(scores)
        assert len(ranking.scores) == 3
        assert ranking.scores[0].instrument_token == "A"
        assert ranking.scores[0].rank == 1
        assert ranking.scores[1].instrument_token == "C"
        assert ranking.scores[1].rank == 2
        assert ranking.scores[2].instrument_token == "B"
        assert ranking.scores[2].rank == 3

    def test_single_instrument_rank(self) -> None:
        ranker = WatchlistRanker()
        score = InstrumentScore(instrument_token="ONLY", composite_score=Decimal("0.5"), computed_at=datetime.utcnow())
        ranking = ranker.rank([score])
        assert len(ranking.scores) == 1
        assert ranking.scores[0].rank == 1

    def test_regime_quality_affects_score(self) -> None:
        ranker = WatchlistRanker()
        indicators = {"rsi_14": Decimal("50"), "atr_14": Decimal("2"), "close": Decimal("100")}
        strong_up = MarketRegimeSnapshot(
            instrument_token="A", regime=MarketRegime.STRONG_UPTREND,
            confidence=Decimal("0.9"), detected_at=datetime.utcnow(),
        )
        down = MarketRegimeSnapshot(
            instrument_token="B", regime=MarketRegime.DOWNTREND,
            confidence=Decimal("0.6"), detected_at=datetime.utcnow(),
        )
        score_up = ranker.score("A", indicators, strong_up)
        score_down = ranker.score("B", indicators, down)
        assert score_up.composite_score > score_down.composite_score

    def test_no_regime_uses_default(self) -> None:
        ranker = WatchlistRanker()
        indicators = {"rsi_14": Decimal("50"), "atr_14": Decimal("2"), "close": Decimal("100")}
        score = ranker.score("INFY", indicators, None)
        assert score.composite_score > Decimal("0")
        assert "regime_quality" in score.factor_scores

    def test_empty_list_returns_empty_ranking(self) -> None:
        ranker = WatchlistRanker()
        ranking = ranker.rank([])
        assert len(ranking.scores) == 0

    def test_factor_scores_present(self) -> None:
        ranker = WatchlistRanker()
        indicators = {"rsi_14": Decimal("60"), "atr_14": Decimal("1.5"), "close": Decimal("200")}
        score = ranker.score("INFY", indicators, None)
        assert "regime_quality" in score.factor_scores
        assert "rsi_momentum" in score.factor_scores
        assert "volatility_opportunity" in score.factor_scores

    def test_determinism(self) -> None:
        ranker = WatchlistRanker()
        indicators = {"rsi_14": Decimal("50"), "atr_14": Decimal("2"), "close": Decimal("100")}
        regime = MarketRegimeSnapshot(
            instrument_token="INFY", regime=MarketRegime.UPTREND,
            confidence=Decimal("0.6"), detected_at=datetime.utcnow(),
        )
        s1 = ranker.score("INFY", indicators, regime)
        s2 = ranker.score("INFY", indicators, regime)
        assert s1.composite_score == s2.composite_score
