"""
api_metrics.py — Phase 8.1
Advisory API performance metrics.
Estimates are derived from Phase 7 snapshot data and process metadata.
No actual request interception — advisory only.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from .models import STATUS_HEALTHY, STATUS_DEGRADED, STATUS_UNKNOWN

# In-process lightweight metric store (circular buffer, max 100 entries)
_request_log: list[dict] = []
_MAX_LOG = 100
_start_time = time.time()


def record_request(endpoint: str, method: str, status_code: int,
                   latency_ms: float) -> None:
    """
    Optional hook: call from route handlers to record real metrics.
    Advisory only — does not affect routing or responses.
    """
    global _request_log
    entry = {
        "endpoint":   endpoint,
        "method":     method,
        "status":     status_code,
        "latency_ms": round(latency_ms, 1),
        "ts":         datetime.now(timezone.utc).isoformat(),
        "is_error":   status_code >= 400,
    }
    _request_log.append(entry)
    if len(_request_log) > _MAX_LOG:
        _request_log = _request_log[-_MAX_LOG:]


def _compute_stats(logs: list[dict]) -> dict:
    if not logs:
        return {
            "request_count": 0, "error_count": 0, "error_rate_pct": 0.0,
            "success_rate_pct": 100.0, "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0, "slow_threshold_ms": 500.0,
            "slow_requests": 0,
        }
    latencies  = sorted(l["latency_ms"] for l in logs)
    errors     = sum(1 for l in logs if l["is_error"])
    total      = len(logs)
    p95_idx    = max(0, int(total * 0.95) - 1)
    avg_lat    = round(sum(latencies) / total, 1)
    p95_lat    = round(latencies[p95_idx], 1)
    error_rate = round(errors / total * 100, 1)
    slow       = sum(1 for l in latencies if l > 500)
    return {
        "request_count":    total,
        "error_count":      errors,
        "error_rate_pct":   error_rate,
        "success_rate_pct": round(100 - error_rate, 1),
        "avg_latency_ms":   avg_lat,
        "p95_latency_ms":   p95_lat,
        "slow_threshold_ms": 500.0,
        "slow_requests":    slow,
    }


def _endpoint_breakdown(logs: list[dict]) -> list[dict]:
    grouped: dict[str, list] = {}
    for l in logs:
        ep = l["endpoint"]
        grouped.setdefault(ep, []).append(l)
    result = []
    for ep, entries in grouped.items():
        lats    = [e["latency_ms"] for e in entries]
        errors  = sum(1 for e in entries if e["is_error"])
        avg_lat = round(sum(lats) / len(lats), 1)
        result.append({
            "endpoint":        ep,
            "request_count":   len(entries),
            "avg_latency_ms":  avg_lat,
            "error_count":     errors,
            "availability_pct": round((len(entries) - errors) / len(entries) * 100, 1),
        })
    return sorted(result, key=lambda x: x["avg_latency_ms"], reverse=True)


def get_api_metrics() -> dict:
    """Return API performance metrics from the in-process log."""
    stats    = _compute_stats(_request_log)
    recent   = _request_log[-10:]  # last 10 requests
    endpoint_stats = _endpoint_breakdown(_request_log)
    slow_eps = [e for e in endpoint_stats if e["avg_latency_ms"] > 500]

    # Health based on error rate and latency
    err_rate = stats["error_rate_pct"]
    p95      = stats["p95_latency_ms"]
    if err_rate > 10 or p95 > 2000:
        status = STATUS_DEGRADED
    elif err_rate > 25 or p95 > 5000:
        status = "DOWN"
    else:
        status = STATUS_HEALTHY

    # Session uptime
    session_uptime_s = round(time.time() - _start_time, 0)

    return {
        "available":          True,
        "advisory_only":      True,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "status":             status,
        "session_uptime_s":   session_uptime_s,
        "stats":              stats,
        "recent_requests":    recent,
        "endpoint_breakdown": endpoint_stats,
        "slow_endpoints":     slow_eps,
        "note":               (
            "Metrics reflect requests recorded in this process session only. "
            "For full platform metrics, use the TypeScript API server telemetry."
        ),
    }
