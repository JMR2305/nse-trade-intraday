"""
data_quality/config_check.py — Phase 8.3
Configuration validation: required environment variables, feature flags,
provider selection, API key presence (values never logged), and scheduler config.

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

import os

from .models import Issue, domain_result

# Keys that must be present (but whose values we never expose)
_REQUIRED_KEYS: list[tuple[str, str]] = [
    ("DATABASE_URL",          "Database connection"),
    ("SESSION_SECRET",        "Session signing"),
]

# Keys that are important but optional
_RECOMMENDED_KEYS: list[tuple[str, str]] = [
    ("ZERODHA_API_KEY",       "Live broker (Zerodha Kite)"),
    ("ZERODHA_API_SECRET",    "Live broker (Zerodha Kite)"),
    ("RESEND_API_KEY",        "Email alerts (Resend)"),
]

# Feature flags and their human labels
_FEATURE_FLAGS: list[tuple[str, str]] = [
    ("PAPER_ANALYTICS_ENABLED",     "Paper Analytics (Phase 8.2)"),
    ("DATA_QUALITY_ENABLED",        "Data Quality (Phase 8.3)"),
    ("STRATEGY_INTELLIGENCE_ENABLED","Strategy Intelligence (Phase 5D.3)"),
    ("AI_PERFORMANCE_ENABLED",      "AI Performance (Phase 5D.4)"),
    ("RESEARCH_LAB_ENABLED",        "Research Lab (Phase 7.5)"),
    ("RISK_OPTIMISATION_ENABLED",   "Risk Optimisation (Phase 6.4)"),
    ("AUTO_PAPER_ENABLED",          "Auto Paper Trading (Phase 20)"),
    ("LIVE_SCAN_ENABLED",           "Live Scan (Phase 7)"),
]

# Valid provider values for MARKET_DATA_PROVIDER
_VALID_PROVIDERS = {"nse_official", "kite", "yahoo", "auto"}


def validate_config() -> dict:
    issues:       list[Issue] = []
    total_checks: int         = 0
    total_passed: int         = 0

    def chk(ok: bool, sev: str, check: str, fld: str, msg: str, val=None):
        nonlocal total_checks, total_passed
        total_checks += 1
        if ok:
            total_passed += 1
        else:
            issues.append(Issue(sev, check, fld, msg, value=val))

    # Required environment variables
    for key, label in _REQUIRED_KEYS:
        val = os.environ.get(key)
        chk(bool(val), "CRITICAL", "REQUIRED_ENV_MISSING", key,
            f"{label}: {key} is not set")

    # Recommended environment variables
    for key, label in _RECOMMENDED_KEYS:
        val = os.environ.get(key)
        chk(bool(val), "WARNING", "RECOMMENDED_ENV_MISSING", key,
            f"{label}: {key} is not set (features requiring it will be disabled)")

    # Feature flag format validation (should be "true"/"false"/"1"/"0")
    flag_states: dict[str, bool] = {}
    for flag, label in _FEATURE_FLAGS:
        raw = os.environ.get(flag, "false")
        enabled = raw.lower() in ("1", "true", "yes")
        flag_states[flag] = enabled
        chk(raw.lower() in ("1", "true", "yes", "0", "false", "no", ""),
            "WARNING", "FLAG_FORMAT", flag,
            f"{flag}={raw!r} — use 'true'/'false' for clarity", raw)

    # Provider selection
    provider = os.environ.get("MARKET_DATA_PROVIDER", "auto").lower().strip()
    chk(provider in _VALID_PROVIDERS,
        "WARNING", "INVALID_PROVIDER", "MARKET_DATA_PROVIDER",
        f"MARKET_DATA_PROVIDER={provider!r} — valid: {_VALID_PROVIDERS}", provider)

    # DATABASE_URL points to postgres (not sqlite)
    db_url = os.environ.get("DATABASE_URL", "")
    chk("postgresql" in db_url or "postgres" in db_url or not db_url,
        "WARNING", "DB_DRIVER", "DATABASE_URL",
        "DATABASE_URL does not appear to be a PostgreSQL URL")

    # Python version compatibility (>= 3.10)
    import sys
    major, minor = sys.version_info[:2]
    chk((major, minor) >= (3, 10),
        "WARNING", "PYTHON_VERSION", "python",
        f"Python {major}.{minor} — recommended ≥ 3.10", f"{major}.{minor}")

    return domain_result(
        "config", total_checks, total_passed, issues,
        extra={
            "flags_checked": len(_FEATURE_FLAGS),
            "flag_states":   {f: ("ENABLED" if v else "DISABLED")
                              for f, v in flag_states.items()},
            "provider":      provider,
        },
    )


# ── Public entry point ────────────────────────────────────────────────────────

def get_config_validation() -> dict:
    return validate_config()
