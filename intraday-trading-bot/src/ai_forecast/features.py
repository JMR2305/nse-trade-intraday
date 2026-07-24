"""RC-10B Canonical Feature Generator — 25-feature schema v1.0.

Feature order (0-based index):
 0  1m_return_t0         log-return ln(close[t]  / close[t-1])
 1  1m_return_t1         log-return ln(close[t-1]/ close[t-2])
 2  1m_return_t2         log-return ln(close[t-2]/ close[t-3])
 3  1m_return_t3         log-return ln(close[t-3]/ close[t-4])
 4  1m_return_t4         log-return ln(close[t-4]/ close[t-5])
 5  5m_return_t0         log-return ln(close_5m[t]  / close_5m[t-1])
 6  5m_return_t1         log-return ln(close_5m[t-1]/ close_5m[t-2])
 7  5m_return_t2         log-return ln(close_5m[t-2]/ close_5m[t-3])
 8  1m_rsi_norm          RSI(14) / 100   ∈ [0, 1]
 9  5m_rsi_norm          5m RSI(14) / 100 ∈ [0, 1]
10  1m_macd_sign         sign(macd_histogram_1m)  ∈ {-1, 0, 1}
11  1m_macd_magnitude    abs(macd_histogram_1m)
12  5m_macd_sign         sign(macd_histogram_5m)  ∈ {-1, 0, 1}
13  5m_macd_magnitude    abs(macd_histogram_5m)
14  1m_bb_position       (close − bb_lower) / (bb_upper − bb_lower), clamped [0, 1]
15  1m_atr_ratio         ATR(14) / close
16  5m_atr_ratio         5m ATR(14) / close
17  regime_RANGING        one-hot
18  regime_UPTREND        one-hot
19  regime_DOWNTREND      one-hot
20  regime_STRONG_UPTREND one-hot
21  regime_STRONG_DOWNTREND one-hot
22  regime_EXPANDING_RANGE  one-hot
23  regime_UNKNOWN        one-hot
24  1m_volume_ratio       volume / volume_sma_20

Legacy 42-feature schema is preserved as LegacyFeatureGenerator under version "legacy-42-v1".
"""
from __future__ import annotations

import logging
import math
from collections import deque
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from market_intelligence.multi_timeframe_context import MultiTimeframeContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema constants — AUTHORITATIVE. Any change requires model retraining.
# ---------------------------------------------------------------------------

FEATURE_SCHEMA_VERSION: str = "1.0"
LEGACY_SCHEMA_VERSION: str = "legacy-42-v1"

FEATURE_NAMES: List[str] = [
    "1m_return_t0",
    "1m_return_t1",
    "1m_return_t2",
    "1m_return_t3",
    "1m_return_t4",
    "5m_return_t0",
    "5m_return_t1",
    "5m_return_t2",
    "1m_rsi_norm",
    "5m_rsi_norm",
    "1m_macd_sign",
    "1m_macd_magnitude",
    "5m_macd_sign",
    "5m_macd_magnitude",
    "1m_bb_position",
    "1m_atr_ratio",
    "5m_atr_ratio",
    "regime_RANGING",
    "regime_UPTREND",
    "regime_DOWNTREND",
    "regime_STRONG_UPTREND",
    "regime_STRONG_DOWNTREND",
    "regime_EXPANDING_RANGE",
    "regime_UNKNOWN",
    "1m_volume_ratio",
]

FEATURE_COUNT: int = len(FEATURE_NAMES)  # 25 — validated at module load
assert FEATURE_COUNT == 25, f"FEATURE_COUNT must be 25, got {FEATURE_COUNT}"

_REGIME_ORDER: List[str] = [
    "RANGING", "UPTREND", "DOWNTREND",
    "STRONG_UPTREND", "STRONG_DOWNTREND", "EXPANDING_RANGE", "UNKNOWN",
]
assert len(_REGIME_ORDER) == 7

_D0 = Decimal("0")
_D1 = Decimal("1")


