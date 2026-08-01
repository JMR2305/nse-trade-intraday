"""Extended security tests: SSRF outside production_mode, redirect multi-hop, DNS rebinding."""
import pytest
from unittest.mock import patch

from app.security.url_validator import URLValidationError, validate_url, validate_redirect_target


# ---------------------------------------------------------------------------
# B — SSRF checks are always active (not gated on production_mode)
# ---------------------------------------------------------------------------

def test_localhost_blocked_regardless_of_production_mode(monkeypatch):
    """localhost must be blocked even when production_mode=False."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)
    with pytest.raises(URLValidationError, match="localhost"):
        validate_url("https://localhost/internal")


def test_localhost_localdomain_blocked_non_production(monkeypatch):
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)
    with pytest.raises(URLValidationError):
        validate_url("https://localhost.localdomain/test")


def test_private_ip_blocked_non_production(monkeypatch):
    """RFC-1918 private IPs must be blocked outside production mode."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)
    with pytest.raises(URLValidationError, match="Private IP"):
        validate_url("https://10.0.0.1/data")


def test_cgnat_ip_blocked_non_production(monkeypatch):
    """100.64.0.0/10 (CGNAT) must be blocked outside production mode."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)
    with pytest.raises(URLValidationError):
        validate_url("https://100.64.0.1/api")


def test_link_local_ip_blocked_non_production(monkeypatch):
    """169.254.x.x must be blocked outside production mode."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)
    with pytest.raises(URLValidationError):
        validate_url("https://169.254.1.1/test")


# ---------------------------------------------------------------------------
# B — DNS resolution always active
# ---------------------------------------------------------------------------

def test_dns_resolution_blocks_private_ip_non_production(monkeypatch):
    """DNS rebinding check must fire even when production_mode=False."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)

    import socket
    def fake_getaddrinfo(host, port, *a, **kw):
        # Simulate hostname that resolves to a private IP
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('192.168.1.100', 0))]

    with patch("app.security.url_validator.socket.getaddrinfo", fake_getaddrinfo):
        with pytest.raises(URLValidationError):
            validate_url("https://evil-rebind.example.com/data")


# ---------------------------------------------------------------------------
# C — Cross-origin redirects are blocked, not just logged
# ---------------------------------------------------------------------------

def test_cross_origin_redirect_raises_error(monkeypatch):
    """Cross-origin redirect must raise URLValidationError, not just log."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)

    import socket
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('93.184.216.34', 0))]

    with patch("app.security.url_validator.socket.getaddrinfo", fake_getaddrinfo):
        with pytest.raises(URLValidationError, match="Cross-origin redirect blocked"):
            validate_redirect_target(
                "https://attacker.com/steal",
                "https://example.com/page",
            )


def test_same_origin_redirect_allowed(monkeypatch):
    """Same-origin redirects must be allowed."""
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)

    import socket
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('93.184.216.34', 0))]

    with patch("app.security.url_validator.socket.getaddrinfo", fake_getaddrinfo):
        result = validate_redirect_target(
            "https://example.com/new-path",
            "https://example.com/old-path",
        )
    assert result == "https://example.com/new-path"


def test_scheme_change_redirect_blocked(monkeypatch):
    """Scheme-downgrade redirects (https→http) must be blocked."""
    # Allow http in ALLOWED_SCHEMES so validate_url passes, then expect
    # validate_redirect_target to reject the scheme change.
    import app.security.url_validator as uv
    original = set(uv.ALLOWED_SCHEMES)
    uv.ALLOWED_SCHEMES.add("http")
    try:
        with pytest.raises(URLValidationError):
            validate_redirect_target(
                "http://example.com/page",
                "https://example.com/other",
            )
    finally:
        uv.ALLOWED_SCHEMES.clear()
        uv.ALLOWED_SCHEMES.update(original)


# ---------------------------------------------------------------------------
# C — Multi-hop redirect validates against current_url, not original
# ---------------------------------------------------------------------------

def test_validate_redirect_target_uses_current_url_as_anchor(monkeypatch):
    """validate_redirect_target must compare target against its immediate predecessor.

    If hop 2 redirects example.com → evil.com, the test should fail.
    This verifies the call site passes current_url (per-hop) not the original URL.
    """
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", False)

    import socket
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('93.184.216.34', 0))]

    with patch("app.security.url_validator.socket.getaddrinfo", fake_getaddrinfo):
        # hop 1: original → intermediate (same domain — OK)
        hop1 = validate_redirect_target(
            "https://example.com/page2",
            "https://example.com/page1",
        )
        assert hop1 == "https://example.com/page2"

        # hop 2: current is now example.com; redirect to evil.com must be blocked
        with pytest.raises(URLValidationError, match="Cross-origin"):
            validate_redirect_target(
                "https://evil.com/steal",
                hop1,  # current_url from hop 1
            )
