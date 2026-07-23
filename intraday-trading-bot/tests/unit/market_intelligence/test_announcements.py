"""Unit tests for AnnouncementIntelligenceService and classify_announcement."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from market_intelligence.multi_timeframe_context import AnnouncementRecord
from market_intelligence.announcements import (
    AnnouncementIntelligenceService,
    classify_announcement,
)


def _make_record(
    ann_id: str,
    token: str = "INFY",
    exchange: str = "NSE",
    classification: str = "EARNINGS_RESULT",
    headline: str = "Q1 Results",
    published_at: datetime | None = None,
) -> AnnouncementRecord:
    return AnnouncementRecord(
        announcement_id=ann_id,
        instrument_token=token,
        exchange=exchange,
        tradingsymbol=token,
        classification=classification,
        headline=headline,
        published_at=published_at or datetime.utcnow(),
    )


class TestClassifyAnnouncement:
    def test_earnings_classification(self) -> None:
        assert classify_announcement("Q1 FY26 Earnings Results", "Net profit increased") == "EARNINGS_RESULT"

    def test_dividend_classification(self) -> None:
        assert classify_announcement("Final Dividend of Rs 10 per share declared", "") == "DIVIDEND"

    def test_bonus_classification(self) -> None:
        assert classify_announcement("Bonus Issue in ratio 1:1", "") == "BONUS"

    def test_stock_split(self) -> None:
        assert classify_announcement("Stock Split from Rs 10 to Rs 2 face value", "") == "STOCK_SPLIT"

    def test_merger(self) -> None:
        assert classify_announcement("Merger with XYZ Ltd approved", "") == "MERGER_ACQUISITION"

    def test_board_meeting(self) -> None:
        assert classify_announcement("Board Meeting on 25th July", "") == "BOARD_MEETING"

    def test_regulatory(self) -> None:
        assert classify_announcement("SEBI compliance update", "") == "REGULATORY"

    def test_other_when_no_match(self) -> None:
        assert classify_announcement("Random announcement about nothing specific", "") == "OTHER"

    def test_case_insensitive(self) -> None:
        assert classify_announcement("EARNINGS RESULT Q1", "") == "EARNINGS_RESULT"


class TestAnnouncementIntelligenceService:
    def test_ingest_new_announcement(self) -> None:
        service = AnnouncementIntelligenceService()
        record = _make_record("ANN001")
        assert service.ingest_announcement(record) is True

    def test_deduplication_same_id(self) -> None:
        service = AnnouncementIntelligenceService()
        record = _make_record("ANN001")
        assert service.ingest_announcement(record) is True
        assert service.ingest_announcement(record) is False

    def test_deduplication_different_exchanges(self) -> None:
        service = AnnouncementIntelligenceService()
        r1 = _make_record("ANN001", exchange="NSE")
        r2 = _make_record("ANN001", exchange="BSE")
        assert service.ingest_announcement(r1) is True
        assert service.ingest_announcement(r2) is True  # different exchange key

    def test_get_active_returns_ingested(self) -> None:
        service = AnnouncementIntelligenceService()
        service.ingest_announcement(_make_record("ANN001"))
        active = service.get_active_announcements_sync("INFY")
        assert len(active) == 1
        assert active[0].announcement_id == "ANN001"

    def test_ttl_expiry_removes_record(self) -> None:
        # ttl_hours=1: records older than 1 hour are expired
        service = AnnouncementIntelligenceService(ttl_hours=1)
        old = _make_record(
            "ANN_OLD", published_at=datetime.utcnow() - timedelta(hours=2)
        )
        new = _make_record("ANN_NEW", published_at=datetime.utcnow())
        service.ingest_announcement(old)
        service.ingest_announcement(new)
        service.clear_expired()
        active = service.get_active_announcements_sync("INFY")
        assert len(active) == 1
        assert active[0].announcement_id == "ANN_NEW"

    def test_get_active_no_cache_returns_empty(self) -> None:
        service = AnnouncementIntelligenceService()
        assert service.get_active_announcements_sync("UNKNOWN") == []

    def test_multiple_instruments_separate_cache(self) -> None:
        service = AnnouncementIntelligenceService()
        service.ingest_announcement(_make_record("ANN001", token="INFY"))
        service.ingest_announcement(_make_record("ANN002", token="TCS"))
        assert len(service.get_active_announcements_sync("INFY")) == 1
        assert len(service.get_active_announcements_sync("TCS")) == 1

    def test_poll_and_classify_returns_zero(self) -> None:
        service = AnnouncementIntelligenceService()
        result = asyncio.run(service.poll_and_classify(None))
        assert result == 0

    def test_get_active_announcements_sync_never_raises(self) -> None:
        # Even with a corrupted cache entry (simulate by testing unknown)
        service = AnnouncementIntelligenceService()
        result = service.get_active_announcements_sync("NONEXISTENT")
        assert result == []

    def test_is_blackout_period_true_recent(self) -> None:
        service = AnnouncementIntelligenceService()
        service.ingest_announcement(_make_record("ANN001"))
        assert service.is_blackout_period("INFY", window_minutes=30) is True

    def test_is_blackout_period_false_old(self) -> None:
        service = AnnouncementIntelligenceService()
        old = _make_record("ANN001", published_at=datetime.utcnow() - timedelta(hours=2))
        service.ingest_announcement(old)
        assert service.is_blackout_period("INFY", window_minutes=30) is False

    def test_clear_expired_removes_old(self) -> None:
        service = AnnouncementIntelligenceService(ttl_hours=1)
        old = _make_record("OLD", published_at=datetime.utcnow() - timedelta(hours=2))
        fresh = _make_record("FRESH")
        service.ingest_announcement(old)
        service.ingest_announcement(fresh)
        removed = service.clear_expired()
        assert removed == 1
        assert len(service.get_active_announcements_sync("INFY")) == 1

    def test_ingest_multiple_classifications(self) -> None:
        service = AnnouncementIntelligenceService()
        service.ingest_announcement(_make_record("A1", classification="EARNINGS_RESULT"))
        service.ingest_announcement(_make_record("A2", classification="DIVIDEND"))
        service.ingest_announcement(_make_record("A3", classification="BONUS"))
        active = service.get_active_announcements_sync("INFY")
        assert len(active) == 3

    def test_idempotent_double_ingest(self) -> None:
        service = AnnouncementIntelligenceService()
        record = _make_record("ANN999")
        service.ingest_announcement(record)
        service.ingest_announcement(record)
        active = service.get_active_announcements_sync("INFY")
        assert len(active) == 1

    def test_ingest_returns_false_for_duplicate(self) -> None:
        service = AnnouncementIntelligenceService()
        r = _make_record("DUP")
        service.ingest_announcement(r)
        result = service.ingest_announcement(r)
        assert result is False
