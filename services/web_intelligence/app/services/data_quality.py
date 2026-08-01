"""Data quality evaluation service."""
from app.domain.enums import DataQualityStatus
from app.domain.models import RawSnapshot
from app.logging import get_logger

logger = get_logger(__name__)


class DataQualityEvaluator:
    """Evaluate data quality of fetched snapshots and parsed records."""

    def evaluate_snapshot(self, snapshot: RawSnapshot) -> DataQualityStatus:
        """Evaluate the quality of a raw snapshot."""
        if snapshot.error_code or snapshot.error_message:
            if snapshot.data_quality_status != DataQualityStatus.UNKNOWN:
                return snapshot.data_quality_status
            return DataQualityStatus.HTTP_ERROR

        if snapshot.http_status is None:
            return DataQualityStatus.HTTP_ERROR

        if snapshot.http_status >= 500:
            return DataQualityStatus.HTTP_ERROR

        if snapshot.http_status == 429:
            return DataQualityStatus.RATE_LIMITED

        if snapshot.http_status >= 400:
            return DataQualityStatus.HTTP_ERROR

        if not snapshot.content_hash or snapshot.content_hash == hashlib.sha256(b"").hexdigest():
            return DataQualityStatus.EMPTY_CONTENT

        return DataQualityStatus.VALID

    def evaluate_parser_result(
        self,
        record_count: int,
        expected_min_records: int = 1,
    ) -> DataQualityStatus:
        """Evaluate parser result quality."""
        if record_count == 0:
            return DataQualityStatus.EMPTY_CONTENT
        if record_count < expected_min_records:
            return DataQualityStatus.PARTIAL
        return DataQualityStatus.VALID


import hashlib  # noqa: E402
