"""Domain models and enums for the Web Intelligence Collector."""
from .enums import (
    SourceType,
    RecordType,
    DataQualityStatus,
    ValidationStatus,
    ConfidenceStatus,
    CollectionRunStatus,
)
from .models import ApprovedSource, RawSnapshot, IntelligenceRecord, CollectionRun

__all__ = [
    "SourceType",
    "RecordType", 
    "DataQualityStatus",
    "ValidationStatus",
    "ConfidenceStatus",
    "CollectionRunStatus",
    "ApprovedSource",
    "RawSnapshot",
    "IntelligenceRecord",
    "CollectionRun",
]
