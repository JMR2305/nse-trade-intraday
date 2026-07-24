"""Tests for RC-10B canonical 25-feature schema."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ai_forecast.features import (
    FEATURE_COUNT,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    FeatureGenerator,
    FeatureVector,
    LegacyFeatureGenerator,
)
from market_intelligence.multi_timeframe_context import (
    MarketRegime,
    MarketRegimeSnapshot,
    MultiTimeframeContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GEN_AT = datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc).isoformat()


def make_regime(regime_enum: MarketRegime, confidence: str = "0.8") -> MarketRegimeSnapshot:
    return MarketRegimeSnapshot(
        instrument_token="INFY",
        regime=regime_enum,
        confidence=Decimal(confidence),
        detected_at=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
    )


def make_mtf(
    timeframes: dict | None = None,
    regime: MarketRegimeSnapshot | None = None,
) -> MultiTimeframeContext:
    return MultiTimeframeContext(
        instrument_token="INFY",
        snapshot_timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc),
        timeframes=timeframes or {},
        regime=regime,
        active_announcements=[],
        watchlist_rank=None,
        composite_score=None,
    )


def make_full_1m(
    close: str = "1500",
    rsi: str = "55",
    macd_hist: str = "2.5",
    bb_upper: str = "1520",
    bb_lower: str = "1480",
    atr: str = "10",
    volume: str = "5000",
    volume_sma: str = "4000",
) -> dict:
    return {
        "close": Decimal(close),
        "rsi_14": Decimal(rsi),
        "macd_histogram": Decimal(macd_hist),
        "bb_upper_20": Decimal(bb_upper),
        "bb_lower_20": Decimal(bb_lower),
        "atr_14": Decimal(atr),
    }


def make_full_5m(close: str = "1502", rsi: str = "58", macd_hist: str = "3.0", atr: str = "15") -> dict:
    return {
        "close": Decimal(close),
        "rsi_14": Decimal(rsi),
        "macd_histogram": Decimal(macd_hist),
        "atr_14": Decimal(atr),
    }


def push_closes(gen: FeatureGenerator, token: str, closes: list, volumes: list | None = None) -> None:
    """Simulate receiving N 1m bars with the given closes."""
    for i, c in enumerate(closes):
        vol = (volumes[i] if volumes else Decimal("5000"))
        gen.update_bar(token, Decimal(str(c)), Decimal(str(vol)))


# ---------------------------------------------------------------------------
# Schema constant tests
# ---------------------------------------------------------------------------

class TestSchemaConstants:
    def test_feature_count_is_25(self) -> None:
        assert FEATURE_COUNT == 25

    def test_feature_names_length(self) -> None:
        assert len(FEATURE_NAMES) == 25

    def test_schema_version_is_1_0(self) -> None:
        assert FEATURE_SCHEMA_VERSION == "1.0"

    def test_legacy_schema_version(self) -> None:
        assert LEGACY_SCHEMA_VERSION == "legacy-42-v1"

    def test_feature_names_order(self) -> None:
        assert FEATURE_NAMES[0] == "1m_return_t0"
        assert FEATURE_NAMES[4] == "1m_return_t4"
        assert FEATURE_NAMES[5] == "5m_return_t0"
        assert FEATURE_NAMES[7] == "5m_return_t2"
        assert FEATURE_NAMES[8] == "1m_rsi_norm"
        assert FEATURE_NAMES[9] == "5m_rsi_norm"
        assert FEATURE_NAMES[17] == "regime_RANGING"
        assert FEATURE_NAMES[23] == "regime_UNKNOWN"
        assert FEATURE_NAMES[24] == "1m_volume_ratio"


# ---------------------------------------------------------------------------
# FeatureGenerator (canonical schema)
# ---------------------------------------------------------------------------

class TestFeatureGenerator:
    def test_generates_25_features(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m(), "5m": make_full_5m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.feature_count == FEATURE_COUNT

    def test_schema_version_is_canonical(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.schema_version == FEATURE_SCHEMA_VERSION
        assert fv.schema_version != LEGACY_SCHEMA_VERSION

    def test_feature_vector_immutable(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        with pytest.raises(Exception):
            fv.features = ()  # type: ignore[misc]

    # 1m returns features (0-4)
    def test_1m_returns_default_zero_when_no_history(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[0] == Decimal("0")  # no history yet

    def test_1m_returns_computed_after_history(self) -> None:
        gen = FeatureGenerator()
        closes = [1000, 1010, 1020, 1030, 1040, 1050]
        push_closes(gen, "INFY", closes)
        mtf = make_mtf({"1m": make_full_1m(close="1050")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        # feature[0] = ln(1050/1040) ≈ ln(1.009615...)
        expected_r0 = Decimal(str(round(math.log(1050 / 1040), 8)))
        assert fv.features[0] == expected_r0

    def test_1m_returns_deterministic(self) -> None:
        """Same buffer state + same context → same output."""
        gen1 = FeatureGenerator()
        gen2 = FeatureGenerator()
        closes = [100, 101, 102, 103, 104, 105]
        push_closes(gen1, "INFY", closes)
        push_closes(gen2, "INFY", closes)
        mtf = make_mtf({"1m": make_full_1m(close="105")})
        fv1 = gen1.generate("INFY", mtf, _GEN_AT)
        fv2 = gen2.generate("INFY", mtf, _GEN_AT)
        assert fv1.features == fv2.features

    def test_partial_history_fills_zeros(self) -> None:
        """With 3 closes we can compute 2 returns; the other 3 should be 0."""
        gen = FeatureGenerator()
        push_closes(gen, "INFY", [100, 101, 102])
        mtf = make_mtf({"1m": make_full_1m(close="102")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[0] != Decimal("0")  # ln(102/101)
        assert fv.features[1] != Decimal("0")  # ln(101/100)
        assert fv.features[2] == Decimal("0")  # not enough history
        assert fv.features[3] == Decimal("0")
        assert fv.features[4] == Decimal("0")

    # RSI (features 8-9)
    def test_rsi_normalised_to_0_1(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m(rsi="70"), "5m": make_full_5m(rsi="40")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[8] == Decimal("0.7")
        assert fv.features[9] == Decimal("0.4")

    def test_rsi_defaults_to_0_5_when_missing(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": {}, "5m": {}})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[8] == Decimal("0.5")
        assert fv.features[9] == Decimal("0.5")

    # MACD (features 10-13)
    def test_macd_sign_positive(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m(macd_hist="3.5")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[10] == Decimal("1")

    def test_macd_sign_negative(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m(macd_hist="-2.0")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[10] == Decimal("-1")

    def test_macd_magnitude(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m(macd_hist="-4.2")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[11] == Decimal("4.2")

    # Bollinger position (feature 14)
    def test_bb_position_midpoint(self) -> None:
        gen = FeatureGenerator()
        # close = 1500, upper = 1600, lower = 1400 → position = 0.5
        mtf = make_mtf({"1m": {
            "close": Decimal("1500"),
            "bb_upper_20": Decimal("1600"),
            "bb_lower_20": Decimal("1400"),
        }})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[14] == Decimal("0.5")

    def test_bb_position_clamped(self) -> None:
        gen = FeatureGenerator()
        # close above upper → clamped to 1
        mtf = make_mtf({"1m": {
            "close": Decimal("1700"),
            "bb_upper_20": Decimal("1600"),
            "bb_lower_20": Decimal("1400"),
        }})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[14] == Decimal("1")

    # ATR ratio (features 15-16)
    def test_atr_ratio_1m(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": {"close": Decimal("2000"), "atr_14": Decimal("20")}})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[15] == Decimal("0.01")

    # Regime one-hot (features 17-23)
    def test_regime_one_hot_uptrend(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf(regime=make_regime(MarketRegime.UPTREND))
        fv = gen.generate("INFY", mtf, _GEN_AT)
        # RANGING=17, UPTREND=18
        assert fv.features[17] == Decimal("0")  # RANGING
        assert fv.features[18] == Decimal("1")  # UPTREND — should be 1

    def test_regime_one_hot_exactly_one_active(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf(regime=make_regime(MarketRegime.DOWNTREND, "0.7"))
        fv = gen.generate("INFY", mtf, _GEN_AT)
        one_hot = list(fv.features[17:24])
        assert sum(int(v) for v in one_hot) == 1
        assert one_hot[2] == Decimal("1")  # DOWNTREND is index 2

    def test_regime_unknown_when_none(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf()  # no regime
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[23] == Decimal("1")  # UNKNOWN

    # Volume ratio (feature 24)
    def test_volume_ratio_default_one_when_no_history(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.features[24] == Decimal("1")

    def test_volume_ratio_computed(self) -> None:
        gen = FeatureGenerator()
        # push 5 bars with vol=4000, then one bar with vol=8000
        push_closes(gen, "INFY",
                    [100, 101, 102, 103, 104],
                    volumes=[4000, 4000, 4000, 4000, 4000])
        gen.update_bar("INFY", Decimal("105"), Decimal("8000"))
        mtf = make_mtf({"1m": make_full_1m(close="105")})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        # sma_vol ~ (5×4000 + 8000)/6 ≈ 4666.7, current=8000
        assert fv.features[24] > Decimal("1")

    # Per-instrument isolation
    def test_different_instruments_independent(self) -> None:
        gen = FeatureGenerator()
        push_closes(gen, "INFY", [100, 110, 120, 130, 140, 150])
        push_closes(gen, "RELI", [500, 490, 480, 470, 460, 450])
        mtf_infy = make_mtf({"1m": {"close": Decimal("150")}})
        mtf_reli = make_mtf({"1m": {"close": Decimal("450")}})
        fv_infy = gen.generate("INFY", mtf_infy, _GEN_AT)
        fv_reli = gen.generate("RELI", mtf_reli, _GEN_AT)
        # 1m_return_t0 should have opposite signs
        assert fv_infy.features[0] > Decimal("0")
        assert fv_reli.features[0] < Decimal("0")


# ---------------------------------------------------------------------------
# Legacy generator — schema version must NOT emit "1.0"
# ---------------------------------------------------------------------------

class TestLegacyFeatureGenerator:
    def test_schema_version_is_legacy(self) -> None:
        gen = LegacyFeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.schema_version == LEGACY_SCHEMA_VERSION
        assert fv.schema_version != FEATURE_SCHEMA_VERSION

    def test_does_not_emit_canonical_version(self) -> None:
        gen = LegacyFeatureGenerator()
        mtf = make_mtf({"1m": make_full_1m()})
        fv = gen.generate("INFY", mtf, _GEN_AT)
        assert fv.schema_version != "1.0"
