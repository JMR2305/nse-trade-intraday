"""HTTP fetch client with rate limiting, retries, security, and streaming."""
import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.domain.enums import DataQualityStatus
from app.logging import get_logger
from app.metrics.metrics import FetchMetrics, MetricsCollector
from app.security.url_validator import URLValidationError, validate_redirect_target, validate_url

logger = get_logger(__name__)


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    url: str
    status_code: int | None
    headers: dict[str, str]
    content: bytes
    duration_ms: int
    content_type: str | None
    error: str | None = None
    data_quality_status: DataQualityStatus = DataQualityStatus.UNKNOWN
    retry_count: int = 0


class _HourlyRateLimiter:
    """Track and enforce per-domain hourly request limits."""

    def __init__(self) -> None:
        self._domain_windows: dict[str, list[float]] = {}

    def is_allowed(self, domain: str, max_per_hour: int) -> bool:
        """Check if a request to this domain is within the hourly limit."""
        now = time.monotonic()
        window = self._domain_windows.get(domain, [])
        # Keep only requests in the last hour
        cutoff = now - 3600.0
        window = [t for t in window if t > cutoff]
        self._domain_windows[domain] = window
        return len(window) < max_per_hour

    def record_request(self, domain: str) -> None:
        """Record that a request was made to this domain."""
        self._domain_windows.setdefault(domain, []).append(time.monotonic())

    def get_remaining(self, domain: str, max_per_hour: int) -> int:
        """Get remaining requests in the current hour window."""
        now = time.monotonic()
        window = self._domain_windows.get(domain, [])
        cutoff = now - 3600.0
        window = [t for t in window if t > cutoff]
        self._domain_windows[domain] = window
        return max(0, max_per_hour - len(window))


