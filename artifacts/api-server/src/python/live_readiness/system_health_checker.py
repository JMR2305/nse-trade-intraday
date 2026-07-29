"""
system_health_checker.py — Phase 6.5
System Health validation: API latency, module health, DB connectivity,
service availability, background task status.

Uses only stdlib — no psutil or external dependencies.
READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os, sys, time
from typing import List
from .readiness_models import ReadinessCheck, PASS, WARN, FAIL


def check_system_health() -> dict:
    """
    Run all system health checks. Returns:
      - checks: list of ReadinessCheck dicts
      - score: 0–100
      - latency_ms: measured Python call latency proxy
      - db_accessible: bool
      - modules_healthy: bool
    """
    checks: List[ReadinessCheck] = []

    # 1. Python runtime health
    checks.append(_check_python_runtime())

    # 2. Database connectivity
    db_ok, db_detail = _probe_db()
    checks.append(ReadinessCheck(
        name="db_connectivity",
        label="Database Connectivity",
        status=PASS if db_ok else WARN,
        required=False,
        detail=db_detail,
        category="SystemHealth",
    ))

    # 3. API call latency proxy (time a Python import + small computation)
    latency_ms, latency_check = _check_latency()
    checks.append(latency_check)

    # 4. Core module imports
    for mod_check in _check_core_modules():
        checks.append(mod_check)

    # 5. Phase 6.x module availability
    for phase_check in _check_phase_modules():
        checks.append(phase_check)

    # 6. Environment variables present (not values)
    checks.append(_check_env_health())

    score = _category_score(checks)

    return {
        "checks": [c.to_dict() for c in checks],
        "score": score,
        "latency_ms": round(latency_ms, 1),
        "db_accessible": db_ok,
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == PASS),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "failures": sum(1 for c in checks if c.status == FAIL),
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_python_runtime() -> ReadinessCheck:
    ver = sys.version_info
    ok = ver.major == 3 and ver.minor >= 10
    return ReadinessCheck(
        name="python_runtime",
        label="Python Runtime",
        status=PASS if ok else WARN,
        required=True,
        detail=f"Python {ver.major}.{ver.minor}.{ver.micro} — {'OK' if ok else 'Python 3.10+ recommended'}",
        category="SystemHealth",
    )


def _probe_db() -> tuple:
    """Try a lightweight DB probe — checks if portfolio_store can load."""
    try:
        t0 = time.monotonic()
        from portfolio_store import load_state
        state = load_state()
        ms = (time.monotonic() - t0) * 1000
        return True, f"Portfolio store accessible in {ms:.0f}ms"
    except Exception as e:
        short = str(e)[:120]
        return False, f"Portfolio store probe failed: {short}"


def _check_latency() -> tuple:
    """Measure internal call latency via a simple timed operation."""
    t0 = time.monotonic()
    # Simulate a lightweight computation
    _ = sum(i * i for i in range(1000))
    ms = (time.monotonic() - t0) * 1000

    if ms < 5:
        status, detail = PASS, f"Internal latency {ms:.1f}ms — excellent"
    elif ms < 20:
        status, detail = PASS, f"Internal latency {ms:.1f}ms — good"
    elif ms < 100:
        status, detail = WARN, f"Internal latency {ms:.1f}ms — acceptable"
    else:
        status, detail = WARN, f"Internal latency {ms:.1f}ms — elevated"

    check = ReadinessCheck(
        name="api_latency",
        label="Internal Processing Latency",
        status=status,
        required=False,
        detail=detail,
        category="SystemHealth",
    )
    return ms, check


def _check_core_modules() -> List[ReadinessCheck]:
    checks = []
    core = [
        ("config", "Config Module"),
        ("portfolio_store", "Portfolio Store"),
        ("paper_trading_validation.validation_collector", "Paper Trading Validation"),
    ]
    for mod, label in core:
        try:
            __import__(mod)
            checks.append(ReadinessCheck(
                name=f"module_{mod.replace('.', '_')}",
                label=label,
                status=PASS,
                required=True,
                detail=f"{label} module loaded successfully.",
                category="SystemHealth",
            ))
        except Exception as e:
            checks.append(ReadinessCheck(
                name=f"module_{mod.replace('.', '_')}",
                label=label,
                status=FAIL,
                required=True,
                detail=f"Import failed: {str(e)[:120]}",
                category="SystemHealth",
            ))
    return checks


def _check_phase_modules() -> List[ReadinessCheck]:
    checks = []
    phases = [
        ("paper_trading_validation.shared_services", "Phase 6.1 Validation"),
        ("strategy_optimisation.shared_services", "Phase 6.2 Strategy Optimisation"),
        ("ai_optimisation.shared_services", "Phase 6.3 AI Optimisation"),
        ("risk_optimisation.shared_services", "Phase 6.4 Risk Optimisation"),
    ]
    for mod, label in phases:
        try:
            __import__(mod)
            checks.append(ReadinessCheck(
                name=f"phase_{label.lower().replace(' ', '_').replace('.', '')}",
                label=label,
                status=PASS,
                required=False,
                detail=f"{label} module available.",
                category="SystemHealth",
            ))
        except Exception as e:
            checks.append(ReadinessCheck(
                name=f"phase_{label.lower().replace(' ', '_').replace('.', '')}",
                label=label,
                status=WARN,
                required=False,
                detail=f"Module unavailable: {str(e)[:80]}",
                category="SystemHealth",
            ))
    return checks


def _check_env_health() -> ReadinessCheck:
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        return ReadinessCheck(
            name="database_url_set",
            label="Database URL Configured",
            status=PASS,
            required=True,
            detail="DATABASE_URL is set.",
            category="SystemHealth",
        )
    return ReadinessCheck(
        name="database_url_set",
        label="Database URL Configured",
        status=WARN,
        required=False,
        detail="DATABASE_URL not set — using default SQLite fallback.",
        category="SystemHealth",
    )


def _category_score(checks: List[ReadinessCheck]) -> float:
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)
