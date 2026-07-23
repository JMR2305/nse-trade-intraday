"""StrategyScorer — scores strategy alignment with current market conditions.

Regime alignment is computed per-instrument and averaged.
Instrument suitability is derived from WatchlistRankingSnapshot scores.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional

from market_intelligence.multi_timeframe_context import (
    MarketRegime,
    MarketRegimeSnapshot,
    StrategyScore,
    WatchlistRankingSnapshot,
)
from strategy.contracts import StrategyConfig

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")

# Per-strategy-type preferred regimes and their alignment weights
_TREND_ALIGNMENT: Dict[MarketRegime, Decimal] = {
    MarketRegime.STRONG_UPTREND: Decimal("1.0"),
    MarketRegime.UPTREND: Decimal("0.8"),
    MarketRegime.STRONG_DOWNTREND: Decimal("0.7"),
    MarketRegime.DOWNTREND: Decimal("0.6"),
    MarketRegime.EXPANDING_RANGE: Decimal("0.4"),
    MarketRegime.RANGING: Decimal("0.2"),
    MarketRegime.UNKNOWN: Decimal("0.3"),
}

_MEAN_REVERSION_ALIGNMENT: Dict[MarketRegime, Decimal] = {
    MarketRegime.RANGING: Decimal("1.0"),
    MarketRegime.EXPANDING_RANGE: Decimal("0.7"),
    MarketRegime.UNKNOWN: Decimal("0.4"),
    MarketRegime.UPTREND: Decimal("0.3"),
    MarketRegime.DOWNTREND: Decimal("0.3"),
    MarketRegime.STRONG_UPTREND: Decimal("0.1"),
    MarketRegime.STRONG_DOWNTREND: Decimal("0.1"),
}

_DEFAULT_ALIGNMENT: Dict[MarketRegime, Decimal] = {
    r: Decimal("0.5") for r in MarketRegime
}


def _get_alignment_table(strategy_type: str) -> Dict[MarketRegime, Decimal]:
    st = strategy_type.lower()
    if "trend" in st:
        return _TREND_ALIGNMENT
    if "mean_reversion" in st or "mean reversion" in st or "reversion" in st:
        return _MEAN_REVERSION_ALIGNMENT
    return _DEFAULT_ALIGNMENT


class StrategyScorer:
    """Stateless scorer.  Thread-safe (no mutable state)."""

    def score(
        self,
        config: StrategyConfig,
        ranking: WatchlistRankingSnapshot,
        regimes: Dict[str, MarketRegimeSnapshot],
    ) -> StrategyScore:
        """Score a strategy's alignment with current market conditions."""
        if not config.instrument_tokens:
            return StrategyScore(
                strategy_id=config.strategy_id,
                score=_ZERO,
                regime_alignment=_ZERO,
                instrument_suitability=_ZERO,
                computed_at=datetime.utcnow(),
            )

        alignment_table = _get_alignment_table(config.strategy_type)

        # Regime alignment: average over instruments
        total_align = _ZERO
        count = 0
        for token in config.instrument_tokens:
            regime_snap = regimes.get(token)
            if regime_snap is not None:
                base = alignment_table.get(regime_snap.regime, Decimal("0.3"))
                # Weight by confidence
                adjusted = base * (Decimal("0.5") + Decimal("0.5") * regime_snap.confidence)
                total_align += adjusted
                count += 1

        regime_alignment = (total_align / Decimal(str(count))) if count > 0 else Decimal("0.4")
        regime_alignment = max(_ZERO, min(_ONE, regime_alignment))

        # Instrument suitability: average composite score for configured instruments
        rank_map = {s.instrument_token: s.composite_score for s in ranking.scores}
        total_suit = _ZERO
        suit_count = 0
        for token in config.instrument_tokens:
            cs = rank_map.get(token)
            if cs is not None:
                total_suit += cs
                suit_count += 1

        if suit_count > 0:
            instrument_suitability = total_suit / Decimal(str(suit_count))
        else:
            instrument_suitability = Decimal("0.5")  # neutral default
        instrument_suitability = max(_ZERO, min(_ONE, instrument_suitability))

        # Overall score: weighted combination
        overall = (
            regime_alignment * Decimal("0.6") + instrument_suitability * Decimal("0.4")
        )
        overall = max(_ZERO, min(_ONE, overall))

        return StrategyScore(
            strategy_id=config.strategy_id,
            score=overall,
            regime_alignment=regime_alignment,
            instrument_suitability=instrument_suitability,
            computed_at=datetime.utcnow(),
        )
