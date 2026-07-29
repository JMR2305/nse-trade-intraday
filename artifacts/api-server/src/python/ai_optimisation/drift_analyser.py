"""
drift_analyser.py — Phase 6.3
Monitor model drift across 6 dimensions:
Prediction, Confidence, Strategy, Market Regime, Sector, Performance.

Compares the most-recent 20 trades (or half the dataset, whichever is larger)
to the full historical baseline.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from collections import Counter
from typing import List
from .optimisation_models import DriftMetric


_RECENT_N = 20


def analyse_drift(records: list) -> dict:
    if not records:
        return {
            "total_drift_dimensions": 6,
            "metrics": [],
            "overall_drift_severity": "NONE",
            "drift_score": 0.0,
            "advisory_only": True,
        }

    n_recent = max(_RECENT_N, len(records) // 3)
    sorted_recs = sorted(records, key=lambda r: r.timestamp)
    if len(sorted_recs) <= n_recent:
        # Not enough history to split — return stable
        return {
            "total_drift_dimensions": 6,
            "metrics": _stable_metrics(),
            "overall_drift_severity": "LOW",
            "drift_score": 0.0,
            "advisory_only": True,
        }

    baseline = sorted_recs[:-n_recent]
    recent   = sorted_recs[-n_recent:]

    metrics = [
        _prediction_drift(baseline, recent),
        _confidence_drift(baseline, recent),
        _strategy_drift(baseline, recent),
        _regime_drift(baseline, recent),
        _sector_drift(baseline, recent),
        _performance_drift(baseline, recent),
    ]

    high_count   = sum(1 for m in metrics if m.severity == "HIGH")
    medium_count = sum(1 for m in metrics if m.severity == "MEDIUM")
    if high_count >= 2:
        overall = "HIGH"
    elif high_count == 1 or medium_count >= 2:
        overall = "MEDIUM"
    elif medium_count == 1:
        overall = "LOW"
    else:
        overall = "STABLE"

    drift_score = round(
        sum(0.5 if m.severity == "MEDIUM" else (1.0 if m.severity == "HIGH" else 0.0)
            for m in metrics) / 6.0, 4
    )

    return {
        "total_drift_dimensions": 6,
        "metrics": [m.to_dict() for m in metrics],
        "overall_drift_severity": overall,
        "drift_score": drift_score,
        "advisory_only": True,
    }


def _avg(lst: list) -> float:
    return sum(lst) / len(lst) if lst else 0.0


def _severity(drift: float, low: float = 0.05, high: float = 0.15) -> str:
    d = abs(drift)
    if d >= high:
        return "HIGH"
    if d >= low:
        return "MEDIUM"
    return "LOW"


def _prediction_drift(baseline: list, recent: list) -> DriftMetric:
    base_acc = _avg([1.0 if (r.pnl or 0) > 0 else 0.0 for r in baseline])
    rec_acc  = _avg([1.0 if (r.pnl or 0) > 0 else 0.0 for r in recent])
    drift    = rec_acc - base_acc
    sev      = _severity(drift)
    advisory = (
        "Prediction accuracy is improving." if drift > 0.05
        else "Significant drop in prediction accuracy — review signal quality."
        if drift < -0.10 else "Prediction accuracy is stable."
    )
    return DriftMetric("Prediction", base_acc, rec_acc, drift, sev, advisory)


def _confidence_drift(baseline: list, recent: list) -> DriftMetric:
    base_conf = _avg([r.ai_confidence or 0.0 for r in baseline])
    rec_conf  = _avg([r.ai_confidence or 0.0 for r in recent])
    drift     = rec_conf - base_conf
    sev       = _severity(drift, low=0.03, high=0.10)
    advisory  = (
        "AI confidence is rising — monitor calibration."
        if drift > 0.05 else
        "AI confidence has dropped — model may be more cautious."
        if drift < -0.05 else "Confidence level is stable."
    )
    return DriftMetric("Confidence", base_conf, rec_conf, drift, sev, advisory)


def _strategy_drift(baseline: list, recent: list) -> DriftMetric:
    """Measures shift in the dominant strategy (by trade count)."""
    def top_share(recs: list) -> float:
        if not recs:
            return 0.0
        c = Counter(r.strategy for r in recs)
        return c.most_common(1)[0][1] / len(recs)

    base_share = top_share(baseline)
    rec_share  = top_share(recent)
    drift      = rec_share - base_share
    sev        = _severity(drift, low=0.10, high=0.25)
    advisory   = (
        "Strategy concentration has increased recently — review diversification."
        if drift > 0.15 else
        "Strategy mix has shifted significantly." if abs(drift) > 0.10
        else "Strategy distribution is stable."
    )
    return DriftMetric("Strategy", base_share, rec_share, drift, sev, advisory)


def _regime_drift(baseline: list, recent: list) -> DriftMetric:
    def top_share(recs: list) -> float:
        if not recs:
            return 0.0
        c = Counter(r.market_regime for r in recs)
        return c.most_common(1)[0][1] / len(recs)

    base_share = top_share(baseline)
    rec_share  = top_share(recent)
    drift      = rec_share - base_share
    sev        = _severity(drift, low=0.10, high=0.25)
    advisory   = (
        "Market regime composition has shifted — verify strategy–regime alignment."
        if abs(drift) > 0.15 else "Regime distribution is stable."
    )
    return DriftMetric("Market Regime", base_share, rec_share, drift, sev, advisory)


def _sector_drift(baseline: list, recent: list) -> DriftMetric:
    def top_share(recs: list) -> float:
        if not recs:
            return 0.0
        c = Counter(r.sector for r in recs)
        return c.most_common(1)[0][1] / len(recs)

    base_share = top_share(baseline)
    rec_share  = top_share(recent)
    drift      = rec_share - base_share
    sev        = _severity(drift, low=0.10, high=0.25)
    advisory   = (
        "Sector concentration has changed — check sector performance alignment."
        if abs(drift) > 0.15 else "Sector distribution is stable."
    )
    return DriftMetric("Sector", base_share, rec_share, drift, sev, advisory)


def _performance_drift(baseline: list, recent: list) -> DriftMetric:
    base_ret = _avg([r.pnl_pct or 0.0 for r in baseline])
    rec_ret  = _avg([r.pnl_pct or 0.0 for r in recent])
    drift    = rec_ret - base_ret
    sev      = _severity(drift, low=0.5, high=1.5)
    advisory = (
        "Recent returns are improving." if drift > 0.5
        else "Recent returns have declined — review strategy parameters."
        if drift < -1.0 else "Return performance is stable."
    )
    return DriftMetric("Performance", base_ret, rec_ret, drift, sev, advisory)


def _stable_metrics() -> list:
    dims = ["Prediction", "Confidence", "Strategy", "Market Regime", "Sector", "Performance"]
    return [DriftMetric(d, 0.0, 0.0, 0.0, "LOW", "Insufficient history for drift analysis.").to_dict()
            for d in dims]
