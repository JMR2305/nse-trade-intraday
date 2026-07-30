"""
shared_services.py — Phase 7.5
Public interface for the Research, Simulation & Innovation Lab.

READ-ONLY. ADVISORY-ONLY. Never modifies portfolio, signals, strategies,
risk parameters, AI models, or any execution engine.
"""
from __future__ import annotations
import json
import csv
import io
from typing import Any, Dict, List

from .models import is_enabled, disabled_response

# ── Upstream snapshot loaders ─────────────────────────────────────────────────

def _market_snap() -> Dict[str, Any]:
    try:
        from market_intelligence.shared_services import get_market_intelligence_snapshot
        return get_market_intelligence_snapshot()
    except Exception:
        return {}


def _event_snap() -> Dict[str, Any]:
    try:
        from event_intelligence.shared_services import get_event_intelligence_snapshot
        return get_event_intelligence_snapshot()
    except Exception:
        return {}


def _macro_snap() -> Dict[str, Any]:
    try:
        from macro_intelligence.shared_services import get_macro_intelligence_snapshot
        return get_macro_intelligence_snapshot()
    except Exception:
        return {}


def _explainable_snap() -> Dict[str, Any]:
    try:
        from explainable_ai.shared_services import get_explainable_ai_snapshot
        return get_explainable_ai_snapshot()
    except Exception:
        return {}


def _risk_snap() -> Dict[str, Any]:
    try:
        from risk_optimisation.shared_services import get_risk_optimisation_snapshot
        return get_risk_optimisation_snapshot()
    except Exception:
        return {}


def _performance_snap() -> Dict[str, Any]:
    try:
        from portfolio_performance.shared_services import get_portfolio_performance_snapshot
        return get_portfolio_performance_snapshot()
    except Exception:
        return {}


def _signals() -> List[Dict[str, Any]]:
    try:
        import signals_store
        return signals_store.load_signals() or []
    except Exception:
        return []


def _signal_snapshots() -> List[Dict[str, Any]]:
    try:
        import signals_store
        return signals_store.load_signal_snapshots() or []
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_summary() -> Dict[str, Any]:
    """Research Lab overview: KPIs, score, grade, quick summaries."""
    if not is_enabled():
        return disabled_response("get_summary")

    from .strategy_research   import build_strategy_profiles
    from .scenario_simulation import simulate_all_scenarios
    from .risk_simulation     import simulate_risk
    from .performance_benchmark import compute_benchmark
    from .innovation_workspace import get_all_experiments, get_workspace_summary
    from .research_reports    import generate_research_report
    from .models              import research_grade, trend_label

    signals  = _signals()
    market   = _market_snap()
    macro    = _macro_snap()
    risk     = _risk_snap()
    perf     = _performance_snap()
    xai      = _explainable_snap()

    strategies  = build_strategy_profiles(signals, risk)
    scenarios   = simulate_all_scenarios(signals, macro, market)
    risk_sim    = simulate_risk(signals, risk, macro)
    benchmark   = compute_benchmark(signals, risk, perf, xai)
    experiments = get_all_experiments()
    ws_summary  = get_workspace_summary(experiments)
    report      = generate_research_report(
        strategies, scenarios, risk_sim, benchmark,
        experiments, market, macro, xai
    )

    return {
        "status":             "ENABLED",
        "advisory_only":      True,
        "research_score":     report.research_score,
        "grade":              report.grade,
        "trend":              report.trend,
        "executive_summary":  report.executive_summary,
        "top_strategy":       strategies[0].to_dict() if strategies else None,
        "total_strategies":   len(strategies),
        "total_scenarios":    len(scenarios),
        "total_experiments":  ws_summary["total"],
        "complete_experiments": ws_summary["complete"],
        "total_signals":      len(signals),
        "expected_drawdown":  risk_sim.expected_drawdown,
        "benchmark_alpha":    benchmark.relative_alpha,
        "benchmark_winner":   benchmark.winner,
    }


def get_strategies() -> Dict[str, Any]:
    """Full strategy comparison profiles for all 7 strategy types."""
    if not is_enabled():
        return disabled_response("get_strategies")

    from .strategy_research import build_strategy_profiles

    signals    = _signals()
    risk       = _risk_snap()
    profiles   = build_strategy_profiles(signals, risk)

    return {
        "status":      "ENABLED",
        "advisory_only": True,
        "strategies":  [p.to_dict() for p in profiles],
        "total":       len(profiles),
        "top_strategy": profiles[0].strategy_type if profiles else None,
    }


def get_simulations() -> Dict[str, Any]:
    """All 8 scenario simulation results."""
    if not is_enabled():
        return disabled_response("get_simulations")

    from .scenario_simulation import simulate_all_scenarios

    signals   = _signals()
    macro     = _macro_snap()
    market    = _market_snap()
    scenarios = simulate_all_scenarios(signals, macro, market)

    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "scenarios":    [s.to_dict() for s in scenarios],
        "total":        len(scenarios),
        "highest_opportunity": max(scenarios, key=lambda s: s.opportunity_score).scenario_type
            if scenarios else None,
        "highest_threat": max(scenarios, key=lambda s: s.threat_score).scenario_type
            if scenarios else None,
    }


def get_replay() -> Dict[str, Any]:
    """Historical signal replay frames with summary statistics."""
    if not is_enabled():
        return disabled_response("get_replay")

    from .historical_replay import build_replay_frames, replay_summary

    snapshots = _signal_snapshots()
    frames    = build_replay_frames(snapshots, limit=50)
    summary   = replay_summary(frames)

    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "frames":       [f.to_dict() for f in frames],
        "summary":      summary,
    }


