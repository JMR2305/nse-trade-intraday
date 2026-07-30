"""
job_monitor.py — Phase 8.1
Background job and scheduler monitoring.
Reads scheduler state from environment and scan_state_store indicators.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import json
from datetime import datetime, timezone, timedelta
from .models import STATUS_HEALTHY, STATUS_DEGRADED, STATUS_UNKNOWN


def _load_scan_state() -> dict:
    """Try to read the last scan state to infer scheduler health."""
    try:
        from scan_state_store import get_latest_snapshot  # type: ignore
        snap = get_latest_snapshot()
        if snap:
            return {
                "scan_id":     snap.get("scan_id"),
                "snapshot_ts": snap.get("snapshot_ts"),
                "status":      snap.get("status", "UNKNOWN"),
            }
    except Exception:
        pass
    # Fallback: try the JSON cache file
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "phase7_scan_cache.json"),
        "/home/runner/workspace/artifacts/api-server/src/python/phase7_scan_cache.json",
    ]
    for path in candidates:
        try:
            with open(os.path.abspath(path)) as f:
                data = json.load(f)
            return {
                "scan_id":     data.get("scan_id"),
                "snapshot_ts": data.get("snapshot_ts"),
                "status":      data.get("status", "UNKNOWN"),
            }
        except Exception:
            continue
    return {}


def _format_next_run(interval_min: int) -> str:
    """Estimate next scheduled run time from interval."""
    try:
        next_dt = datetime.now(timezone.utc) + timedelta(minutes=interval_min)
        return next_dt.isoformat()
    except Exception:
        return "UNKNOWN"


def get_job_monitor() -> dict:
    """Aggregate background job and scheduler status."""
    scan_state  = _load_scan_state()
    scan_id     = scan_state.get("scan_id")
    scan_ts_raw = scan_state.get("snapshot_ts")
    scan_status = scan_state.get("status", "UNKNOWN")

    # Infer scan age
    scan_age_min  = None
    scan_fresh    = False
    STALE_SCAN_MIN = 60  # scans older than 60 min are stale during market hours
    if scan_ts_raw:
        try:
            ts = datetime.fromisoformat(str(scan_ts_raw).replace("Z", "+00:00"))
            scan_age_min = round((datetime.now(timezone.utc) - ts).total_seconds() / 60, 1)
            scan_fresh   = scan_age_min < STALE_SCAN_MIN
        except Exception:
            pass

    # Scan scheduler interval from env
    try:
        interval_min = int(os.environ.get("SCAN_INTERVAL_MIN", 60))
    except Exception:
        interval_min = 60

    # Infer scheduler health
    if scan_id and scan_fresh:
        scheduler_status = STATUS_HEALTHY
    elif scan_id and not scan_fresh:
        scheduler_status = STATUS_DEGRADED
    else:
        scheduler_status = STATUS_UNKNOWN

    # Known background jobs
    jobs = [
        {
            "job_id":      "market_scan",
            "name":        "Live Market Scan",
            "status":      scan_status,
            "last_run_ts": scan_ts_raw,
            "age_min":     scan_age_min,
            "fresh":       scan_fresh,
            "interval_min": interval_min,
            "next_run_ts": _format_next_run(interval_min),
        },
        {
            "job_id":      "phase7_snapshot_publish",
            "name":        "Scan Bundle Publish",
            "status":      "FOLLOWS_SCAN",
            "description": "Runs post-scan; publishes derived cache bundle.",
            "interval_min": interval_min,
        },
        {
            "job_id":      "scan_lock_heartbeat",
            "name":        "Scan Lock Heartbeat",
            "status":      "AUTOMATIC",
            "description": "DB-durable heartbeat renewed every 15 s during active scan.",
        },
    ]

    health_score = (
        90.0 if scheduler_status == STATUS_HEALTHY  else
        50.0 if scheduler_status == STATUS_DEGRADED else
        30.0
    )

    return {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "scheduler_status": scheduler_status,
        "health_score":    health_score,
        "scan_interval_min": interval_min,
        "last_scan": {
            "scan_id":    scan_id,
            "timestamp":  scan_ts_raw,
            "age_min":    scan_age_min,
            "fresh":      scan_fresh,
            "status":     scan_status,
        },
        "jobs":         jobs,
        "running_count":   sum(1 for j in jobs if j.get("status") in ("RUNNING", "FOLLOWS_SCAN", "AUTOMATIC")),
        "failed_count":    0,  # no persistent failure log in current architecture
        "retry_queue":     [],
    }
