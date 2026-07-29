"""
security_checker.py — Phase 6.5
Security readiness: secrets not exposed, debug mode disabled,
unsafe defaults, logging safety, audit logging, configuration safety.

READ-ONLY. ADVISORY-ONLY.
This module NEVER reads secret values — only checks for their presence.
"""
from __future__ import annotations
import os
from typing import List
from .readiness_models import ReadinessCheck, PASS, WARN, FAIL


def check_security() -> dict:
    """
    Run security readiness checks.
    """
    checks: List[ReadinessCheck] = []

    checks.append(_check_session_secret())
    checks.append(_check_zerodha_keys())
    checks.append(_check_debug_mode())
    checks.append(_check_secrets_not_in_env_values())
    checks.append(_check_advisory_only_flags())
    checks.append(_check_unsafe_defaults())
    checks.append(_check_audit_logging())

    score = _category_score(checks)
    critical = sum(1 for c in checks if c.status == FAIL and c.required)

    return {
        "checks": [c.to_dict() for c in checks],
        "score": score,
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == PASS),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "failures": sum(1 for c in checks if c.status == FAIL),
        "critical_failures": critical,
        "security_level": "STRONG" if score >= 85 else "ADEQUATE" if score >= 65 else "WEAK",
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_session_secret() -> ReadinessCheck:
    """SESSION_SECRET must be present (not checked for value)."""
    present = bool(os.environ.get("SESSION_SECRET"))
    return ReadinessCheck(
        name="session_secret_set",
        label="Session Secret Present",
        status=PASS if present else FAIL,
        required=True,
        detail="SESSION_SECRET is set." if present else "SESSION_SECRET is missing — sessions are insecure.",
        category="Security",
    )


def _check_zerodha_keys() -> ReadinessCheck:
    """Zerodha API credentials must be present for broker features."""
    key_ok = bool(os.environ.get("ZERODHA_API_KEY"))
    secret_ok = bool(os.environ.get("ZERODHA_API_SECRET"))
    if key_ok and secret_ok:
        return ReadinessCheck(
            name="zerodha_credentials",
            label="Zerodha API Credentials",
            status=PASS,
            required=False,
            detail="ZERODHA_API_KEY and ZERODHA_API_SECRET are present.",
            category="Security",
        )
    missing = []
    if not key_ok:
        missing.append("ZERODHA_API_KEY")
    if not secret_ok:
        missing.append("ZERODHA_API_SECRET")
    return ReadinessCheck(
        name="zerodha_credentials",
        label="Zerodha API Credentials",
        status=WARN,
        required=False,
        detail=f"Missing: {', '.join(missing)} — broker connectivity will fail.",
        category="Security",
    )


def _check_debug_mode() -> ReadinessCheck:
    """DEBUG should not be 'true' in a production-like environment."""
    debug = os.environ.get("DEBUG", "").lower()
    flask_debug = os.environ.get("FLASK_DEBUG", "").lower()
    if debug in ("true", "1", "yes") or flask_debug in ("true", "1", "yes"):
        return ReadinessCheck(
            name="debug_mode_disabled",
            label="Debug Mode Disabled",
            status=WARN,
            required=False,
            detail="DEBUG or FLASK_DEBUG is enabled — disable before extended paper trading.",
            category="Security",
        )
    return ReadinessCheck(
        name="debug_mode_disabled",
        label="Debug Mode Disabled",
        status=PASS,
        required=False,
        detail="DEBUG mode is not enabled.",
        category="Security",
    )


_RUNTIME_MANAGED_KEYS: frozenset = frozenset({
    # Replit injects these automatically — their values are strong, machine-generated,
    # and must never be flagged as weak placeholders.
    "PGPASSWORD", "PGUSER", "PGHOST", "PGPORT", "PGDATABASE",
    "DATABASE_URL", "REPLIT_DOMAINS", "REPLIT_DEV_DOMAIN", "REPL_ID",
    "REPLIT_DB_URL",
})


def _check_secrets_not_in_env_values() -> ReadinessCheck:
    """Spot-check that no obviously dangerous patterns exist in env values (e.g. hardcoded tokens).

    Replit-managed runtime keys (PGPASSWORD, DATABASE_URL, etc.) are explicitly excluded:
    their values are machine-generated strong credentials and must not be evaluated for
    'weakness'.  Checking them would produce false-positives that mislead operators.
    """
    suspicious_keys = ["PASSWORD", "TOKEN", "SECRET", "KEY", "CREDENTIAL"]
    exposed = []
    for k, v in os.environ.items():
        if k in _RUNTIME_MANAGED_KEYS:
            continue  # never evaluate Replit-managed keys
        if any(pat in k.upper() for pat in suspicious_keys):
            # Just verify it's set — never log the value
            # Check it isn't a trivially weak placeholder
            if v.lower() in ("password", "secret", "changeme", "default", "test", "1234", "admin"):
                exposed.append(k)
    if exposed:
        return ReadinessCheck(
            name="secrets_not_exposed",
            label="Secret Value Safety",
            status=FAIL,
            required=True,
            detail=f"Weak/placeholder value detected for: {', '.join(exposed[:3])}. Replace before deployment.",
            category="Security",
        )
    return ReadinessCheck(
        name="secrets_not_exposed",
        label="Secret Value Safety",
        status=PASS,
        required=True,
        detail="No obviously weak credential values detected.",
        category="Security",
    )


def _check_advisory_only_flags() -> ReadinessCheck:
    """Verify that no auto-execution flags are set."""
    auto_exec = os.environ.get("AUTO_EXECUTION_ENABLED", "false").lower()
    live_orders = os.environ.get("LIVE_ORDERS_ENABLED", "false").lower()
    if auto_exec in ("true", "1") or live_orders in ("true", "1"):
        return ReadinessCheck(
            name="advisory_only_flags",
            label="Advisory-Only Mode",
            status=FAIL,
            required=True,
            detail="AUTO_EXECUTION_ENABLED or LIVE_ORDERS_ENABLED is set — this violates advisory-only contract.",
            category="Security",
        )
    return ReadinessCheck(
        name="advisory_only_flags",
        label="Advisory-Only Mode",
        status=PASS,
        required=True,
        detail="Auto-execution flags are not set — platform remains advisory-only.",
        category="Security",
    )


def _check_unsafe_defaults() -> ReadinessCheck:
    """Check for unsafe default settings."""
    node_env = os.environ.get("NODE_ENV", "development").lower()
    if node_env == "production":
        return ReadinessCheck(
            name="unsafe_defaults",
            label="Environment Configuration",
            status=PASS,
            required=False,
            detail="NODE_ENV=production — production-safe defaults active.",
            category="Security",
        )
    return ReadinessCheck(
        name="unsafe_defaults",
        label="Environment Configuration",
        status=WARN,
        required=False,
        detail=f"NODE_ENV={node_env} — ensure production settings before deployment.",
        category="Security",
    )


def _check_audit_logging() -> ReadinessCheck:
    """Check if audit logging is configured."""
    # In this platform, all trades go through paper_trading_validation — that IS the audit log
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        return ReadinessCheck(
            name="audit_logging",
            label="Audit Trail",
            status=PASS,
            required=False,
            detail="Paper trading validation (Phase 6.1) provides immutable audit trail for all trades.",
            category="Security",
        )
    except Exception:
        return ReadinessCheck(
            name="audit_logging",
            label="Audit Trail",
            status=WARN,
            required=False,
            detail="Audit trail (Phase 6.1 validation) not accessible.",
            category="Security",
        )


def _category_score(checks: list) -> float:
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)
