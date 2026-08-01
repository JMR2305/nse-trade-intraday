"""Parser for local HTML fixture sources."""
from datetime import datetime

from app.collectors.scrapling_adapter import ScraplingAdapter
from app.domain.enums import ConfidenceStatus, DataQualityStatus, RecordType, ValidationStatus
from app.domain.models import IntelligenceRecord
from app.logging import get_logger
from app.parsers.base_parser import ParseResult, SourceParser

logger = get_logger(__name__)


class FixtureParser(SourceParser):
    """Parser for deterministic local HTML fixtures.

    Expects fixture HTML with:
    - <div class="fixture-item">
    - <span class="fixture-title">Title</span>
    - <span class="fixture-summary">Summary</span>
    - <span class="fixture-date">ISO date</span>
    """

    @property
    def parser_name(self) -> str:
        return "fixture_parser"

    @property
    def parser_version(self) -> str:
        return "1.0.0"

    def parse(
        self, html_content: str, source_url: str, snapshot_id: str, source_id: str
    ) -> ParseResult:
        adapter = ScraplingAdapter()
        doc = adapter.parse_html(html_content, url=source_url)

        items = doc.find("div.fixture-item")
        if not items:
            body = doc.find("body")
            if not body:
                return ParseResult(
                    records=[],
                    data_quality_status=DataQualityStatus.PARSER_MISMATCH,
                    parser_version=self.parser_version,
                    error_message="No <body> tag found in fixture",
                )
            return ParseResult(
                records=[],
                data_quality_status=DataQualityStatus.PARSER_MISMATCH,
                parser_version=self.parser_version,
                error_message="Expected div.fixture-item selectors not found",
            )

        records: list[IntelligenceRecord] = []
        for idx, item in enumerate(items):
            try:
                title_elem = item.find("span.fixture-title")
                title = title_elem[0].text() if title_elem else ""

                summary_elem = item.find("span.fixture-summary")
                summary = summary_elem[0].text() if summary_elem else ""

                date_elem = item.find("span.fixture-date")
                published_at = None
                if date_elem:
                    try:
                        published_at = datetime.fromisoformat(date_elem[0].text().strip())
                    except ValueError:
                        pass

                record_id = f"{source_id}_{snapshot_id}_{idx}"
                record = IntelligenceRecord(
                    id=record_id,
                    source_id=source_id,
                    record_type=RecordType.GENERIC,
                    title=title,
                    summary=summary,
                    published_at=published_at,
                    canonical_url=source_url,
                    source_reference=f"fixture_{idx}",
                    content_hash="",
                    raw_snapshot_id=snapshot_id,
                    confidence_status=ConfidenceStatus.HIGH,
                    validation_status=ValidationStatus.PENDING,
                    parser_version=self.parser_version,
                    metadata={"parser": self.parser_name, "fixture": True, "index": idx},
                )
                records.append(record)
            except Exception as e:
                logger.warning("fixture_item_parse_error", index=idx, error=str(e))
                continue

        if not records:
            return ParseResult(
                records=[],
                data_quality_status=DataQualityStatus.EMPTY_CONTENT,
                parser_version=self.parser_version,
                error_message="Fixture items found but no records extracted",
            )

        return ParseResult(
            records=records,
            data_quality_status=DataQualityStatus.VALID,
            parser_version=self.parser_version,
        )
