"""SQLAlchemy ORM models mapping to domain models."""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Enum, Float, Integer, String, Text

from app.domain.enums import (
    CollectionRunStatus,
    ConfidenceStatus,
    DataQualityStatus,
    RecordType,
    SourceType,
    ValidationStatus,
)
from app.repositories.database import Base


class ApprovedSourceORM(Base):
    __tablename__ = "approved_sources"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    base_url = Column(String(2048), nullable=False)
    source_type = Column(Enum(SourceType), nullable=False)
    enabled = Column(Integer, default=1, nullable=False)
    robots_policy = Column(Text, default="")
    request_interval_seconds = Column(Float, default=5.0, nullable=False)
    maximum_requests_per_hour = Column(Integer, default=60, nullable=False)
    user_agent = Column(String(512), nullable=False)
    parser_name = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RawSnapshotORM(Base):
    __tablename__ = "raw_snapshots"

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), nullable=False, index=True)
    requested_url = Column(String(2048), nullable=False)
    canonical_url = Column(String(2048), nullable=False)
    retrieved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    http_status = Column(Integer, nullable=True)
    content_type = Column(String(255), nullable=True)
    content_hash = Column(String(64), nullable=False)
    raw_content_location = Column(String(1024), nullable=False)
    response_headers = Column(JSON, default=dict)
    fetch_duration_ms = Column(Integer, default=0, nullable=False)
    parser_version = Column(String(32), default="unknown", nullable=False)
    collection_run_id = Column(String(64), nullable=False, index=True)
    data_quality_status = Column(Enum(DataQualityStatus), default=DataQualityStatus.UNKNOWN, nullable=False)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)


class IntelligenceRecordORM(Base):
    __tablename__ = "intelligence_records"

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), nullable=False, index=True)
    record_type = Column(Enum(RecordType), nullable=False)
    title = Column(Text, default="", nullable=False)
    summary = Column(Text, default="", nullable=False)
    published_at = Column(DateTime, nullable=True)
    effective_at = Column(DateTime, nullable=True)
    canonical_url = Column(String(2048), nullable=False)
    source_reference = Column(String(512), default="", nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    raw_snapshot_id = Column(String(64), nullable=False)
    confidence_status = Column(Enum(ConfidenceStatus), default=ConfidenceStatus.UNVERIFIED, nullable=False)
    validation_status = Column(Enum(ValidationStatus), default=ValidationStatus.PENDING, nullable=False)
    data_quality_status = Column(Enum(DataQualityStatus), default=DataQualityStatus.UNKNOWN, nullable=False)
    parser_version = Column(String(32), default="unknown", nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)


class CollectionRunORM(Base):
    __tablename__ = "collection_runs"

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(Enum(CollectionRunStatus), default=CollectionRunStatus.PENDING, nullable=False)
    pages_requested = Column(Integer, default=0, nullable=False)
    pages_succeeded = Column(Integer, default=0, nullable=False)
    pages_failed = Column(Integer, default=0, nullable=False)
    records_extracted = Column(Integer, default=0, nullable=False)
    records_inserted = Column(Integer, default=0, nullable=False)
    records_updated = Column(Integer, default=0, nullable=False)
    duplicates_ignored = Column(Integer, default=0, nullable=False)
    failure_reason = Column(Text, nullable=True)