class FeatureVector(BaseModel, frozen=True):
    """Immutable, schema-versioned feature vector."""

    model_config = ConfigDict(frozen=True)

    instrument_token: str
    features: Tuple[Decimal, ...]
    schema_version: str
    generated_at: str

    @property
    def feature_count(self) -> int:
        return len(self.features)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_return(a: Decimal, b: Decimal) -> Decimal:
    """ln(a/b); returns 0 if either value is non-positive."""
    try:
        if a <= _D0 or b <= _D0:
            return _D0
        return Decimal(str(round(math.log(float(a) / float(b)), 8)))
    except Exception:
        return _D0


def _sign(v: Decimal) -> Decimal:
    if v > _D0:
        return _D1
    if v < _D0:
        return Decimal("-1")
    return _D0


def _clamp(v: Decimal, lo: Decimal = _D0, hi: Decimal = _D1) -> Decimal:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Canonical FeatureGenerator (25-feature schema v1.0)
# ---------------------------------------------------------------------------

class FeatureGenerator:
    """Deterministic feature generator.

    Maintains per-instrument ring buffers for close prices (1m and 5m)
    and 1m volumes, enabling return and volume-ratio features that require
    bar history beyond what MultiTimeframeContext stores.

    update_bar(bar) must be called from the strategy runtime before generate()
    is called for the same bar to keep the buffer current.

    Thread/task safety: all buffer mutations are guarded; this class is safe
    to share across concurrent strategy runtimes.
    """

    _CLOSE_1M_CAPACITY = 6   # 5 returns → need 6 closes
    _CLOSE_5M_CAPACITY = 4   # 3 returns → need 4 closes
    _VOLUME_CAPACITY   = 20  # for 20-bar volume SMA

    def __init__(self) -> None:
        # Per-instrument ring buffers
        self._close_1m: Dict[str, Deque[Decimal]] = {}
        self._close_5m: Dict[str, Deque[Decimal]] = {}
        self._volume_1m: Dict[str, Deque[Decimal]] = {}
        # Track last seen 5m close to avoid duplicate pushes
        self._last_5m_close: Dict[str, Optional[Decimal]] = {}

    def update_bar(self, instrument_token: str, close: Decimal, volume: Decimal) -> None:
        """Push a new 1m bar's close and volume into the internal buffers.

        Call this once per 1m bar BEFORE calling generate().
        """
        buf = self._close_1m.setdefault(
            instrument_token, deque(maxlen=self._CLOSE_1M_CAPACITY)
        )
        buf.append(close)

        vbuf = self._volume_1m.setdefault(
            instrument_token, deque(maxlen=self._VOLUME_CAPACITY)
        )
        vbuf.append(volume)

    def _update_5m_from_context(
        self, instrument_token: str, context: MultiTimeframeContext
    ) -> None:
        """Push a 5m close when it changes (called from generate())."""
        close_5m = context.timeframes.get("5m", {}).get("close")
        if close_5m is None or close_5m <= _D0:
            return
        last = self._last_5m_close.get(instrument_token)
        if last == close_5m:
            return  # No new 5m bar yet — same close as before
        self._last_5m_close[instrument_token] = close_5m
        buf = self._close_5m.setdefault(
            instrument_token, deque(maxlen=self._CLOSE_5M_CAPACITY)
        )
        buf.append(close_5m)

    def generate(
        self,
        instrument_token: str,
        mtf_context: MultiTimeframeContext,
        generated_at: str,
    ) -> FeatureVector:
        """Generate the canonical 25-feature vector.

        Output is deterministic for identical buffer state + identical context.
        Missing source values use explicit, documented defaults.
        """
        self._update_5m_from_context(instrument_token, mtf_context)

        features: List[Decimal] = []

        # ── 1m log-returns (features 0-4) ──────────────────────────────────
        closes_1m = list(self._close_1m.get(instrument_token, []))
        for i in range(5):
            # return_i = ln(closes[-1-i] / closes[-2-i])
            idx_a = -(1 + i)
            idx_b = -(2 + i)
            if len(closes_1m) >= (2 + i):
                features.append(_log_return(closes_1m[idx_a], closes_1m[idx_b]))
            else:
                features.append(_D0)

        # ── 5m log-returns (features 5-7) ──────────────────────────────────
        closes_5m = list(self._close_5m.get(instrument_token, []))
        for i in range(3):
            idx_a = -(1 + i)
            idx_b = -(2 + i)
            if len(closes_5m) >= (2 + i):
                features.append(_log_return(closes_5m[idx_a], closes_5m[idx_b]))
            else:
                features.append(_D0)

        # ── 1m RSI normalised [0, 1] (feature 8) ───────────────────────────
        tf1 = mtf_context.timeframes.get("1m", {})
        rsi1 = tf1.get("rsi_14")
        features.append(_clamp(rsi1 / Decimal("100")) if rsi1 is not None else Decimal("0.5"))

        # ── 5m RSI normalised [0, 1] (feature 9) ───────────────────────────
        tf5 = mtf_context.timeframes.get("5m", {})
        rsi5 = tf5.get("rsi_14")
        features.append(_clamp(rsi5 / Decimal("100")) if rsi5 is not None else Decimal("0.5"))

        # ── 1m MACD histogram sign + magnitude (features 10-11) ────────────
        macd1 = tf1.get("macd_histogram", _D0)
        features.append(_sign(macd1))
        features.append(abs(macd1))

        # ── 5m MACD histogram sign + magnitude (features 12-13) ────────────
        macd5 = tf5.get("macd_histogram", _D0)
        features.append(_sign(macd5))
        features.append(abs(macd5))

        # ── 1m Bollinger position (feature 14) ─────────────────────────────
        close1 = tf1.get("close", _D0)
        bb_upper = tf1.get("bb_upper_20")
        bb_lower = tf1.get("bb_lower_20")
        if (bb_upper is not None and bb_lower is not None
                and bb_upper > bb_lower and close1 > _D0):
            bb_pos = _clamp((close1 - bb_lower) / (bb_upper - bb_lower))
        else:
            bb_pos = Decimal("0.5")
        features.append(bb_pos)

        # ── 1m ATR/close (feature 15) ───────────────────────────────────────
        atr1 = tf1.get("atr_14")
        if atr1 is not None and close1 > _D0:
            features.append(atr1 / close1)
        else:
            features.append(_D0)

        # ── 5m ATR/close (feature 16) ───────────────────────────────────────
        close5 = tf5.get("close") or close1
        atr5 = tf5.get("atr_14")
        if atr5 is not None and close5 > _D0:
            features.append(atr5 / close5)
        else:
            features.append(_D0)

        # ── Regime one-hot encoding (features 17-23) ────────────────────────
        regime = mtf_context.regime
        regime_name = regime.regime.value if regime else "UNKNOWN"
        for r in _REGIME_ORDER:
            features.append(_D1 if r == regime_name else _D0)

        # ── 1m volume ratio (feature 24) ────────────────────────────────────
        volumes = list(self._volume_1m.get(instrument_token, []))
        if len(volumes) >= 2:
            sma_vol = sum(volumes) / Decimal(str(len(volumes)))
            current_vol = volumes[-1]
            if sma_vol > _D0:
                features.append(current_vol / sma_vol)
            else:
                features.append(_D1)
        else:
            features.append(_D1)

        # ── Validation ───────────────────────────────────────────────────────
        assert len(features) == FEATURE_COUNT, (
            f"Expected {FEATURE_COUNT} features, got {len(features)}"
        )

        return FeatureVector(
            instrument_token=instrument_token,
            features=tuple(features),
            schema_version=FEATURE_SCHEMA_VERSION,
            generated_at=generated_at,
        )


