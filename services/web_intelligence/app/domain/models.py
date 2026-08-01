"""Pydantic domain models for the Web Intelligence Collector."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    CollectionRunStatus,
    ConfidenceStatus,
    DataQualityStatus,
    RecordType,
    SourceType,
    ValidationStatus,
)


class ApprovedSource(BaseModel):
    """An approved intelligence source configuration."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique source identifier")
    name: str = Field(..., description="Human-readable source name")
    base_url: str = Field(..., description="Base URL of the source")
    source_type: SourceType = Field(..., description="Type of source")
    enabled: bool = Field(default=True, description="Whether collection is enabled")
    robots_policy: str = Field(default="", description="Robots.txt policy summary")
    request_interval_seconds: float = Field(default=5.0, ge=0.0)
    maximum_requests_per_hour: int = Field(default=60, ge=0)
    user_agent: str = Field(..., description="User agent string for this source")
    parser_name: str = Field(..., description="Name of the parser to use")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RawSnapshot(BaseModel):
    """A raw snapshot of fetched content."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique snapshot identifier")
    source_id: str = Field(..., description="Reference to the source")
    requested_url: str = Field(..., description="URL that was requested")
    canonical_url: str = Field(..., description="Resolved canonical URL")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    http_status: int | None = Field(default=None)
    content_type: str | None = Field(default=None)
    content_hash: str = Field(..., description="SHA-256 hash of content")
    raw_content_location: str = Field(..., description="Storage path for raw content")
    response_headers: dict[str, str] = Field(default_factory=dict)
    fetch_duration_ms: int = Field(default=0)
    parser_version: str = Field(default="unknown")
    collection_run_id: str = Field(...)
    data_quality_status: DataQualityStatus = Field(default=DataQualityStatus.UNKNOWN)
    error_code: str | None = Field(default=None)
    error_message: str | None = Field(default=None)


class IntelligenceRecord(BaseModel):
    """A structured intelligence record extracted from raw snapshots."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique record identifier")
    source_id: str = Field(..., description="Reference to the source")
    record_type: RecordType = Field(...)
    title: str = Field(default="", description="Extracted title")
    summary: str = Field(default="", description="Extracted summary")
    published_at: datetime | None = Field(default=None)
    effective_at: datetime | None = Field(default=None)
    canonical_url: str = Field(...)
    source_reference: str = Field(default="", description="External reference ID")
    content_hash: str = Field(..., description="Hash of normalized content")
    raw_snapshot_id: str = Field(...)
    confidence_status: ConfidenceStatus = Field(default=ConfidenceStatus.UNVERIFIED)
    validation_status: ValidationStatus = Field(default=ValidationStatus.PENDING)
    data_quality_status: DataQualityStatus = Field(default=DataQualityStatus.UNKNOWN)
    parser_version: str = Field(default="unknown")
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionRun(BaseModel):
    """A single collection run for a source."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique run identifier")
    source_id: str = Field(...)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)
    status: CollectionRunStatus = Field(default=CollectionRunStatus.PENDING)
    pages_requested: int = Field(default=0)
    pages_succeeded: int = Field(default=0)
    pages_failed: int = Field(default=0)
    records_extracted: int = Field(default=0)
    records_inserted: int = Field(default=0)
    records_updated: int = Field(default=0)
    duplicates_ignored: int = Field(default=0)
    failure_reason: str | None = Field(default=None)
