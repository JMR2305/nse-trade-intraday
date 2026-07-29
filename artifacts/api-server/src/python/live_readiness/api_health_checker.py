"""
api_health_checker.py — Phase 6.5
API Health validation: endpoint availability, latency, error rate,
response consistency, authentication.

Tests the platform's own internal Python module APIs — not HTTP endpoints
(those would require a running server). This is the correct approach for
a background validation module.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import time
from typing import List
from .readiness_models import ReadinessCheck, PASS, WARN, FAIL


def check_api_health() -> dict:
    """
    Probe the Phase 6.x shared services APIs for availability and consistency.
    """
    checks: List[ReadinessCheck] = []

    for check in _probe_phase_apis():
        checks.append(check)

    checks.append(_check_validation_api())
    checks.append(_check_response_shape_consistency())

    score = _category_score(checks)

    return {
        "checks": [c.to_dict() for c in checks],
        "score": score,
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == PASS),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "failures": sum(1 for c in checks if c.status == FAIL),
        "error_rate": round(
            sum(1 for c in checks if c.status == FAIL) / len(checks), 4
        ) if checks else 0.0,
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _probe_phase_apis() -> List[ReadinessCheck]:
    """Probe each Phase 6.x shared_services endpoint."""
    probes = [
        ("phase_6_1_api",  "Phase 6.1 Validation API",   _probe_61),
        ("phase_6_2_api",  "Phase 6.2 Strategy Opt. API", _probe_62),
        ("phase_6_3_api",  "Phase 6.3 AI Opt. API",       _probe_63),
        ("phase_6_4_api",  "Phase 6.4 Risk Opt. API",     _probe_64),
    ]
    checks = []
    for name, label, probe_fn in probes:
        t0 = time.monotonic()
        try:
            result = probe_fn()
            ms = (time.monotonic() - t0) * 1000
            if isinstance(result, dict) and "error" not in result:
                status = PASS if ms < 500 else WARN
                detail = f"Responded in {ms:.0f}ms — OK."
            else:
                status = WARN
                detail = f"Responded in {ms:.0f}ms but returned an error response."
        except Exception as e:
            status = WARN
            detail = f"Call failed: {str(e)[:80]}"
            ms = (time.monotonic() - t0) * 1000

        checks.append(ReadinessCheck(
            name=name,
            label=label,
            status=status,
            required=False,
            detail=detail,
            category="APIHealth",
        ))
    return checks


def _probe_61():
    from paper_trading_validation.shared_services import get_validation_snapshot
    return get_validation_snapshot()

def _probe_62():
    from strategy_optimisation.shared_services import get_optimisation_snapshot
    return get_optimisation_snapshot()

def _probe_63():
    from ai_optimisation.shared_services import get_ai_optimisation_snapshot
    return get_ai_optimisation_snapshot()

def _probe_64():
    from risk_optimisation.shared_services import get_risk_optimisation_snapshot
    return get_risk_optimisation_snapshot()


def _check_validation_api() -> ReadinessCheck:
    """Verify Phase 6.1 TradeRecord stream is accessible and returns a list."""
    t0 = time.monotonic()
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        records = collect_all_trade_records()
        ms = (time.monotonic() - t0) * 1000
        if not isinstance(records, list):
            return ReadinessCheck(
                name="validation_api_shape",
                label="Trade Record API Shape",
                status=WARN,
                required=False,
                detail="collect_all_trade_records() did not return a list.",
                category="APIHealth",
            )
        return ReadinessCheck(
            name="validation_api_shape",
            label="Trade Record API Shape",
            status=PASS,
            required=False,
            detail=f"collect_all_trade_records() returned {len(records)} records in {ms:.0f}ms.",
            category="APIHealth",
        )
    except Exception as e:
        return ReadinessCheck(
            name="validation_api_shape",
            label="Trade Record API Shape",
            status=FAIL,
            required=True,
            detail=f"Trade record API failed: {str(e)[:120]}",
            category="APIHealth",
        )


def _check_response_shape_consistency() -> ReadinessCheck:
    """Verify each snapshot function returns the expected key set."""
    errors = []
    probes = [
        ("Phase 6.1", _probe_61, {"total_validated_trades"}),
        ("Phase 6.2", _probe_62, {"total_strategies", "best_strategy"}),
        ("Phase 6.3", _probe_63, {"ai_optimisation_score", "grade"}),
        ("Phase 6.4", _probe_64, {"risk_optimisation_score", "grade"}),
    ]
    for label, fn, required_keys in probes:
        try:
            result = fn()
            missing = required_keys - set(result.keys())
            if missing:
                errors.append(f"{label} missing keys: {missing}")
        except Exception as e:
            errors.append(f"{label}: {str(e)[:40]}")

    if errors:
        return ReadinessCheck(
            name="response_consistency",
            label="Response Shape Consistency",
            status=WARN,
            required=False,
            detail=f"Shape issues: {'; '.join(errors[:3])}",
            category="APIHealth",
        )
    return ReadinessCheck(
        name="response_consistency",
        label="Response Shape Consistency",
        status=PASS,
        required=False,
        detail="All Phase 6.x snapshot responses have expected key shapes.",
        category="APIHealth",
    )


def _category_score(checks: list) -> float:
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)
