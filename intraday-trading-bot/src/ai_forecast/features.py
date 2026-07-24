from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from market_intelligence.multi_timeframe_context import MultiTimeframeContext

logger = logging.getLogger(__name__)

FEATURE_SCHEMA_VERSION = "1.0"


class FeatureVector(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True)

    instrument_token: str
    features: Tuple[Decimal, ...]
    schema_version: str
    generated_at: str

    @property
    def feature_count(self) -> int:
        return len(self.features)


class FeatureGenerator:
    """Deterministic feature generator from MultiTimeframeContext.

    Produces exactly 42 features in fixed order:
    1.  SMA-10 / close
    2.  SMA-20 / close
    3.  SMA-50 / close
    4.  EMA-9 / close
    5.  EMA-21 / close
    6.  RSI-14
    7.  ATR-14 / close
    8.  ADX-14
    9.  +DI-14
    10. -DI-14
    11. MACD-line
    12. MACD-signal
    13. MACD-histogram
    14. VWAP / close
    15. Bollinger-upper / close
    16. Bollinger-lower / close
    17. Bollinger-width
    18. 5m SMA-10 / close
    19. 5m SMA-20 / close
    20. 5m RSI-14
    21. 5m ATR-14 / close
    22. 5m ADX-14
    23. 15m SMA-10 / close
    24. 15m SMA-20 / close
    25. 15m RSI-14
    26. 15m ATR-14 / close
    27. 15m ADX-14
    28. 1h SMA-10 / close
    29. 1h SMA-20 / close
    30. 1h RSI-14
    31. 1h ATR-14 / close
    32. 1h ADX-14
    33. Regime-confidence
    34. Regime-encoding (0=RANGING,1=UPTREND,2=DOWNTREND,3=STRONG_UPTREND,4=STRONG_DOWNTREND,5=EXPANDING_RANGE,6=UNKNOWN)
    35. Announcement-count
    36. Announcement-has-earnings (0/1)
    37. Announcement-has-dividend (0/1)
    38. Announcement-has-bonus (0/1)
    39. Announcement-has-split (0/1)
    40. Watchlist-rank / 100
    41. Watchlist-composite-score
    42. Time-of-day (minutes since 09:15 / 375)
    """

    _REGIME_ENCODING = {
        "RANGING": Decimal("0"),
        "UPTREND": Decimal("1"),
        "DOWNTREND": Decimal("2"),
        "STRONG_UPTREND": Decimal("3"),
        "STRONG_DOWNTREND": Decimal("4"),
        "EXPANDING_RANGE": Decimal("5"),
        "UNKNOWN": Decimal("6"),
    }

    def generate(
        self,
        instrument_token: str,
        mtf_context: MultiTimeframeContext,
        generated_at: str,
    ) -> FeatureVector:
        """Generate deterministic feature vector from multi-timeframe context."""
        features: List[Decimal] = []
        close = self._get_close(mtf_context)

        # 1m timeframe features (1-17)
        tf_1m = mtf_context.timeframes.get("1m", {})
        features.extend(self._extract_tf_features(tf_1m, close))

        # 5m timeframe features (18-22)
        tf_5m = mtf_context.timeframes.get("5m", {})
        features.extend(self._extract_tf_features_compact(tf_5m, close))

        # 15m timeframe features (23-27)
        tf_15m = mtf_context.timeframes.get("15m", {})
        features.extend(self._extract_tf_features_compact(tf_15m, close))

        # 1h timeframe features (28-32)
        tf_1h = mtf_context.timeframes.get("1h", {})
        features.extend(self._extract_tf_features_compact(tf_1h, close))

        # Regime features (33-34)
        regime = mtf_context.regime
        if regime:
            features.append(regime.confidence)
            features.append(self._REGIME_ENCODING.get(regime.regime.value, Decimal("6")))
        else:
            features.append(Decimal("0"))
            features.append(Decimal("6"))

        # Announcement features (35-39)
        announcements = mtf_context.active_announcements
        features.append(Decimal(str(len(announcements))))
        has_cls = {c: False for c in ["EARNINGS_RESULT", "DIVIDEND", "BONUS", "STOCK_SPLIT"]}
        for ann in announcements:
            if ann.classification in has_cls:
                has_cls[ann.classification] = True
        features.append(Decimal("1") if has_cls["EARNINGS_RESULT"] else Decimal("0"))
        features.append(Decimal("1") if has_cls["DIVIDEND"] else Decimal("0"))
        features.append(Decimal("1") if has_cls["BONUS"] else Decimal("0"))
        features.append(Decimal("1") if has_cls["STOCK_SPLIT"] else Decimal("0"))

        # Watchlist features (40-41)
        rank = mtf_context.watchlist_rank
        if rank is not None:
            features.append(Decimal(str(rank)) / Decimal("100"))
        else:
            features.append(Decimal("0"))

        score = mtf_context.composite_score
        if score is not None:
            features.append(score)
        else:
            features.append(Decimal("0"))

        # Time-of-day feature (42)
        features.append(self._time_of_day_feature(generated_at))

        assert len(features) == 42, f"Expected 42 features, got {len(features)}"

        return FeatureVector(
            instrument_token=instrument_token,
            features=tuple(features),
            schema_version=settings.ai_forecast.feature_schema_version,
            generated_at=generated_at,
        )

    def _get_close(self, mtf_context: MultiTimeframeContext) -> Decimal:
        """Get close price from 1m timeframe or default to 1."""
        tf_1m = mtf_context.timeframes.get("1m", {})
        close = tf_1m.get("close")
        if close is not None and close > 0:
            return close
        return Decimal("1")

    def _extract_tf_features(self, tf_data: Dict[str, Decimal], close: Decimal) -> List[Decimal]:
        """Extract 17 features from a single timeframe."""
        f: List[Decimal] = []

        sma10 = tf_data.get("sma_10")
        f.append(sma10 / close if sma10 is not None and close > 0 else Decimal("0"))

        sma20 = tf_data.get("sma_20")
        f.append(sma20 / close if sma20 is not None and close > 0 else Decimal("0"))

        sma50 = tf_data.get("sma_50")
        f.append(sma50 / close if sma50 is not None and close > 0 else Decimal("0"))

        ema9 = tf_data.get("ema_9")
        f.append(ema9 / close if ema9 is not None and close > 0 else Decimal("0"))

        ema21 = tf_data.get("ema_21")
        f.append(ema21 / close if ema21 is not None and close > 0 else Decimal("0"))

        rsi = tf_data.get("rsi_14")
        f.append(rsi if rsi is not None else Decimal("50"))

        atr = tf_data.get("atr_14")
        f.append(atr / close if atr is not None and close > 0 else Decimal("0"))

        adx = tf_data.get("adx_14")
        f.append(adx if adx is not None else Decimal("0"))

        pdi = tf_data.get("plus_di_14")
        f.append(pdi if pdi is not None else Decimal("0"))

        mdi = tf_data.get("minus_di_14")
        f.append(mdi if mdi is not None else Decimal("0"))

        macd = tf_data.get("macd_line")
        f.append(macd if macd is not None else Decimal("0"))

        signal = tf_data.get("macd_signal")
        f.append(signal if signal is not None else Decimal("0"))

        hist = tf_data.get("macd_histogram")
        f.append(hist if hist is not None else Decimal("0"))

        vwap = tf_data.get("vwap")
        f.append(vwap / close if vwap is not None and close > 0 else Decimal("0"))

        bb_upper = tf_data.get("bb_upper_20")
        f.append(bb_upper / close if bb_upper is not None and close > 0 else Decimal("0"))

        bb_lower = tf_data.get("bb_lower_20")
        f.append(bb_lower / close if bb_lower is not None and close > 0 else Decimal("0"))

        bb_middle = tf_data.get("bb_middle_20")
        if bb_upper is not None and bb_lower is not None and bb_middle is not None and bb_middle > 0:
            f.append((bb_upper - bb_lower) / bb_middle)
        else:
            f.append(Decimal("0"))

        return f

    def _extract_tf_features_compact(
        self, tf_data: Dict[str, Decimal], close: Decimal
    ) -> List[Decimal]:
        """Extract 5 compact features from a timeframe."""
        f: List[Decimal] = []

        sma10 = tf_data.get("sma_10")
        f.append(sma10 / close if sma10 is not None and close > 0 else Decimal("0"))

        sma20 = tf_data.get("sma_20")
        f.append(sma20 / close if sma20 is not None and close > 0 else Decimal("0"))

        rsi = tf_data.get("rsi_14")
        f.append(rsi if rsi is not None else Decimal("50"))

        atr = tf_data.get("atr_14")
        f.append(atr / close if atr is not None and close > 0 else Decimal("0"))

        adx = tf_data.get("adx_14")
        f.append(adx if adx is not None else Decimal("0"))

        return f

    def _time_of_day_feature(self, generated_at: str) -> Decimal:
        """Minutes since 09:15 IST / 375 (total NSE session minutes)."""
        try:
            from datetime import datetime, time, timedelta
            dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            ist = dt + timedelta(hours=5, minutes=30)
            market_open = time(9, 15)
            market_close = time(15, 30)
            t = ist.time()
            if t < market_open:
                return Decimal("0")
            if t > market_close:
                return Decimal("1")
            minutes = (t.hour - 9) * 60 + (t.minute - 15)
            return Decimal(str(minutes)) / Decimal("375")
        except Exception:
            return Decimal("0.5")
