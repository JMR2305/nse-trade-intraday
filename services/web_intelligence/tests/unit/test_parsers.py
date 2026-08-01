"""Tests for source parsers."""
import pytest

from app.domain.enums import DataQualityStatus, RecordType
from app.parsers.fixture_parser import FixtureParser
from app.parsers.generic_static_parser import GenericStaticParser


class TestFixtureParser:
    def test_parse_valid_fixture(self):
        html = """<!DOCTYPE html><html><body>
        <div class="fixture-item">
            <span class="fixture-title">Test Title</span>
            <span class="fixture-summary">Test Summary</span>
            <span class="fixture-date">2024-01-15T10:00:00</span>
        </div>
        </body></html>"""
        parser = FixtureParser()
        result = parser.parse(html, "file://test.html", "snap-1", "src-1")
        assert result.data_quality_status == DataQualityStatus.VALID
        assert len(result.records) == 1
        assert result.records[0].title == "Test Title"
        assert result.records[0].record_type == RecordType.GENERIC

    def test_parse_no_items_fails_closed(self):
        html = "<html><body><p>No items here</p></body></html>"
        parser = FixtureParser()
        result = parser.parse(html, "file://test.html", "snap-1", "src-1")
        assert result.data_quality_status == DataQualityStatus.PARSER_MISMATCH

    def test_parse_empty_body_fails_closed(self):
        html = "<html></html>"
        parser = FixtureParser()
        result = parser.parse(html, "file://test.html", "snap-1", "src-1")
        assert result.data_quality_status == DataQualityStatus.PARSER_MISMATCH


class TestGenericStaticParser:
    def test_parse_valid_page(self):
        html = """<!DOCTYPE html><html><body>
        <article class="intelligence-item">
            <h2 class="title">Announcement</h2>
            <p class="summary">Details here</p>
            <time datetime="2024-01-10T09:00:00+00:00">Jan 10</time>
        </article>
        </body></html>"""
        parser = GenericStaticParser()
        result = parser.parse(html, "https://example.com/news", "snap-1", "src-1")
        assert result.data_quality_status == DataQualityStatus.VALID
        assert len(result.records) == 1
        assert result.records[0].title == "Announcement"

    def test_parse_no_articles_fails_closed(self):
        html = "<html><body><p>Nothing relevant</p></body></html>"
        parser = GenericStaticParser()
        result = parser.parse(html, "https://example.com", "snap-1", "src-1")
        assert result.data_quality_status == DataQualityStatus.PARSER_MISMATCH
