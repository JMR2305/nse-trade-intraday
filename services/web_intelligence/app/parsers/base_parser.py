"""Base parser interface and registry."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.domain.enums import DataQualityStatus, RecordType
from app.domain.models import IntelligenceRecord


@dataclass
class ParseResult:
    """Result of parsing a raw snapshot."""

    records: list[IntelligenceRecord]
    data_quality_status: DataQualityStatus
    parser_version: str
    error_message: str | None = None
    raw_metadata: dict[str, Any] | None = None


class SourceParser(ABC):
    """Abstract base class for source-specific parsers."""

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Unique parser identifier."""
        ...

    @property
    @abstractmethod
    def parser_version(self) -> str:
        """Parser version string."""
        ...

    @abstractmethod
    def parse(self, html_content: str, source_url: str, snapshot_id: str, source_id: str) -> ParseResult:
        """Parse HTML content and return extracted records.

        Must fail closed: if required selectors are missing,
        return PARSER_MISMATCH status rather than empty success.
        """
        ...


class ParserRegistry:
    """Registry of available parsers."""

    def __init__(self) -> None:
        self._parsers: dict[str, SourceParser] = {}

    def register(self, parser: SourceParser) -> None:
        self._parsers[parser.parser_name] = parser

    def get(self, name: str) -> SourceParser | None:
        return self._parsers.get(name)

    def list_parsers(self) -> list[str]:
        return list(self._parsers.keys())

    def clear(self) -> None:
        self._parsers.clear()
