"""WatchlistRanker — scores and ranks instruments by trading opportunity quality.

Composite score weights:
  - regime_quality   0.35  (regime type × confidence)
  - rsi_momentum     0.20  (RSI normalised to [0, 1])
  - volatility_opp   0.20  (ATR/close, capped)
  - volume_ratio     0.15  (relative volume; defaults to 1.0 without history)
  - spread_liquidity 0.10  (defaults to 1.0 without quote data)
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from market_intelligence.multi_timeframe_context import (
    InstrumentScore,
    MarketRegime,
    MarketRegimeSnapshot,
    WatchlistRankingSnapshot,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")

# Weights must sum to 1.0
_W_REGIME = Decimal("0.35")
_W_RSI = Decimal("0.20")
_W_VOL_OPP = Decimal("0.20")
_W_VOLUME = Decimal("0.15")
_W_SPREAD = Decimal("0.10")

# Regime quality lookup (score × confidence in caller)
_REGIME_BASE: Dict[MarketRegime, Decimal] = {
    MarketRegime.STRONG_UPTREND: Decimal("1.0"),
    MarketRegime.UPTREND: Decimal("0.7"),
    MarketRegime.RANGING: Decimal("0.4"),
    MarketRegime.EXPANDING_RANGE: Decimal("0.5"),
    MarketRegime.STRONG_DOWNTREND: Decimal("0.1"),
    MarketRegime.DOWNTREND: Decimal("0.1"),
    MarketRegime.UNKNOWN: Decimal("0.3"),
}


class WatchlistRanker:
    """Stateless scorer.  Thread-safe (no mutable state)."""

    def score(
        self,
        instrument_token: str,
        indicators: Dict[str, Decimal],
        regime: Optional[MarketRegimeSnapshot] = None,
    ) -> InstrumentScore:
        """Score one instrument.  Returns composite score in [0, 1]."""
        factor_scores: Dict[str, Decimal] = {}

        # 1. Regime quality
        if regime is not None:
            base = _REGIME_BASE.get(regime.regime, Decimal("0.3"))
            # Weight by confidence
            rq = base * (Decimal("0.5") + Decimal("0.5") * regime.confidence)
        else:
            rq = Decimal("0.3")
        factor_scores["regime_quality"] = rq

        # 2. RSI momentum (normalised to [0, 1])
        rsi = indicators.get("rsi_14")
        rsi_score = (rsi / Decimal("100")) if rsi is not None else Decimal("0.5")
        factor_scores["rsi_momentum"] = rsi_score

        # 3. Volatility opportunity (ATR/close × 10, capped at 1.0)
        atr = indicators.get("atr_14")
        close = indicators.get("close")
        if atr is not None and close is not None and close > _ZERO:
            raw = atr / close * Decimal("10")
            vol_opp = min(raw, _ONE)
        else:
            vol_opp = Decimal("0.3")
        factor_scores["volatility_opportunity"] = vol_opp

        # 4. Volume ratio (default 1.0 — requires historical volume averages)
        volume_score = _ONE
        factor_scores["volume_ratio"] = volume_score

        # 5. Spread / liquidity (default 1.0 — requires Quote data)
        spread_score = _ONE
        factor_scores["spread_liquidity"] = spread_score

        composite = (
            rq * _W_REGIME
            + rsi_score * _W_RSI
            + vol_opp * _W_VOL_OPP
            + volume_score * _W_VOLUME
            + spread_score * _W_SPREAD
        )
        composite = max(_ZERO, min(_ONE, composite))

        return InstrumentScore(
            instrument_token=instrument_token,
            composite_score=composite,
            computed_at=datetime.utcnow(),
            factor_scores=factor_scores,
            rank=0,  # assigned by rank()
        )

    def rank(self, scores: List[InstrumentScore]) -> WatchlistRankingSnapshot:
        """Sort scores descending and assign integer ranks starting at 1."""
        if not scores:
            return WatchlistRankingSnapshot(scores=[], computed_at=datetime.utcnow())

        sorted_scores = sorted(scores, key=lambda s: s.composite_score, reverse=True)
        ranked = [
            InstrumentScore(
                instrument_token=s.instrument_token,
                composite_score=s.composite_score,
                computed_at=s.computed_at,
                factor_scores=s.factor_scores,
                rank=i + 1,
            )
            for i, s in enumerate(sorted_scores)
        ]
        return WatchlistRankingSnapshot(scores=ranked, computed_at=datetime.utcnow())
