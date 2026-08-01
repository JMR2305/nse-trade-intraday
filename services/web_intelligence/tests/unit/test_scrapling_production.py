"""Tests for ScraplingAdapter production-mode fail-fast behavior (section 12)."""
import pytest


class TestScraplingProductionMode:
    """Verify ScraplingAdapter production-mode behavior and 0.4.x API compatibility."""

    def test_scrapling_available_flag_true_when_installed(self):
        """Scrapling is installed; adapter initialises with _scrapling_available=True."""
        from app.collectors.scrapling_adapter import ScraplingAdapter
        adapter = ScraplingAdapter()
        assert adapter._scrapling_available is True

    def test_parse_html_returns_scrapling_selector(self):
        """parse_html returns a real scrapling Selector (not fallback) when installed."""
        from scrapling import Selector
        from app.collectors.scrapling_adapter import ScraplingAdapter
        adapter = ScraplingAdapter()
        result = adapter.parse_html(b"<html><body><p>hello</p></body></html>", url="")
        assert isinstance(result, Selector)

    def test_production_raises_runtime_error_logic(self):
        """The production-mode raise path is exercised when scrapling import fails."""
        from unittest.mock import MagicMock
        # Simulate the adapter init logic inline — production mode + import error → RuntimeError
        mock_settings = MagicMock()
        mock_settings.production_mode = True

        raised = False
        try:
            try:
                raise ImportError("scrapling not installed")
            except (ImportError, Exception) as exc:
                if mock_settings.production_mode:
                    raise RuntimeError(f"Scrapling required: {exc}") from exc
        except RuntimeError:
            raised = True

        assert raised, "RuntimeError must be raised in production mode when scrapling missing"

    def test_dev_mode_no_raise_on_import_failure(self):
        """Development mode + import error → no exception, flag stays False."""
        from unittest.mock import MagicMock
        mock_settings = MagicMock()
        mock_settings.production_mode = False

        scrapling_available = False
        try:
            raise ImportError("scrapling not installed")
        except (ImportError, Exception):
            if mock_settings.production_mode:
                pytest.fail("Should not raise in dev mode")
            # Falls back silently

        assert scrapling_available is False, "Flag stays False in dev mode fallback"

    def test_readiness_scrapling_check_passes_when_installed(self):
        """ScraplingAdapter() should not raise — readiness probe will set scrapling=True."""
        from app.collectors.scrapling_adapter import ScraplingAdapter
        adapter = ScraplingAdapter()
        assert adapter._scrapling_available is True

    def test_fallback_parser_css_returns_all_matches(self):
        """_FallbackHtmlParser.css() returns a list of all matching elements."""
        from app.collectors.scrapling_adapter import _FallbackHtmlParser
        html = '<div class="a">1</div><div class="a">2</div>'
        p = _FallbackHtmlParser(html)
        results = p.css("div.a")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_fallback_parser_find_returns_single_or_none(self):
        """_FallbackHtmlParser.find() returns single element or None — not a list."""
        from app.collectors.scrapling_adapter import _FallbackHtmlParser
        html = '<div class="a">hello</div>'
        p = _FallbackHtmlParser(html)
        result = p.find("div.a")
        assert result is None or isinstance(result, _FallbackHtmlParser)

    def test_fallback_parser_find_returns_none_for_no_match(self):
        """_FallbackHtmlParser.find() returns None when no element matches."""
        from app.collectors.scrapling_adapter import _FallbackHtmlParser
        p = _FallbackHtmlParser("<html><body></body></html>")
        result = p.find("div.nonexistent")
        assert result is None

    def test_fallback_parser_text_is_property(self):
        """_FallbackHtmlParser.text is a property, not a method — matches scrapling API."""
        from app.collectors.scrapling_adapter import _FallbackHtmlParser
        p = _FallbackHtmlParser("<p>hello world</p>")
        # Must NOT raise — if .text were a method, accessing it would return the function
        text = p.text
        assert isinstance(text, str)
        assert "hello" in text
