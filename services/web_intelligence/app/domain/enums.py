"""Enumeration definitions for the Web Intelligence Collector."""
from enum import Enum


class SourceType(str, Enum):
    """Types of approved intelligence sources."""

    GENERIC_STATIC_PAGE = "generic_static_page"
    LOCAL_HTML_FIXTURE = "local_html_fixture"


class RecordType(str, Enum):
    """Types of intelligence records."""

    ANNOUNCEMENT = "announcement"
    CIRCULAR = "circular"
    REGULATORY_NOTICE = "regulatory_notice"
    MARKET_HOLIDAY = "market_holiday"
    EVENT_METADATA = "event_metadata"
    GENERIC = "generic"


class DataQualityStatus(str, Enum):
    """Data quality assessment statuses."""

    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    PARSER_MISMATCH = "parser_mismatch"
    EMPTY_CONTENT = "empty_content"
    HTTP_ERROR = "http_error"
    BLOCKED = "blocked"
    ROBOTS_DISALLOWED = "robots_disallowed"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    """Validation state of an intelligence record."""

    PENDING = "pending"
    VALIDATED = "validated"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ConfidenceStatus(str, Enum):
    """Confidence level in extracted data."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"


class CollectionRunStatus(str, Enum):
    """Status of a collection run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
