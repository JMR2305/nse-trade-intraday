"""
data_quality/shared_services.py — Phase 8.3
Stable public interface for the Data Quality & Validation Framework.

All downstream phases import ONLY from here — never from sub-modules directly.

Public API:
  get_summary()            → dict   (overall score + all-domain highlights)
  get_market()             → dict   (market data validation)
  get_preopen()            → dict   (pre-open data validation)
  get_paper()              → dict   (paper trading validation)
  get_portfolio()          → dict   (portfolio validation)
  get_ai()                 → dict   (AI validation)
  get_signals()            → dict   (signal validation)
  get_config()             → dict   (configuration validation)
  get_alerts()             → dict   (all issues across domains, ranked)
  get_export_json()        → dict   (full report bundle)
  get_export_csv()         → str    (CSV of all issues)
  get_data_quality_snapshot() → dict  (flat KPI for Executive Dashboard)

READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    is_enabled, disabled_response, quality_grade,
    SEVERITY_ORDER, _now_iso,
)

_DOMAIN_WEIGHTS = {
    "market":    0.20,
    "preopen":   0.10,
    "paper":     0.15,
    "portfolio": 0.15,
    "ai":        0.15,
    "signals":   0.10,
    "config":    0.15,
}


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default if default is not None else {}


def _load_market():
    from .market import get_market_validation
    return _safe(get_market_validation, {"available": False, "score": 0, "domain": "market"})


def _load_preopen():
    from .preopen import get_preopen_validation
    return _safe(get_preopen_validation, {"available": False, "score": 0, "domain": "preopen"})


def _load_paper():
    from .paper import get_paper_validation
    return _safe(get_paper_validation, {"available": False, "score": 0, "domain": "paper"})


def _load_portfolio():
    from .portfolio import get_portfolio_validation
    return _safe(get_portfolio_validation, {"available": False, "score": 0, "domain": "portfolio"})


def _load_ai():
    from .ai_check import get_ai_validation
    return _safe(get_ai_validation, {"available": False, "score": 0, "domain": "ai"})


def _load_signals():
    from .signals import get_signal_validation
    return _safe(get_signal_validation, {"available": False, "score": 0, "domain": "signals"})


def _load_config():
    from .config_check import get_config_validation
    return _safe(get_config_validation, {"available": False, "score": 0, "domain": "config"})


# ── Score components (Completeness / Consistency / etc.) ─────────────────────

def _compute_score_components(domains: dict[str, dict]) -> dict:
    """
    Derive the 6 quality dimensions from the domain results.

    Each dimension aggregates a specific class of checks:
    - Completeness : MISSING issues absent
    - Consistency  : CRITICAL issues absent
    - Accuracy     : WARNING issues absent
    - Freshness    : STALE issues absent
    - Integrity    : DUPLICATE issues absent
    - Validity     : overall pass_rate
    """
    dims: dict[str, list[float]] = {
        "completeness": [], "consistency": [], "accuracy": [],
        "freshness": [],    "integrity": [],   "validity": [],
    }

    for d in domains.values():
        issues  = d.get("issues", [])
        checked = max(d.get("checks_run", 1), 1)
        passed  = d.get("checks_passed", 0)

        missing   = sum(1 for i in issues if i.get("severity") == "MISSING")
        critical  = sum(1 for i in issues if i.get("severity") == "CRITICAL")
        warning   = sum(1 for i in issues if i.get("severity") == "WARNING")
        stale     = sum(1 for i in issues if i.get("severity") == "STALE")
        duplicate = sum(1 for i in issues if i.get("severity") == "DUPLICATE")

        dims["completeness"].append(max(0.0, 100 - missing * 20))
        dims["consistency"].append(max(0.0, 100 - critical * 25))
        dims["accuracy"].append(max(0.0, 100 - warning * 10))
        dims["freshness"].append(max(0.0, 100 - stale * 30))
        dims["integrity"].append(max(0.0, 100 - duplicate * 15))
        dims["validity"].append(round(passed / checked * 100, 1))

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    return {k: min(100.0, avg(v)) for k, v in dims.items()}


def _weighted_score(domains: dict[str, dict]) -> float:
    total = 0.0
    for name, weight in _DOMAIN_WEIGHTS.items():
        score = float(domains.get(name, {}).get("score", 0))
        total += score * weight
    return round(total, 1)


# ── Public API ────────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """Overall Data Quality Score + all-domain highlights."""
    if not is_enabled():
        return disabled_response()

    market    = _load_market()
    preopen   = _load_preopen()
    paper     = _load_paper()
    portfolio = _load_portfolio()
    ai        = _load_ai()
    signals   = _load_signals()
    config    = _load_config()

    domains = {
        "market": market, "preopen": preopen, "paper": paper,
        "portfolio": portfolio, "ai": ai, "signals": signals, "config": config,
    }

    score      = _weighted_score(domains)
    grade      = quality_grade(score)
    components = _compute_score_components(domains)

    total_issues   = sum(len(d.get("issues", [])) for d in domains.values())
    critical_count = sum(d.get("critical_count", 0) for d in domains.values())
    warning_count  = sum(d.get("warning_count",  0) for d in domains.values())

    domain_summary = [
        {
            "domain":        name,
            "score":         d.get("score", 0),
            "grade":         d.get("grade", "D"),
            "checks_run":    d.get("checks_run", 0),
            "checks_passed": d.get("checks_passed", 0),
            "checks_failed": d.get("checks_failed", 0),
            "critical":      d.get("critical_count", 0),
            "warnings":      d.get("warning_count", 0),
        }
        for name, d in domains.items()
    ]

    result = {
        "status":          "ENABLED",
        "available":       True,
        "advisory_only":   True,
        "generated_at":    _now_iso(),
        "quality_score":   score,
        "grade":           grade,
        "score_components": components,
        "total_issues":    total_issues,
        "critical_count":  critical_count,
        "warning_count":   warning_count,
        "domains":         domain_summary,
    }

    # Persist run history — non-blocking; never raises to the caller.
    try:
        from .history_store import persist_run as _persist
        _persist(result)
    except Exception:
        pass

    return result


def get_market() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_market()


def get_preopen() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_preopen()


def get_paper() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_paper()


def get_portfolio() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_portfolio()


def get_ai() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_ai()


def get_signals() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_signals()


def get_config() -> dict:
    if not is_enabled(): return disabled_response()
    return _load_config()


def get_alerts() -> dict:
    """Aggregate all issues across domains, sorted by severity then domain."""
    if not is_enabled(): return disabled_response()

    loaders = [
        ("market", _load_market), ("preopen", _load_preopen),
        ("paper", _load_paper),   ("portfolio", _load_portfolio),
        ("ai", _load_ai),         ("signals", _load_signals),
        ("config", _load_config),
    ]

    all_alerts: list[dict] = []
    for name, loader in loaders:
        result = loader()
        for issue in result.get("issues", []):
            all_alerts.append({**issue, "domain": name})

    all_alerts.sort(key=lambda i: (
        SEVERITY_ORDER.get(i.get("severity", "INFO"), 99),
        i.get("domain", ""),
    ))

    critical = [a for a in all_alerts if a.get("severity") == "CRITICAL"]
    warnings = [a for a in all_alerts if a.get("severity") == "WARNING"]
    info     = [a for a in all_alerts if a.get("severity") == "INFO"]
    dupes    = [a for a in all_alerts if a.get("severity") == "DUPLICATE"]
    missing  = [a for a in all_alerts if a.get("severity") == "MISSING"]
    stale    = [a for a in all_alerts if a.get("severity") == "STALE"]

    return {
        "status":          "ENABLED",
        "available":       True,
        "advisory_only":   True,
        "generated_at":    _now_iso(),
        "total":           len(all_alerts),
        "critical":        critical,
        "warnings":        warnings,
        "info":            info,
        "duplicates":      dupes,
        "missing":         missing,
        "stale":           stale,
        "total_critical":  len(critical),
        "total_warnings":  len(warnings),
    }


def get_export_json() -> dict:
    """Full validation report bundle."""
    if not is_enabled(): return disabled_response()
    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "generated_at": _now_iso(),
        "summary":      get_summary(),
        "market":       _load_market(),
        "preopen":      _load_preopen(),
        "paper":        _load_paper(),
        "portfolio":    _load_portfolio(),
        "ai":           _load_ai(),
        "signals":      _load_signals(),
        "config":       _load_config(),
    }


def get_export_csv() -> str:
    """CSV of all issues across all domains."""
    if not is_enabled():
        return "status,message\nDISABLED,Set DATA_QUALITY_ENABLED=true"

    report = get_export_json()
    rows = ["domain,severity,check,field,message,symbol,value"]

    for domain in ("market", "preopen", "paper", "portfolio", "ai", "signals", "config"):
        for issue in report.get(domain, {}).get("issues", []):
            def _esc(v):
                s = str(v).replace('"', '""')
                return f'"{s}"' if (',' in s or '"' in s or '\n' in s) else s
            rows.append(",".join([
                domain,
                _esc(issue.get("severity", "")),
                _esc(issue.get("check", "")),
                _esc(issue.get("field", "")),
                _esc(issue.get("message", "")),
                _esc(issue.get("symbol", "")),
                _esc(issue.get("value", "")),
            ]))

    return "\n".join(rows)


def get_history(limit: int = 30) -> dict:
    """Return last N validation runs for trend analysis."""
    if not is_enabled():
        return disabled_response()

    import random
    from .history_store import get_history as _get_history, prune_old_runs

    # Lazy pruning — runs at ~1 % call rate to avoid DB pressure.
    if random.random() < 0.01:
        _safe(prune_old_runs)

    runs = _safe(lambda: _get_history(limit=limit), [])
    return {
        "status":       "ENABLED",
        "available":    True,
        "advisory_only": True,
        "total_runs":   len(runs),
        "runs":         runs,
        "generated_at": _now_iso(),
    }


def get_data_quality_snapshot() -> dict:
    """Flat KPI dict for Executive Dashboard integration (Phase 8.5+)."""
    if not is_enabled():
        return {"available": False, "advisory_only": True, "quality_score": 0}

    summary = get_summary()
    return {
        "available":      True,
        "advisory_only":  True,
        "quality_score":  summary.get("quality_score", 0),
        "grade":          summary.get("grade", "D"),
        "critical_count": summary.get("critical_count", 0),
        "warning_count":  summary.get("warning_count", 0),
        "total_issues":   summary.get("total_issues", 0),
        "generated_at":   summary.get("generated_at", _now_iso()),
    }