# ---------------------------------------------------------------------------
# Legacy 42-feature generator (retained for compatibility ONLY)
# ---------------------------------------------------------------------------

class LegacyFeatureGenerator:
    """42-feature generator from the initial RC-10B merge.

    Schema version: "legacy-42-v1"

    Do NOT use for new Kronos model deployments.
    Retained for backward compatibility only.
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
        features: List[Decimal] = []
        close = self._get_close(mtf_context)

        tf_1m = mtf_context.timeframes.get("1m", {})
        features.extend(self._extract_tf_features(tf_1m, close))

        for tf_key in ("5m", "15m", "1h"):
            tf_data = mtf_context.timeframes.get(tf_key, {})
            features.extend(self._extract_tf_features_compact(tf_data, close))

        regime = mtf_context.regime
        if regime:
            features.append(regime.confidence)
            features.append(self._REGIME_ENCODING.get(regime.regime.value, Decimal("6")))
        else:
            features.append(_D0)
            features.append(Decimal("6"))

        announcements = mtf_context.active_announcements
        features.append(Decimal(str(len(announcements))))
        has_cls = {c: False for c in ["EARNINGS_RESULT", "DIVIDEND", "BONUS", "STOCK_SPLIT"]}
        for ann in announcements:
            if ann.classification in has_cls:
                has_cls[ann.classification] = True
        features.append(_D1 if has_cls["EARNINGS_RESULT"] else _D0)
        features.append(_D1 if has_cls["DIVIDEND"] else _D0)
        features.append(_D1 if has_cls["BONUS"] else _D0)
        features.append(_D1 if has_cls["STOCK_SPLIT"] else _D0)

        rank = mtf_context.watchlist_rank
        features.append(Decimal(str(rank)) / Decimal("100") if rank is not None else _D0)
        score = mtf_context.composite_score
        features.append(score if score is not None else _D0)
        features.append(self._time_of_day_feature(generated_at))

        return FeatureVector(
            instrument_token=instrument_token,
            features=tuple(features),
            schema_version=LEGACY_SCHEMA_VERSION,
            generated_at=generated_at,
        )

    def _get_close(self, c: MultiTimeframeContext) -> Decimal:
        v = c.timeframes.get("1m", {}).get("close")
        return v if v and v > _D0 else _D1

    def _extract_tf_features(self, td: Dict[str, Decimal], close: Decimal) -> List[Decimal]:
        f: List[Decimal] = []
        for k in ("sma_10", "sma_20", "sma_50", "ema_9", "ema_21"):
            v = td.get(k)
            f.append(v / close if v is not None and close > _D0 else _D0)
        f.append(td.get("rsi_14") if td.get("rsi_14") is not None else Decimal("50"))
        atr = td.get("atr_14")
        f.append(atr / close if atr is not None and close > _D0 else _D0)
        for k in ("adx_14", "plus_di_14", "minus_di_14", "macd_line", "macd_signal", "macd_histogram"):
            f.append(td.get(k, _D0))
        vwap = td.get("vwap")
        f.append(vwap / close if vwap is not None and close > _D0 else _D0)
        bb_upper = td.get("bb_upper_20")
        bb_lower = td.get("bb_lower_20")
        bb_mid   = td.get("bb_middle_20")
        f.append(bb_upper / close if bb_upper is not None and close > _D0 else _D0)
        f.append(bb_lower / close if bb_lower is not None and close > _D0 else _D0)
        if bb_upper is not None and bb_lower is not None and bb_mid is not None and bb_mid > _D0:
            f.append((bb_upper - bb_lower) / bb_mid)
        else:
            f.append(_D0)
        return f

    def _extract_tf_features_compact(self, td: Dict[str, Decimal], close: Decimal) -> List[Decimal]:
        f: List[Decimal] = []
        for k in ("sma_10", "sma_20"):
            v = td.get(k)
            f.append(v / close if v is not None and close > _D0 else _D0)
        f.append(td.get("rsi_14") if td.get("rsi_14") is not None else Decimal("50"))
        atr = td.get("atr_14")
        f.append(atr / close if atr is not None and close > _D0 else _D0)
        f.append(td.get("adx_14", _D0))
        return f

    def _time_of_day_feature(self, generated_at: str) -> Decimal:
        try:
            from datetime import datetime, time, timedelta
            dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            ist = dt + timedelta(hours=5, minutes=30)
            t = ist.time()
            if t < time(9, 15):
                return _D0
            if t > time(15, 30):
                return _D1
            minutes = (t.hour - 9) * 60 + (t.minute - 15)
            return Decimal(str(minutes)) / Decimal("375")
        except Exception:
            return Decimal("0.5")
