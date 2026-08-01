"""Scrapling adapter behind a clean interface."""
from typing import Any

from app.logging import get_logger

logger = get_logger(__name__)


class ScraplingAdapter:
    """Adapter to keep Scrapling-specific code isolated.

    This allows swapping or upgrading the scraping framework
    without changing downstream code.
    """

    def __init__(self) -> None:
        self._scrapling_available = False
        try:
            from scrapling import Fetcher

            self._Fetcher = Fetcher
            self._scrapling_available = True
            logger.info("scrapling_adapter_initialized")
        except ImportError:
            logger.warning("scrapling_not_available_using_fallback")

    def parse_html(self, html_content: bytes | str, url: str = "") -> Any:
        """Parse HTML content and return a traversable document.

        Returns a Scrapling Adaptor object or a minimal fallback.
        """
        if self._scrapling_available:
            fetcher = self._Fetcher()
            return fetcher.adapt(html_content, url=url)

        # Fallback: minimal HTML parsing
        return _FallbackHtmlParser(html_content, url)


class _FallbackHtmlParser:
    """Minimal fallback parser when Scrapling is not installed."""

    def __init__(self, content: bytes | str, url: str = "") -> None:
        self._content = content.decode("utf-8") if isinstance(content, bytes) else content
        self._url = url

    def find(self, selector: str) -> list["_FallbackHtmlParser"]:
        """Basic selector support for testing — handles tag, .class, tag.class, #id."""
        import re

        results: list[_FallbackHtmlParser] = []

        if selector.startswith("#"):
            # ID selector
            pattern = re.compile(rf'id=["\']{re.escape(selector[1:])}["\']')
            matches = pattern.findall(self._content)
            for _ in matches:
                results.append(_FallbackHtmlParser(self._content, self._url))

        elif selector.startswith("."):
            # Pure class selector — .foo
            class_name = selector[1:]
            pattern = re.compile(
                rf'<\w+[^>]+class=["\'][^"\']*(?:^|\\s){re.escape(class_name)}(?:\\s|["\'])',
                re.IGNORECASE,
            )
            # Simpler: just look for the class anywhere in an element opening tag
            pattern2 = re.compile(
                rf'class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\']',
            )
            for m in pattern2.finditer(self._content):
                # Extract the element content from the opening tag position
                start = self._content.rfind("<", 0, m.start())
                if start >= 0:
                    results.append(_FallbackHtmlParser(self._content[start:], self._url))

        elif "." in selector:
            # Compound selector: tag.class (e.g. div.fixture-item, span.fixture-title)
            tag, class_name = selector.split(".", 1)
            # Find all opening tags of this type with the matching class
            open_tag_pat = re.compile(
                rf'<{re.escape(tag)}\b[^>]*class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*>',
                re.IGNORECASE,
            )
            for m in open_tag_pat.finditer(self._content):
                # Capture content from the opening tag to the matching closing tag
                start = m.start()
                close_tag = f"</{tag}>"
                end = self._content.find(close_tag, m.end())
                if end >= 0:
                    chunk = self._content[start : end + len(close_tag)]
                else:
                    chunk = self._content[start:]
                results.append(_FallbackHtmlParser(chunk, self._url))

        else:
            # Plain tag selector
            pattern = re.compile(rf'<{re.escape(selector)}[\s>]', re.IGNORECASE)
            if pattern.search(self._content):
                results.append(_FallbackHtmlParser(self._content, self._url))

        return results

    def text(self) -> str:
        """Return raw text content."""
        import re

        text = re.sub(r"<[^>]+>", " ", self._content)
        return " ".join(text.split())

    @property
    def url(self) -> str:
        return self._url
