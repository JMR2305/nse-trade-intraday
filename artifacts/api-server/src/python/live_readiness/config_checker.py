"""
config_checker.py — Phase 6.5
Configuration validation: environment variables, feature flags,
database config, required services, configuration checksum.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os, hashlib
from typing import List
from .readiness_models import ReadinessCheck, PASS, WARN, FAIL


# All the Phase 6.x feature flags
PHASE_FLAGS = {
    "STRATEGY_OPTIMISATION_ENABLED": "Phase 6.2 Strategy Optimisation",
    "AI_OPTIMISATION_ENABLED":        "Phase 6.3 AI Optimisation",
    "RISK_OPTIMISATION_ENABLED":      "Phase 6.4 Risk Optimisation",
    "READINESS_VALIDATION_ENABLED":   "Phase 6.5 Live Readiness",
}

REQUIRED_ENV_KEYS = ["DATABASE_URL", "SESSION_SECRET"]
BROKER_ENV_KEYS   = ["ZERODHA_API_KEY", "ZERODHA_API_SECRET"]


def check_config() -> dict:
    """
    Run configuration validation checks.
    """
    checks: List[ReadinessCheck] = []

    checks.append(_check_database_config())
    checks.append(_check_required_env_vars())
    checks.append(_check_broker_env_vars())
    checks.append(_check_feature_flags())
    checks.append(_check_config_module())
    checks.append(_check_config_checksum())

    score = _category_score(checks)

    return {
        "checks": [c.to_dict() for c in checks],
        "score": score,
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == PASS),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "failures": sum(1 for c in checks if c.status == FAIL),
        "feature_flags": {
            flag: (os.environ.get(flag, "false").lower() == "true")
            for flag in PHASE_FLAGS
        },
        "config_checksum": _build_checksum(),
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_database_config() -> ReadinessCheck:
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        return ReadinessCheck(
            name="database_config",
            label="Database Configuration",
            status=PASS,
            required=True,
            detail="PostgreSQL DATABASE_URL configured.",
            category="Config",
        )
    if db_url:
        return ReadinessCheck(
            name="database_config",
            label="Database Configuration",
            status=WARN,
            required=False,
            detail=f"DATABASE_URL set but not PostgreSQL ({db_url[:20]}...).",
            category="Config",
        )
    return ReadinessCheck(
        name="database_config",
        label="Database Configuration",
        status=WARN,
        required=False,
        detail="DATABASE_URL not set — using SQLite fallback.",
        category="Config",
    )


def _check_required_env_vars() -> ReadinessCheck:
    missing = [k for k in REQUIRED_ENV_KEYS if not os.environ.get(k)]
    if missing:
        return ReadinessCheck(
            name="required_env_vars",
            label="Required Environment Variables",
            status=FAIL if "SESSION_SECRET" in missing else WARN,
            required=True,
            detail=f"Missing: {', '.join(missing)}",
            category="Config",
        )
    return ReadinessCheck(
        name="required_env_vars",
        label="Required Environment Variables",
        status=PASS,
        required=True,
        detail=f"All required env vars present: {', '.join(REQUIRED_ENV_KEYS)}",
        category="Config",
    )


def _check_broker_env_vars() -> ReadinessCheck:
    missing = [k for k in BROKER_ENV_KEYS if not os.environ.get(k)]
    if missing:
        return ReadinessCheck(
            name="broker_env_vars",
            label="Broker API Credentials",
            status=WARN,
            required=False,
            detail=f"Missing broker env vars: {', '.join(missing)} — broker features disabled.",
            category="Config",
        )
    return ReadinessCheck(
        name="broker_env_vars",
        label="Broker API Credentials",
        status=PASS,
        required=False,
        detail="ZERODHA_API_KEY and ZERODHA_API_SECRET are present.",
        category="Config",
    )


def _check_feature_flags() -> ReadinessCheck:
    enabled = {k: v for k, v in {
        flag: os.environ.get(flag, "false").lower() == "true"
        for flag in PHASE_FLAGS
    }.items() if v}
    disabled = [PHASE_FLAGS[k] for k in PHASE_FLAGS if k not in enabled]

    n_enabled = len(enabled)
    if n_enabled == len(PHASE_FLAGS):
        return ReadinessCheck(
            name="feature_flags",
            label="Phase 6.x Feature Flags",
            status=PASS,
            required=False,
            detail=f"All {len(PHASE_FLAGS)} Phase 6.x feature flags enabled.",
            category="Config",
        )
    if n_enabled >= 2:
        return ReadinessCheck(
            name="feature_flags",
            label="Phase 6.x Feature Flags",
            status=WARN,
            required=False,
            detail=f"{n_enabled}/{len(PHASE_FLAGS)} flags enabled. Disabled: {', '.join(disabled[:3])}",
            category="Config",
        )
    return ReadinessCheck(
        name="feature_flags",
        label="Phase 6.x Feature Flags",
        status=WARN,
        required=False,
        detail=f"Only {n_enabled} feature flag(s) enabled — consider enabling all Phase 6.x modules.",
        category="Config",
    )


def _check_config_module() -> ReadinessCheck:
    try:
        import config
        attrs = dir(config)
        important = ["DEFAULT_WATCHLIST"]
        present = [a for a in important if a in attrs]
        missing = [a for a in important if a not in attrs]
        if missing:
            return ReadinessCheck(
                name="config_module",
                label="Config Module Attributes",
                status=WARN,
                required=False,
                detail=f"Config module loaded. Missing: {', '.join(missing)}",
                category="Config",
            )
        return ReadinessCheck(
            name="config_module",
            label="Config Module Attributes",
            status=PASS,
            required=False,
            detail=f"Config module OK — {len(present)}/{len(important)} expected attributes present.",
            category="Config",
        )
    except Exception as e:
        return ReadinessCheck(
            name="config_module",
            label="Config Module Attributes",
            status=FAIL,
            required=True,
            detail=f"Config module import failed: {str(e)[:120]}",
            category="Config",
        )


def _check_config_checksum() -> ReadinessCheck:
    """
    Generate a deterministic checksum of the current feature flag configuration.
    This allows operators to detect configuration drift across restarts.
    """
    checksum = _build_checksum()
    return ReadinessCheck(
        name="config_checksum",
        label="Configuration Checksum",
        status=PASS,
        required=False,
        detail=f"Config checksum: {checksum} — use to detect configuration drift.",
        category="Config",
    )


def _build_checksum() -> str:
    """Build a short deterministic hash of key config values (flags only, no secrets)."""
    flags = "|".join(
        f"{k}={os.environ.get(k, 'false')}"
        for k in sorted(PHASE_FLAGS.keys())
    )
    return hashlib.md5(flags.encode()).hexdigest()[:8]


def _category_score(checks: list) -> float:
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)
