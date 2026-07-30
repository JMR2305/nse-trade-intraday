"""
system_health.py — Phase 8.1
System & resource health monitoring using /proc filesystem.
No external packages required — pure Linux /proc introspection.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone

from .models import STATUS_HEALTHY, STATUS_DEGRADED, STATUS_DOWN, STATUS_UNKNOWN


def _read_proc(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""


def get_uptime_seconds() -> float:
    """Read uptime from /proc/uptime."""
    raw = _read_proc("/proc/uptime")
    if not raw:
        return 0.0
    try:
        return float(raw.split()[0])
    except Exception:
        return 0.0


def get_memory_info() -> dict:
    """Parse /proc/meminfo for memory stats."""
    raw = _read_proc("/proc/meminfo")
    if not raw:
        return {"available": False, "total_mb": 0, "used_mb": 0,
                "free_mb": 0, "usage_pct": 0.0}
    try:
        info: dict = {}
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                val = int(parts[1])  # kB
                info[key] = val
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        used  = total - avail
        pct   = round(used / total * 100, 1) if total else 0.0
        return {
            "available":  True,
            "total_mb":   round(total / 1024, 1),
            "used_mb":    round(used / 1024, 1),
            "free_mb":    round(avail / 1024, 1),
            "usage_pct":  pct,
            "status":     STATUS_DEGRADED if pct > 85 else STATUS_HEALTHY,
        }
    except Exception:
        return {"available": False, "total_mb": 0, "used_mb": 0,
                "free_mb": 0, "usage_pct": 0.0, "status": STATUS_UNKNOWN}


def get_cpu_info() -> dict:
    """Load average from /proc/loadavg as a CPU proxy."""
    raw = _read_proc("/proc/loadavg")
    if not raw:
        return {"available": False, "load_1m": 0.0, "load_5m": 0.0,
                "load_15m": 0.0, "status": STATUS_UNKNOWN}
    try:
        parts  = raw.split()
        load1  = float(parts[0])
        load5  = float(parts[1])
        load15 = float(parts[2])
        # Estimate usage: load > 2.0 = degraded on typical container
        status = STATUS_DEGRADED if load1 > 2.0 else STATUS_HEALTHY
        return {
            "available": True,
            "load_1m":   round(load1,  2),
            "load_5m":   round(load5,  2),
            "load_15m":  round(load15, 2),
            "status":    status,
        }
    except Exception:
        return {"available": False, "load_1m": 0.0, "load_5m": 0.0,
                "load_15m": 0.0, "status": STATUS_UNKNOWN}


def get_disk_info() -> dict:
    """Disk usage via os.statvfs."""
    try:
        sv    = os.statvfs("/")
        total = sv.f_frsize * sv.f_blocks
        free  = sv.f_frsize * sv.f_bfree
        used  = total - free
        pct   = round(used / total * 100, 1) if total else 0.0
        status = STATUS_DEGRADED if pct > 85 else STATUS_HEALTHY
        return {
            "available": True,
            "total_gb":  round(total / 1e9, 2),
            "used_gb":   round(used  / 1e9, 2),
            "free_gb":   round(free  / 1e9, 2),
            "usage_pct": pct,
            "status":    status,
        }
    except Exception:
        return {"available": False, "total_gb": 0, "used_gb": 0,
                "free_gb": 0, "usage_pct": 0.0, "status": STATUS_UNKNOWN}


def get_process_info() -> dict:
    """Self process stats from /proc/self/status."""
    raw = _read_proc("/proc/self/status")
    pid = os.getpid()
    if not raw:
        return {"available": False, "pid": pid, "rss_mb": 0.0}
    try:
        info: dict = {}
        for line in raw.splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                info[parts[0].strip()] = parts[1].strip()
        rss_kb = int(info.get("VmRSS", "0 kB").split()[0])
        vm_kb  = int(info.get("VmSize", "0 kB").split()[0])
        return {
            "available": True,
            "pid":       pid,
            "rss_mb":    round(rss_kb / 1024, 1),
            "vm_mb":     round(vm_kb  / 1024, 1),
            "threads":   int(info.get("Threads", 1)),
        }
    except Exception:
        return {"available": False, "pid": pid, "rss_mb": 0.0}


def get_feature_flags() -> dict:
    """Check status of all platform feature flags."""
    flags = {
        "MARKET_INTELLIGENCE_HUB_ENABLED": None,
        "EVENT_INTELLIGENCE_ENABLED":      None,
        "MACRO_INTELLIGENCE_ENABLED":      None,
        "EXPLAINABLE_AI_ENABLED":          None,
        "RESEARCH_LAB_ENABLED":            None,
        "OBSERVABILITY_CENTER_ENABLED":    None,
        "AI_PERFORMANCE_ENABLED":          None,
        "STRATEGY_INTELLIGENCE_ENABLED":   None,
        "RISK_OPTIMISATION_ENABLED":       None,
        "PAPER_TRADING_ENABLED":           None,
    }
    result = {}
    enabled_count = 0
    for flag in flags:
        val = os.environ.get(flag, "false").lower() == "true"
        result[flag] = val
        if val:
            enabled_count += 1
    return {
        "available":      True,
        "flags":          result,
        "enabled_count":  enabled_count,
        "total_flags":    len(flags),
    }


def get_environment_status() -> dict:
    """Check critical environment variables are set."""
    critical = ["DATABASE_URL", "SESSION_SECRET"]
    optional = ["ZERODHA_API_KEY", "ZERODHA_API_SECRET",
                "KITE_ACCESS_TOKEN", "RESEND_API_KEY"]
    missing_critical = [k for k in critical if not os.environ.get(k)]
    has_broker = bool(os.environ.get("ZERODHA_API_KEY") or
                      os.environ.get("KITE_ACCESS_TOKEN"))
    status = STATUS_DOWN if missing_critical else STATUS_HEALTHY
    return {
        "available":        True,
        "status":           status,
        "missing_critical": missing_critical,
        "broker_configured": has_broker,
        "environment":      os.environ.get("NODE_ENV", "development"),
    }


def get_system_health() -> dict:
    """Aggregate all system-level health indicators."""
    uptime_s  = get_uptime_seconds()
    memory    = get_memory_info()
    cpu       = get_cpu_info()
    disk      = get_disk_info()
    process   = get_process_info()
    flags     = get_feature_flags()
    env       = get_environment_status()

    # Health score: each component contributes
    components = [memory, cpu, disk]
    component_scores: list[float] = []
    for c in components:
        s = c.get("status", STATUS_UNKNOWN)
        component_scores.append(100.0 if s == STATUS_HEALTHY else
                                50.0  if s == STATUS_DEGRADED else 0.0)

    health_score = round(sum(component_scores) / len(component_scores), 1) if component_scores else 50.0
    overall = (STATUS_HEALTHY  if health_score >= 80 else
               STATUS_DEGRADED if health_score >= 50 else STATUS_DOWN)

    uptime_h  = round(uptime_s / 3600, 1)
    uptime_d  = round(uptime_s / 86400, 2)

    return {
        "available":     True,
        "advisory_only": True,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "health_score":  health_score,
        "uptime_seconds": uptime_s,
        "uptime_hours":  uptime_h,
        "uptime_days":   uptime_d,
        "memory":        memory,
        "cpu":           cpu,
        "disk":          disk,
        "process":       process,
        "feature_flags": flags,
        "environment":   env,
    }