class FetchClient:
    """Secure HTTP fetch client with domain rate limiting and global concurrency."""

    def __init__(
        self,
        *,
        concurrency_limit: int | None = None,
        timeout_seconds: float | None = None,
        max_response_size: int | None = None,
        retry_count: int | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self.concurrency_limit = concurrency_limit or settings.global_concurrency_limit
        self.timeout_seconds = timeout_seconds or settings.request_timeout_seconds
        self.max_response_size = max_response_size or settings.maximum_response_size_bytes
        self.retry_count = retry_count or settings.retry_count
        self.metrics = metrics or MetricsCollector()

        self._semaphore = asyncio.Semaphore(self.concurrency_limit)
        self._domain_last_request: dict[str, float] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._hourly_limiter = _HourlyRateLimiter()

    async def fetch(
        self,
        url: str,
        *,
        user_agent: str | None = None,
        request_interval_seconds: float = 5.0,
        maximum_requests_per_hour: int = 60,
        headers: dict[str, str] | None = None,
        allow_file_urls: bool = False,
    ) -> FetchResult:
        """Fetch a URL with security checks, rate limiting, and retries.

        LOCAL_HTML_FIXTURE sources must pass ``allow_file_urls=True`` to read
        from the local filesystem.  All other URLs go through the full SSRF /
        scheme / redirect security stack regardless of the URL scheme.
        """
        start_time = time.monotonic()

        # file:// is ONLY allowed for LOCAL_HTML_FIXTURE sources that explicitly
        # opt in.  Without the flag, file:// is blocked by the URL validator
        # like any other unsupported scheme.
        if url.startswith("file://") and allow_file_urls:
            return await self._fetch_local_file(url, start_time)

        retry_count = 0

        try:
            validated_url = validate_url(url)
        except URLValidationError as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self.metrics.record_fetch(
                "unknown",
                FetchMetrics(success=False, latency_ms=duration_ms, error_type="url_validation"),
            )
            return FetchResult(
                url=url,
                status_code=None,
                headers={},
                content=b"",
                duration_ms=duration_ms,
                content_type=None,
                error=str(e),
                data_quality_status=DataQualityStatus.BLOCKED,
            )

        from urllib.parse import urlparse

        domain = urlparse(validated_url).netloc

        # Hourly rate limit check
        if not self._hourly_limiter.is_allowed(domain, maximum_requests_per_hour):
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self.metrics.record_rate_limit(domain)
            logger.warning("hourly_rate_limit_exceeded", domain=domain, max_per_hour=maximum_requests_per_hour)
            return FetchResult(
                url=validated_url,
                status_code=None,
                headers={},
                content=b"",
                duration_ms=duration_ms,
                content_type=None,
                error=f"Hourly rate limit exceeded for {domain}",
                data_quality_status=DataQualityStatus.RATE_LIMITED,
            )

        user_agent = user_agent or settings.default_user_agent
        request_headers = {"User-Agent": user_agent}
        if headers:
            request_headers.update(headers)

        async with self._semaphore:
            # Domain-specific rate limiting (interval between requests)
            await self._respect_domain_rate_limit(domain, request_interval_seconds)
            self._hourly_limiter.record_request(domain)

            for attempt in range(self.retry_count + 1):
                try:
                    result = await self._do_fetch(
                        validated_url, request_headers, start_time
                    )
                    if result.status_code == 429:
                        self.metrics.record_rate_limit(domain)
                        if attempt < self.retry_count:
                            wait = self._backoff_with_jitter(attempt)
                            logger.warning(
                                "rate_limited_retrying",
                                url=validated_url,
                                attempt=attempt + 1,
                                wait_seconds=wait,
                            )
                            await asyncio.sleep(wait)
                            retry_count += 1
                            continue
                        result.data_quality_status = DataQualityStatus.RATE_LIMITED
                        return result

                    if result.status_code and 400 <= result.status_code < 500:
                        # Don't retry most 4xx except 408/429
                        if result.status_code not in (408, 429):
                            result.data_quality_status = DataQualityStatus.HTTP_ERROR
                            return result

                    if result.status_code and 200 <= result.status_code < 300:
                        result.data_quality_status = DataQualityStatus.VALID
                        result.retry_count = retry_count
                        return result

                    # Retry on 5xx or other transient issues
                    if attempt < self.retry_count:
                        wait = self._backoff_with_jitter(attempt)
                        await asyncio.sleep(wait)
                        retry_count += 1
                        continue

                    result.data_quality_status = DataQualityStatus.HTTP_ERROR
                    return result

                except httpx.TimeoutException:
                    if attempt < self.retry_count:
                        wait = self._backoff_with_jitter(attempt)
                        await asyncio.sleep(wait)
                        retry_count += 1
                        continue
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    self.metrics.record_fetch(
                        domain,
                        FetchMetrics(
                            success=False, latency_ms=duration_ms, error_type="timeout"
                        ),
                    )
                    return FetchResult(
                        url=validated_url,
                        status_code=None,
                        headers={},
                        content=b"",
                        duration_ms=duration_ms,
                        content_type=None,
                        error="Request timeout",
                        data_quality_status=DataQualityStatus.HTTP_ERROR,
                        retry_count=retry_count,
                    )
                except Exception as e:
                    if attempt < self.retry_count:
                        wait = self._backoff_with_jitter(attempt)
                        await asyncio.sleep(wait)
                        retry_count += 1
                        continue
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    self.metrics.record_fetch(
                        domain,
                        FetchMetrics(
                            success=False, latency_ms=duration_ms, error_type=type(e).__name__
                        ),
                    )
                    return FetchResult(
                        url=validated_url,
                        status_code=None,
                        headers={},
                        content=b"",
                        duration_ms=duration_ms,
                        content_type=None,
                        error=str(e),
                        data_quality_status=DataQualityStatus.UNKNOWN,
                        retry_count=retry_count,
                    )

            # Should not reach here
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return FetchResult(
                url=validated_url,
                status_code=None,
                headers={},
                content=b"",
                duration_ms=duration_ms,
                content_type=None,
                error="Max retries exceeded",
                data_quality_status=DataQualityStatus.HTTP_ERROR,
                retry_count=retry_count,
            )

    async def _fetch_local_file(self, url: str, start_time: float) -> FetchResult:
        """Read a local file:// URL from the filesystem.

        Only used by LOCAL_HTML_FIXTURE sources in development / testing.
        No SSRF checks apply — the path must be an absolute filesystem path
        under the project directory and should never be user-supplied.
        """
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        # file:///absolute/path → netloc="", path="/absolute/path" — use as-is
        # file://relative/path  → netloc="relative", path="/path" — reconstruct
        if parsed.netloc:
            file_path = parsed.netloc + parsed.path
        else:
            file_path = parsed.path
        start = time.monotonic()
        try:
            with open(file_path, "rb") as fh:
                content = fh.read()
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.debug("local_file_fetched", path=file_path, size=len(content))
            return FetchResult(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                content=content,
                duration_ms=duration_ms,
                content_type="text/html",
                data_quality_status=DataQualityStatus.VALID,
            )
        except OSError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning("local_file_fetch_failed", path=file_path, error=str(e))
            return FetchResult(
                url=url,
                status_code=None,
                headers={},
                content=b"",
                duration_ms=duration_ms,
                content_type=None,
                error=f"local file read error: {e}",
                data_quality_status=DataQualityStatus.HTTP_ERROR,
            )

    async def _do_fetch(
        self, url: str, headers: dict[str, str], start_time: float
    ) -> FetchResult:
        """Perform the actual HTTP fetch with streaming size limits and content-type validation."""
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        timeout = httpx.Timeout(self.timeout_seconds)

        # Custom redirect handler to validate each hop
        async with httpx.AsyncClient(
            limits=limits, timeout=timeout, follow_redirects=False
        ) as client:
            current_url = url
            redirect_count = 0
            max_redirects = settings.max_redirects

            while redirect_count <= max_redirects:
                response = await client.get(current_url, headers=headers)

                if 300 <= response.status_code < 400:
                    redirect_count += 1
                    if redirect_count > max_redirects:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        return FetchResult(
                            url=url,
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            content=b"",
                            duration_ms=duration_ms,
                            content_type=response.headers.get("content-type"),
                            error=f"Too many redirects (max {max_redirects})",
                            data_quality_status=DataQualityStatus.BLOCKED,
                        )

                    location = response.headers.get("location")
                    if not location:
                        break

                    # Validate redirect target — pass current_url (immediate predecessor),
                    # not the original first URL, so multi-hop chains validate correctly.
                    try:
                        from urllib.parse import urljoin
                        next_url = urljoin(current_url, location)
                        current_url = validate_redirect_target(next_url, current_url)
                        continue
                    except URLValidationError as e:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        return FetchResult(
                            url=url,
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            content=b"",
                            duration_ms=duration_ms,
                            content_type=response.headers.get("content-type"),
                            error=f"Redirect validation failed: {e}",
                            data_quality_status=DataQualityStatus.BLOCKED,
                        )

                # Not a redirect — process response
                break

            # Content-type validation
            content_type_header = response.headers.get("content-type", "")
            content_type = content_type_header.split(";")[0].strip().lower() if content_type_header else ""

            if settings.strict_content_type_validation:
                allowed = [ct.lower() for ct in settings.allowed_content_types]
                if content_type and content_type not in allowed:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    return FetchResult(
                        url=current_url,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        content=b"",
                        duration_ms=duration_ms,
                        content_type=content_type,
                        error=f"Content type '{content_type}' not in allowed list: {allowed}",
                        data_quality_status=DataQualityStatus.BLOCKED,
                    )

            # Streaming read with size limit
            content = b""
            async for chunk in response.aiter_bytes(chunk_size=8192):
                content += chunk
                if len(content) > self.max_response_size:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    return FetchResult(
                        url=current_url,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        content=b"",
                        duration_ms=duration_ms,
                        content_type=content_type,
                        error=f"Response size exceeds maximum {self.max_response_size} bytes",
                        data_quality_status=DataQualityStatus.BLOCKED,
                    )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            from urllib.parse import urlparse as _urlparse
            _domain = _urlparse(current_url).netloc or "unknown"
            self.metrics.record_fetch(
                _domain,
                FetchMetrics(
                    success=response.status_code < 400,
                    latency_ms=duration_ms,
                    retry_count=0,
                ),
            )
            return FetchResult(
                url=current_url,
                status_code=response.status_code,
                headers=dict(response.headers),
                content=content,
                duration_ms=duration_ms,
                content_type=content_type,
            )

    async def _respect_domain_rate_limit(
        self, domain: str, interval_seconds: float
    ) -> None:
        """Ensure we wait between requests to the same domain."""
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()

        async with self._domain_locks[domain]:
            last = self._domain_last_request.get(domain)
            if last is not None:
                elapsed = time.monotonic() - last
                if elapsed < interval_seconds:
                    wait = interval_seconds - elapsed
                    logger.debug("domain_rate_limit_wait", domain=domain, wait_seconds=wait)
                    await asyncio.sleep(wait)
            self._domain_last_request[domain] = time.monotonic()

    def _backoff_with_jitter(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        base = min(2 ** attempt, 60)
        jitter = random.uniform(0, 1)
        return base + jitter
