"""
db_metrics.py — Phase 8.1
Database connectivity and health monitoring.
Read-only probe — no queries that modify data.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from .models import STATUS_HEALTHY, STATUS_DEGRADED, STATUS_DOWN, STATUS_UNKNOWN


def _probe_postgres() -> dict:
    """
    Try a minimal Postgres connection probe.
    Uses psycopg2 if available; falls back to socket probe via DATABASE_URL.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return {
            "connected": False,
            "latency_ms": 0.0,
            "error": "DATABASE_URL not set",
            "status": STATUS_UNKNOWN,
        }

    start = time.time()
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(db_url, connect_timeout=1)
        latency = round((time.time() - start) * 1000, 1)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return {
            "connected":  True,
            "latency_ms": latency,
            "error":      None,
            "status":     STATUS_HEALTHY,
        }
    except ImportError:
        # psycopg2 not available — try socket check
        pass
    except Exception as e:
        return {
            "connected":  False,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error":      str(e)[:120],
            "status":     STATUS_DOWN,
        }

    # Socket fallback: parse host+port from DATABASE_URL
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(db_url)
        host   = parsed.hostname or "localhost"
        port   = parsed.port or 5432
        import socket
        sock = socket.create_connection((host, port), timeout=1)
        latency = round((time.time() - start) * 1000, 1)
        sock.close()
        return {
            "connected":  True,
            "latency_ms": latency,
            "error":      None,
            "status":     STATUS_HEALTHY,
            "note":       "Socket probe only — psycopg2 not available.",
        }
    except Exception as e:
        return {
            "connected":  False,
            "latency_ms": round((time.time() - start) * 1000, 1),
            "error":      str(e)[:120],
            "status":     STATUS_DOWN,
        }


def _estimate_pool_usage() -> dict:
    """
    Estimate connection pool usage from environment.
    Actual pool introspection requires integration with the ORM layer.
    """
    return {
        "pool_size":       int(os.environ.get("DB_POOL_SIZE", 10)),
        "active_conns":    None,   # not introspectable from Python side
        "idle_conns":      None,
        "pool_usage_pct":  None,
        "note":            "Pool metrics require ORM instrumentation.",
    }


def get_db_metrics() -> dict:
    """Aggregate database health metrics."""
    probe = _probe_postgres()
    pool  = _estimate_pool_usage()
    db_url_set = bool(os.environ.get("DATABASE_URL"))

    # Simple health score
    if probe["status"] == STATUS_HEALTHY:
        health_score = 90.0
        lat = probe["latency_ms"]
        if lat > 500: health_score = 70.0
        if lat > 1000: health_score = 50.0
    elif probe["status"] == STATUS_DOWN:
        health_score = 0.0
    else:
        health_score = 30.0

    return {
        "available":       True,
        "advisory_only":   True,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "status":          probe["status"],
        "health_score":    health_score,
        "connection": {
            "connected":   probe["connected"],
            "latency_ms":  probe["latency_ms"],
            "error":       probe.get("error"),
            "url_set":     db_url_set,
        },
        "pool":            pool,
        "operations": {
            "read_probe":  probe["status"] == STATUS_HEALTHY,
            "write_probe": None,   # write probes avoided — advisory-only
            "slow_query_threshold_ms": 200,
        },
        "storage": {
            "note": "Storage metrics require DB admin privileges — not collected.",
        },
    }
