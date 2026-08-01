"""URL validation and SSRF prevention with DNS and redirect checks."""
import ipaddress
import re
import socket
from urllib.parse import urlparse

from app.config import settings
from app.logging import get_logger

logger = get_logger(__name__)

ALLOWED_SCHEMES = {"https"}
if settings.allow_http_for_tests:
    ALLOWED_SCHEMES.add("http")

# Private/reserved IP ranges
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
]

_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.aws.internal",
    "169.254.170.2",
    "metadata",
    "metadata.google.internal.",
}

# Source domain allow-list (empty = all domains allowed after other checks)
# Populated from config


class URLValidationError(Exception):
    """Raised when a URL fails security validation."""

    pass


def _is_blocked_ip(ip_str: str) -> bool:
    """Check if an IP address is in a blocked network."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return True
    except ValueError:
        return False
    return False


def _resolve_and_validate_host(hostname: str) -> None:
    """Resolve hostname and validate the resulting IPs against blocked ranges.

    This prevents DNS rebinding attacks where a hostname initially resolves
    to a public IP but later resolves to a private IP.
    """
    try:
        # Get all addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, None)
        seen_ips = set()
        for info in addr_info:
            ip_str = str(info[4][0])
            if ip_str in seen_ips:
                continue
            seen_ips.add(ip_str)
            if _is_blocked_ip(ip_str):
                logger.warning("dns_rebinding_blocked", hostname=hostname, resolved_ip=ip_str)
                raise URLValidationError(
                    f"Hostname {hostname} resolves to blocked IP {ip_str}"
                )
    except socket.gaierror as e:
        logger.warning("dns_resolution_failed", hostname=hostname, error=str(e))
        raise URLValidationError(f"Could not resolve hostname: {hostname}") from e


def validate_url(url: str, *, allow_file: bool = False) -> str:
    """Validate a URL for safety. Returns canonical URL or raises URLValidationError.

    Checks:
    - Scheme allow-list
    - No localhost/private IPs (always blocked, regardless of mode)
    - DNS resolution with IP validation (rebinding protection, always active)
    - No metadata service addresses
    - No file:// or ftp://
    - Basic format validation
    - Directory traversal prevention
    - Domain allow-list enforcement (if configured)
    """
    if not url or not isinstance(url, str):
        raise URLValidationError("URL must be a non-empty string")

    # Prevent null bytes and control characters
    if "\x00" in url or "\x00" in repr(url):
        raise URLValidationError("URL contains null bytes")

    parsed = urlparse(url)

    # Scheme validation
    if parsed.scheme == "file" and allow_file:
        return url

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise URLValidationError(
            f"URL scheme '{parsed.scheme}' not allowed. Allowed: {ALLOWED_SCHEMES}"
        )

    if parsed.scheme in ("file", "ftp", "sftp", "gopher", "telnet"):
        raise URLValidationError(f"URL scheme '{parsed.scheme}' is forbidden")

    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL has no valid hostname")

    hostname_lower = hostname.lower()

    # Block metadata service hosts
    if hostname_lower in _METADATA_HOSTS or hostname_lower.startswith("metadata"):
        raise URLValidationError("Metadata service access is blocked")

    # Block localhost names — always, regardless of mode
    if hostname_lower in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
        raise URLValidationError("localhost access is blocked")

    # Direct IP address checks — always block private ranges
    try:
        ip = ipaddress.ip_address(hostname)
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise URLValidationError(f"Private IP address {ip} is blocked")
    except ValueError:
        # Not an IP address, likely a domain name — resolve and check
        # Always perform DNS resolution for rebinding protection
        _resolve_and_validate_host(hostname)

    # Domain allow-list enforcement
    allowed_domains = getattr(settings, "allowed_source_domains", None)
    if allowed_domains and hostname_lower not in {d.lower() for d in allowed_domains}:
        raise URLValidationError(
            f"Domain '{hostname}' is not in the approved source allow-list"
        )

    # Block suspicious characters in path (directory traversal)
    if parsed.path:
        if ".." in parsed.path or "\x00" in parsed.path:
            raise URLValidationError("URL path contains suspicious characters")

    logger.debug("url_validated", url=url, hostname=hostname)
    return url


def validate_redirect_target(target: str, original: str) -> str:
    """Validate a redirect target URL with strict checks.

    Re-validates the full URL security model on every redirect hop.
    ``original`` must be the *immediate predecessor* URL so that each hop is
    validated against its correct anchor (callers must pass ``current_url``,
    not the very first URL).

    Cross-origin redirects are **rejected** — all redirects must stay on the
    same host as the approved source being crawled.
    """
    validated = validate_url(target)
    orig_parsed = urlparse(original)
    target_parsed = urlparse(validated)

    # Enforce same-scheme
    if orig_parsed.scheme != target_parsed.scheme:
        raise URLValidationError(
            f"Redirect scheme changed from {orig_parsed.scheme} to {target_parsed.scheme}"
        )

    # Cross-origin redirects are blocked — not merely logged
    if orig_parsed.netloc != target_parsed.netloc:
        logger.warning(
            "cross_origin_redirect_blocked",
            original=original,
            target=validated,
            original_host=orig_parsed.netloc,
            target_host=target_parsed.netloc,
        )
        raise URLValidationError(
            f"Cross-origin redirect blocked: {orig_parsed.netloc} → {target_parsed.netloc}"
        )

    # Re-validate DNS on redirect target
    if target_parsed.hostname:
        try:
            ipaddress.ip_address(target_parsed.hostname)
        except ValueError:
            _resolve_and_validate_host(target_parsed.hostname)

    return validated
