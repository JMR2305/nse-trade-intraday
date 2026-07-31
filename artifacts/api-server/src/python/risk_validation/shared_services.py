"""
risk_validation/shared_services.py — Phase 8.4
Public API for the Advanced Risk Validation Framework.

Aggregates all domain validators into a composite risk validation score.
Generates alerts and export bundles.

Weights:
  Portfolio   30 %
  Sector      15 %
  Correlation 10 %
  Stress      10 %
  Tail Risk   10 %
  Execution   10 %
  Market Risk 10 %
  Drift        5 %

READ-ONLY · ADVISORY-ONLY — never modifies any position, strategy or order.
"""
from __future__ import annotations

import csv
import io
import json

from .models import (
    is_enabled, disabled_response, risk_grade, risk_trend, _now_iso,
)

# ── Domain weights (must sum to 1.0) ─────────────────────────────────────────

_WEIGHTS: dict[str, float] = {
    "portfolio":   0.30,
    "sector":      0.15,
    "correlation": 0.10,
    "stress":      0.10,
    "tail_risk":   0.10,
    "execution":   0.10,
    "market_risk": 0.10,
    "drift":       0.05,
}

# ── Safe loader ───────────────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default if default is not None else {}


def _now_iso_local() -> str:
    return _now_iso()


# ── Domain loaders ────────────────────────────────────────────────────────────

def _load_portfolio():
    from .portfolio import get_portfolio_validation
    return _safe(get_portfolio_validation, {"score": 0, "available": False})

def _load_sector():
    from .sector import get_sector_validation
    return _safe(get_sector_validation, {"score": 0, "available": False})

def _load_correlation():
    from .correlation import get_correlation_validation
    return _safe(get_correlation_validation, {"score": 0, "available": False})

def _load_stress():
    from .stress import get_stress_validation
    return _safe(get_stress_validation, {"score": 0, "available": False})

def _load_tail_risk():
    from .tail_risk import get_tail_risk_validation
    return _safe(get_tail_risk_validation, {"score": 0, "available": False})

def _load_execution():
    from .execution import get_execution_validation
    return _safe(get_execution_validation, {"score": 0, "available": False})

def _load_market_risk():
    from .market_risk import get_market_risk_validation
    return _safe(get_market_risk_validation, {"score": 0, "available": False})

def _load_drift():
    from .drift import get_drift_validation
    return _safe(get_drift_validation, {"score": 0, "available": False})


# ── Composite score ───────────────────────────────────────────────────────────

def _weighted_score(domains: dict[str, dict]) -> float:
    """Compute weighted average across all domains, skipping unavailable ones."""
    total_w = score_sum = 0.0
    for name, weight in _WEIGHTS.items():
        d = domains.get(name, {})
        if d.get("available", True):
            score_sum += d.get("score", 0) * weight
            total_w   += weight
    if total_w == 0:
        return 0.0
    return round(score_sum / total_w, 1)


# ── Alert aggregation ─────────────────────────────────────────────────────────

def _aggregate_alerts(domains: dict[str, dict]) -> dict:
    critical: list[dict] = []
    warnings: list[dict] = []
    info:     list[dict] = []

    for name, d in domains.items():
        for issue in d.get("issues", []):
            item = dict(issue, domain=name)
            sev  = issue.get("severity", "")
            if sev == "CRITICAL": critical.append(item)
            elif sev == "WARNING": warnings.append(item)
            else:                  info.append(item)

    return {
        "critical":       critical,
        "warnings":       warnings,
        "info":           info,
        "total_critical": len(critical),
        "total_warnings": len(warnings),
        "total_info":     len(info),
        "total":          len(critical) + len(warnings) + len(info),
    }


# ── Domain summary row ────────────────────────────────────────────────────────

