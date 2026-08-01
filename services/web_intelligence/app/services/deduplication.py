"""Deterministic deduplication service."""
import hashlib
from datetime import datetime

from app.domain.enums import DataQualityStatus
from app.domain.models import IntelligenceRecord
from app.logging import get_logger
from app.repositories.intelligence_repository import IntelligenceRepository

logger = get_logger(__name__)


class DeduplicationService:
    """Deterministic deduplication using multiple signals."""

    def __init__(self, repository: IntelligenceRepository) -> None:
        self._repository = repository

    async def process_record(
        self, record: IntelligenceRecord
    ) -> tuple[IntelligenceRecord, bool, bool]:
        """Process a record for deduplication.

        Computes a deterministic content hash, then looks for an existing
        record scoped to the same ``source_id``.  When a new record is
        detected it is persisted immediately so that subsequent calls within
        the same session can detect it as a duplicate.

        Returns:
            (record, is_new, was_updated):
            - is_new: True if this is a brand new record (has been saved)
            - was_updated: True if an existing record had its content changed
        """
        # Compute normalized content hash
        normalized = self._normalize_record(record)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        record = record.model_copy(update={"content_hash": content_hash})

        # Check for existing duplicate — scope by source_id to avoid cross-source collisions
        existing = await self._repository.find_duplicate(
            canonical_url=record.canonical_url,
            title=record.title,
            source_reference=record.source_reference,
            content_hash=record.content_hash,
            source_id=record.source_id,
        )

        if existing is None:
            logger.debug(
                "new_record_detected",
                record_id=record.id,
                source_id=record.source_id,
                content_hash=content_hash[:16],
            )
            # Persist immediately so later calls within the same session see it
            await self._repository.save(record)
            return record, True, False

        # Duplicate found
        if existing.content_hash != content_hash:
            # Content changed - update last_seen
            logger.info(
                "record_content_changed",
                record_id=existing.id,
                source_id=record.source_id,
                old_hash=existing.content_hash[:16],
                new_hash=content_hash[:16],
            )
            await self._repository.update_last_seen(
                existing.id,
                record.raw_snapshot_id,
                content_hash,
                str(record.data_quality_status.value),
            )
            return existing, False, True

        logger.debug(
            "exact_duplicate_ignored",
            record_id=existing.id,
            source_id=record.source_id,
        )
        return existing, False, False

    def _normalize_record(self, record: IntelligenceRecord) -> str:
        """Create a normalized string for hashing.

        Normalizes:
        - canonical_url (lowercase, strip)
        - title (lowercase, strip, collapse whitespace)
        - summary (lowercase, strip, collapse whitespace)
        - published_at (ISO format if present)
        - source_reference (exact)
        """
        url = record.canonical_url.lower().strip()
        title = " ".join(record.title.lower().strip().split())
        summary = " ".join(record.summary.lower().strip().split())
        pub = record.published_at.isoformat() if record.published_at else ""
        ref = record.source_reference.strip()

        return f"{url}|{title}|{summary}|{pub}|{ref}"
