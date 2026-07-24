from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest

from ai_forecast.features import FeatureGenerator, FeatureVector, FEATURE_SCHEMA_VERSION
from market_intelligence.multi_timeframe_context import (
    MarketRegime,
    MarketRegimeSnapshot,
    AnnouncementRecord,
    MultiTimeframeContext,
)


def make_mtf_context(
    timeframes: dict = None,
    regime: MarketRegimeSnapshot = None,
    announcements: list = None,
    rank: int = None,
    score: Decimal = None,
) -> MultiTimeframeContext:
    return MultiTimeframeContext(
        instrument_token="INFY",
        snapshot_timestamp=datetime.utcnow(),
        timeframes=timeframes or {},
        regime=regime,
        active_announcements=announcements or [],
        watchlist_rank=rank,
        composite_score=score,
    )


class TestFeatureGenerator:
    def test_generates_42_features(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context()
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.feature_count == 42

    def test_schema_version(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context()
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.schema_version == FEATURE_SCHEMA_VERSION

    def test_instrument_token_preserved(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context()
        fv = gen.generate("TCS", mtf, datetime.utcnow().isoformat())
        assert fv.instrument_token == "TCS"

    def test_1m_features_with_data(self) -> None:
        gen = FeatureGenerator()
        tf_1m = {
            "sma_10": Decimal("105"),
            "sma_20": Decimal("104"),
            "sma_50": Decimal("103"),
            "ema_9": Decimal("106"),
            "ema_21": Decimal("105"),
            "rsi_14": Decimal("55"),
            "atr_14": Decimal("2.5"),
            "adx_14": Decimal("25"),
            "plus_di_14": Decimal("20"),
            "minus_di_14": Decimal("15"),
            "macd_line": Decimal("1.5"),
            "macd_signal": Decimal("1.2"),
            "macd_histogram": Decimal("0.3"),
            "vwap": Decimal("104"),
            "bb_upper_20": Decimal("110"),
            "bb_middle_20": Decimal("105"),
            "bb_lower_20": Decimal("100"),
            "close": Decimal("105"),
        }
        mtf = make_mtf_context(timeframes={"1m": tf_1m})
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.feature_count == 42
        assert fv.features[0] > 0  # SMA-10/close
        assert fv.features[5] == Decimal("55")  # RSI
        assert fv.features[7] == Decimal("25")  # ADX

    def test_1m_features_defaults_when_missing(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context(timeframes={"1m": {"close": Decimal("100")}})
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.feature_count == 42
        assert fv.features[5] == Decimal("50")  # Default RSI
        assert fv.features[7] == Decimal("0")   # Default ADX

    def test_regime_features(self) -> None:
        gen = FeatureGenerator()
        regime = MarketRegimeSnapshot(
            instrument_token="INFY",
            regime=MarketRegime.UPTREND,
            confidence=Decimal("0.75"),
            detected_at=datetime.utcnow(),
        )
        mtf = make_mtf_context(regime=regime)
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.features[32] == Decimal("0.75")  # confidence (0-indexed: 33rd feature)
        assert fv.features[33] == Decimal("1")     # UPTREND encoding

    def test_regime_unknown_defaults(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context()
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.features[32] == Decimal("0")  # No confidence
        assert fv.features[33] == Decimal("6")  # UNKNOWN encoding

    def test_announcement_features(self) -> None:
        gen = FeatureGenerator()
        announcements = [
            AnnouncementRecord(
                announcement_id="ANN001",
                instrument_token="INFY",
                exchange="NSE",
                tradingsymbol="INFY",
                classification="EARNINGS_RESULT",
                headline="Q1 Results",
                published_at=datetime.utcnow(),
            ),
            AnnouncementRecord(
                announcement_id="ANN002",
                instrument_token="INFY",
                exchange="NSE",
                tradingsymbol="INFY",
                classification="DIVIDEND",
                headline="Dividend",
                published_at=datetime.utcnow(),
            ),
        ]
        mtf = make_mtf_context(announcements=announcements)
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.features[34] == Decimal("2")   # Count
        assert fv.features[35] == Decimal("1")   # Has earnings
        assert fv.features[36] == Decimal("1")   # Has dividend
        assert fv.features[37] == Decimal("0")   # No bonus
        assert fv.features[38] == Decimal("0")   # No split

    def test_watchlist_features(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context(rank=5, score=Decimal("0.85"))
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.features[39] == Decimal("0.05")  # rank/100
        assert fv.features[40] == Decimal("0.85")  # composite score

    def test_time_of_day_feature(self) -> None:
        gen = FeatureGenerator()
        mtf = make_mtf_context()
        import datetime as dt
        ts = datetime(2026, 7, 24, 4, 30, tzinfo=dt.timezone.utc).isoformat()
        fv = gen.generate("INFY", mtf, ts)
        assert fv.features[41] > Decimal("0")
        assert fv.features[41] <= Decimal("1")

    def test_determinism(self) -> None:
        """Same input produces same feature vector."""
        gen1 = FeatureGenerator()
        gen2 = FeatureGenerator()
        tf_1m = {
            "sma_10": Decimal("105"),
            "rsi_14": Decimal("55"),
            "close": Decimal("105"),
        }
        mtf = make_mtf_context(timeframes={"1m": tf_1m})
        ts = datetime.utcnow().isoformat()
        fv1 = gen1.generate("INFY", mtf, ts)
        fv2 = gen2.generate("INFY", mtf, ts)
        assert fv1.features == fv2.features

    def test_multiple_timeframes(self) -> None:
        gen = FeatureGenerator()
        tf_1m = {"close": Decimal("100"), "rsi_14": Decimal("50")}
        tf_5m = {"close": Decimal("100"), "rsi_14": Decimal("52")}
        tf_15m = {"close": Decimal("100"), "rsi_14": Decimal("48")}
        tf_1h = {"close": Decimal("100"), "rsi_14": Decimal("51")}
        mtf = make_mtf_context(timeframes={"1m": tf_1m, "5m": tf_5m, "15m": tf_15m, "1h": tf_1h})
        fv = gen.generate("INFY", mtf, datetime.utcnow().isoformat())
        assert fv.feature_count == 42
        assert fv.features[5] == Decimal("50")   # 1m RSI
        assert fv.features[19] == Decimal("52")  # 5m RSI
        assert fv.features[24] == Decimal("48")  # 15m RSI
        assert fv.features[29] == Decimal("51")  # 1h RSI

    def test_feature_vector_immutable(self) -> None:
        fv = FeatureVector(
            instrument_token="INFY",
            features=tuple([Decimal("0.5")] * 42),
            schema_version="1.0",
            generated_at=datetime.utcnow().isoformat(),
        )
        with pytest.raises(Exception):
            fv.features = tuple([Decimal("0.6")] * 42)
