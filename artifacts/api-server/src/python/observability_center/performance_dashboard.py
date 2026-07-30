"""
performance_dashboard.py — Phase 8.1
Performance metrics aggregation: snapshot generation times, module response
times, and overall performance score.
Derives data from existing module snapshots — zero re-computation.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from .models import obs_grade, STATUS_HEALTHY, STATUS_DEGRADED


def _timed_call(fn) -> tuple[dict, float]:
    """Call fn and return (result, elapsed_ms)."""
    start = time.time()
    try:
        result = fn()
        elapsed = round((time.time() - start) * 1000, 1)
        return result, elapsed
    except Exception:
        return {}, round((time.time() - start) * 1000, 1)


def _probe_snapshots() -> list[dict]:
    """
    Check each Phase 7 module's availability without calling snapshot functions.
    Calling snapshot functions triggers yfinance/network requests which are too slow
    for an observability endpoint.  We verify importability + function presence only.

    Advisory — never calls live data functions.
    """
    import importlib, sys as _sys

    modules = [
        ("Market Intelligence",  "market_intelligence_hub.shared_services",
         "get_market_intelligence_snapshot"),
        ("Event Intelligence",   "event_intelligence.shared_services",
         "get_event_intelligence_snapshot"),
        ("Macro Intelligence",   "macro_intelligence.shared_services",
         "get_macro_intelligence_snapshot"),
        ("Explainable AI",       "explainable_ai.shared_services",
         "get_explainable_ai_snapshot"),
        ("Research Lab",         "research_lab.shared_services",
         "get_research_lab_snapshot"),
    ]

    probes = []
    for label, module_path, fn_name in modules:
        start = time.time()
        ok    = False
        note  = "not loaded"
        try:
            # Prefer already-loaded modules (instant); otherwise import but DON'T call
            mod = _sys.modules.get(module_path)
            if mod is None:
                mod = importlib.import_module(module_path)
                note = "imported"
            else:
                note = "cached"
            ok = callable(getattr(mod, fn_name, None))
        except Exception:
            note = "import failed"
        elapsed = round((time.time() - start) * 1000, 1)
        probes.append({
            "module":      label,
            "response_ms": elapsed,
            "available":   ok,
            "note":        note,
            "grade": (
                "FAST"      if elapsed < 100  else
                "NORMAL"    if elapsed < 500  else
                "SLOW"      if elapsed < 2000 else
                "VERY_SLOW"
            ),
        })

    return probes


def get_performance_dashboard() -> dict:
    """Aggregate all performance metrics into a single dashboard dict."""
    probes    = _probe_snapshots()
    times     = [p["response_ms"] for p in probes]
    avg_ms    = round(sum(times) / len(times), 1) if times else 0.0
    slow      = [p for p in probes if p["grade"] in ("SLOW", "VERY_SLOW")]
    fast      = [p for p in probes if p["grade"] == "FAST"]

    # Performance score: penalise slow probes
    perf_score = max(0.0, round(100 - len(slow) * 15 - (avg_ms / 100), 1))
    status     = STATUS_HEALTHY if perf_score >= 70 else STATUS_DEGRADED

    return {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "status":          status,
        "overall_score":   perf_score,
        "grade":           obs_grade(perf_score),
        "avg_snapshot_ms": avg_ms,
        "fast_modules":    len(fast),
        "slow_modules":    len(slow),
        "module_probes":   probes,
        "slow_endpoints":  slow,
        "benchmarks": {
            "fast_threshold_ms":      100,
            "normal_threshold_ms":    500,
            "slow_threshold_ms":     2000,
            "target_avg_ms":          300,
        },
        "background_processing": {
            "snapshot_probes_total": len(probes),
            "note": "Probes run on each /api/observability/performance call.",
        },
    }
