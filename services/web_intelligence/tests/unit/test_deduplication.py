"""Tests for deduplication service."""
from datetime import datetime

import pytest

from app.domain.enums import ConfidenceStatus, DataQualityStatus, RecordType, ValidationStatus
from app.domain.models import IntelligenceRecord
from app.services.deduplication import DeduplicationService


class MockIntelligenceRepository:
    def __init__(self):
        self.records = {}

    async def find_duplicate(
        self,
        canonical_url,
        title,
        source_reference,
        content_hash,
        source_id=None,
    ):
        for r in self.records.values():
            if source_id and r.source_id != source_id:
                continue
            if r.source_reference == source_reference and source_reference:
                return r
            if r.content_hash == content_hash and content_hash:
                return r
            if r.canonical_url == canonical_url and r.title == title:
                return r
        return None

    async def save(self, record):
        self.records[record.id] = record

    async def update_last_seen(self, record_id, snapshot_id, content_hash, data_quality_status):
        if record_id in self.records:
            r = self.records[record_id]
            self.records[record_id] = r.model_copy(update={
                "last_seen_at": datetime.utcnow(),
                "raw_snapshot_id": snapshot_id,
                "content_hash": content_hash,
                "data_quality_status": DataQualityStatus(data_quality_status),
            })


@pytest.mark.asyncio
async def test_new_record_detected():
    repo = MockIntelligenceRepository()
    service = DeduplicationService(repo)
    record = IntelligenceRecord(
        id="r1", source_id="s1", record_type=RecordType.GENERIC,
        title="Test", summary="Summary", canonical_url="https://example.com/a",
        source_reference="ref-1", content_hash="", raw_snapshot_id="snap-1",
        confidence_status=ConfidenceStatus.MEDIUM, validation_status=ValidationStatus.PENDING,
        data_quality_status=DataQualityStatus.VALID,
    )
    result, is_new, was_updated = await service.process_record(record)
    assert is_new is True
    assert was_updated is False
    assert result.content_hash != ""


@pytest.mark.asyncio
async def test_exact_duplicate_ignored():
    repo = MockIntelligenceRepository()
    service = DeduplicationService(repo)
    record = IntelligenceRecord(
        id="r1", source_id="s1", record_type=RecordType.GENERIC,
        title="Test", summary="Summary", canonical_url="https://example.com/a",
        source_reference="ref-1", content_hash="", raw_snapshot_id="snap-1",
        confidence_status=ConfidenceStatus.MEDIUM, validation_status=ValidationStatus.PENDING,
        data_quality_status=DataQualityStatus.VALID,
    )
    await service.process_record(record)
    result, is_new, was_updated = await service.process_record(record)
    assert is_new is False
    assert was_updated is False


@pytest.mark.asyncio
async def test_content_change_updates_last_seen():
    repo = MockIntelligenceRepository()
    service = DeduplicationService(repo)
    record1 = IntelligenceRecord(
        id="r1", source_id="s1", record_type=RecordType.GENERIC,
        title="Test", summary="Summary", canonical_url="https://example.com/a",
        source_reference="ref-1", content_hash="", raw_snapshot_id="snap-1",
        confidence_status=ConfidenceStatus.MEDIUM, validation_status=ValidationStatus.PENDING,
        data_quality_status=DataQualityStatus.VALID,
    )
    await service.process_record(record1)
    record2 = record1.model_copy(update={
        "summary": "Changed summary",
        "raw_snapshot_id": "snap-2",
        "data_quality_status": DataQualityStatus.VALID,
    })
    result, is_new, was_updated = await service.process_record(record2)
    assert is_new is False
    assert was_updated is True
