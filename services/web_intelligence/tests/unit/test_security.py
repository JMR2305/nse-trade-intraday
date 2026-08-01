"""Tests for security controls."""
import pytest

from app.security.url_validator import URLValidationError, validate_url


def test_validate_https_url_allowed():
    assert validate_url("https://example.com/path") == "https://example.com/path"


def test_validate_http_blocked_in_production(monkeypatch):
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", True)
    with pytest.raises(URLValidationError):
        validate_url("http://example.com")


def test_validate_localhost_blocked_in_production(monkeypatch):
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", True)
    with pytest.raises(URLValidationError):
        validate_url("https://localhost:8000/test")


def test_validate_private_ip_blocked_in_production(monkeypatch):
    monkeypatch.setattr("app.security.url_validator.settings.production_mode", True)
    with pytest.raises(URLValidationError):
        validate_url("https://192.168.1.1/api")


def test_validate_metadata_service_blocked():
    with pytest.raises(URLValidationError):
        validate_url("https://169.254.169.254/latest/meta-data")


def test_validate_file_scheme_blocked():
    with pytest.raises(URLValidationError):
        validate_url("file:///etc/passwd")


def test_validate_ftp_scheme_blocked():
    with pytest.raises(URLValidationError):
        validate_url("ftp://example.com/file.txt")


def test_validate_directory_traversal_blocked():
    with pytest.raises(URLValidationError):
        validate_url("https://example.com/../../../etc/passwd")


def test_validate_empty_url_rejected():
    with pytest.raises(URLValidationError):
        validate_url("")