def _domain_summary_row(name: str, d: dict) -> dict:
    return {
        "domain":         name,
        "score":          d.get("score",         0),
        "grade":          d.get("grade",         "D"),
        "checks_run":     d.get("checks_run",    0),
        "checks_passed":  d.get("checks_passed", 0),
        "checks_failed":  d.get("checks_failed", 0),
        "critical":       d.get("critical_count", 0),
        "warnings":       d.get("warning_count",  0),
        "available":      d.get("available",      False),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_summary() -> dict:
    if not is_enabled(): return disabled_response()

    domains = {
        "portfolio":   _load_portfolio(),
        "sector":      _load_sector(),
        "correlation": _load_correlation(),
        "stress":      _load_stress(),
        "tail_risk":   _load_tail_risk(),
        "execution":   _load_execution(),
        "market_risk": _load_market_risk(),
        "drift":       _load_drift(),
    }

    score      = _weighted_score(domains)
    grade      = risk_grade(score)
    alerts     = _aggregate_alerts(domains)
    total_issues   = alerts["total"]
    critical_count = alerts["total_critical"]
    warning_count  = alerts["total_warnings"]

    return {
        "status":          "ENABLED",
        "available":       True,
        "advisory_only":   True,
        "generated_at":    _now_iso_local(),
        "risk_score":      score,
        "grade":           grade,
        "trend":           "Stable",   # single-point; drift module flags changes
        "total_issues":    total_issues,
        "critical_count":  critical_count,
        "warning_count":   warning_count,
        "domains":         [_domain_summary_row(k, v) for k, v in domains.items()],
        "weights":         _WEIGHTS,
        "alerts":          alerts,
    }


def get_portfolio_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_portfolio()


def get_sector_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_sector()


def get_correlation_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_correlation()


def get_stress_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_stress()


def get_tail_risk_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_tail_risk()


def get_execution_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_execution()


def get_market_risk_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_market_risk()


def get_drift_data() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_drift()


def get_alerts_data() -> dict:
    if not is_enabled(): return disabled_response()
    domains = {
        "portfolio":   _load_portfolio(),
        "sector":      _load_sector(),
        "correlation": _load_correlation(),
        "stress":      _load_stress(),
        "tail_risk":   _load_tail_risk(),
        "execution":   _load_execution(),
        "market_risk": _load_market_risk(),
        "drift":       _load_drift(),
    }
    agg = _aggregate_alerts(domains)
    return {
        "status":       "ENABLED",
        "available":    True,
        "advisory_only": True,
        "generated_at": _now_iso_local(),
        **agg,
    }


def get_export_json() -> dict:
    if not is_enabled(): return disabled_response()
    domains = {
        "portfolio":   _load_portfolio(),
        "sector":      _load_sector(),
        "correlation": _load_correlation(),
        "stress":      _load_stress(),
        "tail_risk":   _load_tail_risk(),
        "execution":   _load_execution(),
        "market_risk": _load_market_risk(),
        "drift":       _load_drift(),
    }
    score = _weighted_score(domains)
    return {
        "status":        "ENABLED",
        "advisory_only": True,
        "generated_at":  _now_iso_local(),
        "risk_score":    score,
        "grade":         risk_grade(score),
        "domains":       domains,
        "alerts":        _aggregate_alerts(domains),
    }


def get_export_csv() -> str:
    data = get_export_json()
    if data.get("status") == "DISABLED":
        return ""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["domain", "score", "grade", "critical", "warnings",
                     "checks_run", "checks_passed"])
    for name, d in data.get("domains", {}).items():
        writer.writerow([
            name,
            d.get("score", 0), d.get("grade", ""),
            d.get("critical_count", 0), d.get("warning_count", 0),
            d.get("checks_run", 0), d.get("checks_passed", 0),
        ])
    return buf.getvalue()


def get_risk_validation_snapshot() -> dict:
    """Consolidated read for downstream phase integrations."""
    if not is_enabled():
        return {"status": "DISABLED", "advisory_only": True}
    domains = {
        "portfolio":   _load_portfolio(),
        "sector":      _load_sector(),
        "correlation": _load_correlation(),
        "stress":      _load_stress(),
        "tail_risk":   _load_tail_risk(),
        "execution":   _load_execution(),
        "market_risk": _load_market_risk(),
        "drift":       _load_drift(),
    }
    score = _weighted_score(domains)
    return {
        "status":        "ENABLED",
        "advisory_only": True,
        "generated_at":  _now_iso_local(),
        "risk_score":    score,
        "grade":         risk_grade(score),
        "domains":       {k: _domain_summary_row(k, v) for k, v in domains.items()},
    }