def get_benchmark() -> Dict[str, Any]:
    """Performance benchmark comparison (Research vs NIFTY vs Market vs Paper)."""
    if not is_enabled():
        return disabled_response("get_benchmark")

    from .performance_benchmark import compute_benchmark
    from .parameter_experiments import run_parameter_experiments
    from .regime_comparison     import build_regime_profiles

    signals  = _signals()
    risk     = _risk_snap()
    perf     = _performance_snap()
    xai      = _explainable_snap()

    benchmark = compute_benchmark(signals, risk, perf, xai)
    params    = run_parameter_experiments(signals)
    regimes   = build_regime_profiles(signals, risk)

    return {
        "status":        "ENABLED",
        "advisory_only": True,
        "benchmark":     benchmark.to_dict(),
        "regimes":       [r.to_dict() for r in regimes],
        "experiments":   [p.to_dict() for p in params],
        "risk_simulation": None,   # available via /summary
    }


def get_reports() -> Dict[str, Any]:
    """Full auto-generated research report."""
    if not is_enabled():
        return disabled_response("get_reports")

    from .strategy_research    import build_strategy_profiles
    from .scenario_simulation  import simulate_all_scenarios
    from .risk_simulation      import simulate_risk
    from .performance_benchmark import compute_benchmark
    from .innovation_workspace import get_all_experiments
    from .research_reports     import generate_research_report

    signals  = _signals()
    market   = _market_snap()
    macro    = _macro_snap()
    risk     = _risk_snap()
    perf     = _performance_snap()
    xai      = _explainable_snap()

    strategies  = build_strategy_profiles(signals, risk)
    scenarios   = simulate_all_scenarios(signals, macro, market)
    risk_sim    = simulate_risk(signals, risk, macro)
    benchmark   = compute_benchmark(signals, risk, perf, xai)
    experiments = get_all_experiments()
    report      = generate_research_report(
        strategies, scenarios, risk_sim, benchmark,
        experiments, market, macro, xai
    )

    return {
        "status":       "ENABLED",
        "advisory_only": True,
        "report":       report.to_dict(),
        "innovations":  [e.to_dict() for e in experiments],
    }


_SNAPSHOT_CACHE_FILE = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "_snapshot_cache.json"
)
_SNAPSHOT_TTL_SECONDS = 300   # 5 minutes — balances freshness vs. yfinance latency


def _load_snapshot_cache() -> Dict[str, Any] | None:
    """Return cached snapshot if it exists and is younger than TTL, else None."""
    import time, json as _json, os as _os
    if not _os.path.exists(_SNAPSHOT_CACHE_FILE):
        return None
    try:
        with open(_SNAPSHOT_CACHE_FILE, "r") as f:
            cached = _json.load(f)
        if time.time() - cached.get("_cached_at", 0) < _SNAPSHOT_TTL_SECONDS:
            cached.pop("_cached_at", None)
            return cached
    except Exception:
        pass
    return None


def _save_snapshot_cache(snap: Dict[str, Any]) -> None:
    """Persist snapshot to file with a timestamp key."""
    import time, json as _json
    try:
        payload = dict(snap)
        payload["_cached_at"] = time.time()
        with open(_SNAPSHOT_CACHE_FILE, "w") as f:
            _json.dump(payload, f, default=str)
    except Exception:
        pass


def get_research_lab_snapshot() -> Dict[str, Any]:
    """
    Flat KPI snapshot for cross-phase aggregation.

    Results are cached to a file for _SNAPSHOT_TTL_SECONDS so that the
    spawn-per-request Python model does not re-fetch yfinance on every call.
    First call after cache expiry is slow (~15 s); subsequent calls are <100 ms.
    """
    if not is_enabled():
        return disabled_response("get_research_lab_snapshot")

    cached = _load_snapshot_cache()
    if cached is not None:
        return cached

    summary = get_summary()
    snap = {
        "status":            "ENABLED",
        "research_score":    summary.get("research_score", 0),
        "grade":             summary.get("grade", "N/A"),
        "trend":             summary.get("trend", "STABLE"),
        "total_strategies":  summary.get("total_strategies", 0),
        "total_scenarios":   summary.get("total_scenarios", 0),
        "total_experiments": summary.get("total_experiments", 0),
        "expected_drawdown": summary.get("expected_drawdown", 0),
        "benchmark_alpha":   summary.get("benchmark_alpha", 0),
        "advisory_only":     True,
    }
    _save_snapshot_cache(snap)
    return snap


def export_csv() -> str:
    """Export strategy comparison as CSV."""
    if not is_enabled():
        return "status,message\nDISABLED,RESEARCH_LAB_ENABLED not set"

    from .strategy_research import build_strategy_profiles
    signals  = _signals()
    risk     = _risk_snap()
    profiles = build_strategy_profiles(signals, risk)

    buf = io.StringIO()
    fields = [
        "strategy_type", "label", "signal_count", "win_rate",
        "avg_confidence", "avg_drawdown", "consistency",
        "risk_score", "performance_score", "grade",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for p in profiles:
        writer.writerow(p.to_dict())
    return buf.getvalue()


def export_json() -> str:
    """Export full research snapshot as JSON."""
    if not is_enabled():
        return json.dumps(disabled_response("export_json"))

    snapshot = get_research_lab_snapshot()
    return json.dumps(snapshot, default=str, indent=2)
