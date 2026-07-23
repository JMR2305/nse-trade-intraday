"""Integration tests: AnnouncementIntelligenceService in-memory persistence."""
from __future__ import annotations

from datetime import datetime

from market_intelligence.multi_timeframe_context import AnnouncementRecord
from market_intelligence.announcements import AnnouncementIntelligenceService


class TestAnnouncementPersistence:
    def test_ingest_and_retrieve(self) -> None:
        service = AnnouncementIntelligenceService()
        record = AnnouncementRecord(
            announcement_id="ANN001",
            instrument_token="INFY",
            exchange="NSE",
            tradingsymbol="INFY",
            classification="EARNINGS_RESULT",
            headline="Q1 Results",
            published_at=datetime.utcnow(),
        )
        assert service.ingest_announcement(record) is True
        active = service.get_active_announcements_sync("INFY")
        assert len(active) == 1
        assert active[0].announcement_id == "ANN001"

    def test_idempotent_upsert(self) -> None:
        service = AnnouncementIntelligenceService()
        record = AnnouncementRecord(
            announcement_id="ANN001",
            instrument_token="INFY",
            exchange="NSE",
            tradingsymbol="INFY",
            classification="EARNINGS_RESULT",
            headline="Q1 Results",
            published_at=datetime.utcnow(),
        )
        service.ingest_announcement(record)
        service.ingest_announcement(record)
        active = service.get_active_announcements_sync("INFY")
        assert len(active) == 1
