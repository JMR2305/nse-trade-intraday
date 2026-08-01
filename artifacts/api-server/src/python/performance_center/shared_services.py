"""
shared_services.py — Phase 8.7 Performance Centre
All performance analysis functions. Reuses upstream snapshots; never duplicates profiling.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import csv
import io
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from .models import (
    API_TARGET_AVG_MS, API_TARGET_P95_MS, API_TARGET_ERROR_PCT,
    DB_TARGET_LATENCY_MS,
    CACHE_TARGET_HIT_PCT,
    SCAN_FRESH_THRESHOLD_MIN,
    MEM_WARN_PCT, CPU_WARN_LOAD, DISK_WARN_PCT,
    PAGE_TARGET_LOAD_MS, BUNDLE_WARN_KB,
    MAX_SYMBOLS_PER_SCAN, CONCURRENT_USER_TARGET, SCHEDULER_SLOTS,
    FUTURE_AGENTS,
    STATUS_HEALTHY, STATUS_DEGRADED, STATUS_UNKNOWN,
    PerfRecommendation,
    disabled_response, is_enabled, perf_grade, perf_trend,
)

# ── Safe wrapper ───────────────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ── Upstream loaders (read-only, _safe wrapped) ───────────────────────────────

def _load_obs() -> dict:
    def _f():
        from observability_center.shared_services import get_observability_snapshot  # type: ignore
        return get_observability_snapshot()
    return _safe(_f) or {}


def _load_ops() -> dict:
    def _f():
        from operations_center.shared_services import get_operations_snapshot  # type: ignore
        return get_operations_snapshot()
    return _safe(_f) or {}


def _load_sec() -> dict:
    def _f():
        from security_center.shared_services import get_security_snapshot  # type: ignore
        return get_security_snapshot()
    return _safe(_f) or {}


def _load_api_metrics() -> dict:
    def _f():
        from observability_center.api_metrics import get_api_metrics  # type: ignore
        return get_api_metrics()
    return _safe(_f) or {}


def _load_db_metrics() -> dict:
    def _f():
        from observability_center.db_metrics import get_db_metrics  # type: ignore
        return get_db_metrics()
    return _safe(_f) or {}


def _load_cache_metrics() -> dict:
    def _f():
        from observability_center.cache_metrics import get_cache_metrics  # type: ignore
        return get_cache_metrics()
    return _safe(_f) or {}


def _load_job_monitor() -> dict:
    def _f():
        from observability_center.job_monitor import get_job_monitor  # type: ignore
        return get_job_monitor()
    return _safe(_f) or {}


def _load_system_health() -> dict:
    def _f():
        from observability_center.system_health import get_system_health  # type: ignore
        return get_system_health()
    return _safe(_f) or {}


def _load_scan_runs(limit: int = 20) -> list:
    def _f():
        from phase20_store import list_scan_runs  # type: ignore
        return list_scan_runs(limit=limit)
    return _safe(_f) or []


# ── Sub-module helpers ─────────────────────────────────────────────────────────

def _score_api(raw: dict) -> float:
    stats = raw.get("stats", {})
    avg   = stats.get("avg_latency_ms", 0.0)
    p95   = stats.get("p95_latency_ms", 0.0)
    err   = stats.get("error_rate_pct", 0.0)
    cnt   = stats.get("request_count", 0)
    if cnt == 0:
        return 80.0   # no data = neutral, not penalised

    score = 100.0
    if avg  > API_TARGET_AVG_MS:  score -= min(30, (avg - API_TARGET_AVG_MS) / 10)
    if p95  > API_TARGET_P95_MS:  score -= min(20, (p95 - API_TARGET_P95_MS) / 40)
    if err  > API_TARGET_ERROR_PCT: score -= min(30, (err - API_TARGET_ERROR_PCT) * 5)
    return round(max(0.0, min(100.0, score)), 1)


def _score_db(raw: dict) -> float:
    lat = raw.get("connection", {}).get("latency_ms", 0.0)
    connected = raw.get("connection", {}).get("connected", False)
    if not connected:
        return 20.0
    score = 100.0
    if lat > DB_TARGET_LATENCY_MS:
        score -= min(40, (lat - DB_TARGET_LATENCY_MS) / 5)
    return round(max(0.0, min(100.0, score)), 1)


def _score_cache(raw: dict) -> float:
    hit = raw.get("cache_hit_rate_est_pct", 100.0)
    stale = raw.get("stale_entries", 0)
    score = hit
    score -= stale * 5
    return round(max(0.0, min(100.0, score)), 1)


def _score_scheduler(raw: dict) -> float:
    status = raw.get("scheduler_status", STATUS_UNKNOWN)
    if status == STATUS_HEALTHY:  return 90.0
    if status == STATUS_DEGRADED: return 55.0
    return 30.0


def _score_resources(raw: dict) -> float:
    mem  = raw.get("memory", {}).get("usage_pct", 0.0)
    load = raw.get("cpu",    {}).get("load_1m",   0.0)
    disk = raw.get("disk",   {}).get("usage_pct", 0.0)
    score = 100.0
    if mem  > MEM_WARN_PCT:  score -= (mem  - MEM_WARN_PCT)  * 1.5
    if load > CPU_WARN_LOAD: score -= (load - CPU_WARN_LOAD) * 10
    if disk > DISK_WARN_PCT: score -= (disk - DISK_WARN_PCT) * 1.5
    return round(max(0.0, min(100.0, score)), 1)


def _score_frontend() -> float:
    # Frontend score is estimated from bundle sizes; no runtime instrumentation.
    total_kb = _estimate_bundle_kb()
    score = 100.0
    if total_kb > BUNDLE_WARN_KB:
        score -= min(30, (total_kb - BUNDLE_WARN_KB) / 100)
    return round(max(0.0, min(100.0, score)), 1)


def _estimate_bundle_kb() -> float:
    """Estimate dashboard bundle size from dist directory if built."""
    candidates = [
        "artifacts/trading-dashboard/dist/assets",
        "/home/runner/workspace/artifacts/trading-dashboard/dist/assets",
    ]
    for path in candidates:
        if os.path.isdir(path):
            total = sum(
                os.path.getsize(os.path.join(path, f))
                for f in os.listdir(path)
                if f.endswith((".js", ".css"))
            )
            return round(total / 1024, 1)
    return 0.0  # dev mode: no dist yet


# ── Public endpoint functions ──────────────────────────────────────────────────

def get_api_performance() -> dict:
    if not is_enabled():
        return disabled_response()
    raw   = _load_api_metrics()
    score = _score_api(raw)
    stats = raw.get("stats", {})
    return {
        "available":            True,
        "advisory_only":        True,
        "read_only":            True,
        "generated_at":         datetime.now(timezone.utc).isoformat(),
        "performance_score":    score,
        "grade":                perf_grade(score),
        "status":               raw.get("status", STATUS_UNKNOWN),
        "session_uptime_s":     raw.get("session_uptime_s", 0),
        "request_count":        stats.get("request_count", 0),
        "avg_latency_ms":       stats.get("avg_latency_ms", 0.0),
        "p95_latency_ms":       stats.get("p95_latency_ms", 0.0),
        "error_rate_pct":       stats.get("error_rate_pct", 0.0),
        "success_rate_pct":     stats.get("success_rate_pct", 100.0),
        "slow_requests":        stats.get("slow_requests", 0),
        "slow_threshold_ms":    stats.get("slow_threshold_ms", 500.0),
        "endpoint_breakdown":   raw.get("endpoint_breakdown", []),
        "slow_endpoints":       raw.get("slow_endpoints", []),
        "recent_requests":      raw.get("recent_requests", []),
        "targets": {
            "avg_latency_ms":  API_TARGET_AVG_MS,
            "p95_latency_ms":  API_TARGET_P95_MS,
            "error_rate_pct":  API_TARGET_ERROR_PCT,
        },
        "note": raw.get("note", "API metrics from in-process Python log only."),
    }


def get_database_performance() -> dict:
    if not is_enabled():
        return disabled_response()
    raw   = _load_db_metrics()
    score = _score_db(raw)
    conn  = raw.get("connection", {})
    return {
        "available":         True,
        "advisory_only":     True,
        "read_only":         True,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "performance_score": score,
        "grade":             perf_grade(score),
        "status":            raw.get("status", STATUS_UNKNOWN),
        "health_score":      raw.get("health_score", 0.0),
        "connection": {
            "connected":    conn.get("connected", False),
            "latency_ms":   conn.get("latency_ms", 0.0),
            "error":        conn.get("error"),
            "url_set":      conn.get("url_set", False),
        },
        "pool":              raw.get("pool", {}),
        "operations":        raw.get("operations", {}),
        "storage":           raw.get("storage", {}),
        "targets": {
            "latency_ms":         DB_TARGET_LATENCY_MS,
            "slow_query_ms":      200,
        },
    }


def get_cache_performance() -> dict:
    if not is_enabled():
        return disabled_response()
    raw   = _load_cache_metrics()
    score = _score_cache(raw)
    return {
        "available":             True,
        "advisory_only":         True,
        "read_only":             True,
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "performance_score":     score,
        "grade":                 perf_grade(score),
        "status":                raw.get("status", STATUS_UNKNOWN),
        "total_entries":         raw.get("total_entries", 0),
        "stale_entries":         raw.get("stale_entries", 0),
        "cache_hit_rate_est_pct": raw.get("cache_hit_rate_est_pct", 100.0),
        "memory_est_kb":         raw.get("memory_est_kb", 0),
        "stale_threshold_s":     raw.get("stale_threshold_s", 120),
        "caches":                raw.get("caches", []),
        "targets": {
            "hit_rate_pct":  CACHE_TARGET_HIT_PCT,
            "stale_warn_s":  120,
        },
        "note": raw.get("note", "In-process Python module caches only."),
    }


def get_scheduler_performance() -> dict:
    if not is_enabled():
        return disabled_response()
    raw      = _load_job_monitor()
    runs     = _load_scan_runs(limit=10)
    score    = _score_scheduler(raw)

    # Derive scan timing stats from recent scan runs
    durations = [
        r.get("duration_s") for r in runs
        if isinstance(r.get("duration_s"), (int, float))
    ]
    avg_duration_s = round(sum(durations) / len(durations), 1) if durations else None
    max_duration_s = max(durations) if durations else None

    return {
        "available":         True,
        "advisory_only":     True,
        "read_only":         True,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "performance_score": score,
        "grade":             perf_grade(score),
        "scheduler_status":  raw.get("scheduler_status", STATUS_UNKNOWN),
        "health_score":      raw.get("health_score", 30.0),
        "scan_interval_min": raw.get("scan_interval_min", 60),
        "last_scan":         raw.get("last_scan", {}),
        "jobs":              raw.get("jobs", []),
        "running_count":     raw.get("running_count", 0),
        "failed_count":      raw.get("failed_count", 0),
        "retry_queue":       raw.get("retry_queue", []),
        "recent_scan_runs":  runs[:5],
        "scan_timing": {
            "avg_duration_s": avg_duration_s,
            "max_duration_s": max_duration_s,
            "run_count":      len(runs),
        },
        "targets": {
            "fresh_threshold_min": SCAN_FRESH_THRESHOLD_MIN,
        },
    }


def get_resource_performance() -> dict:
    if not is_enabled():
        return disabled_response()
    raw   = _load_system_health()
    score = _score_resources(raw)
    mem   = raw.get("memory", {})
    cpu   = raw.get("cpu",    {})
    disk  = raw.get("disk",   {})
    proc  = raw.get("process", {})
    env   = raw.get("environment", {})

    # Estimate node process count from /proc
    node_procs = _count_node_processes()

    return {
        "available":         True,
        "advisory_only":     True,
        "read_only":         True,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "performance_score": score,
        "grade":             perf_grade(score),
        "overall_status":    raw.get("overall_status", STATUS_UNKNOWN),
        "uptime_hours":      raw.get("uptime_hours", 0.0),
        "memory": {
            "total_mb":    mem.get("total_mb", 0),
            "used_mb":     mem.get("used_mb", 0),
            "free_mb":     mem.get("free_mb", 0),
            "usage_pct":   mem.get("usage_pct", 0.0),
            "status":      mem.get("status", STATUS_UNKNOWN),
        },
        "cpu": {
            "load_1m":     cpu.get("load_1m", 0.0),
            "load_5m":     cpu.get("load_5m", 0.0),
            "load_15m":    cpu.get("load_15m", 0.0),
            "status":      cpu.get("status", STATUS_UNKNOWN),
        },
        "disk": {
            "total_gb":    disk.get("total_gb", 0),
            "used_gb":     disk.get("used_gb", 0),
            "free_gb":     disk.get("free_gb", 0),
            "usage_pct":   disk.get("usage_pct", 0.0),
            "status":      disk.get("status", STATUS_UNKNOWN),
        },
        "process": {
            "pid":         proc.get("pid"),
            "rss_mb":      proc.get("rss_mb", 0.0),
            "vm_mb":       proc.get("vm_mb", 0.0),
            "threads":     proc.get("threads", 1),
            "label":       "Python worker (this process)",
        },
        "node_processes": node_procs,
        "targets": {
            "mem_warn_pct":  MEM_WARN_PCT,
            "cpu_warn_load": CPU_WARN_LOAD,
            "disk_warn_pct": DISK_WARN_PCT,
        },
    }


def _count_node_processes() -> dict:
    """Count running node processes via /proc (read-only)."""
    count = 0
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            cmd_path = f"/proc/{pid_dir}/comm"
            try:
                with open(cmd_path) as f:
                    comm = f.read().strip()
                if comm in ("node", "nodejs"):
                    count += 1
            except Exception:
                continue
    except Exception:
        pass
    return {"count": count, "note": "Counted from /proc/*/comm (read-only)."}


def get_frontend_performance() -> dict:
    if not is_enabled():
        return disabled_response()

    bundle_kb  = _estimate_bundle_kb()
    score      = _score_frontend()

    # Estimate page-load time: heuristic based on bundle size
    est_load_ms = round(bundle_kb / 100 * 80 + 400, 0) if bundle_kb > 0 else None

    return {
        "available":          True,
        "advisory_only":      True,
        "read_only":          True,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "performance_score":  score,
        "grade":              perf_grade(score),
        "bundle": {
            "total_kb":        bundle_kb,
            "warn_threshold_kb": BUNDLE_WARN_KB,
            "built":           bundle_kb > 0,
            "note":            "Bundle size from dist/assets (production build only).",
        },
        "page_load": {
            "estimated_ms":    est_load_ms,
            "target_ms":       PAGE_TARGET_LOAD_MS,
            "source":          "heuristic (bundle-size proxy)",
            "note":            "Real page-load metrics require browser instrumentation (e.g. Web Vitals).",
        },
        "dashboard_features": {
            "lazy_loading":    False,
            "code_splitting":  True,
            "vite_build":      True,
            "react_query":     True,
        },
        "targets": {
            "page_load_ms":  PAGE_TARGET_LOAD_MS,
            "bundle_kb":     BUNDLE_WARN_KB,
        },
        "note": (
            "Frontend metrics are estimated. Real Core Web Vitals require "
            "browser-side instrumentation. Bundle size is from production dist; "
            "0 KB in dev mode is expected."
        ),
    }


def get_scalability_estimate() -> dict:
    if not is_enabled():
        return disabled_response()
    sys_raw  = _load_system_health()
    mem      = sys_raw.get("memory", {})
    cpu      = sys_raw.get("cpu", {})
    sched    = _load_job_monitor()

    mem_free_mb   = mem.get("free_mb", 0.0)
    mem_total_mb  = mem.get("total_mb", 1024.0) or 1024.0
    load_1m       = cpu.get("load_1m", 0.0)

    # Capacity estimates: heuristic based on available resources
    mem_headroom_pct  = round(mem_free_mb / mem_total_mb * 100, 1)
    cpu_headroom      = max(0.0, 4.0 - load_1m)  # assume 4-core container

    max_stocks = min(MAX_SYMBOLS_PER_SCAN, int(mem_free_mb / 2))  # 2 MB per symbol est
    max_users  = min(CONCURRENT_USER_TARGET, max(1, int(cpu_headroom * 5)))
    sched_cap  = SCHEDULER_SLOTS

    interval_min = sched.get("scan_interval_min", 60)
    sched_load_pct = round(min(100, 60 / max(1, interval_min) * 100), 1)

    # Future agent capacity
    agents_possible = max(1, int(mem_free_mb / 128))  # 128 MB per agent est

    return {
        "available":             True,
        "advisory_only":         True,
        "read_only":             True,
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "current_capacity": {
            "max_symbols_per_scan":     max_stocks,
            "concurrent_users":         max_users,
            "scheduler_slots":          sched_cap,
            "scheduler_load_pct":       sched_load_pct,
            "mem_headroom_pct":         mem_headroom_pct,
            "cpu_headroom_cores":       round(cpu_headroom, 2),
        },
        "recommended_capacity": {
            "max_symbols_per_scan":     min(MAX_SYMBOLS_PER_SCAN, max_stocks * 2),
            "concurrent_users":         CONCURRENT_USER_TARGET,
            "scheduler_slots":          SCHEDULER_SLOTS,
            "note":                     "Recommendations based on 50% headroom principle.",
        },
        "multi_agent_readiness": {
            "agents_possible":  agents_possible,
            "agents":           [
                {"name": a, "status": "READY_WHEN_PROVISIONED"}
                for a in FUTURE_AGENTS
            ],
            "note": (
                "Multi-agent architecture is a future capability. "
                "Each agent estimated at 128 MB RAM."
            ),
        },
        "bottlenecks": _identify_bottlenecks(mem, cpu, {}, {}),
        "note": (
            "All capacity estimates are heuristic. "
            "Production sizing requires load testing."
        ),
    }


def _identify_bottlenecks(mem: dict, cpu: dict, db: dict, cache: dict) -> list[str]:
    bottlenecks: list[str] = []
    if mem.get("usage_pct", 0) > MEM_WARN_PCT:
        bottlenecks.append(f"Memory usage at {mem.get('usage_pct')}% — above {MEM_WARN_PCT}% threshold.")
    if cpu.get("load_1m", 0) > CPU_WARN_LOAD:
        bottlenecks.append(f"CPU load {cpu.get('load_1m')} — above {CPU_WARN_LOAD} threshold.")
    if db.get("connection", {}).get("latency_ms", 0) > DB_TARGET_LATENCY_MS:
        bottlenecks.append("Database connection latency exceeds target.")
    if cache.get("stale_entries", 0) > 2:
        bottlenecks.append("Multiple stale cache entries — consider cache refresh.")
    return bottlenecks


def get_benchmark() -> dict:
    if not is_enabled():
        return disabled_response()
    runs = _load_scan_runs(limit=20)

    def _scan_summary(run: dict) -> dict:
        return {
            "scan_id":       run.get("scan_id"),
            "started_at":    run.get("started_at"),
            "duration_s":    run.get("duration_s"),
            "symbols_req":   run.get("symbols_requested"),
            "symbols_recv":  run.get("symbols_received"),
            "status":        run.get("status"),
            "provider":      run.get("provider"),
        }

    durations = [
        r.get("duration_s") for r in runs
        if isinstance(r.get("duration_s"), (int, float))
    ]
    avg_dur   = round(sum(durations) / len(durations), 1) if durations else None
    best_dur  = min(durations) if durations else None
    worst_dur = max(durations) if durations else None

    # Rolling average (last 5)
    recent5 = durations[:5]
    rolling_avg = round(sum(recent5) / len(recent5), 1) if recent5 else None

    # Trend: compare most recent vs rolling
    trend = "STABLE"
    if durations and rolling_avg is not None:
        latest = durations[0]
        if latest < rolling_avg * 0.9:  trend = "IMPROVING"
        elif latest > rolling_avg * 1.1: trend = "DEGRADING"

    obs  = _load_obs()
    perf_score_baseline = obs.get("performance_score", 70.0) or 70.0

    return {
        "available":         True,
        "advisory_only":     True,
        "read_only":         True,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "comparison": {
            "current_session":   {"avg_duration_s": rolling_avg, "run_count": len(recent5)},
            "rolling_average":   {"avg_duration_s": avg_dur,     "run_count": len(durations)},
            "peak_performance":  {"best_duration_s": best_dur},
            "worst_performance": {"worst_duration_s": worst_dur},
        },
        "trend":              trend,
        "performance_score_baseline": perf_score_baseline,
        "recent_runs":        [_scan_summary(r) for r in runs[:10]],
        "note": (
            "Benchmark compares scan run durations from the last 20 completed scans. "
            "Cross-session benchmarking requires persistent timing storage."
        ),
    }


def get_recommendations() -> dict:
    if not is_enabled():
        return disabled_response()

    recs: list[PerfRecommendation] = []

    # API
    api_raw   = _load_api_metrics()
    api_stats = api_raw.get("stats", {})
    if api_stats.get("avg_latency_ms", 0) > API_TARGET_AVG_MS:
        recs.append(PerfRecommendation(
            domain="API", severity="WARNING",
            title="API response time above target",
            detail=(
                f"Average latency {api_stats['avg_latency_ms']} ms exceeds "
                f"target {API_TARGET_AVG_MS} ms. "
                "Consider caching frequently-called endpoints or enabling Redis."
            )
        ))
    if api_stats.get("error_rate_pct", 0) > API_TARGET_ERROR_PCT:
        recs.append(PerfRecommendation(
            domain="API", severity="CRITICAL",
            title="API error rate elevated",
            detail=(
                f"Error rate {api_stats['error_rate_pct']}% exceeds "
                f"target {API_TARGET_ERROR_PCT}%. "
                "Review error logs in the Observability Center."
            )
        ))

    # Database
    db_raw = _load_db_metrics()
    db_lat = db_raw.get("connection", {}).get("latency_ms", 0.0)
    if db_lat > DB_TARGET_LATENCY_MS:
        recs.append(PerfRecommendation(
            domain="Database", severity="WARNING",
            title="Database connection latency above target",
            detail=(
                f"DB latency {db_lat} ms exceeds target {DB_TARGET_LATENCY_MS} ms. "
                "Consider connection pooling (PgBouncer) or co-locating the database."
            )
        ))
    if not db_raw.get("connection", {}).get("connected", True):
        recs.append(PerfRecommendation(
            domain="Database", severity="CRITICAL",
            title="Database unreachable",
            detail="Platform cannot connect to the database. Check DATABASE_URL and network."
        ))

    # Cache
    cache_raw = _load_cache_metrics()
    stale = cache_raw.get("stale_entries", 0)
    hit   = cache_raw.get("cache_hit_rate_est_pct", 100.0)
    if stale > 2:
        recs.append(PerfRecommendation(
            domain="Cache", severity="WARNING",
            title="Multiple stale cache entries detected",
            detail=(
                f"{stale} stale cache entries found. "
                "Consider running a fresh market scan to refresh caches."
            )
        ))
    if hit < CACHE_TARGET_HIT_PCT:
        recs.append(PerfRecommendation(
            domain="Cache", severity="INFO",
            title="Cache hit rate below target",
            detail=(
                f"Estimated cache hit rate {hit}% is below target {CACHE_TARGET_HIT_PCT}%. "
                "Consider caching the Market Intelligence snapshot."
            )
        ))

    # Scheduler
    job_raw = _load_job_monitor()
    last    = job_raw.get("last_scan", {})
    age     = last.get("age_min")
    if isinstance(age, (int, float)) and age > SCAN_FRESH_THRESHOLD_MIN:
        recs.append(PerfRecommendation(
            domain="Scheduler", severity="WARNING",
            title="Scheduler approaching execution limit",
            detail=(
                f"Last scan is {age:.0f} min old (limit: {SCAN_FRESH_THRESHOLD_MIN} min). "
                "Consider running a manual scan or reducing the scan interval."
            )
        ))

    # Resources
    sys_raw = _load_system_health()
    mem_pct = sys_raw.get("memory", {}).get("usage_pct", 0.0)
    cpu_l   = sys_raw.get("cpu", {}).get("load_1m", 0.0)
    disk_pct = sys_raw.get("disk", {}).get("usage_pct", 0.0)
    if mem_pct > MEM_WARN_PCT:
        recs.append(PerfRecommendation(
            domain="Resources", severity="WARNING",
            title="Memory usage approaching limit",
            detail=(
                f"Memory at {mem_pct}% (warn: {MEM_WARN_PCT}%). "
                "Review Python worker memory and clear unused caches."
            )
        ))
    if cpu_l > CPU_WARN_LOAD:
        recs.append(PerfRecommendation(
            domain="Resources", severity="WARNING",
            title="CPU load elevated",
            detail=(
                f"Load average {cpu_l} (warn: {CPU_WARN_LOAD}). "
                "Consider spreading scan intervals or reducing symbol count."
            )
        ))
    if disk_pct > DISK_WARN_PCT:
        recs.append(PerfRecommendation(
            domain="Resources", severity="WARNING",
            title="Disk usage high",
            detail=f"Disk at {disk_pct}% (warn: {DISK_WARN_PCT}%). Archive old scan data."
        ))

    # Frontend
    bundle_kb = _estimate_bundle_kb()
    if bundle_kb > BUNDLE_WARN_KB:
        recs.append(PerfRecommendation(
            domain="Frontend", severity="INFO",
            title="Dashboard bundle size above threshold",
            detail=(
                f"Bundle is {bundle_kb:.0f} KB (threshold: {BUNDLE_WARN_KB} KB). "
                "Dashboard rendering could be reduced by lazy loading heavy tabs."
            )
        ))

    # Positive note if no issues
    if not recs:
        recs.append(PerfRecommendation(
            domain="Platform", severity="INFO",
            title="Platform performance within all targets",
            detail="All monitored metrics are within target ranges. No optimisations required."
        ))

    critical  = [r for r in recs if r.severity == "CRITICAL"]
    warnings  = [r for r in recs if r.severity == "WARNING"]
    info_recs = [r for r in recs if r.severity == "INFO"]

    return {
        "available":          True,
        "advisory_only":      True,
        "read_only":          True,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "recommendation_count": len(recs),
        "critical_count":     len(critical),
        "warning_count":      len(warnings),
        "info_count":         len(info_recs),
        "recommendations": [
            {
                "domain":       r.domain,
                "severity":     r.severity,
                "title":        r.title,
                "detail":       r.detail,
                "advisory_only": True,
            }
            for r in recs
        ],
        "note": "All recommendations are advisory only. No automatic optimisations are applied.",
    }


def get_performance_summary() -> dict:
    if not is_enabled():
        return disabled_response()

    api_raw   = _load_api_metrics()
    db_raw    = _load_db_metrics()
    cache_raw = _load_cache_metrics()
    sched_raw = _load_job_monitor()
    sys_raw   = _load_system_health()

    api_score   = _score_api(api_raw)
    db_score    = _score_db(db_raw)
    cache_score = _score_cache(cache_raw)
    sched_score = _score_scheduler(sched_raw)
    res_score   = _score_resources(sys_raw)
    fe_score    = _score_frontend()

    overall = round(
        api_score   * 0.20 +
        db_score    * 0.20 +
        cache_score * 0.15 +
        sched_score * 0.15 +
        res_score   * 0.20 +
        fe_score    * 0.10,
        1
    )

    obs  = _load_obs()
    baseline = obs.get("performance_score", overall)
    trend = perf_trend(overall, float(baseline) if baseline else overall)

    status = (
        STATUS_HEALTHY  if overall >= 80 else
        STATUS_DEGRADED if overall >= 50 else
        STATUS_DOWN
    )

    return {
        "available":          True,
        "advisory_only":      True,
        "read_only":          True,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "performance_score":  overall,
        "grade":              perf_grade(overall),
        "trend":              trend,
        "status":             status,
        "component_scores": {
            "api":       api_score,
            "database":  db_score,
            "cache":     cache_score,
            "scheduler": sched_score,
            "resources": res_score,
            "frontend":  fe_score,
        },
        "weights": {
            "api": 0.20, "database": 0.20, "cache": 0.15,
            "scheduler": 0.15, "resources": 0.20, "frontend": 0.10,
        },
        "top_bottlenecks": _identify_bottlenecks(
            sys_raw.get("memory", {}),
            sys_raw.get("cpu", {}),
            db_raw,
            cache_raw,
        ),
        "obs_score":    obs.get("observability_score"),
        "obs_grade":    obs.get("grade"),
    }


# ── Downstream snapshot interface ──────────────────────────────────────────────

def get_performance_snapshot() -> dict:
    """
    Lightweight snapshot for Phase 8.8 and future multi-agent architecture.
    No resource-heavy sub-module calls.
    """
    if not is_enabled():
        return {"available": False, "advisory_only": True, "read_only": True}

    obs  = _load_obs()
    ops  = _load_ops()
    sys_raw = _load_system_health()

    obs_score  = float(obs.get("performance_score", 70) or 70)
    ops_score  = float(ops.get("operations_score",  70) or 70)
    res_score  = _score_resources(sys_raw)

    snapshot_score = round(obs_score * 0.45 + ops_score * 0.30 + res_score * 0.25, 1)

    return {
        "available":         True,
        "advisory_only":     True,
        "read_only":         True,
        "performance_score": snapshot_score,
        "grade":             perf_grade(snapshot_score),
        "obs_score":         obs_score,
        "ops_score":         ops_score,
        "resource_score":    res_score,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
    }


# ── Export ─────────────────────────────────────────────────────────────────────

def get_export_json() -> dict:
    if not is_enabled():
        return disabled_response()
    return {
        "available":      True,
        "advisory_only":  True,
        "read_only":      True,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "export_format":  "json",
        "summary":        get_performance_summary(),
        "api":            get_api_performance(),
        "database":       get_database_performance(),
        "cache":          get_cache_performance(),
        "scheduler":      get_scheduler_performance(),
        "resources":      get_resource_performance(),
        "frontend":       get_frontend_performance(),
        "scalability":    get_scalability_estimate(),
        "recommendations": get_recommendations(),
        "benchmark":      get_benchmark(),
    }


def get_export_csv() -> dict:
    if not is_enabled():
        return disabled_response()
    summary    = get_performance_summary()
    api_data   = get_api_performance()
    db_data    = get_database_performance()
    cache_data = get_cache_performance()
    sched_data = get_scheduler_performance()
    res_data   = get_resource_performance()

    rows = [
        ["domain",    "metric",             "value",   "unit",     "advisory_only"],
        ["summary",   "performance_score",  summary.get("performance_score"), "score",  True],
        ["summary",   "grade",              summary.get("grade"),              "",       True],
        ["summary",   "trend",              summary.get("trend"),              "",       True],
        ["api",       "avg_latency_ms",     api_data.get("avg_latency_ms"),   "ms",     True],
        ["api",       "p95_latency_ms",     api_data.get("p95_latency_ms"),   "ms",     True],
        ["api",       "error_rate_pct",     api_data.get("error_rate_pct"),   "%",      True],
        ["api",       "request_count",      api_data.get("request_count"),    "count",  True],
        ["database",  "latency_ms",         db_data.get("connection", {}).get("latency_ms"), "ms", True],
        ["database",  "health_score",       db_data.get("health_score"),      "score",  True],
        ["cache",     "hit_rate_est_pct",   cache_data.get("cache_hit_rate_est_pct"), "%", True],
        ["cache",     "stale_entries",      cache_data.get("stale_entries"),  "count",  True],
        ["scheduler", "scheduler_status",   sched_data.get("scheduler_status"),       "",  True],
        ["scheduler", "health_score",       sched_data.get("health_score"),   "score",  True],
        ["resources", "mem_usage_pct",      res_data.get("memory", {}).get("usage_pct"), "%", True],
        ["resources", "cpu_load_1m",        res_data.get("cpu",    {}).get("load_1m"),   "",  True],
        ["resources", "disk_usage_pct",     res_data.get("disk",   {}).get("usage_pct"), "%", True],
    ]

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerows(rows)

    return {
        "available":     True,
        "advisory_only": True,
        "read_only":     True,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "export_format": "csv",
        "csv":           buf.getvalue(),
        "row_count":     len(rows) - 1,  # exclude header
    }
