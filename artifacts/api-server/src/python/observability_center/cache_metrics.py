"""
cache_metrics.py — Phase 8.1
In-process cache monitoring across all Phase 7 modules.
Inspects _cache dicts without modifying them.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from .models import STATUS_HEALTHY, STATUS_DEGRADED, STATUS_UNKNOWN


def _inspect_module_cache(module_path: str, cache_attr: str = "_cache") -> dict:
    """
    Safely inspect a module-level _cache dict.
    Returns entry count and freshness info without touching the cache.
    """
    try:
        mod = sys.modules.get(module_path)
        if mod is None:
            return {"entries": 0, "loaded": False}
        cache = getattr(mod, cache_attr, {})
        if not isinstance(cache, dict):
            return {"entries": 0, "loaded": True, "note": "Non-dict cache"}
        entries = len(cache)
        now     = datetime.now(timezone.utc)
        freshness = []
        for key, val in cache.items():
            if isinstance(val, dict) and "ts" in val:
                age_s = round((now - val["ts"]).total_seconds(), 0)
                freshness.append({"key": key, "age_s": age_s})
        return {
            "entries":   entries,
            "loaded":    True,
            "freshness": freshness,
        }
    except Exception:
        return {"entries": 0, "loaded": False, "error": "inspect failed"}


# ── Module caches to monitor ───────────────────────────────────────────────────
_MONITORED_CACHES = [
    ("market_intelligence_hub.volatility_analyser",  "_cache", "mih.volatility"),
    ("macro_intelligence.volatility_intelligence",   "_cache", "macro.volatility"),
    ("macro_intelligence.global_markets",            "_cache", "macro.global"),
    ("macro_intelligence.market_flows",              "_cache", "macro.flows"),
    ("macro_intelligence.currency_intelligence",     "_cache", "macro.currency"),
    ("macro_intelligence.commodity_intelligence",    "_cache", "macro.commodity"),
]


def get_cache_metrics() -> dict:
    """Inspect all known in-process caches and report health."""
    cache_details = []
    total_entries = 0
    stale_count   = 0
    STALE_THRESHOLD_S = 120  # entries older than 2 min flagged as potentially stale

    for module_path, attr, label in _MONITORED_CACHES:
        info = _inspect_module_cache(module_path, attr)
        entries = info.get("entries", 0)
        total_entries += entries

        # Check for stale entries
        stale_entries = 0
        for f in info.get("freshness", []):
            if f.get("age_s", 0) > STALE_THRESHOLD_S:
                stale_entries += 1
                stale_count += 1

        cache_details.append({
            "label":        label,
            "module":       module_path,
            "loaded":       info.get("loaded", False),
            "entries":      entries,
            "stale_entries": stale_entries,
            "freshness":    info.get("freshness", []),
        })

    hit_rate_est = round(max(0, 100 - stale_count * 10), 1)
    status = STATUS_HEALTHY if stale_count == 0 else STATUS_DEGRADED

    # Memory estimate: rough heuristic, 2 KB per cache entry
    mem_est_kb = total_entries * 2

    return {
        "available":        True,
        "advisory_only":    True,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "status":           status,
        "total_entries":    total_entries,
        "stale_entries":    stale_count,
        "cache_hit_rate_est_pct": hit_rate_est,
        "memory_est_kb":    mem_est_kb,
        "stale_threshold_s": STALE_THRESHOLD_S,
        "caches":           cache_details,
        "note": (
            "Cache metrics reflect in-process Python module caches only. "
            "Redis/external caches are not monitored from Python."
        ),
    }
