#!/usr/bin/env python3
"""
check_startup_deps.py — Python dependency validator for ApexQuant AI API server.

Verifies that all required Python packages are importable and that
essential environment variables are present. Called at API server startup
via the health/ready route or as a standalone preflight check.

Output: JSON on stdout.
  { "success": true,  "packages": [...], "env": [...] }
  { "success": false, "missing_packages": [...], "missing_env": [...], "fix": "..." }

Exit code 0 = all OK, exit code 1 = one or more deps missing.

Usage:
  python check_startup_deps.py
  uv run python check_startup_deps.py
"""

from __future__ import annotations

import importlib
import json
import os
import sys

# ---------------------------------------------------------------------------
# Required Python packages
# Each entry: (import_name, human_label, criticality)
#   criticality: "CRITICAL" | "HIGH" | "MEDIUM"
#   CRITICAL = without this, the API server cannot start at all
#   HIGH     = without this, market data / scans fail entirely
#   MEDIUM   = without this, a specific feature is degraded
# ---------------------------------------------------------------------------
REQUIRED_PACKAGES: list[tuple[str, str, str]] = [
    ("yfinance",    "yfinance>=1.5.1 (NSE market data via Yahoo Finance)", "HIGH"),
    ("pandas",      "pandas>=3.0 (DataFrame manipulation)",               "HIGH"),
    ("numpy",       "numpy>=2.4 (numerical calculations)",                 "HIGH"),
    ("sqlalchemy",  "sqlalchemy>=2.0 (async ORM for PostgreSQL)",          "CRITICAL"),
    ("asyncpg",     "asyncpg>=0.29 (PostgreSQL async driver)",             "CRITICAL"),
    ("psycopg2",    "psycopg2-binary>=2.9 (sync PostgreSQL driver)",       "HIGH"),
    ("kiteconnect", "kiteconnect>=5.2 (Zerodha Kite broker client)",       "MEDIUM"),
    ("reportlab",   "reportlab>=4.0 (PDF report generation)",              "MEDIUM"),
    ("openpyxl",    "openpyxl>=3.1 (Excel export)",                        "MEDIUM"),
]

# ---------------------------------------------------------------------------
# Required environment variables
# Each entry: (var_name, description, required_in)
#   required_in: "production" | "always"
# ---------------------------------------------------------------------------
REQUIRED_ENV_VARS: list[tuple[str, str, str]] = [
    # "always"     = must be set in every environment (dev + prod)
    # "production" = only required in NODE_ENV=production
    # "runtime"    = injected at process start by the platform (not a user secret)
    ("DATABASE_URL",      "PostgreSQL connection string",              "always"),
    ("SESSION_SECRET",    "Express session signing secret",            "always"),
    ("ZERODHA_API_KEY",   "Zerodha Kite API key (live data session)",  "production"),
    # PORT is injected by the Replit workflow runtime — do not configure manually.
]

# ---------------------------------------------------------------------------


def check_packages() -> tuple[list[str], list[str]]:
    """Returns (present, missing) package labels."""
    present: list[str] = []
    missing: list[str] = []
    for mod, label, _crit in REQUIRED_PACKAGES:
        try:
            importlib.import_module(mod)
            present.append(label)
        except ImportError:
            missing.append(label)
    return present, missing


def check_env_vars() -> tuple[list[str], list[str]]:
    """Returns (present, missing) env var names."""
    is_prod = os.environ.get("NODE_ENV", "") == "production"
    present: list[str] = []
    missing: list[str] = []
    for var, desc, scope in REQUIRED_ENV_VARS:
        needed = scope == "always" or (scope == "production" and is_prod)
        if not needed:
            continue
        if os.environ.get(var):
            present.append(f"{var} ({desc})")
        else:
            missing.append(f"{var} — {desc}")
    return present, missing


def main() -> None:
    present_pkg, missing_pkg = check_packages()
    present_env, missing_env = check_env_vars()

    all_ok = not missing_pkg and not missing_env

    result: dict = {
        "success": all_ok,
        "packages_ok":  present_pkg,
        "env_ok":       present_env,
    }

    if missing_pkg:
        result["missing_packages"] = missing_pkg
        result["fix_packages"] = (
            "Run `uv sync` in the workspace root to install missing Python packages. "
            "All dependencies are declared in /pyproject.toml."
        )

    if missing_env:
        result["missing_env"] = missing_env
        result["fix_env"] = (
            "Set the listed environment variables via Replit Secrets "
            "(Tools → Secrets in the Replit workspace). "
            "Never commit secret values to source control."
        )

    print(json.dumps(result, indent=2))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
