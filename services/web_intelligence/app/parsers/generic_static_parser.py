"""Parser for generic static test pages."""
from datetime import datetime
from typing import Any

from app.collectors.scrapling_adapter import ScraplingAdapter
from app.domain.enums import ConfidenceStatus, DataQualityStatus, RecordType, ValidationStatus
from app.domain.models import IntelligenceRecord
from app.logging import get_logger
from app.parsers.base_parser import ParseResult, SourceParser

logger = get_logger(__name__)


class GenericStaticParser(SourceParser):
    """Parser for generic approved static pages.

    Expects HTML with article-like structures:
    - <article class="intelligence-item">
    - <h2 class="title">Title</h2>
    - <p class="summary">Summary</p>
    - <time datetime="...">Publication date</time>

    Compatible with scrapling 0.4.x Selector API:
    - Use `css()` to select multiple elements (returns iterable Selectors)
    - Use `find()` to get the first matching element (returns single Selector or None)
    - Access text via the `.text` property — not the `.text()` method
    """

    @property
    def parser_name(self) -> str:
        return "generic_static_parser"

    @property
    def parser_version(self) -> str:
        return "1.0.0"

    def parse(
        self, html_content: str, source_url: str, snapshot_id: str, source_id: str
    ) -> ParseResult:
        adapter = ScraplingAdapter()
        doc = adapter.parse_html(html_content, url=source_url)

        # css() returns all matching elements; find() returns the first only
        articles = doc.css("article.intelligence-item")
        if not articles:
            body = doc.find("body")
            if not body:
                logger.warning(
                    "parser_mismatch_no_body",
                    parser=self.parser_name,
                    source_url=source_url,
                    snapshot_id=snapshot_id,
                )
                return ParseResult(
                    records=[],
                    data_quality_status=DataQualityStatus.PARSER_MISMATCH,
                    parser_version=self.parser_version,
                    error_message="No <body> tag found in document",
                )

            logger.warning(
                "parser_mismatch_no_articles",
                parser=self.parser_name,
                source_url=source_url,
                snapshot_id=snapshot_id,
            )
            return ParseResult(
                records=[],
                data_quality_status=DataQualityStatus.PARSER_MISMATCH,
                parser_version=self.parser_version,
                error_message="Expected article.intelligence-item selectors not found",
            )

        records: list[IntelligenceRecord] = []
        for idx, article in enumerate(articles):
            try:
                title_elem = article.find("h2.title")
                title = title_elem.text if title_elem else ""

                summary_elem = article.find("p.summary")
                summary = summary_elem.text if summary_elem else ""

                time_elem = article.find("time")
                published_at = None
                if time_elem:
                    import re
                    match = re.search(r'datetime=["\']([^"\']+)["\']', str(html_content))
                    if match:
                        try:
                            published_at = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
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
                    source_reference=f"generic_{idx}",
                    content_hash="",  # Will be filled by deduplication service
                    raw_snapshot_id=snapshot_id,
                    confidence_status=ConfidenceStatus.MEDIUM,
                    validation_status=ValidationStatus.PENDING,
                    parser_version=self.parser_version,
                    metadata={"parser": self.parser_name, "index": idx},
                )
                records.append(record)
            except Exception as e:
                logger.warning(
                    "article_parse_error",
                    parser=self.parser_name,
                    index=idx,
                    error=str(e),
                )
                continue

        if not records:
            return ParseResult(
                records=[],
                data_quality_status=DataQualityStatus.EMPTY_CONTENT,
                parser_version=self.parser_version,
                error_message="Articles found but no records could be extracted",
            )

        return ParseResult(
            records=records,
            data_quality_status=DataQualityStatus.VALID,
            parser_version=self.parser_version,
        )
